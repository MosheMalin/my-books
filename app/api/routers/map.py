# -*- coding: utf-8 -*-
"""/api/v1/map — the physical map (P6.2, MAP_PLAN §3).

THIN by rule (H3), like every router here: the decisions live in
``app/domain/place.py`` and the multi-store orchestration in
``app/map_edit.py``, and what is here is the HTTP shape. Four mappings carry
meaning rather than convention:

  - **the drawing is READ whole and WRITTEN one object at a time.** ``GET
    /map`` is the plan screen's only query; every write names one object. A
    "save the whole plan" route would make the last tab to press a key the
    winner of every disagreement, and the lab showed that a plan is edited in
    bursts of tiny changes;
  - an object in another library is **404, not 403** (§4.2), before any
    capability check. The store returns it as absent, so the route cannot leak
    existence even by accident;
  - **409 for a refusal, never a cascade.** Removing a storey with rooms on
    it, or a bookcase with shelves still standing in it, answers 409 with the
    counts. Nothing here auto-removes;
  - **a structural edit reports what it cost the shelves.** Removing a column
    removes real ``Shelf`` rows (§3.1), so the response says which were
    deleted and which SURVIVED unaddressed — the owner is entitled to know a
    shelf did not vanish.

⚠ Two capabilities, and only two. Reading the map is ``BROWSE``; every write
is ``EDIT_MAP``, §4.2's row 7, which has been in the policy matrix since P4.0
waiting for exactly these routes.

**[DECIDED 2026-08-16 — owner] Reading the map stays BROWSE**, and it was
argued before it was decided. A security review put the case for Editor+:
``VIEW_PHOTOS`` is deliberately Editor+ because *"the photos show the inside
of a home, and 'viewer' may mean a friend browsing what you own"*, and a
labelled floor plan is arguably a more legible disclosure than a photograph —
room names, their positions and sizes, and where every bookcase stands.

The owner overruled it: **everyone who can see the books sees the map.** The
map exists to answer *"where is my book"* (P6.5), and a viewer who can find a
title but not walk to it has been handed half a feature. So this is a
decision on record rather than an oversight — do not "tighten" it without
asking, and note the asymmetry the review cited runs the other way too:
nothing here has been shown to anybody yet.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_book_store,
    get_clock,
    get_id_gen,
    get_map_store,
    get_shelf_store,
)
from app.api.dto import (
    BookcaseCreate,
    BookcaseDrawnDTO,
    BookcaseDTO,
    BookcasePatch,
    DepthApplyDTO,
    FloorCreate,
    FloorDTO,
    FloorPatch,
    MapDTO,
    PlaceCreate,
    PlaceDTO,
    PlacePatch,
    SectionCreate,
    SectionDTO,
    SectionEditDTO,
    SectionPatch,
    ShelfDTO,
    SiteCreate,
    SiteDTO,
    SitePatch,
    SlotDepthPatch,
    SlotRemovalDTO,
)
from app.api.policy import require
from app.domain import (
    Bookcase,
    Capability,
    DomainError,
    Floor,
    LibraryRef,
    NotEmpty,
    Place,
    Section,
    ShelfAddress,
    Site,
    TooManySlots,
    apply_default_levels,
    check_bookcase_size,
    new_bookcase,
    new_floor,
    new_place,
    new_section,
    new_site,
    next_section,
    renumber_sections,
    with_column_count,
    with_column_levels,
    with_default_depth,
    with_default_levels,
)
from app.domain.place import NotOnThisFloor
from app.map_edit import (
    apply_depth_default,
    deepest_occupied_depths,
    apply_slot_change,
    attach_case_to_room,
    clear_bookcase_slots,
    clear_section_slots,
    draw_bookcase,
)
from app.ports import Clock, IdGen
from app.ports.map import MapStore
from app.ports.store import (
    BookStore,
    DuplicateSectionOrdinal,
    ShelfStore,
    UnknownParent,
)

router = APIRouter(prefix="/map", tags=["map"])

READ = Capability.BROWSE
EDIT = Capability.EDIT_MAP


def _gone(what: str) -> HTTPException:
    """Absent and foreign are the same answer (§4.2)."""
    return HTTPException(status.HTTP_404_NOT_FOUND, f"no such {what}")


def _site(store: MapStore, library: LibraryRef, site_id: str) -> Site:
    got = store.get_site(library, site_id)
    if got is None:
        raise _gone("site")
    return got


def _floor(store: MapStore, library: LibraryRef, floor_id: str) -> Floor:
    got = store.get_floor(library, floor_id)
    if got is None:
        raise _gone("floor")
    return got


def _place(store: MapStore, library: LibraryRef, place_id: str) -> Place:
    got = store.get_place(library, place_id)
    if got is None:
        raise _gone("place")
    return got


def _bookcase(store: MapStore, library: LibraryRef, case_id: str) -> Bookcase:
    got = store.get_bookcase(library, case_id)
    if got is None:
        raise _gone("bookcase")
    return got


def _section(store: MapStore, library: LibraryRef, section_id: str) -> Section:
    got = store.get_section(library, section_id)
    if got is None:
        raise _gone("section")
    return got


@contextmanager
def _translated():
    """Turn the domain's and the stores' refusals into the right status.

    ⚠ It wraps the CONSTRUCTION as well as the write, and that is the fix a
    review measured: `Site.__post_init__` and `dataclasses.replace` both
    validate, both sat outside the old `try`, and seven ordinary inputs — a
    whitespace name, `front="Q"` — answered **500**. A mutating route that
    answers 500 is one the phone client cannot classify, so it retries.

    ``UnknownParent`` is 404 rather than 400: a client naming a floor that is
    not there is naming something that, as far as this library is concerned,
    does not exist — the same answer §4.2 gives for a foreign one.
    """
    try:
        yield
    except UnknownParent as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (NotOnThisFloor, NotEmpty, TooManySlots,
            DuplicateSectionOrdinal) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _remove(delete, library: LibraryRef, record_id: str, what: str) -> None:
    # 409 (via `_translated`) carries the message that says WHAT is in the
    # way — "cannot delete" with no reason is what makes the next reader
    # delete the guard.
    with _translated():
        removed = delete(library, record_id)
    if not removed:
        raise _gone(what)


# --- the whole drawing ----------------------------------------------------

@router.get("", response_model=MapDTO)
def get_map(
    library: LibraryRef = Depends(require(READ)),
    store: MapStore = Depends(get_map_store),
) -> MapDTO:
    """Every site, floor, room, bookcase and section of this library.

    One call, because that is what an editor needs and because a house is
    tens of rows. An undrawn library answers with empty lists, which is the
    normal state and not an error.
    """
    return MapDTO.of(store.load_map(library))


# --- sites ----------------------------------------------------------------

@router.post("/sites", response_model=SiteDTO,
             status_code=status.HTTP_201_CREATED)
def create_site(
    body: SiteCreate,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    ids: IdGen = Depends(get_id_gen),
) -> SiteDTO:
    with _translated():
        site = new_site(id=ids.new_id(), library_id=library.id,
                        name=body.name, order=body.order)
        store.save_site(library, site)
    return SiteDTO.of(site)


@router.patch("/sites/{site_id}", response_model=SiteDTO)
def patch_site(
    site_id: str,
    body: SitePatch,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
) -> SiteDTO:
    site = _site(store, library, site_id)
    with _translated():
        site = _replace(site, name=body.name, order=body.order)
        store.save_site(library, site)
    return SiteDTO.of(site)


@router.delete("/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_site(
    site_id: str,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
) -> None:
    """Remove a site and its EMPTY storeys. **409** if a room or a bookcase
    still stands on one of them, or if it is the only site."""
    _remove(store.delete_site, library, site_id, "site")


# --- floors ---------------------------------------------------------------

@router.post("/floors", response_model=FloorDTO,
             status_code=status.HTTP_201_CREATED)
def create_floor(
    body: FloorCreate,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    ids: IdGen = Depends(get_id_gen),
) -> FloorDTO:
    with _translated():
        floor = new_floor(id=ids.new_id(), library_id=library.id,
                          site_id=body.site_id, name=body.name,
                          order=body.order)
        store.save_floor(library, floor)
    return FloorDTO.of(floor)


@router.patch("/floors/{floor_id}", response_model=FloorDTO)
def patch_floor(
    floor_id: str,
    body: FloorPatch,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
) -> FloorDTO:
    floor = _floor(store, library, floor_id)
    with _translated():
        floor = _replace(floor, name=body.name, order=body.order)
        store.save_floor(library, floor)
    return FloorDTO.of(floor)


@router.delete("/floors/{floor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_floor(
    floor_id: str,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
) -> None:
    """**409** naming the rooms and cases still on it, or if it is its site's
    only storey — the way out of that is to remove the site."""
    _remove(store.delete_floor, library, floor_id, "floor")


# --- places (rooms) -------------------------------------------------------

@router.post("/places", response_model=PlaceDTO,
             status_code=status.HTTP_201_CREATED)
def create_place(
    body: PlaceCreate,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    ids: IdGen = Depends(get_id_gen),
) -> PlaceDTO:
    with _translated():
        place = new_place(id=ids.new_id(), library_id=library.id,
                          floor_id=body.floor_id, rect=body.rect.to_domain(),
                          name=body.name, order=body.order)
        store.save_place(library, place)
    return PlaceDTO.of(place)


@router.patch("/places/{place_id}", response_model=PlaceDTO)
def patch_place(
    place_id: str,
    body: PlacePatch,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
) -> PlaceDTO:
    place = _place(store, library, place_id)
    with _translated():
        place = _replace(place, name=body.name, order=body.order,
                         rect=body.rect.to_domain() if body.rect else None)
        store.save_place(library, place)
        # ⚠ The storey moves through its OWN call, which takes the room's
        # bookcases with it. A review moved a room upstairs with a plain
        # field write and left its case on the ground floor — the state
        # `NotOnThisFloor` exists to forbid — and the case was then
        # un-renamable, un-movable and un-resizable forever, every write
        # answering 409 about a mismatch the owner never created.
        if body.floor_id is not None and body.floor_id != place.floor_id:
            place = store.move_place(library, place, body.floor_id)
    return PlaceDTO.of(place)


@router.delete("/places/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_place(
    place_id: str,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
) -> None:
    """Remove a room. **Its bookcases stay** where they stand, attached to no
    room — deleting a container never destroys what it held."""
    _remove(store.delete_place, library, place_id, "place")


# --- bookcases ------------------------------------------------------------

@router.post("/bookcases", response_model=BookcaseDrawnDTO,
             status_code=status.HTTP_201_CREATED)
def create_bookcase(
    body: BookcaseCreate,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    ids: IdGen = Depends(get_id_gen),
    clock: Clock = Depends(get_clock),
) -> BookcaseDrawnDTO:
    """Draw a bookcase — **and every shelf its first section describes.**

    §3.1: a drawn slot IS a Shelf. Ask for 2 columns of 5 and ten real, empty,
    addressed shelves come into existence, each carrying the section's depth
    as a COPY. That is the point of the route, not a side effect of it.

    The answer names that first section, because the client addresses it in
    the very next gesture and has no other way to learn its id — see
    :class:`BookcaseDrawnDTO`.
    """
    with _translated():
        case = new_bookcase(id=ids.new_id(), library_id=library.id,
                            floor_id=body.floor_id, rect=body.rect.to_domain(),
                            name=body.name, front=body.front,
                            place_id=body.place_id, order=body.order)
        # The ceiling BEFORE the write, not after: the point is not to refuse
        # the 1601st row, it is to never spend 16 seconds writing the first
        # 1600 (§ MAX_SLOTS_PER_BOOKCASE).
        check_bookcase_size([new_section(
            id="probe", library_id=library.id, bookcase_id=case.id,
            columns=body.columns, default_levels=body.levels,
            default_depth=body.depth)])
        drawn = draw_bookcase(store, shelves, library, case, ids=ids,
                              clock=clock, columns=body.columns,
                              levels=body.levels, depth=body.depth)
    return BookcaseDrawnDTO.of_drawn(drawn.bookcase, drawn.sections[0])


@router.patch("/bookcases/{case_id}", response_model=BookcaseDTO)
def patch_bookcase(
    case_id: str,
    body: BookcasePatch,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
) -> BookcaseDTO:
    """Move, resize, rename, turn — or point the case at another room.

    ⚠ ``place_id`` and ``detach`` are two fields because a JSON null cannot
    mean both *"unchanged"* and *"let go of the room"*. Letting go is
    explicit, always: containment may only ever REASSIGN a case, never orphan
    one, and the lab found that the hard way twice.
    """
    if body.detach and body.place_id is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "detach and place_id in one request mean two different things",
        )
    case = _bookcase(store, library, case_id)
    if body.floor_id is not None and (case.place_id or body.place_id):
        # A case in a room is on that room's storey by construction; moving
        # it alone is how the "bricked bookcase" state was reachable. The
        # room is what moves, and it takes its furniture with it.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a case attached to a room moves with the room; move the room, "
            "or detach the case first",
        )
    room = _place(store, library, body.place_id) if body.place_id else None
    with _translated():
        case = _replace(case, name=body.name, front=body.front,
                        order=body.order, floor_id=body.floor_id,
                        rect=body.rect.to_domain() if body.rect else None)
        if body.detach or room is not None:
            return BookcaseDTO.of(
                attach_case_to_room(store, library, case, room))
        store.save_bookcase(library, case)
    return BookcaseDTO.of(case)


@router.delete("/bookcases/{case_id}/slots", response_model=SlotRemovalDTO)
def clear_bookcase(
    case_id: str,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
) -> SlotRemovalDTO:
    """Empty every slot of a bookcase, so the case can then be deleted.

    A separate call from the delete on purpose: the owner sees the counts
    first, and an occupied shelf is DETACHED rather than destroyed. A delete
    that quietly emptied the slots itself is the silent data-loss path
    MAP_PLAN §2 predicted for this pillar.
    """
    _bookcase(store, library, case_id)
    return SlotRemovalDTO.of(
        clear_bookcase_slots(store, shelves, books, library, case_id))


@router.delete("/bookcases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bookcase(
    case_id: str,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
) -> None:
    """Remove a case and its sections. **409** while any shelf still stands in
    one of its slots — empty them first, through ``DELETE .../slots``."""
    _remove(store.delete_bookcase, library, case_id, "bookcase")


# --- sections -------------------------------------------------------------

@router.post("/sections", response_model=SectionEditDTO,
             status_code=status.HTTP_201_CREATED)
def create_section(
    body: SectionCreate,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
    ids: IdGen = Depends(get_id_gen),
    clock: Clock = Depends(get_clock),
) -> SectionEditDTO:
    """Add a section — a hutch on the base, or a plinth under it.

    It copies the shape of the section it stands against, because a hutch
    usually has about as many columns as its base and re-entering what is
    already on screen is not a feature. Adding at the BOTTOM renumbers the
    ones above: ``ordinal`` is bottom-first, unique, and printed in addresses.
    """
    _bookcase(store, library, body.bookcase_id)
    with _translated():
        # Recomputed from the LIVE snapshot every time, and written as one
        # set. A review measured the previous shape — renumber one section at
        # a time, outside any transaction: a failure part-way left the
        # sections shifted, the new one never created, a GAP in the ordinals
        # the address prints, and every retry widened it. Two concurrent adds
        # did the same with no failure at all.
        siblings = [s for s in store.load_map(library).sections
                    if s.bookcase_id == body.bookcase_id]
        section = next_section(body.bookcase_id, siblings, id=ids.new_id(),
                               where=body.where)
        ordered = ([section] + sorted(siblings, key=lambda s: s.ordinal)
                   if body.where == "bottom"
                   else sorted(siblings, key=lambda s: s.ordinal) + [section])
        settled = renumber_sections(ordered)
        check_bookcase_size(settled)
        store.save_sections(library, settled)
        section = next(s for s in settled if s.id == section.id)
    # ⚠ From EMPTY up to the shape, not from the shape to itself. A section
    # that has never been saved has no slots yet, so the change has to be
    # computed against nothing — asking `with_column_count` for the width it
    # already claims reports no new slots at all, and the hutch arrives with
    # a grid on screen and not one shelf behind it.
    blank = _replace(section, column_levels=())
    change = with_column_count(blank, section.column_count)
    return _edit(store, shelves, books, library, change, ids=ids, clock=clock)


@router.patch("/sections/{section_id}", response_model=SectionEditDTO)
def patch_section(
    section_id: str,
    body: SectionPatch,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
    ids: IdGen = Depends(get_id_gen),
    clock: Clock = Depends(get_clock),
) -> SectionEditDTO:
    """Change the grid, or the defaults.

    The defaults are creation-time values (§3.3) — setting one touches no
    existing shelf, and applying it is a separate, explicit call. The grid
    changes DO touch shelves, which is what the response reports.
    """
    # ⚠ ONE grid instruction per request, checked before anything is read.
    # A review measured the old fall-through: `{"columns":3,"column":1,
    # "levels":9}` answered 200 having silently dropped the per-column edit,
    # and `{"column":2}` alone answered 200 having done nothing at all — an
    # elevation panel that saves what it is showing would apply half its edit
    # every time and be told it succeeded.
    per_column = body.column is not None or body.levels is not None
    if body.columns is not None and per_column:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "`columns` resizes the whole section and `column`/`levels` one "
            "column of it; one request carries one grid instruction",
        )
    if per_column and (body.column is None or body.levels is None):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "`column` and `levels` name one column's height together",
        )
    section = _section(store, library, section_id)
    with _translated():
        if body.default_levels is not None:
            section = with_default_levels(section, body.default_levels)
        if body.default_depth is not None:
            section = with_default_depth(section, body.default_depth)
        change = None
        if body.columns is not None:
            change = with_column_count(section, body.columns)
        elif per_column:
            change = with_column_levels(section, body.column, body.levels)
        if change is not None:
            siblings = [s for s in store.load_map(library).sections
                        if s.bookcase_id == section.bookcase_id
                        and s.id != section.id]
            check_bookcase_size(siblings + [change.section])
    if change is None:
        # Defaults only: no slot moves, so nothing is created or removed.
        with _translated():
            store.save_section(library, section)
        return SectionEditDTO(section=SectionDTO.of(section))
    return _edit(store, shelves, books, library, change, ids=ids, clock=clock)


@router.patch("/sections/{section_id}/shelves/{col}/{level}",
              response_model=ShelfDTO)
def set_shelf_depth(
    section_id: str,
    col: int,
    level: int,
    body: SlotDepthPatch,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
) -> ShelfDTO:
    """The per-shelf depth override — *"default for the whole bookcase,
    overridable per shelf"*, in the owner's own words (MAP_PLAN §1).

    Addressed by SLOT rather than by shelf id, because that is what the
    elevation has in its hand: the cell the owner tapped. Both indices are
    1-based, like every address on the wire.

    ⚠ It cannot take a shelf below its deepest occupied depth, for the reason
    §3.3 gives about the section default one level up: a copy recorded at
    depth 2 of a shelf declaring one row is a location `check_depth` then
    refuses, and no foreign key can see it. Deepening is never refused —
    there is nothing behind a shelf to protect.
    """
    _section(store, library, section_id)
    with _translated():
        address = ShelfAddress(section_id, col, level)
    shelf = shelves.get_shelf_at(library, address)
    if shelf is None:
        raise _gone("shelf at that slot")
    floor = deepest_occupied_depths(shelves, books, library, [shelf]).get(
        shelf.id, 1)
    if body.depth_count < floor:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"something stands at depth {floor} on this shelf, so it cannot "
            f"become {body.depth_count} row(s) deep (§5.7)",
        )
    with _translated():
        shelves.save_shelf(library, replace(shelf, depth_count=body.depth_count))
    return ShelfDTO.of(shelves.get_shelf(library, shelf.id),
                       capture_count=len(shelves.list_captures(library, shelf.id)))


@router.post("/sections/{section_id}/levels", response_model=SectionEditDTO)
def apply_levels(
    section_id: str,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
    ids: IdGen = Depends(get_id_gen),
    clock: Clock = Depends(get_clock),
) -> SectionEditDTO:
    """Level every column to the section's default — the explicit, opt-in
    half of the level default."""
    section = _section(store, library, section_id)
    with _translated():
        change = apply_default_levels(section)
        siblings = [s for s in store.load_map(library).sections
                    if s.bookcase_id == section.bookcase_id
                    and s.id != section.id]
        check_bookcase_size(siblings + [change.section])
    return _edit(store, shelves, books, library, change, ids=ids, clock=clock)


@router.post("/sections/{section_id}/depth", response_model=DepthApplyDTO)
def apply_depth(
    section_id: str,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
) -> DepthApplyDTO:
    """Push the section's depth default onto its existing shelves.

    §3.3's explicit half, and the one with the clamp: a shelf with a book in
    the back row keeps its depth, and the response NAMES those shelves so the
    screen can say so instead of claiming it did everything.
    """
    section = _section(store, library, section_id)
    kept = apply_depth_default(shelves, books, library, section)
    return DepthApplyDTO(kept=[s.id for s in kept])


@router.delete("/sections/{section_id}/slots", response_model=SlotRemovalDTO)
def clear_section(
    section_id: str,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
) -> SlotRemovalDTO:
    """Empty ONE section's slots. Separate from the bookcase's, because a
    case with a base and a hutch has two, and *"remove the hutch"* must not
    touch the base."""
    _section(store, library, section_id)
    return SlotRemovalDTO.of(
        clear_section_slots(shelves, books, library, section_id))


@router.delete("/sections/{section_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_section(
    section_id: str,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
) -> None:
    """**409** for the last section of a bookcase (a case with none is not
    simpler, it is unaddressable) and while any of its slots is filled."""
    _remove(store.delete_section, library, section_id, "section")


# --- helpers --------------------------------------------------------------

def _replace(record, **fields):
    """Apply only the fields the client actually sent.

    PATCH semantics in one place: ``None`` means *unchanged*, and every DTO
    above is built so that no field's real value is ``None`` — the one place
    that would have been ambiguous (a bookcase letting go of its room) has
    its own boolean instead.
    """
    from dataclasses import replace

    given = {k: v for k, v in fields.items() if v is not None}
    return replace(record, **given) if given else record


def _edit(store: MapStore, shelves: ShelfStore, books: BookStore,
          library: LibraryRef, change, *, ids: IdGen,
          clock: Clock) -> SectionEditDTO:
    with _translated():
        removal = apply_slot_change(store, shelves, books, library, change,
                                    ids=ids, clock=clock)
    return SectionEditDTO(
        section=SectionDTO.of(change.section),
        created=len(change.added),
        removal=SlotRemovalDTO.of(removal),
    )
