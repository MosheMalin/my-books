# -*- coding: utf-8 -*-
"""Editing the map — persistence only, no rules (P6.1, MAP_PLAN §3).

The third module of its kind, and it exists for the reason
``reconcile_apply.py`` gives in its own docstring: this work needs BOTH
``app.domain`` (the rules and their entities) and ``app.ports``
(``MapStore``, ``ShelfStore``, ``IdGen``, ``Clock``), and neither the pure
domain (H1) nor an API router (whose job is HTTP shape, not orchestration
across two ports) is the right home.

**What is orchestrated here, and why none of it can live in one store.**
MAP_PLAN §3.1 says a drawn slot IS a ``Shelf``. So a bookcase is never one
record:

    draw a case with 2 columns of 5 levels
      -> 1 bookcase + 1 section  (MapStore)
      -> 10 real, empty, addressed shelves  (ShelfStore)

and erasing a column is the same sentence backwards, with the clamp that
makes this item the risky one: **an occupied shelf is detached, never
deleted** (``app.domain.place.plan_slot_removal``). Every function below is
"ask the domain what should happen, then write it through the ports".

⚠ It may import ``app.domain`` and ``app.ports``; it must NOT import
``app.adapters``, and it is imported BY ``app.api``, never the reverse —
``tests/test_layering.py`` enforces both.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.domain import (
    Bookcase,
    LibraryRef,
    Place,
    Section,
    Shelf,
    ShelfAddress,
    SlotChange,
    SlotRemoval,
    apply_default_depth,
    attach_bookcase,
    detach_bookcase,
    new_section,
    new_shelf,
    plan_slot_removal,
    unbind_shelf,
)
from app.ports import Clock, IdGen
from app.ports.map import MapStore
from app.ports.store import BookStore, ShelfNotEmpty, ShelfStore


def deepest_occupied_depths(
    shelves: ShelfStore,
    books: BookStore,
    library: LibraryRef,
    candidates: Iterable[Shelf],
) -> dict[str, int]:
    """How far back something actually stands on each of these shelves.

    ⚠ **Both halves**, and the second is the one a reasonable person leaves
    out. **Captures** are the photographic record a re-read diffs against
    (§5.6); **copies** are the books themselves — a shelf can hold books with
    no photograph at all (a MANUAL entry, or a photo deleted later), so asking
    only about captures calls an occupied shelf empty.

    A shelf with nothing on it is simply absent, which is what makes this the
    answer to both questions the map asks: ``id in result`` is *is anything
    standing here?* and ``result[id]`` is *how far back?* Two separate
    queries could disagree, and this is the pair whose disagreement either
    deletes a shelf or un-declares a book's depth.

    Every destructive function below computes this ITSELF rather than taking
    it as an argument. A required argument stops a caller FORGETTING; it does
    not stop the answer being stale by the time it is used, and a review
    measured that window closing on a book added from the phone while the map
    was open on a laptop.
    """
    from_copies = books.deepest_copy_depth(library)
    from_photos = shelves.deepest_capture_depth(library)
    deepest: dict[str, int] = {}
    for shelf in candidates:
        depth = max(from_copies.get(shelf.id, 0), from_photos.get(shelf.id, 0))
        if depth:
            deepest[shelf.id] = depth
    return deepest


@dataclass(frozen=True)
class DrawnCase:
    """What drawing one bookcase created — the numbers a screen reports back.

    ``shelves`` is a count and not a list on purpose: ten new empty shelves
    are not ten things the owner wants listed, they are one bookcase. The
    ids are on the shelves themselves for anyone who needs them.
    """

    bookcase: Bookcase
    sections: tuple[Section, ...]
    shelves: int


def draw_bookcase(
    map_store: MapStore,
    shelves: ShelfStore,
    library: LibraryRef,
    bookcase: Bookcase,
    *,
    ids: IdGen,
    clock: Clock,
    columns: int,
    levels: int,
    depth: int,
) -> DrawnCase:
    """Create a bookcase, its first section, and every shelf that section
    describes.

    The shelves come into existence HERE rather than lazily on first
    photograph, and that is §3.1's whole point: a drawn slot is a real row
    from the moment it is drawn, so "the books on this shelf" has one code
    path for the drawn and the photographed alike.

    Each shelf takes the section's ``default_depth`` **as a copy** (§3.3).
    Nothing reads back through to the section afterwards.
    """
    map_store.save_bookcase(library, bookcase)
    section = new_section(
        id=ids.new_id(),
        library_id=library.id,
        bookcase_id=bookcase.id,
        ordinal=1,
        columns=columns,
        default_levels=levels,
        default_depth=depth,
    )
    map_store.save_section(library, section)
    made = _fill(shelves, library, section, section.addresses,
                 ids=ids, clock=clock)
    return DrawnCase(bookcase=bookcase, sections=(section,), shelves=made)


def apply_slot_change(
    map_store: MapStore,
    shelves: ShelfStore,
    books: BookStore,
    library: LibraryRef,
    change: SlotChange,
    *,
    ids: IdGen,
    clock: Clock,
) -> SlotRemoval:
    """Persist a section edit: the lost shelves, the grid, and the new ones.

    ⚠ **Removals first, then the section, then the additions**, and the order
    is the whole safety of the function. A review measured the previous one
    (section first): shrinking a column wrote the smaller grid, the removal
    loop then raised, and the shelf left behind was addressed to a slot that
    no longer existed — *"a shelf nothing can render"*, which is what the old
    docstring claimed the order was avoiding. Worse, it did not heal: the
    retry recomputed ``dropped`` from the already-shrunk section, got nothing,
    and the bookcase became permanently undeletable because ``delete_bookcase``
    still counted the stray.

    This order is self-healing in both directions. A failure before the
    section is written leaves the drawing exactly as it was, so the retry
    computes the SAME change and finishes it; a failure after it leaves slots
    with no shelves, which is an unphotographed bookcase — a state the model
    already allows and every screen already handles.

    Occupancy is computed HERE, immediately before the destructive half,
    rather than taken as an argument. A required argument stops a caller
    forgetting; it does not stop the answer going stale between the request
    and the write, and the measured case was a book added from the phone
    while the map was open on a laptop.
    """
    losing = [
        shelf
        for address in change.dropped
        if (shelf := shelves.get_shelf_at(library, address)) is not None
    ]
    removal = _release(shelves, books, library, losing)
    map_store.save_section(library, change.section)
    # The WHOLE address set, not just `change.added` — `_fill` is idempotent
    # by address, so this costs nothing extra and heals a section whose slots
    # lost their shelves to a concurrent edit.
    _fill(shelves, library, change.section, change.section.addresses,
          ids=ids, clock=clock)
    return removal


def clear_bookcase_slots(
    map_store: MapStore,
    shelves: ShelfStore,
    books: BookStore,
    library: LibraryRef,
    bookcase_id: str,
) -> SlotRemoval:
    """Empty every slot of a bookcase, so the case can then be deleted.

    Split from the delete deliberately: ``MapStore.delete_bookcase`` REFUSES
    while a shelf still stands in one of its sections, and the API calls this
    first, having shown the owner the counts. A store method that quietly
    emptied the slots itself would be the silent data-loss path MAP_PLAN §2
    predicted for this exact item.
    """
    return _release(shelves, books, library,
                    _standing_in_bookcase(map_store, shelves, library,
                                          bookcase_id))


def clear_section_slots(
    shelves: ShelfStore,
    books: BookStore,
    library: LibraryRef,
    section_id: str,
) -> SlotRemoval:
    """Empty ONE section's slots, so that section can then be deleted.

    Separate from :func:`clear_bookcase_slots` because they are different
    requests: a bookcase with a base and a hutch has two sections, and
    implementing *"remove the hutch"* by clearing the case would detach or
    delete every shelf in the base as well.
    """
    return _release(shelves, books, library,
                    shelves.list_shelves_in_section(library, section_id))


def _standing_in_bookcase(
    map_store: MapStore,
    shelves: ShelfStore,
    library: LibraryRef,
    bookcase_id: str,
) -> list[Shelf]:
    snapshot = map_store.load_map(library)
    standing: list[Shelf] = []
    for section in snapshot.sections:
        if section.bookcase_id == bookcase_id:
            standing.extend(
                shelves.list_shelves_in_section(library, section.id))
    return standing


def _release(
    shelves: ShelfStore,
    books: BookStore,
    library: LibraryRef,
    losing: Iterable[Shelf],
) -> SlotRemoval:
    """Let go of a set of slots: detach what is occupied, delete what is not.

    The one place either half happens, so the rule cannot be half-applied by
    one caller and not another.
    """
    losing = list(losing)
    occupied = deepest_occupied_depths(shelves, books, library, losing)
    removal = plan_slot_removal(losing, occupied_ids=occupied.keys())
    by_id = {s.id: s for s in losing}
    for shelf_id in removal.detached:
        # It keeps its label, its photos and its books. What it loses is a
        # location the owner has just erased from the drawing — a smaller loss
        # than the shelf, and the only one that was asked for.
        shelves.save_shelf(library, unbind_shelf(by_id[shelf_id]))
    deleted: list[str] = []
    detached = list(removal.detached)
    for shelf_id in removal.deleted:
        try:
            shelves.delete_shelf(library, shelf_id)
            deleted.append(shelf_id)
        except ShelfNotEmpty:
            # It gained a photograph after the occupancy query and before the
            # delete. The store is right to refuse, and the planner's own rule
            # says an occupied shelf is DETACHED — so do that instead of
            # propagating, which is what left a half-applied edit behind.
            shelves.save_shelf(library, unbind_shelf(by_id[shelf_id]))
            detached.append(shelf_id)
    return SlotRemoval(deleted=tuple(deleted), detached=tuple(detached))


def apply_depth_default(
    shelves: ShelfStore,
    books: BookStore,
    library: LibraryRef,
    section: Section,
) -> tuple[Shelf, ...]:
    """Push a section's depth default onto its existing shelves.

    The explicit, opt-in half of §3.3 — and the half that needed books to be
    written at all: :func:`app.domain.apply_default_depth` refuses to take a
    shelf below its deepest occupied depth, and returns the ones it left
    deeper so the screen can say so rather than silently doing less than it
    was asked.

    ⚠ The occupancy is computed HERE, from both stores, for the reason
    :func:`apply_slot_change` gives — and this is the clamp whose absence a
    review measured directly: a copy recorded at depth 2 of a shelf that now
    declares one row, which ``Shelf.check_depth`` then refuses and no foreign
    key can see.

    Returns the shelves that were KEPT deeper.
    """
    standing = shelves.list_shelves_in_section(library, section.id)
    result = apply_default_depth(
        section, standing,
        deepest_occupied=deepest_occupied_depths(shelves, books, library,
                                                 standing),
    )
    for shelf in result.shelves:
        shelves.save_shelf(library, shelf)
    return result.kept


def attach_case_to_room(
    map_store: MapStore,
    library: LibraryRef,
    bookcase: Bookcase,
    place: Place | None,
) -> Bookcase:
    """Point a case at a room (or at none) and persist it.

    Thin, and here rather than in a router so that the one place a bookcase's
    ``place_id`` and ``floor_id`` change together is a place the layering test
    can see. ``place=None`` is an explicit DETACH — geometry-driven
    reassignment goes through ``app.domain.reattach_bookcase``, which never
    orphans.
    """
    moved = attach_bookcase(bookcase, place) if place else detach_bookcase(bookcase)
    map_store.save_bookcase(library, moved)
    return moved


def _fill(
    shelves: ShelfStore,
    library: LibraryRef,
    section: Section,
    addresses: tuple[ShelfAddress, ...],
    *,
    ids: IdGen,
    clock: Clock,
) -> int:
    """Create one empty shelf per address that has none yet.

    **Two queries and one write, whatever the size of the bookcase.** The
    per-address version asked ``get_shelf_at`` and wrote once per slot, and
    the SQLite adapter opens a connection per operation — a security review
    measured 40 columns of 40 costing 16.5 seconds and 1600 connections from
    a 110-byte request. This lists the section once and writes the missing
    shelves as one transaction.

    Idempotent by address, which is what makes a retried request safe: the
    slot is the identity, so a second call finds the shelf already standing
    there instead of minting a twin the unique index would then refuse.

    ⚠ Callers pass the section's WHOLE address set, not just what a change
    added — so a slot left empty by a lost update (two tabs editing one
    section) gains its shelf on the next edit instead of staying a drawn
    rectangle with nothing behind it.
    """
    standing = {s.address for s in shelves.list_shelves_in_section(
        library, section.id)}
    now = clock.now_iso()
    fresh = tuple(
        new_shelf(
            id=ids.new_id(),
            library_id=library.id,
            depth_count=section.default_depth,
            created_at=now,
            address=address,
        )
        for address in addresses if address not in standing
    )
    shelves.save_shelves(library, fresh)
    return len(fresh)
