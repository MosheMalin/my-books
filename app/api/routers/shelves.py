# -*- coding: utf-8 -*-
"""/api/v1/shelves and /api/v1/captures — capture → shelf binding (P2.2).

THIN by rule (H3), same as ``books.py``: the decisions live in
``app/domain/shelf.py`` and in the store contract, and what is here is the HTTP
shape. Two mappings carry meaning rather than convention:

  - a shelf in another library is **404, not 403** (§4.2). The store returns it
    as absent, so the route cannot leak existence even by accident;
  - deleting a shelf that still has photos is **409**, not a cascade. Its
    captures are the record a re-read diffs against (§5.6), and destroying them
    on a misclick is precisely the direction the whole design refuses.

**The binding, which is the item.** ``POST /captures`` may omit ``shelf_id``,
and then a fresh unnamed shelf is created for the photo. That is not a
convenience — a capture with no shelf is a read with nothing to reconcile
against, so "assign it later" is deliberately not a state the model offers.
*Unassigned* on screen means *not yet named*.

⚠ One image = one shelf is a PLACEHOLDER (plan P6.1b). Pillar 6 lets the owner
merge shelf identities once the map can show that two of them are the same
piece of furniture, so nothing here may treat a shelf id as permanent.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    get_book_store,
    get_clock,
    get_id_gen,
    get_read_store,
    get_shelf_store,
)
from app.api.dto import (
    BookDTO,
    CaptureBinding,
    CaptureCreate,
    CaptureDTO,
    CapturePatch,
    DepthStatusDTO,
    ReadSummaryDTO,
    ShelfCreate,
    ShelfDTO,
    ShelfOverviewDTO,
    ShelfPatch,
)
from app.api.policy import require
from app.domain import (
    Capability,
    Book,
    Capture,
    Copy,
    LibraryRef,
    Shelf,
    add_depth,
    capture_onto_a_new_shelf,
    depth_staleness,
    new_capture,
    new_shelf,
    not_seen_streak,
    rename_shelf,
)
from app.domain.shelf import UnknownDepth
from app.ports import Clock, IdGen
from app.ports.store import (
    BookStore,
    DuplicateCaptureSlot,
    ReadStore,
    ShelfNotEmpty,
    ShelfStore,
    UnknownShelf,
)

# One shelf view at a time (a personal library's own §6 sizes), and no
# shelf/depth filter on BookStore.list (P2.5 chose not to add one — see
# reads.py's own `_FULL_LIBRARY_SCAN_LIMIT`) — so `shelf_books` below accepts
# the same honest O(library) trade rather than inventing a second, divergent
# narrowing strategy for a query this rare.
_FULL_LIBRARY_SCAN_LIMIT = 100_000

# The engine's own spine ids encode a left-to-right position within a band
# (`IMG_1234_b0_s07`, `segment.py`) — the closest thing to a stored physical
# order that exists today. See `_physical_order_key`.
_SPINE_INDEX = re.compile(r"(\d+)\s*$")

router = APIRouter(prefix="/shelves", tags=["shelves"])
# Captures get their own root because binding MOVES one between shelves: a
# path that nests the capture under its current shelf would make "change the
# shelf" a change of the resource's own address.
captures = APIRouter(prefix="/captures", tags=["captures"])


def _load(store: ShelfStore, library: LibraryRef, shelf_id: str) -> Shelf:
    shelf = store.get_shelf(library, shelf_id)
    if shelf is None:
        # Absent and foreign are the same answer, deliberately (§4.2).
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such shelf")
    return shelf


def _load_capture(store: ShelfStore, library: LibraryRef, cap_id: str) -> Capture:
    capture = store.get_capture(library, cap_id)
    if capture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such capture")
    return capture


def _dto(store: ShelfStore, library: LibraryRef, shelf: Shelf) -> ShelfDTO:
    return ShelfDTO.of(shelf,
                       capture_count=len(store.list_captures(library, shelf.id)))


def _next_order(store: ShelfStore, library: LibraryRef, shelf_id: str,
                depth: int) -> int:
    """Append after the last photo at this shelf+depth.

    Computed rather than asked for: the intake flow is "photograph the shelf
    left to right", so the caller almost never has an opinion, and making it
    supply one invites two clients disagreeing about the next number.
    """
    here = store.list_captures(library, shelf_id, depth=depth)
    return max((c.order for c in here), default=-1) + 1


def _save_capture(store: ShelfStore, library: LibraryRef, capture: Capture) -> Capture:
    try:
        store.save_capture(library, capture)
    except DuplicateCaptureSlot as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except UnknownShelf as exc:
        # A shelf id from another library lands here too, and answers 404 —
        # the same answer as one that never existed (§4.2).
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return capture


# --- shelves --------------------------------------------------------------

@router.get("", response_model=list[ShelfDTO])
def list_shelves(
    include_virtual: bool = Query(
        False,
        description="Include the wishlist. Excluded by default: it holds books "
                    "the owner does not own, so counting it inflates both the "
                    "shelf list and the apparent size of the library.",
    ),
    library: LibraryRef = Depends(require(Capability.BROWSE)),
    store: ShelfStore = Depends(get_shelf_store),
) -> list[ShelfDTO]:
    """Every shelf, named ones first and alphabetically, then unnamed ones
    oldest-first. Not paged — a personal library has tens of shelves."""
    return [_dto(store, library, s)
            for s in store.list_shelves(library, include_virtual=include_virtual)]


@router.post("", response_model=ShelfDTO, status_code=status.HTTP_201_CREATED)
def create_shelf(
    body: ShelfCreate,
    library: LibraryRef = Depends(require(Capability.CAPTURE)),
    store: ShelfStore = Depends(get_shelf_store),
    clock: Clock = Depends(get_clock),
    id_gen: IdGen = Depends(get_id_gen),
) -> ShelfDTO:
    """Declare a shelf up front. Every field is optional (identity is free).

    Depth is not settable here on purpose — a shelf starts one row deep and
    gains rows through :func:`add_a_row_behind`, because §5.7 makes the second
    row a declaration rather than a number to guess at during creation.
    """
    shelf = new_shelf(
        id=id_gen.new_id(),
        library_id=library.id,
        label=body.label,
        virtual=body.virtual,
        created_at=clock.now_iso(),
    )
    store.save_shelf(library, shelf)
    return _dto(store, library, shelf)


@router.get("/{shelf_id}", response_model=ShelfDTO)
def get_shelf(
    shelf_id: str,
    library: LibraryRef = Depends(require(Capability.BROWSE)),
    store: ShelfStore = Depends(get_shelf_store),
) -> ShelfDTO:
    return _dto(store, library, _load(store, library, shelf_id))


@router.patch("/{shelf_id}", response_model=ShelfDTO)
def patch_shelf(
    shelf_id: str,
    body: ShelfPatch,
    library: LibraryRef = Depends(require(Capability.CAPTURE)),
    store: ShelfStore = Depends(get_shelf_store),
) -> ShelfDTO:
    """Name a shelf, or clear the name — ``""`` is a legal value, not a
    missing one, because a label the owner no longer wants should not be kept
    just to avoid an empty string."""
    shelf = _load(store, library, shelf_id)
    if body.label is not None:
        shelf = rename_shelf(shelf, body.label)
        store.save_shelf(library, shelf)
    return _dto(store, library, shelf)


@router.post("/{shelf_id}/depths", response_model=ShelfDTO)
def add_a_row_behind(
    shelf_id: str,
    library: LibraryRef = Depends(require(Capability.CAPTURE)),
    store: ShelfStore = Depends(get_shelf_store),
) -> ShelfDTO:
    """*"Add a row behind this one"* (§5.7) — the declaration that cannot be
    detected, because nothing in a photo says "this is the row behind"; the
    front books are simply absent.

    Its own endpoint rather than a ``depth_count`` field so the client cannot
    set it to 5 in one step and leave three rows nobody photographed. Refused
    on the wishlist, which has no behind.
    """
    shelf = _load(store, library, shelf_id)
    try:
        deeper = add_depth(shelf)
    except Exception as exc:  # VirtualShelfHasNoDepth — the wishlist
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    store.save_shelf(library, deeper)
    return _dto(store, library, deeper)


@router.delete("/{shelf_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shelf(
    shelf_id: str,
    library: LibraryRef = Depends(require(Capability.CAPTURE)),
    store: ShelfStore = Depends(get_shelf_store),
) -> None:
    """Remove a shelf that holds no photos. **409** if it does.

    Not a cascade: its captures are the record a re-read diffs against (§5.6).
    This is for the shelf created by mistake, not for clearing one out.
    """
    try:
        removed = store.delete_shelf(library, shelf_id)
    except ShelfNotEmpty as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such shelf")


@router.get("/{shelf_id}/captures", response_model=list[CaptureDTO])
def list_shelf_captures(
    shelf_id: str,
    depth: int | None = Query(
        None, ge=1,
        description="Narrow to one row front-to-back. §5.6's not-seen rule and "
                    "the diff view are per depth, and §5.7 #2 forbids merging "
                    "overlaps across depths.",
    ),
    library: LibraryRef = Depends(require(Capability.BROWSE)),
    store: ShelfStore = Depends(get_shelf_store),
) -> list[CaptureDTO]:
    _load(store, library, shelf_id)   # 404 for a foreign or absent shelf
    return [CaptureDTO.of(c)
            for c in store.list_captures(library, shelf_id, depth=depth)]


# --- the shelf-detail screen (P2.8, UI_PLAN §3 level 3) --------------------

@router.get("/{shelf_id}/overview", response_model=ShelfOverviewDTO)
def shelf_overview(
    shelf_id: str,
    library: LibraryRef = Depends(require(Capability.BROWSE)),
    store: ShelfStore = Depends(get_shelf_store),
    reads: ReadStore = Depends(get_read_store),
) -> ShelfOverviewDTO:
    """Declared depth, plus the soft staleness line (UI_PLAN §3: *"rows 2, 3
    not read since 11.3.2026"*) — every declared row, whether or not it was
    ever read, so the depth bar can show ALL of them (§5.7: always visible,
    even at ``depth_count`` 1)."""
    shelf = _load(store, library, shelf_id)
    all_reads = reads.list_reads(library, shelf_id)  # every depth, not narrowed
    statuses = [DepthStatusDTO.of(s)
               for s in depth_staleness(shelf.depth_count, all_reads)]
    return ShelfOverviewDTO.of(
        shelf, capture_count=len(store.list_captures(library, shelf_id)),
        depths=statuses,
    )


def _physical_order_key(book: Book, copy: Copy) -> tuple[bool, int, str, str]:
    """Best-effort left-to-right order for "books at a depth" (UI_PLAN §3).

    No TRUE physical position is stored anywhere yet: a claim's bounding box
    (`Claim.box`) lives only on the live read that produced it (P2.4) and is
    never carried onto a `Copy`/`Provenance` once applied. So this proxies
    from the engine's own spine id, which already encodes a left-to-right
    index within its band (``IMG_1234_b0_s07``) — parsed numerically so
    spine 2 sorts before spine 10, not after. A copy with no spine id at all
    (a manual add, or a legacy import with no spine — CLAUDE.md's P1.3 note)
    sorts after everything that has one, title as the final tiebreak so the
    order is at least stable and alphabetic rather than arbitrary.
    """
    spine_id = copy.last_seen.spine_id if copy.last_seen else ""
    match = _SPINE_INDEX.search(spine_id)
    index = int(match.group(1)) if match else -1
    return (spine_id == "", index, spine_id, book.title)


@router.get("/{shelf_id}/books", response_model=list[BookDTO])
def shelf_books(
    shelf_id: str,
    depth: int = Query(
        1, ge=1,
        description="Which row front-to-back (§5.7 #1 — there is no "
                    "'every depth' view of a shelf's books; a mixed list "
                    "would conflate two different physical locations).",
    ),
    library: LibraryRef = Depends(require(Capability.BROWSE)),
    store: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
    reads: ReadStore = Depends(get_read_store),
) -> list[BookDTO]:
    """The books standing at ONE (shelf, depth), in physical order (best
    effort — see :func:`_physical_order_key`), each copy annotated with its
    own soft *"not seen in the last N reads"* streak (§5.6 option 2, scoped
    to this depth per §5.7 #1 — `app.domain.history.not_seen_streak`).

    This is the durable list of §5.6: a book stays here until a human removes
    it (``remove_from_shelf``), never because a read failed to reconfirm it.
    """
    shelf = _load(store, library, shelf_id)
    try:
        shelf.check_depth(depth)
    except UnknownDepth as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    all_books = books.list(library, limit=_FULL_LIBRARY_SCAN_LIMIT).items
    here: list[tuple[Book, Copy]] = [
        (b, c) for b in all_books for c in b.copies
        if c.location == (shelf_id, depth)
    ]
    here.sort(key=lambda pair: _physical_order_key(*pair))

    shelf_reads = reads.list_reads(library, shelf_id, depth=depth)
    return [
        BookDTO.of(b, streaks={c.id: not_seen_streak(c, shelf_id, depth, shelf_reads)})
        for b, c in here
    ]


# --- captures -------------------------------------------------------------

@captures.post("", response_model=CaptureBinding,
               status_code=status.HTTP_201_CREATED)
def create_capture(
    body: CaptureCreate,
    library: LibraryRef = Depends(require(Capability.CAPTURE)),
    store: ShelfStore = Depends(get_shelf_store),
    clock: Clock = Depends(get_clock),
    id_gen: IdGen = Depends(get_id_gen),
) -> CaptureBinding:
    """File a photo — with a shelf if one is named, on a fresh one if not.

    Returns BOTH the capture and its shelf: when the shelf was auto-created the
    client has no other way to learn its id, and a second round trip to
    discover the thing you just implicitly made is what gets papered over with
    a client-side guess.
    """
    now = clock.now_iso()
    if body.shelf_id is None:
        shelf, capture = capture_onto_a_new_shelf(
            shelf_id=id_gen.new_id(),
            library_id=library.id,
            capture_id=id_gen.new_id(),
            image_id=body.image_id,
            captured_at=now,
        )
        # Order stays 0 — a brand-new shelf has no other photo to follow.
        store.save_shelf(library, shelf)
        _save_capture(store, library, capture)
        return CaptureBinding(capture=CaptureDTO.of(capture),
                              shelf=_dto(store, library, shelf),
                              shelf_created=True)

    shelf = _load(store, library, body.shelf_id)
    capture = _build_capture(
        store, library, shelf, id_gen.new_id(),
        depth=body.depth, order=body.order, image_id=body.image_id,
        captured_at=now,
    )
    _save_capture(store, library, capture)
    return CaptureBinding(capture=CaptureDTO.of(capture),
                          shelf=_dto(store, library, shelf),
                          shelf_created=False)


@captures.get("/{capture_id}", response_model=CaptureDTO)
def get_capture(
    capture_id: str,
    library: LibraryRef = Depends(require(Capability.BROWSE)),
    store: ShelfStore = Depends(get_shelf_store),
) -> CaptureDTO:
    return CaptureDTO.of(_load_capture(store, library, capture_id))


@captures.get("/{capture_id}/reads", response_model=list[ReadSummaryDTO])
def list_capture_reads(
    capture_id: str,
    library: LibraryRef = Depends(require(Capability.BROWSE)),
    store: ShelfStore = Depends(get_shelf_store),
    reads: ReadStore = Depends(get_read_store),
) -> list[ReadSummaryDTO]:
    """Every run that read this photo, most recent first — P2.10's *"clicking
    an image opens its runs"* (§12.2 #10).

    The one place the product answers a run-shaped question, and it is
    deliberate rather than a reversal of §5.5 ("a run is not a user-facing
    concept"): §12.2 #10 settles that the split is by SURFACE. Books and the
    shelf view stay run-free; the Capture tab is where the owner is doing the
    cataloguing and the unit of work IS the photograph, so its history hangs
    off the image. There is still no global list of runs anywhere.

    Reads are matched on the capture, not on its current shelf — see
    ``ReadStore.list_reads_for_capture`` for why a re-bound photo must keep
    the runs that already read it.
    """
    _load_capture(store, library, capture_id)   # 404 for a foreign or absent one
    return [ReadSummaryDTO.of(r)
            for r in reads.list_reads_for_capture(library, capture_id)]


@captures.patch("/{capture_id}", response_model=CaptureBinding)
def bind_capture(
    capture_id: str,
    body: CapturePatch,
    library: LibraryRef = Depends(require(Capability.CAPTURE)),
    store: ShelfStore = Depends(get_shelf_store),
) -> CaptureBinding:
    """Move a photo to another shelf, another row, or another position.

    This is the inline assignment the intake UI performs. Moving to a shelf
    that is not one row deeper than the caller thinks is a **409** naming the
    declared depth, not a silent clamp: filing a photo at a row that does not
    exist would give reconciliation a location with no counterpart in the room.
    """
    capture = _load_capture(store, library, capture_id)
    target_id = body.shelf_id if body.shelf_id is not None else capture.shelf_id
    shelf = _load(store, library, target_id)
    depth = body.depth if body.depth is not None else capture.depth

    order = body.order
    if order is None:
        # Moving to a different shelf or row means the old position is
        # meaningless; staying put means keep it.
        moved = (target_id != capture.shelf_id) or (depth != capture.depth)
        order = _next_order(store, library, target_id, depth) if moved \
            else capture.order

    rebound = _build_capture(
        store, library, shelf, capture.id, depth=depth, order=order,
        image_id=capture.image_id, captured_at=capture.captured_at,
    )
    _save_capture(store, library, rebound)
    return CaptureBinding(capture=CaptureDTO.of(rebound),
                          shelf=_dto(store, library, shelf),
                          shelf_created=False)


@captures.delete("/{capture_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_capture(
    capture_id: str,
    library: LibraryRef = Depends(require(Capability.CAPTURE)),
    store: ShelfStore = Depends(get_shelf_store),
) -> None:
    if not store.delete_capture(library, capture_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such capture")


def _build_capture(
    store: ShelfStore,
    library: LibraryRef,
    shelf: Shelf,
    capture_id: str,
    *,
    depth: int,
    order: int | None,
    image_id: str | None,
    captured_at: str | None,
) -> Capture:
    """``new_capture`` plus the HTTP mapping of its one refusal.

    The depth check is the domain's — ``new_capture`` takes the whole Shelf
    precisely so an undeclared depth cannot enter the system — and all this
    adds is the status code.
    """
    try:
        return new_capture(
            shelf, id=capture_id, depth=depth,
            order=(_next_order(store, library, shelf.id, depth)
                   if order is None else order),
            image_id=image_id, captured_at=captured_at,
        )
    except UnknownDepth as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
