# -*- coding: utf-8 -*-
"""/api/v1/books — the Books tab's API (§6 "Must", plan P1.4).

THIN by rule (H3): every decision that could be called a rule lives in
``app/domain`` or in the store contract. What this module owns is the HTTP
shape — status codes, query validation, and turning a store/domain error into
the right response.

Two of those mappings carry meaning rather than convention:

  - a book in another library is **404, not 403** (§4.2 / P3.3). The store
    already returns it as absent, so the route cannot leak existence even by
    accident;
  - a rename onto a book you already own is **409**, never a silent merge or
    overwrite. It is a real case — fixing a misread title to one you own — and
    the resolution is a decision, not a default.
"""
from __future__ import annotations

import csv
import io
import json
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import (
    current_library,
    get_book_store,
    get_clock,
    get_decision_store,
    get_duplicate_queue,
    get_id_gen,
)
from app.api.dto import (
    BookCreate,
    BookDTO,
    BookPageDTO,
    BookPatch,
    CopyCreate,
    CopyPatch,
    LendRequest,
)
from app.domain import (
    Book,
    CopyAlreadyLentOut,
    CopyFields,
    CopyNotLentOut,
    Decision,
    DecisionKind,
    LibraryRef,
    Status,
    UnknownCopy,
    add_copy,
    approve,
    deletion_sites,
    edit,
    edit_copy,
    lend,
    new_book,
    return_copy,
)
from app.domain.search import matches, parse
from app.ports import Clock, IdGen
from app.ports.decisions import DecisionStore
from app.ports.duplicates import DuplicateQueue
from app.ports.store import BookSort, BookStore, DuplicateBookKey

router = APIRouter(prefix="/books", tags=["books"])

MAX_LIMIT = 200
EXPORT_MAX = 100_000

# The author list is a scan, same honest O(library) trade `EXPORT_MAX` and the
# diff endpoints already take: §6's sizes are a few thousand books, there is no
# author index to narrow with, and inventing one before it is measured to
# matter is the premature half of optimisation.
_AUTHOR_SCAN_LIMIT = 100_000
# Excel opens a UTF-8 CSV as mojibake without it, and "my export is broken" is
# then indistinguishable from "your data is broken".
UTF8_BOM = b"\xef\xbb\xbf"

# Anything a filesystem, a shell or the Content-Disposition grammar itself
# would choke on. Runs of whitespace become one hyphen, so the name has no
# spaces to quote around.
_UNSAFE_IN_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_WHITESPACE = re.compile(r"\s+")


def _download_name(library: LibraryRef, clock: Clock, ext: str) -> str:
    """``books-<library>-<YYYY-MM-DD>.<ext>``.

    The library's own name is in there because an export lands in a Downloads
    folder next to everyone else's files, and `booksnap-library.csv` twice is
    `booksnap-library (1).csv`. The date is the same argument over time — the
    file IS a snapshot, and a snapshot with no date is not one.
    """
    label = _WHITESPACE.sub("-", _UNSAFE_IN_FILENAME.sub("", library.label or
                                                         library.id).strip())
    day = clock.now_iso()[:10]  # ISO-8601: the date is the first ten chars
    return "-".join(part for part in ("books", label, day) if part) + f".{ext}"


def _disposition(name: str) -> str:
    """Both halves of RFC 6266, because the library name may be Hebrew.

    A bare ``filename=`` is ASCII-only, so a Hebrew name would arrive mangled
    or be dropped entirely; ``filename*`` carries the real one and every
    current browser prefers it. The ASCII fallback keeps the date rather than
    degrading to a generic name.
    """
    ascii_name = _WHITESPACE.sub("-", name.encode("ascii", "ignore")
                                 .decode("ascii")).strip("-") or "books.csv"
    ascii_name = re.sub(r"-+", "-", ascii_name).replace('"', "")
    return (f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(name, safe='')}")


def _load(store: BookStore, library: LibraryRef, book_id: str) -> Book:
    book = store.get(library, book_id)
    if book is None:
        # Absent and foreign are the same answer, deliberately (§4.2).
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such book")
    return book


def _save(store: BookStore, library: LibraryRef, book: Book) -> Book:
    try:
        store.save(library, book)
    except DuplicateBookKey as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return book


@router.get("", response_model=BookPageDTO, summary="List or search books")
def list_books(
    library: LibraryRef = Depends(current_library),
    store: BookStore = Depends(get_book_store),
    q: str | None = Query(None,
                          description="Hebrew search over title and author. "
                                      "When present the results are ordered by "
                                      "RELEVANCE and `sort`/`ascending` are "
                                      "ignored — the order is the answer."),
    sort: BookSort = Query(BookSort.TITLE,
                           description="title / author sort on the NORMALIZED "
                                       "forms, so Hebrew orders sensibly."),
    ascending: bool = Query(True),
    book_status: Status | None = Query(None, alias="status"),
    author_key: str | None = Query(None,
                                   description="Normalized author, from a "
                                               "book's author_key."),
    lent_out: bool | None = Query(None,
                                  description="True for the \"who has my "
                                              "books\" view: books with at "
                                              "least one copy currently lent "
                                              "out."),
    duplicates: bool = Query(False,
                             description="True for the \"duplicates to "
                                         "resolve\" queue (§5.4, P2.6): only "
                                         "books with at least one still-open "
                                         "copy-resolution question."),
    duplicate_queue: DuplicateQueue = Depends(get_duplicate_queue),
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> BookPageDTO:
    """One endpoint, two modes.

    Searching is not a filter on top of a sort — relevance IS the order, so a
    `sort` passed alongside `q` would be a promise the server cannot keep.
    It is ignored rather than rejected: a UI that keeps a sort control on
    screen while the user types should not start returning 400s mid-keystroke.
    The `duplicates` filter is ignored during a search too, same as every
    other filter here — the two are ORTHOGONAL views (find a book vs. review
    a queue), and combining them was never asked for.
    """
    if q is not None and q.strip():
        page = store.search(library, q, limit=limit, offset=offset)
    else:
        book_ids = None
        if duplicates:
            # BookStore has no idea what a "duplicate question" is (P2.6's
            # DuplicateQueue is a separate aggregate/port) -- composed here,
            # at the API layer, the same way reads.py composes across four
            # ports to build one diff. A book can have more than one open
            # question (ambiguous at two different locations); the SET of
            # distinct book ids is what the filter narrows to.
            book_ids = tuple({question.existing_book_id for question in
                              duplicate_queue.list_open_questions(library)})
        page = store.list(library, sort=sort, ascending=ascending,
                          status=book_status, author_key=author_key,
                          lent_out=lent_out, book_ids=book_ids,
                          limit=limit, offset=offset)
    return BookPageDTO(
        items=[BookDTO.of(b) for b in page.items],
        total=page.total, offset=page.offset, limit=page.limit,
    )


# Declared BEFORE /{book_id}: FastAPI matches in declaration order, so a
# literal path registered after a parameterised one is unreachable — "export"
# would arrive as a book id and 404. There is a test for this precisely
# because the bug is invisible until someone clicks Export.
@router.get("/authors", response_model=list[str],
            summary="Authors in the library, for an autocomplete")
def list_authors(
    library: LibraryRef = Depends(current_library),
    store: BookStore = Depends(get_book_store),
    q: str = Query("", description="What the owner is typing."),
    limit: int = Query(8, ge=1, le=50),
) -> list[str]:
    """The distinct authors already in this library, narrowed by ``q``.

    For the *"add a book the engine missed"* form (owner, 2026-08-09): typing
    an author you already own should complete, not be retyped — and retyped is
    how ``דויד גרוסמן`` and ``דוד גרוסמן`` end up as two authors that the
    author chip then treats as two people. The tuning UI grew the same control
    for the same reason (``booksnap/static/index.html``'s ``libAuthors``).

    Matching is `app.domain.search`'s, so "the search mechanism" means one
    thing across this codebase: the same particle tolerance and the same
    normalisation the book search and the finding lookup use.

    Returned in the AUTHOR's own spelling, never normalized — normalisation is
    for matching, and an autocomplete that filled in a nikud-stripped,
    final-letter-folded string would quietly rewrite the owner's own data.
    """
    query = parse(q)
    seen: dict[str, str] = {}
    for book in store.list(library, limit=_AUTHOR_SCAN_LIMIT).items:
        author = book.author.strip()
        if not author or book.normalized_author in seen:
            continue
        if query and not matches(query, book.normalized_author):
            continue
        seen[book.normalized_author] = author
    # Alphabetical on the normalized form: a list of names has no relevance
    # order worth inventing, and the same string must not move between two
    # keystrokes that both match it.
    return [seen[k] for k in sorted(seen)][:limit]


@router.get("/export", summary="Export the whole library (CSV or JSON)")
def export_books(
    library: LibraryRef = Depends(current_library),
    store: BookStore = Depends(get_book_store),
    clock: Clock = Depends(get_clock),
    format: str = Query("csv", pattern="^(csv|json)$"),
) -> Response:
    """The honest answer to lock-in (§6): everything, in one file, always.

    CSV is written with a UTF-8 BOM. Without it Excel opens a Hebrew CSV as
    mojibake, and "my export is broken" is indistinguishable from "your data
    is broken".
    """
    books = list(store.list(library, limit=EXPORT_MAX).items)
    if format == "json":
        body = json.dumps(
            {"library": library.id,
             "books": [BookDTO.of(b).model_dump() for b in books]},
            ensure_ascii=False, indent=1,
        ).encode("utf-8")
        return Response(
            body, media_type="application/json; charset=utf-8",
            headers={"Content-Disposition":
                     _disposition(_download_name(library, clock, "json"))},
        )

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["title", "author", "status", "copies", "added_at",
                     "shelf_ids", "tags"])
    for b in books:
        writer.writerow([
            b.title, b.author, b.status.value, b.copy_count, b.added_at or "",
            " ".join(c.shelf_id for c in b.copies if c.shelf_id),
            " ".join(t for c in b.copies for t in c.fields.tags),
        ])
    return Response(
        UTF8_BOM + buf.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 _disposition(_download_name(library, clock, "csv"))},
    )


@router.post("", response_model=BookDTO,
             status_code=status.HTTP_201_CREATED, summary="Add a book by hand")
def create_book(
    payload: BookCreate,
    library: LibraryRef = Depends(current_library),
    store: BookStore = Depends(get_book_store),
    clock: Clock = Depends(get_clock),
    ids: IdGen = Depends(get_id_gen),
) -> BookDTO:
    """A book the reader never found. Lands as ``manual`` — a person typed it,
    which is the strongest evidence the system gets."""
    book_id = ids.new_id()
    book = new_book(
        id=book_id,
        library_id=library.id,
        title=payload.title.strip(),
        author=payload.author.strip(),
        copy_id=ids.new_id(),
        status=Status.MANUAL,
        added_at=clock.now_iso(),
    )
    return BookDTO.of(_save(store, library, book))


@router.get("/{book_id}", response_model=BookDTO, summary="One book")
def get_book(
    book_id: str,
    library: LibraryRef = Depends(current_library),
    store: BookStore = Depends(get_book_store),
) -> BookDTO:
    return BookDTO.of(_load(store, library, book_id))


@router.patch("/{book_id}", response_model=BookDTO,
              summary="Fix the title or author")
def patch_book(
    book_id: str,
    payload: BookPatch,
    library: LibraryRef = Depends(current_library),
    store: BookStore = Depends(get_book_store),
) -> BookDTO:
    """Editing marks the book ``manual`` (UI_PLAN §5). The domain applies
    that; this route only decides what an unresolvable rename returns."""
    book = _load(store, library, book_id)
    if payload.title is None and payload.author is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "nothing to change: send title and/or author")
    updated = edit(
        book,
        title=payload.title.strip() if payload.title is not None else None,
        author=payload.author.strip() if payload.author is not None else None,
    )
    return BookDTO.of(_save(store, library, updated))


@router.post("/{book_id}/approve", response_model=BookDTO,
             summary="Confirm the claim — auto becomes approved")
def approve_book(
    book_id: str,
    library: LibraryRef = Depends(current_library),
    store: BookStore = Depends(get_book_store),
) -> BookDTO:
    """*"✓ — yes, that is the book"* (P2.10, §12.2 #10).

    The middle rung of §5.1's ladder, and the one the product had no route to
    until the image workspace needed it: a book the engine claimed at AUTO
    sits unexamined until a human looks at the photo and says so. Approving
    is what makes the "a human decision outranks an auto one" rule mean
    something on a per-book basis — and `Status.merge` is what makes this
    safe to press twice, or on a book already edited by hand: it never lowers
    a rung.

    No copy_id parameter: approving is about the RECORD's identity (is this
    the right book?), which is book-level, exactly like `patch_book`'s edit.
    Per-copy metadata has its own route.
    """
    return BookDTO.of(_save(store, library, approve(_load(store, library, book_id))))


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete from the library (every copy)")
def delete_book(
    book_id: str,
    library: LibraryRef = Depends(current_library),
    store: BookStore = Depends(get_book_store),
    decisions: DecisionStore = Depends(get_decision_store),
    clock: Clock = Depends(get_clock),
) -> Response:
    """*Delete from the library* — the destructive one of UI_PLAN §5's two
    actions. *Remove from shelf* is a different thing entirely and does not
    live here; it changes a copy, it does not remove a record.

    **It also records a standing "no" wherever the book stood** (owner,
    2026-08-10). Two things were wrong without it, and they are the same
    thing seen from both ends:

      - §5.6 says a rejected book must not be re-added by a later run, and
        deleting is the plainest rejection the product offers — but it wrote
        no decision, so the next read of that shelf would put the book
        straight back;
      - the finding that produced it reverted to an ordinary unanswered
        question. The owner asked for what is actually true: the finding
        should read as **removed** — struck through, with its undo — which is
        exactly how `reconcile()` reports a claim a standing decision
        suppresses.

    `REJECTED`, not `WRONG_BOOK`: the two suppress identically and the kind is
    the audit trail of WHICH question was answered
    (:class:`~app.domain.reconcile.DecisionKind`). Deleting answers "I do not
    have this book", not §5.4's "is this the copy I already have".

    Undo is the workspace's ↩ (`POST .../findings/{id}/restore`), which
    clears the decision and lets the read apply itself again — the book comes
    back as the pending finding it was, not as a record nobody approved.
    """
    book = store.get(library, book_id)
    if book is None or not store.delete(library, book_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such book")
    now = clock.now_iso()
    for shelf_id, depth in deletion_sites(book):
        decisions.save_decision(library, Decision(
            library_id=library.id, shelf_id=shelf_id, depth=depth,
            book_key=book.key, kind=DecisionKind.REJECTED, decided_at=now,
        ))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- copies (P1.7) ---------------------------------------------------------
#
# Every route below returns the whole BookDTO, not a CopyDTO — the client
# store replaces one record and every surface showing that book repaints
# (UI_PLAN §5's "edit it anywhere, it changes everywhere"). A response
# carrying only the changed copy would force the client to reassemble the
# book itself, which is exactly the kind of logic H3 keeps out of the client.

def _apply_to_copy(fn, book: Book, *args: object, **kwargs: object) -> Book:
    """Run a copy-level domain operation, mapping its errors to HTTP.

    One mapping shared by every route below rather than four copies of the
    same except block: an unknown copy id is a 404 (same reasoning as a
    foreign book, §4.2), and both lending-state violations are 409s — the
    request is well-formed, but the copy's current state refuses it, same
    shape as a rename onto a book you already own.
    """
    try:
        return fn(book, *args, **kwargs)
    except UnknownCopy as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such copy") from exc
    except (CopyAlreadyLentOut, CopyNotLentOut) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/{book_id}/copies", response_model=BookDTO,
             status_code=status.HTTP_201_CREATED,
             summary='"I have another copy"')
def create_copy(
    book_id: str,
    payload: CopyCreate,
    library: LibraryRef = Depends(current_library),
    store: BookStore = Depends(get_book_store),
    ids: IdGen = Depends(get_id_gen),
) -> BookDTO:
    """§5.1: the ONLY path that creates a second copy. Lands ``manual`` — a
    person declaring a duplicate is the strongest evidence the system gets;
    no re-read can produce this (`app.domain.book.add_copy`)."""
    book = _load(store, library, book_id)
    updated = add_copy(
        book, copy_id=ids.new_id(), label=payload.label.strip(),
        fields=CopyFields(
            tags=tuple(t.strip() for t in payload.tags if t.strip()),
            condition=payload.condition.strip(),
        ),
    )
    return BookDTO.of(_save(store, library, updated))


@router.patch("/{book_id}/copies/{copy_id}", response_model=BookDTO,
              summary="Fix a copy's label, tags or condition")
def patch_copy(
    book_id: str,
    copy_id: str,
    payload: CopyPatch,
    library: LibraryRef = Depends(current_library),
    store: BookStore = Depends(get_book_store),
) -> BookDTO:
    """Object-level metadata, not identity — unlike :func:`patch_book` this
    never changes the copy's status (`app.domain.book.edit_copy`)."""
    book = _load(store, library, book_id)
    updated = _apply_to_copy(
        edit_copy, book, copy_id,
        label=payload.label.strip() if payload.label is not None else None,
        tags=(tuple(t.strip() for t in payload.tags if t.strip())
              if payload.tags is not None else None),
        condition=(payload.condition.strip()
                  if payload.condition is not None else None),
    )
    return BookDTO.of(_save(store, library, updated))


@router.post("/{book_id}/copies/{copy_id}/lend", response_model=BookDTO,
             summary="Lend a copy out")
def lend_copy(
    book_id: str,
    copy_id: str,
    payload: LendRequest,
    library: LibraryRef = Depends(current_library),
    store: BookStore = Depends(get_book_store),
    clock: Clock = Depends(get_clock),
) -> BookDTO:
    """409 if the copy is already out — return it first (§5.2: one borrower
    per copy, or the earlier one is silently lost from "who has my books")."""
    book = _load(store, library, book_id)
    updated = _apply_to_copy(
        lend, book, copy_id,
        lent_to=payload.lent_to.strip(), lent_at=clock.now_iso(),
        due_at=payload.due_at,
    )
    return BookDTO.of(_save(store, library, updated))


@router.post("/{book_id}/copies/{copy_id}/return", response_model=BookDTO,
             summary="Mark a lent copy returned")
def return_copy_route(
    book_id: str,
    copy_id: str,
    library: LibraryRef = Depends(current_library),
    store: BookStore = Depends(get_book_store),
    clock: Clock = Depends(get_clock),
) -> BookDTO:
    """409 if the copy was never lent, or already marked returned — there is
    no open loan to close (`app.domain.book.return_copy`)."""
    book = _load(store, library, book_id)
    updated = _apply_to_copy(return_copy, book, copy_id,
                             returned_at=clock.now_iso())
    return BookDTO.of(_save(store, library, updated))
