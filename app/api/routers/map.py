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

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    get_book_store,
    get_clock,
    get_decision_store,
    get_duplicate_queue,
    get_id_gen,
    get_journal,
    get_map_store,
    get_read_store,
    get_shelf_store,
)
from app.api.dto import (
    AddressPartsDTO,
    BookcaseCreate,
    BookcaseDrawnDTO,
    BookcaseDTO,
    BookcasePatch,
    DepthApplyDTO,
    FloorCreate,
    FloorDTO,
    FloorPatch,
    MapDTO,
    MergePreviewDTO,
    MergeRefusalDTO,
    MergeRequest,
    MergeResultDTO,
    PlaceCreate,
    PlaceDTO,
    PlacePatch,
    SectionCreate,
    SectionDTO,
    SectionEditDTO,
    SectionGapPatch,
    SectionPatch,
    ShelfAddressDTO,
    ShelfDTO,
    SiteCreate,
    SiteDTO,
    SitePatch,
    SlotDepthPatch,
    ShelfWhereDTO,
    SlotRemovalDTO,
    UndoOfferDTO,
)
from app.api.policy import require
from app.domain import (
    AlreadyOnTheMap,
    Bookcase,
    Capability,
    CellIsGap,
    DomainError,
    Floor,
    LibraryRef,
    NotEmpty,
    Place,
    Section,
    MergeRefused,
    Shelf,
    ShelfAddress,
    Site,
    ShelfWasMerged,
    StripOrder,
    SlotTaken,
    SlotsOccupied,
    TooManySlots,
    VirtualShelfHasNoDepth,
    address_parts,
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
    with_gaps,
)
from app.domain.place import NotOnThisFloor
from app.map_edit import (
    apply_depth_default,
    deepest_occupied_depths,
    apply_gaps,
    apply_slot_change,
    attach_case_to_room,
    bind_shelf_to_slot,
    clear_bookcase_slots,
    clear_section_slots,
    draw_bookcase,
    remove_record,
    unbind_shelf_from_map,
)
from app.domain.alias import resolve
from app.map_merge import Shelves, merge, preview
from app.map_undo import Journal, UndoRefused, offer, undo
from app.ports import Clock, IdGen
from app.ports.decisions import DecisionStore
from app.ports.duplicates import DuplicateQueue
from app.ports.map import MapStore
from app.ports.store import (
    BookStore,
    DuplicateCaptureSlot,
    DuplicateSectionOrdinal,
    DuplicateShelfSlot,
    ReadStore,
    ShelfHasAliases,
    ShelfNotEmpty,
    ShelfStore,
    UnknownParent,
    UnknownShelf,
    WrongLibrary,
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

    ⚠ ``SlotsOccupied`` is listed with the 409s and not left to the
    ``DomainError`` fall-through, which would answer **400**. It is a
    subclass, so the generic clause below would happily have caught it and
    told the client its request was malformed — and a client that believes
    that does not offer to empty the shelf, it edits the request.
    """
    try:
        yield
    except UnknownParent as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (NotOnThisFloor, NotEmpty, TooManySlots, SlotsOccupied,
            SlotTaken, CellIsGap, AlreadyOnTheMap, ShelfWasMerged,
            VirtualShelfHasNoDepth,
            # ⚠ The whole `StoreError` family, not the three this tuple
            # happened to name. `StoreError` subclasses bare `Exception`, so
            # the `DomainError` fall-through below never caught the others —
            # and a security review measured `ShelfNotEmpty` escaping a merge
            # as a **500** on a mutating LAN route, which the client then
            # classifies as *dropped* and invites the owner to retry forever.
            # Every one of these sentences is already owner-readable and every
            # one means *there is something here you have not dealt with*,
            # which is a 409.
            ShelfNotEmpty, ShelfHasAliases, UnknownShelf,
            DuplicateCaptureSlot, WrongLibrary,
            DuplicateSectionOrdinal, DuplicateShelfSlot) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _remove(
    store: MapStore,
    shelves: ShelfStore,
    journal: Journal,
    library: LibraryRef,
    what: str,
    record_id: str,
) -> None:
    # 409 (via `_translated`) carries the message that says WHAT is in the
    # way — "cannot delete" with no reason is what makes the next reader
    # delete the guard.
    #
    # The delete itself moved to `app.map_edit.remove_record` at P6.4b: it now
    # reads the row before destroying it, because an id cannot put a bookcase
    # back. This function keeps exactly the HTTP half — 404 for a record that
    # was not there, 409 for one that refused.
    with _translated():
        removed = remove_record(store, shelves, library, what, record_id,
                                journal=journal)
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


@router.get("/where/{shelf_id}", response_model=ShelfWhereDTO)
def where_is(
    shelf_id: str,
    depth: int | None = Query(
        default=None, ge=1,
        description="The row front-to-back this answer is about \u2014 a COPY's "
                    "depth, which the shelf itself does not have. Omitted, "
                    "the answer names no row.",
    ),
    library: LibraryRef = Depends(require(READ)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
) -> ShelfWhereDTO:
    """Where this shelf stands, in the words a person would use.

    VISION \u00a77's requirement, and the sentence this router's own docstring
    says the map exists for: *"given a book, the UI can answer 'where is it'
    ... including which row front-to-back"*. The Books tab reaches it through
    a copy's ``shelf_id``; the shelf screen reaches it for its own id.

    **A shelf that stands nowhere answers 200 with a null address**, not 404.
    Most shelves stand nowhere \u2014 they were born from a photograph and \u00a73.1
    keeps the drawn and the photographed one population \u2014 so *not on the map
    yet* is the normal state, and a 404 would tell a screen that a shelf it is
    looking at does not exist.

    \u26a0 The id resolves through the alias FIRST (\u00a73.11). A copy's
    ``shelf_id`` is a stored value: after a merge it names an identity that is
    answered for rather than live, and a book whose location silently became
    *nowhere* is exactly the phantom this catalogue is built not to produce.

    \u26a0 It reads the whole drawing rather than asking the store for one
    section's ancestry, for the reason ``GET /map`` gives one route up: a house
    is tens of rows. A dedicated query per level would be four round trips to
    save a few hundred bytes, and a fifth the day a level is added.
    """
    # ⚠ The LIVE row first, the alias table only on a miss. Reading the
    # aliases first and resolving against them is one snapshot older than the
    # `shelves` read that follows, so a merge landing between the two answers
    # 404 for an id that resolves a millisecond later — measured. In this
    # order there is no interleaving where both are absent: either the merge
    # has not happened (the live row is there) or it has (the alias is).
    shelf = shelves.get_shelf(library, shelf_id)
    if shelf is None:
        shelf = shelves.get_shelf(
            library, resolve(shelf_id, shelves.list_aliases(library)))
    if shelf is None:
        raise _gone("shelf")

    plan = store.load_map(library)
    # \u00a73.9's rule for the map's site segment, applied to the same ambiguity
    # in a sentence: one home renders no chrome at all.
    many_sites = len(plan.sites) > 1

    out = ShelfWhereDTO(shelf_id=shelf.id, label=shelf.label,
                        depth_count=shelf.depth_count)
    if shelf.address is None:
        return out

    section = next((s for s in plan.sections
                    if s.id == shelf.address.section_id), None)
    if section is None:
        # Defensive, and stated as such: `sections.bookcase_id` cascades and
        # `shelves.section_id` does not, and every delete path empties a
        # bookcase's slots first \u2014 so a shelf holding an address whose section
        # is gone is unreachable through the API today. The same is true of
        # the three lookups below it.
        # \u26a0 The citation that stood here was \u00a73.10a, which is the GAPS rule
        # and says nothing about this. A wrong stated reason is what makes the
        # next reader delete the guard. Answering "nowhere" is right either
        # way \u2014 it is the same answer the unaddressed branch gives.
        return out
    # ⚠ **The address has to still BE a slot of the section as loaded.**
    # `shelf.address` and this `Section` come from two different reads with no
    # transaction between them, and `address_parts` suppresses the column when
    # the section has one — so a structural edit landing in that window
    # produces a location that was true at no instant. Both measured by a
    # review, against a section edited mid-request:
    #
    #   3 columns → 1: a shelf at column 3 answered *סלון · הכוננית ·
    #   גובה 1* — which is a DIFFERENT, live shelf's address, holding
    #   different books, while the shelf asked about in fact stood nowhere;
    #   a cell gapped: 200 with an address naming a cell the drawing does not
    #   have — rendered by no screen, listed by no picker.
    #
    # `addresses` excludes gapped cells and anything outside the extent, and
    # is the property every destructive and creative path already goes
    # through. Failing it means *not on the map yet*, which is the truth and
    # which every caller already has a sentence for. Same family as the undo
    # journal's lesson: a fingerprint over rows must also watch the SHAPE they
    # land in.
    if shelf.address not in section.addresses:
        return out
    case = next((b for b in plan.bookcases if b.id == section.bookcase_id),
                None)
    if case is None:
        return out
    room = next((p for p in plan.places if p.id == case.place_id), None)
    site = None
    if many_sites:
        floor = next((f for f in plan.floors if f.id == case.floor_id), None)
        found = next((s for s in plan.sites
                      if floor is not None and s.id == floor.site_id), None)
        site = found.name if found is not None else None

    parts = address_parts(
        place=room,
        bookcase=case,
        section=section,
        section_count=sum(1 for s in plan.sections
                          if s.bookcase_id == case.id),
        address=shelf.address,
        # ⚠ Clamped to what the shelf actually HAS. `ge=1` bounds it below
        # and nothing bounded it above, so `?depth=999` on a flat shelf
        # answered 200 with *שורה 999* and the §5.7 note saying the row in
        # front has to be moved. Inert from the product — every write
        # validates a copy's depth through `Shelf.check_depth` — and reachable
        # from any caller, on the one route whose whole job is to say where
        # something is. `depth_count` is already in the reply, so the clamp
        # costs nothing.
        depth=depth if depth and depth <= shelf.depth_count else None,
    )
    return out.model_copy(update={"site": site,
                                  "address": AddressPartsDTO.of(parts)})


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
    shelves: ShelfStore = Depends(get_shelf_store),
    journal: Journal = Depends(get_journal),
) -> None:
    """Remove a site and its EMPTY storeys. **409** if a room or a bookcase
    still stands on one of them, or if it is the only site."""
    _remove(store, shelves, journal, library, "site", site_id)


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
    shelves: ShelfStore = Depends(get_shelf_store),
    journal: Journal = Depends(get_journal),
) -> None:
    """**409** naming the rooms and cases still on it, or if it is its site's
    only storey — the way out of that is to remove the site."""
    _remove(store, shelves, journal, library, "floor", floor_id)


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
    shelves: ShelfStore = Depends(get_shelf_store),
    journal: Journal = Depends(get_journal),
) -> None:
    """Remove a room. **Its bookcases stay** where they stand, attached to no
    room — deleting a container never destroys what it held."""
    _remove(store, shelves, journal, library, "place", place_id)


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
    journal: Journal = Depends(get_journal),
) -> SlotRemovalDTO:
    """Empty every slot of a bookcase, so the case can then be deleted.

    A separate call from the delete on purpose: the owner sees the counts
    first, and an occupied shelf is DETACHED rather than destroyed. A delete
    that quietly emptied the slots itself is the silent data-loss path
    MAP_PLAN §2 predicted for this pillar.
    """
    _bookcase(store, library, case_id)
    return SlotRemovalDTO.of(
        clear_bookcase_slots(store, shelves, books, library, case_id,
                             journal=journal))


@router.delete("/bookcases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bookcase(
    case_id: str,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    journal: Journal = Depends(get_journal),
) -> None:
    """Remove a case and its sections. **409** while any shelf still stands in
    one of its slots — empty them first, through ``DELETE .../slots``."""
    _remove(store, shelves, journal, library, "bookcase", case_id)


# --- sections -------------------------------------------------------------

@router.post("/sections", response_model=SectionEditDTO,
             status_code=status.HTTP_201_CREATED)
def create_section(
    body: SectionCreate,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
    journal: Journal = Depends(get_journal),
    ids: IdGen = Depends(get_id_gen),
    clock: Clock = Depends(get_clock),
) -> SectionEditDTO:
    """Add a section — a hutch on the base, or a plinth under it.

    It copies the shape of the section it stands against, because a hutch
    usually has about as many columns as its base and re-entering what is
    already on screen is not a feature. Adding at the BOTTOM renumbers the
    ones above: ``ordinal`` is bottom-first, unique, and printed in addresses.

    ⚠ ``above_id`` is the general form and exists because ``top``/``bottom``
    cannot say *back where it was*: a review measured a section restored into
    the MIDDLE of a stack by an undo being sent as ``top``, appended by this
    route, and recorded by the client as landed — so the drawing and the
    library disagreed about which unit stands on which, and ``ordinal`` is what
    an address prints.
    """
    if body.where is not None and body.above_id is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "`where` and `above_id` both say where the section goes; one "
            "request carries one instruction",
        )
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
        standing = sorted(siblings, key=lambda s: s.ordinal)
        below = None
        if body.above_id is not None:
            below = next((s for s in standing if s.id == body.above_id), None)
            if below is None:
                # 404 rather than 400: a section of another bookcase and a
                # section that never existed are the same answer, the way a
                # foreign library and a fictional one are.
                raise _gone("section")
        # `next_section` copies the shape of the section it stands against, so
        # the sibling list handed to it IS the choice of neighbour.
        section = next_section(
            body.bookcase_id, [below] if below else siblings, id=ids.new_id(),
            where="top" if below else (body.where or "top"))
        if below is not None:
            at = standing.index(below) + 1
            ordered = standing[:at] + [section] + standing[at:]
        elif body.where == "bottom":
            ordered = [section] + standing
        else:
            ordered = standing + [section]
        settled = renumber_sections(ordered)
        check_bookcase_size(settled)
        store.save_sections(library, settled)
        section = next(s for s in settled if s.id == section.id)
    # ⚠ From EMPTY up to the shape, not from the shape to itself. A section
    # that has never been saved has no slots yet, so the change has to be
    # computed against nothing — asking `with_column_count` for the width it
    # already claims reports no new slots at all, and the hutch arrives with
    # a grid on screen and not one shelf behind it.
    # ⚠ `gaps=()` explicitly. A blank has NO extent, and `Section` refuses a
    # gap outside its extent — so if `next_section` ever copied its
    # neighbour's mask, this line would answer 400 on every section created.
    # It is safe today only because that function chooses not to, which is a
    # decision recorded 200 lines away rather than a property of this caller.
    blank = _replace(section, column_levels=(), gaps=())
    change = with_column_count(blank, section.column_count)
    return _edit(store, shelves, books, library, change, journal=journal,
                 ids=ids, clock=clock)


@router.patch("/sections/{section_id}", response_model=SectionEditDTO)
def patch_section(
    section_id: str,
    body: SectionPatch,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
    journal: Journal = Depends(get_journal),
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
    return _edit(store, shelves, books, library, change, journal=journal,
                 ids=ids, clock=clock)


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
                       capture_count=len(shelves.list_captures(library, shelf.id)),
                       book_count=books.copies_per_shelf(library).get(shelf.id, 0))


@router.patch("/sections/{section_id}/gaps", response_model=SectionEditDTO)
def set_gaps(
    section_id: str,
    body: SectionGapPatch,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
    journal: Journal = Depends(get_journal),
    ids: IdGen = Depends(get_id_gen),
    clock: Clock = Depends(get_clock),
) -> SectionEditDTO:
    """Switch cells off — the space a television stands in — or back on.

    The owner's request, 2026-08-22: *"to allow a place to TV in the middle…
    the lower shelves should not get up now. They should remain in place."*
    So this is **not** a resize: the section's extent is untouched, the
    shelves below a hole keep the level numbers their addresses print, and
    switching the cells back on restores real shelves at the same addresses.

    Three answers a caller has to handle:

      - **409 while one of the cells carries something the owner declared** —
        books, photographs, a name, or a row behind it — naming how many.
        Everywhere else a slot that loses its address DETACHES its shelf (the
        books survive, the location does not); a gap refuses instead, so no
        book loses its location to this gesture. ⚠ It is **not** loss-proof,
        and an earlier draft of this docstring said it was: what a gapped
        cell does not keep is its shelf's **id**, and standing decisions are
        keyed by that id with no foreign key — so a phantom the owner
        rejected at that cell stops being suppressed. `app.map_edit.
        apply_gaps` states the whole cost; §3.11's alias is the fix, in
        P6.4e;
      - **400 for a cell outside the section**, rather than gapping whatever
        is nearest. `with_gaps` raises for the reason `with_column_count`
        records: the lenient answer would be the destructive one;
      - **200 with `removal.detached` non-empty**, which is the race, not the
        rule: a photograph landing between the check and the delete makes the
        store refuse, and `_release` then unaddresses that shelf rather than
        half-applying the edit. A client that assumes `detached` is always
        empty here will be wrong eventually.

    ⚠ It never deletes the bookcase, the section, or a column, however many
    cells are named — a section that is entirely gaps is a legal section with
    its full extent, which is exactly what the owner asked for.
    """
    section = _section(store, library, section_id)
    with _translated():
        change = with_gaps(section,
                           [(cell.column, cell.level) for cell in body.cells],
                           gap=body.gap)
        # ⚠ Only a gesture that CREATES slots is checked, and the clause is
        # load-bearing — `app/web/src/map/limits.ts` states the same rule in
        # the other language: *"a case that is somehow already over a ceiling
        # must still be shrinkable, or the guard becomes the trap"*.
        #
        # `check_bookcase_size` counts ADDRESSES, and a gapped cell is not
        # one — right, because the cap bounds rows and a gap is no row. But a
        # masked case can therefore sit under the ceiling and cross it when
        # the mask comes off, so the check belongs where slots appear.
        #
        # `change.added` rather than `not body.gap`: a review measured the
        # direction flag surviving its own mutation (`if True` left 757 tests
        # green), because "restoring" is only over-ceiling-able when it
        # actually adds something. Asking the change what it DOES is true in
        # both directions and cannot drift from the flag the client sent.
        if change.added:
            siblings = [s for s in store.load_map(library).sections
                        if s.bookcase_id == section.bookcase_id
                        and s.id != section.id]
            check_bookcase_size(siblings + [change.section])
        removal = apply_gaps(store, shelves, books, library, change,
                             journal=journal, ids=ids, clock=clock)
    return SectionEditDTO(
        section=SectionDTO.of(change.section),
        created=len(change.added),
        removal=SlotRemovalDTO.of(removal),
    )


@router.post("/sections/{section_id}/levels", response_model=SectionEditDTO)
def apply_levels(
    section_id: str,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
    journal: Journal = Depends(get_journal),
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
    return _edit(store, shelves, books, library, change, journal=journal,
                 ids=ids, clock=clock)


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
    journal: Journal = Depends(get_journal),
) -> SlotRemovalDTO:
    """Empty ONE section's slots. Separate from the bookcase's, because a
    case with a base and a hutch has two, and *"remove the hutch"* must not
    touch the base."""
    _section(store, library, section_id)
    return SlotRemovalDTO.of(
        clear_section_slots(store, shelves, books, library, section_id,
                            journal=journal))


@router.delete("/sections/{section_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_section(
    section_id: str,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    journal: Journal = Depends(get_journal),
) -> None:
    """**409** for the last section of a bookcase (a case with none is not
    simpler, it is unaddressable) and while any of its slots is filled."""
    _remove(store, shelves, journal, library, "section", section_id)


# --- undo (P6.4b, MAP_PLAN §3.15) -----------------------------------------

# --- binding a shelf to a slot (P6.4c, MAP_PLAN §3.14) --------------------
#
# ⚠ **Addressed by SHELF, not by cell**, unlike `set_shelf_depth` one screen
# up — and the DELETE is the reason. `DELETE /sections/{id}/shelves/{c}/{l}`
# is the same URL shape the elevation uses for a depth override, and it would
# read as *delete the shelf in this cell* to anybody scanning a log or a
# client. What is created and destroyed here is an ADDRESS; the shelf itself
# survives both, with its books, its photographs and its label. The path says
# exactly that, and the pair is symmetric, which is worth more than matching
# the neighbour.


def _shelf_dto(shelves: ShelfStore, books: BookStore, library: LibraryRef,
               shelf: Shelf) -> ShelfDTO:
    """One shelf, counted — over every identity it answers for.

    ⚠ `formerly` too, and the merge route is the one with the strongest
    reason to be right about it: a review measured `POST .../merge` answering
    `formerly: []` about the alias row it had just written. Nothing renders
    that field today, which makes it a wrong answer on the wire waiting for
    whoever does.
    """
    aliases = shelves.aliases_of(library, shelf.id)
    here = (shelf.id,) + tuple(a.alias_id for a in aliases)
    counts = books.copies_per_shelf(library)
    return ShelfDTO.of(
        shelf,
        capture_count=sum(len(shelves.list_captures(library, one))
                          for one in here),
        book_count=sum(counts.get(one, 0) for one in here),
        formerly=aliases,
    )


@router.put("/shelves/{shelf_id}/address", response_model=ShelfDTO)
def bind_shelf(
    shelf_id: str,
    body: ShelfAddressDTO,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
) -> ShelfDTO:
    """Put an unaddressed shelf into a free slot — **the safe half of P6.4**.

    §3.11 splits binding in two and §3.14 keeps them apart: this one gains an
    address and joins no identities, so nothing moves and nothing is lost.
    Two shelves becoming one is a MERGE (P6.4d), and a taken slot is where
    this route stops rather than something it resolves.

    The answers, and each is a different sentence for the owner:

      - **404** — no such shelf, or no such section. Foreign and fictional are
        the same answer (§4.2);
      - **400** — a cell outside the section's extent. The client is drawing
        from a shape this section does not have;
      - **409, four ways** — the cell is a GAP (§3.10a: switched off is not a
        slot, and switching it back on is its own decision about the
        furniture); the shelf ALREADY stands somewhere (a move is an unbind
        and a bind, each worth its own ✓); the slot is TAKEN, naming the
        occupant so the client can offer the merge; or the shelf is the
        WISHLIST, which stands nowhere by construction (§5.7).

    ⚠ **It records no undo, and that is not an oversight.** Binding into a
    free slot destroys nothing — the same reason `set_gaps` records nothing
    when it switches a cell back ON — and the journal is one deep, so an entry
    for a purely additive edit does not merely add noise, it evicts the real
    undo standing behind it. The inverse is one press of the control beside
    it.

    ⚠ The body is `ShelfAddressDTO`, the type the response already carries,
    rather than a request twin of it. An address is an address in both
    directions, and three fields declared twice is the fork this project
    keeps a rule about.
    """
    shelf = shelves.get_shelf(library, shelf_id)
    if shelf is None:
        raise _gone("shelf")
    section = _section(store, library, body.section_id)
    with _translated():
        address = ShelfAddress(section.id, body.col, body.level)
        bound = bind_shelf_to_slot(store, shelves, library, shelf, section,
                                   address)
    return _shelf_dto(shelves, books, library, bound)


@router.delete("/shelves/{shelf_id}/address", response_model=ShelfDTO)
def unbind_shelf_route(
    shelf_id: str,
    section_id: str | None = Query(
        default=None,
        description="The cell the caller believes this shelf stands in. "
                    "Optional, and checked only when the shelf still has an "
                    "address — so a retry stays a no-op. Given and wrong "
                    "means the drawing moved: 409.",
    ),
    col: int | None = Query(default=None, ge=1),
    level: int | None = Query(default=None, ge=1),
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
    journal: Journal = Depends(get_journal),
) -> ShelfDTO:
    """Take a shelf off the drawing. The shelf survives; only the address goes.

    **200 either way.** A shelf that already stands nowhere is answered with
    itself rather than a 409 — the retry a dropped response provokes must not
    look like a new failure, and there is nothing for the caller to do
    differently.

    It records an undo where :func:`bind_shelf` does not, because this is the
    direction that loses something: an address is what a person read off a
    drawing, and §3.15's list is *destroy or detach*. Every other detach in
    the map is journalled, and one reached deliberately rather than as the
    side effect of erasing a column is not a smaller loss.

    ⚠ It answers with a `ShelfDTO` rather than 204, and an earlier version of
    this note claimed the map client uses it to skip a round trip. It does
    not: `useMapSync.slotWrite` discards the body and re-derives the whole
    document, because `free` and `id` are server facts this document now has
    wrong in more places than the one cell. The DTO is here because a shelf's
    state after the write is what a caller of a shelf route expects to be
    told, and because a 204 would make the counts unavailable to anything but
    a second request.

    ⚠ The three query parameters are the cell the CALLER thinks it is
    emptying, and they are how a stale screen is caught: a panel that has not
    seen the shelf move would otherwise detach it from the address somebody
    just set, and answer 200. All three or none — two of them describe no
    cell.
    """
    shelf = shelves.get_shelf(library, shelf_id)
    if shelf is None:
        raise _gone("shelf")
    given = (section_id, col, level)
    if any(v is not None for v in given) and any(v is None for v in given):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "name the whole cell or none of it: section_id, col and level")
    with _translated():
        expected = (ShelfAddress(section_id, col, level)
                    if section_id is not None else None)
        detached = unbind_shelf_from_map(store, shelves, library, shelf,
                                         journal=journal, expected=expected)
    return _shelf_dto(shelves, books, library, detached)


def _ports(store, shelves, books, reads, decisions, duplicates) -> Shelves:
    return Shelves(map_store=store, shelves=shelves, books=books, reads=reads,
                   decisions=decisions, duplicates=duplicates)


def _both(shelves: ShelfStore, library: LibraryRef, shelf_id: str,
          into: str) -> tuple[Shelf, Shelf]:
    absorbed = shelves.get_shelf(library, shelf_id)
    survivor = shelves.get_shelf(library, into)
    if absorbed is None or survivor is None:
        # Foreign and fictional are the same answer (§4.2), and so is "the
        # one you named has already been absorbed" — its row is gone, which
        # from here is indistinguishable from never having existed.
        raise _gone("shelf")
    return absorbed, survivor


def _strip(value: str) -> StripOrder:
    try:
        return StripOrder(value)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "strip must be `absorbed_first` or `survivor_first`; which half "
            "of the merged shelf is to the left is declared, never detected "
            "(§3.12)") from exc


@router.post("/shelves/{shelf_id}/merge/preview",
             response_model=MergePreviewDTO)
def preview_merge(
    shelf_id: str,
    body: MergeRequest,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
    reads: ReadStore = Depends(get_read_store),
    decisions: DecisionStore = Depends(get_decision_store),
    duplicates: DuplicateQueue = Depends(get_duplicate_queue),
) -> MergePreviewDTO:
    """What absorbing this shelf into `into` would move. **Writes nothing.**

    §3.15 keeps the preview even though undo exists: *"it is not a substitute
    for undo but the other half of the same courtesy"*. §3.14 is why it is a
    separate call rather than a field on the merge — every merge is an
    explicit ✓, and a ✓ given without seeing what moves is not one.

    **200 for a refusal too**, carried in `refused` with a stable `reason`
    beside the sentence. A preview that answers 409 cannot show the owner why,
    which is the only thing it is for — and the client would be parsing
    English out of a `detail` string, which is the finding P6.4c left on this
    item's row.

    ⚠ It is a POST because it takes a body, not because it writes: `strip`
    changes the answer (§3.12) and a GET with a mandatory query triple is the
    same request wearing a URL. `tests/test_api.py` asserts the library is
    byte-identical afterwards.
    """
    absorbed, survivor = _both(shelves, library, shelf_id, body.into)
    ports = _ports(store, shelves, books, reads, decisions, duplicates)
    # ⚠ `absorbed.id != survivor.id` FIRST. `resolve` answers with the id it
    # was handed when nothing has absorbed it, so *A already resolves to B* is
    # trivially true for A == B — and this route answered 200 `already: true`
    # for a merge the write refuses with 409. A preview that promises a state
    # the write will not produce is the one thing the shared `gather` exists
    # to prevent, and the same `resolve` trap 5cd19fb fixed one function over.
    if (absorbed.id != survivor.id
            and resolve(absorbed.id,
                        shelves.list_aliases(library)) == survivor.id):
        return MergePreviewDTO(absorbed_id=absorbed.id,
                               survivor_id=survivor.id, already=True,
                               depth=survivor.depth_count)
    try:
        plan = preview(ports, library, absorbed, survivor,
                       strip=_strip(body.strip))
    except MergeRefused as exc:
        if exc.reason == "other_library":
            raise _gone("shelf") from exc
        return MergePreviewDTO(
            absorbed_id=absorbed.id, survivor_id=survivor.id,
            depth=survivor.depth_count,
            refused=MergeRefusalDTO(reason=exc.reason, say=str(exc)))
    return MergePreviewDTO.of(absorbed.id, survivor.id, plan)


@router.post("/shelves/{shelf_id}/merge", response_model=MergeResultDTO)
def merge_shelves(
    shelf_id: str,
    body: MergeRequest,
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
    reads: ReadStore = Depends(get_read_store),
    decisions: DecisionStore = Depends(get_decision_store),
    duplicates: DuplicateQueue = Depends(get_duplicate_queue),
    clock: Clock = Depends(get_clock),
    journal: Journal = Depends(get_journal),
) -> MergeResultDTO:
    """Absorb this shelf into `into`. **The dangerous half of P6.4.**

    Two identities become one: a population of copies moves, two capture
    strips join, standing answers move with the wood (§3.13), and the absorbed
    identity survives as an alias of its id AND its former address (§3.11).
    It is undoable, and the inverse is the rows as they stood — §3.15 put the
    journal ahead of this item precisely so this sentence could be written.

    The answers:

      - **404** — either shelf is gone, foreign or fictional (§4.2);
      - **400** — `strip` is not one of the two;
      - **409** — refused, with a stable `reason` in `detail.reason` and the
        sentence in `detail.say`. Six reasons, and each is a different thing
        for a screen to say;
      - **200** — done, or already done. A retry after a dropped response is a
        no-op (§3.15), never a second merge.

    ⚠ `detail` is an OBJECT here where every other route in this file sends a
    string. That is the finding P6.4c left on this row: a client offered a
    merge by a 409 whose occupant is prose has to parse English or throw the
    whole thing away, and both were measured happening.
    """
    absorbed, survivor = _both(shelves, library, shelf_id, body.into)
    ports = _ports(store, shelves, books, reads, decisions, duplicates)
    with _translated():
        try:
            done = merge(ports, library, absorbed, survivor,
                         strip=_strip(body.strip), journal=journal,
                         clock=clock)
        except MergeRefused as exc:
            if exc.reason == "other_library":
                # ⚠ **404, never a named refusal.** `_both` already scopes both
                # lookups, so this is a safety net — and a security review
                # measured what the net answers if the lookup is ever widened
                # (resolving `into` through the alias table is a natural P6.4e
                # move): a REAL shelf of another library answered
                # `other_library` while a fictional one answered 404, which is
                # exactly the distinction §4.2 exists to abolish. Foreign and
                # fictional are the same answer, at every door.
                raise _gone("shelf") from exc
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"reason": exc.reason, "say": str(exc)}) from exc
    moved = (MergePreviewDTO.of(absorbed.id, survivor.id, done.plan)
             if done.plan is not None
             else MergePreviewDTO(absorbed_id=absorbed.id,
                                  survivor_id=survivor.id, already=True,
                                  depth=done.survivor.depth_count))
    return MergeResultDTO(
        survivor=_shelf_dto(shelves, books, library, done.survivor),
        moved=moved)


@router.get("/undo", response_model=UndoOfferDTO)
def get_undo(
    library: LibraryRef = Depends(require(READ)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    journal: Journal = Depends(get_journal),
) -> UndoOfferDTO:
    """What a press of *undo* would put back, or why it cannot.

    ``BROWSE``, not ``EDIT_MAP``, and deliberately: this writes nothing, and
    it is the same question *"what happened to my map last"* that everyone who
    can see the map may ask. The route that ACTS is the one that needs the
    capability.

    Answers 200 with ``available: false`` rather than 404 when there is
    nothing to take back — *"no map edit has been recorded"* is an answer, and
    a client forced to read 404 as data cannot tell it from a misspelt path.
    """
    return UndoOfferDTO.of(offer(journal, store, shelves, library))


@router.post("/undo", response_model=UndoOfferDTO)
def post_undo(
    library: LibraryRef = Depends(require(EDIT)),
    store: MapStore = Depends(get_map_store),
    shelves: ShelfStore = Depends(get_shelf_store),
    books: BookStore = Depends(get_book_store),
    journal: Journal = Depends(get_journal),
) -> UndoOfferDTO:
    """Take back the last destructive map edit.

    **409, naming what moved**, when the world has changed under the entry —
    §3.15's *"an undo that cannot prove the world is still as it left it
    refuses, and says why"*. 409 rather than 400: the request is not
    malformed, the state conflicts with it, and that is the difference between
    a client that offers to reload and one that edits the request.

    The response is the offer as it stands AFTER the undo, so the control that
    called it learns in the same round trip that there is now nothing more to
    take back. There is no redo, and no second entry underneath.
    """
    # ⚠ `_translated()` as well, like every other mutating route here. A
    # review reached a 500 with two ordinary gestures: delete a section, add
    # another (additive, so it records nothing), press undo — the replay hits
    # `sections_by_bookcase` and raises `DuplicateSectionOrdinal`, which this
    # route was the only one in the router not translating. A 500 is the one
    # answer the phone client cannot classify, so it retries.
    try:
        with _translated():
            entry = undo(journal, store, shelves, books, library)
    except UndoRefused as exc:
        # ⚠ A STRING detail, never the dict this first carried. The client
        # reads `e.detail || e.message` and renders it, so an object arrives
        # as an empty alert (the trap CLAUDE.md records) — and the words a
        # person sees have to come from `app/web/src/map/text.ts` anyway,
        # where they have a Hebrew form. What moved stays machine-readable on
        # `GET /map/undo`, which answers `reason` and `changed`.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    # ⚠ `restored` — what this call DID — beside the forward-looking offer.
    # The offer after an undo is correctly empty (there is nothing more to
    # take back), so a client announcing from `restores` could only ever say
    # zero: measured as *"0 books went back to their own shelf"* with 22 on
    # the shelf and the alias gone. The two answer different questions and
    # both are wanted in one round trip.
    said = UndoOfferDTO.of(offer(journal, store, shelves, library))
    return said.model_copy(update={"restored": entry.restore.counts()})


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
          library: LibraryRef, change, *, journal: Journal, ids: IdGen,
          clock: Clock) -> SectionEditDTO:
    with _translated():
        removal = apply_slot_change(store, shelves, books, library, change,
                                    journal=journal, ids=ids, clock=clock)
    return SectionEditDTO(
        section=SectionDTO.of(change.section),
        created=len(change.added),
        removal=SlotRemovalDTO.of(removal),
    )
