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

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import current_library, get_book_store, get_clock, get_id_gen
from app.api.dto import BookCreate, BookDTO, BookPageDTO, BookPatch
from app.domain import Book, LibraryRef, Status, edit, new_book
from app.ports import Clock, IdGen
from app.ports.store import BookSort, BookStore, DuplicateBookKey

router = APIRouter(prefix="/books", tags=["books"])

MAX_LIMIT = 200
EXPORT_MAX = 100_000
# Excel opens a UTF-8 CSV as mojibake without it, and "my export is broken" is
# then indistinguishable from "your data is broken".
UTF8_BOM = b"\xef\xbb\xbf"


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
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> BookPageDTO:
    """One endpoint, two modes.

    Searching is not a filter on top of a sort — relevance IS the order, so a
    `sort` passed alongside `q` would be a promise the server cannot keep.
    It is ignored rather than rejected: a UI that keeps a sort control on
    screen while the user types should not start returning 400s mid-keystroke.
    """
    if q is not None and q.strip():
        page = store.search(library, q, limit=limit, offset=offset)
    else:
        page = store.list(library, sort=sort, ascending=ascending,
                          status=book_status, author_key=author_key,
                          limit=limit, offset=offset)
    return BookPageDTO(
        items=[BookDTO.of(b) for b in page.items],
        total=page.total, offset=page.offset, limit=page.limit,
    )


# Declared BEFORE /{book_id}: FastAPI matches in declaration order, so a
# literal path registered after a parameterised one is unreachable — "export"
# would arrive as a book id and 404. There is a test for this precisely
# because the bug is invisible until someone clicks Export.
@router.get("/export", summary="Export the whole library (CSV or JSON)")
def export_books(
    library: LibraryRef = Depends(current_library),
    store: BookStore = Depends(get_book_store),
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
                     'attachment; filename="booksnap-library.json"'},
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
                 'attachment; filename="booksnap-library.csv"'},
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


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete from the library (every copy)")
def delete_book(
    book_id: str,
    library: LibraryRef = Depends(current_library),
    store: BookStore = Depends(get_book_store),
) -> Response:
    """*Delete from the library* — the destructive one of UI_PLAN §5's two
    actions. *Remove from shelf* is a different thing entirely and does not
    live here; it changes a copy, it does not remove a record."""
    if not store.delete(library, book_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such book")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
