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
    SlotsOccupied,
    apply_default_depth,
    attach_bookcase,
    detach_bookcase,
    new_section,
    new_shelf,
    plan_bind,
    plan_slot_removal,
    slot_taken,
    unbind_shelf,
)
from app.domain.map_undo import MapRestore
from app.map_undo import Journal, record
from app.ports import Clock, IdGen
from app.ports.map import MapStore
from app.ports.store import (
    BookStore,
    DuplicateShelfSlot,
    ShelfHasAliases,
    ShelfNotEmpty,
    ShelfStore,
)


def deepest_occupied_depths(
    shelves: ShelfStore,
    books: BookStore,
    library: LibraryRef,
    candidates: Iterable[Shelf],
) -> dict[str, int]:
    """How far back something actually stands on each of these shelves.

    ⚠ **THREE halves since P6.4a**, and the third has no depth at all: a
    shelf other identities resolve to is OCCUPIED because it is a SURVIVOR,
    not because its aliases hold anything. An absorbed identity with zero
    copies and zero captures folds zero — and after a merge its captures are
    gone anyway — so the survivor read as empty, `plan_slot_removal` scheduled
    it for DELETE, and `delete_shelf` then raised `ShelfHasAliases` out of the
    middle of a destructive loop. Measured: three of four labelled shelves
    destroyed, ZERO journal entries (recording happens after the loop), and
    the bookcase left permanently undeletable.

    ⚠ **Both other halves**, and the second is the one a reasonable person
    leaves out. **Captures** are the photographic record a re-read diffs against
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
    # Copied, because the fold below writes into them and a port that returns
    # a Mapping has not promised the caller may edit it.
    from_copies = dict(books.deepest_copy_depth(library))
    from_photos = dict(shelves.deepest_capture_depth(library))
    # ⚠ **A shelf other identities resolve to is OCCUPIED** (P6.4a, §3.11).
    # Nothing is rewritten when shelves merge, so a copy that arrived with an
    # absorbed identity still names IT — and both dictionaries above are keyed
    # by the id on the row. Without this fold, a cell whose live shelf is
    # empty while its alias holds books reads as empty, and §3.10a's gap
    # silently swallows it: measured as the exact hole that check exists to
    # prevent, one identity out of reach.
    for alias in shelves.list_aliases(library):
        for source in (from_copies, from_photos):
            # ⚠ `get`, NOT `pop`. Popping MOVES the occupancy off the absorbed
            # shelf, which is only safe once its row is gone — and nothing
            # enforces that, since `save_alias` accepts an `alias_id` that is
            # still live and that window is exactly what a merge passes
            # through. Measured with the alias written and the row not yet
            # removed: the absorbed shelf read as empty, its cell was gapped
            # and silently detached instead of refused, and
            # `apply_depth_default` shallowed it under a copy standing at
            # depth 2 — the corruption its own docstring says a review already
            # measured once. A stale entry for a row that IS gone is inert:
            # such a shelf is never in `candidates`.
            deep = source.get(alias.alias_id, 0)
            if deep > source.get(alias.shelf_id, 0):
                source[alias.shelf_id] = deep
        # Depth zero and still occupied: being a survivor is the occupancy.
        from_copies.setdefault(alias.shelf_id, 0)
        from_copies[alias.shelf_id] = max(from_copies[alias.shelf_id], 1)
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
    return DrawnCase(bookcase=bookcase, sections=(section,),
                     shelves=len(made))


def apply_slot_change(
    map_store: MapStore,
    shelves: ShelfStore,
    books: BookStore,
    library: LibraryRef,
    change: SlotChange,
    *,
    journal: Journal,
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
    was = map_store.get_section(library, change.section.id)
    removal, before = _release(shelves, books, library,
                               _losing(shelves, library, change))
    map_store.save_section(library, change.section)
    # The WHOLE address set, not just `change.added` — `_fill` is idempotent
    # by address, so this costs nothing extra and heals a section whose slots
    # lost their shelves to a concurrent edit.
    made = _fill(shelves, library, change.section, change.section.addresses,
                 ids=ids, clock=clock)
    # ⚠ Only if something was actually LOST. §3.15 is about destructive
    # edits, and GROWING a column destroys nothing — but the journal is one
    # deep, so an entry for a purely additive edit does not merely add noise,
    # it evicts the real undo standing behind it. `made` rides along rather
    # than triggering: `_fill` mints shelves on a removal too (it heals slots
    # a concurrent edit emptied), and those must not survive the undo.
    if before:
        _record(journal, map_store, shelves, library, kind="remove_column",
                tag=f"section:{change.section.id}", was=was,
                shelves_before=before, created=made,
                wrote=_wrote(removal, before, made, change.section, ()))
    return removal


def apply_gaps(
    map_store: MapStore,
    shelves: ShelfStore,
    books: BookStore,
    library: LibraryRef,
    change: SlotChange,
    *,
    journal: Journal,
    ids: IdGen,
    clock: Clock,
) -> SlotRemoval:
    """Switch cells off (or back on) — :func:`apply_slot_change` that REFUSES.

    The one difference from every other slot edit, and it is the owner's
    decision (2026-08-22): a column shrink DETACHES an occupied shelf, so a
    book keeps its copy and loses its location; a gap **refuses** while
    anything the owner declared is standing there, and names what.

    ⚠⚠ **What a gap costs, stated exactly, because the first draft of this
    docstring got it wrong and a review measured it.** It said *"nothing was
    there to lose"*. An EMPTY shelf is not an empty thing: gapping and
    restoring a cell was measured losing a shelf's label
    (``מדף הטלוויזיה`` → ``""``), its per-shelf depth override (3 → the
    section default), and its id. So:

      - **books and photographs** refuse the gap — nothing that stands on a
        shelf can be lost to this gesture;
      - **a label, and a row declared BEHIND this shelf**, refuse it too:
        both are things the owner said about this cell (`rename_shelf`, and
        §5.7's *"add a row behind this one"*, which no photograph can
        detect), and each has a remedy the owner can act on — clear the name,
        take the row back;
      - **a shelf SHALLOWER than the section's default does not refuse**, and
        the asymmetry is measured rather than tidy. §3.3 makes a default
        drift away from its shelves by design, so `!=` refused every cell of
        any section whose default had been raised without applying — the
        feature's own scenario, and a refusal whose only remedy was to
        rewrite the depth of the entire section;
      - **standing decisions do NOT refuse it, and do not survive it.** They
        are keyed ``(library, shelf, depth, book_key)`` with no foreign key,
        so deleting the shelf orphans them and §5.6 stops suppressing a
        phantom the owner already rejected at that cell. It is not refused
        because the owner cannot ACT on such a refusal — there is no screen
        for clearing a decision — and a refusal nobody can satisfy is one
        they retry. §3.11's alias is the machinery that fixes this properly;
        P6.4e ("history across the seam") is where it lands.

    A column shrink has always had the same three costs; what is new is that
    a gap makes it a routine, reversible-LOOKING gesture, which is exactly
    why the cost is written here rather than assumed away.

    ⚠ The occupancy is asked HERE, immediately before the write, and for the
    reason :func:`deepest_occupied_depths` states — a required argument stops
    a caller forgetting, not the answer going stale. The window it cannot
    close (a photograph landing between this check and the delete) falls
    through to ``_release``, which detaches rather than propagating; that is
    the existing, argued behaviour for a slot that loses its address, and the
    alternative is a half-applied edit.

    ⚠ **P6.4a must extend this.** ``deepest_occupied_depths`` asks both stores
    about a LIVE ``shelf.id``. Once an alias exists, *"a shelf other
    identities resolve to is OCCUPIED"* has to reach it, or a cell whose live
    shelf is empty while its alias holds books passes this check and is
    gapped — and it does so without a single test going red.
    """
    # DEEPER than a fresh shelf here would be, not merely DIFFERENT. `!=` was
    # measured refusing every cell of an ordinary section: §3.3 says editing a
    # section's default touches no existing shelf, so "make the wall unit two
    # rows deep, then put the TV in the middle" — the feature's own scenario —
    # left six shelves at 1 beside a default of 2 and refused all of them,
    # naming a depth nobody had typed. Shallower than the default loses
    # nothing on a restore, because a restored shelf comes back AT the
    # default; deeper does, one row per cell.
    def declared(shelf: Shelf) -> bool:
        return bool(shelf.label) or shelf.depth_count > change.section.default_depth

    losing = _losing(shelves, library, change)
    # ⚠ The REFUSAL looks only at the cells this request named. `_losing` also
    # returns strays a concurrent edit left outside the extent (see its ⚠),
    # and refusing a television because some other cell of the case is
    # mis-addressed would be a refusal about something the owner cannot see.
    # Those strays are still RELEASED below — healing them is the point.
    named = {(a.col, a.level) for a in change.dropped}
    occupied = deepest_occupied_depths(shelves, books, library, losing)
    standing = tuple(
        shelf for shelf in losing
        if (shelf.address.col, shelf.address.level) in named
        and (shelf.id in occupied or declared(shelf))
    )
    if standing:
        raise SlotsOccupied(
            f"{len(standing)} of the cells still hold books, photographs, a "
            "name or a row behind them; empty or clear them before making "
            "the space",
            standing,
        )
    # `declared` again, INSIDE the destructive loop, because this check and
    # the delete are one query apart — see `_release`, where a review measured
    # a label typed in that window being destroyed outright.
    was = map_store.get_section(library, change.section.id)
    removal, before = _release(shelves, books, library, losing,
                               protect=declared)
    map_store.save_section(library, change.section)
    made = _fill(shelves, library, change.section, change.section.addresses,
                 ids=ids, clock=clock)
    # Switching cells OFF is the fifth destructive edit (P6.3.2, which
    # arrived after §3.15 named four). Switching them back ON destroys
    # nothing, so it records nothing — same rule and same reason as
    # `apply_slot_change` above, and the client's own drawing history is
    # what takes back an additive edit.
    if before:
        _record(journal, map_store, shelves, library, kind="gaps",
                tag=f"section:{change.section.id}", was=was,
                shelves_before=before, created=made,
                wrote=_wrote(removal, before, made, change.section, ()))
    return removal


def clear_bookcase_slots(
    map_store: MapStore,
    shelves: ShelfStore,
    books: BookStore,
    library: LibraryRef,
    bookcase_id: str,
    *,
    journal: Journal,
) -> SlotRemoval:
    """Empty every slot of a bookcase, so the case can then be deleted.

    Split from the delete deliberately: ``MapStore.delete_bookcase`` REFUSES
    while a shelf still stands in one of its sections, and the API calls this
    first, having shown the owner the counts. A store method that quietly
    emptied the slots itself would be the silent data-loss path MAP_PLAN §2
    predicted for this exact item.
    """
    removal, before = _release(
        shelves, books, library,
        _standing_in_bookcase(map_store, shelves, library, bookcase_id))
    # Tagged by the BOOKCASE, which is what makes this and the delete that
    # follows it one undo — see `app.domain.map_undo.coalesces_with`.
    _record(journal, map_store, shelves, library, kind="clear_bookcase",
            tag=f"bookcase:{bookcase_id}", shelves_before=before,
            wrote=_wrote(removal, before, (), None, ()))
    return removal


def clear_section_slots(
    map_store: MapStore,
    shelves: ShelfStore,
    books: BookStore,
    library: LibraryRef,
    section_id: str,
    *,
    journal: Journal,
) -> SlotRemoval:
    """Empty ONE section's slots, so that section can then be deleted.

    Separate from :func:`clear_bookcase_slots` because they are different
    requests: a bookcase with a base and a hutch has two sections, and
    implementing *"remove the hutch"* by clearing the case would detach or
    delete every shelf in the base as well.
    """
    removal, before = _release(
        shelves, books, library,
        shelves.list_shelves_in_section(library, section_id))
    _record(journal, map_store, shelves, library, kind="clear_section",
            tag=f"section:{section_id}", shelves_before=before,
            wrote=_wrote(removal, before, (), None, ()))
    return removal


def remove_record(
    map_store: MapStore,
    shelves: ShelfStore,
    library: LibraryRef,
    what: str,
    record_id: str,
    *,
    journal: Journal,
) -> bool:
    """Delete one map record, having first remembered it. ``False`` if absent.

    The five deletes went through a shared helper in the router
    (``_remove``), which is the right shape for turning a store's refusal into
    a 404 or a 409 and the wrong place to capture an inverse: a router that
    reads the row first is a router that can forget to. So the read, the
    delete and the recording are one function here, and the router keeps only
    the HTTP half.

    A bookcase carries its sections, because ``sections`` CASCADEs from
    ``bookcases`` in the schema — they go with it silently, and an undo that
    restored the case alone would put back an unaddressable shell, which is
    the state ``delete_section`` refuses to create on purpose.
    """
    table = {
        "site": (map_store.get_site, map_store.delete_site, "sites"),
        "floor": (map_store.get_floor, map_store.delete_floor, "floors"),
        "place": (map_store.get_place, map_store.delete_place, "places"),
        "bookcase": (map_store.get_bookcase, map_store.delete_bookcase,
                     "bookcases"),
        "section": (map_store.get_section, map_store.delete_section,
                    "sections"),
    }
    get, delete, field = table[what]
    was = get(library, record_id)
    # ⚠ Whatever ELSE the delete takes with it, or the undo puts back a
    # container and reports success while its contents stay gone. Three of the
    # five deletes reach past their own row, and two reviews measured all
    # three: a bookcase CASCADEs its sections in the schema; deleting a site
    # takes its empty storeys ("floors leave with their site"); deleting a
    # place NULLs the `place_id` of every case that stood in it. Only the
    # first was captured, so undoing a site deletion restored a site with zero
    # storeys — a state `delete_floor` refuses to create on purpose — and
    # undoing a room deletion left every bookcase attached to no room, with
    # nothing said either time.
    also: dict[str, tuple] = {}
    if was is not None:
        drawing = map_store.load_map(library)
        if what == "bookcase":
            also["sections"] = tuple(x for x in drawing.sections
                                     if x.bookcase_id == record_id)
        elif what == "site":
            also["floors"] = tuple(x for x in drawing.floors
                                   if x.site_id == record_id)
        elif what == "place":
            also["bookcases"] = tuple(x for x in drawing.bookcases
                                      if x.place_id == record_id)

    if not delete(library, record_id):
        return False

    # The tag is the thing removed, so `DELETE .../slots` followed by
    # `DELETE .../bookcases/{id}` — two requests, one operation — coalesce
    # into the single entry that puts both halves back. A site, floor or
    # place has no slot-clearing half and so needs no tag: RESTRICT already
    # refuses to remove one with anything under it.
    tag = f"{what}:{record_id}" if what in ("bookcase", "section") else ""
    tables = {field: (was,) if was is not None else ()}
    tables.update(also)
    # ⚠ **The three cascades are not the same kind of event, and what this
    # edit LEFT BEHIND has to tell them apart.** A site's floors and a
    # bookcase's sections are DELETED with their parent — absent. A room's
    # bookcases SURVIVE it: `delete_place` NULLs `place_id`, it does not
    # destroy furniture ("deleting a container never destroys what it held").
    #
    # Writing all three down as gone is what the first version did, and it was
    # invisible for two items because `_record` was dropping `wrote` on the
    # floor. The moment P6.4c forwarded it, `test_undoing_a_room_removal_puts_
    # its_bookcases_back_in_it` went red: the entry remembered a bookcase that
    # had been destroyed, the world had one that was merely detached, and the
    # fingerprint refused every room deletion for the rest of its life. That
    # test is the gate; it needed no change to become one.
    surviving = also.get("bookcases", ()) if what == "place" else ()
    kept_ids = {(f"bookcases:{case.id}") for case in surviving}
    gone = tuple((name, r.id) for name, kept in tables.items() for r in kept
                 if f"{name}:{r.id}" not in kept_ids)
    left = _wrote(None, (), (), None, gone)
    left.update({f"bookcases:{case.id}": detach_bookcase(case)
                 for case in surviving})
    _record(journal, map_store, shelves, library, kind=f"delete_{what}",
            tag=tag, wrote=left, **tables)
    return True


def _wrote(
    removal: SlotRemoval | None,
    before: tuple[Shelf, ...],
    created: tuple[Shelf, ...],
    section: Section | None,
    gone: tuple,
) -> dict:
    """What this edit LEFT BEHIND, keyed as the fingerprint keys it.

    Handed to the journal so the digest is taken from what we wrote rather
    than from a read that can already contain somebody else's work — the
    window `app.map_undo.fingerprint` documents, and the one `_release`'s own
    ⚠ says the hoisted re-read could not close.

    Every branch is what this module just did: a released shelf was either
    deleted (ABSENT, ``None``) or unbound, a created shelf stands as minted, a
    deleted record is gone, and an edited section is the one we saved.
    """
    wrote: dict = {}
    if section is not None:
        wrote[f"sections:{section.id}"] = section
    if removal is not None:
        deleted = set(removal.deleted)
        for shelf in before:
            wrote[f"shelves:{shelf.id}"] = (
                None if shelf.id in deleted else unbind_shelf(shelf))
    for shelf in created:
        wrote[f"shelves:{shelf.id}"] = shelf
    for name, record_id in gone:
        wrote[f"{name}:{record_id}"] = None
    return wrote


def _record(
    journal: Journal,
    map_store: MapStore,
    shelves: ShelfStore,
    library: LibraryRef,
    *,
    kind: str,
    tag: str,
    was: Section | None = None,
    shelves_before: tuple[Shelf, ...] = (),
    created: tuple[Shelf, ...] = (),
    wrote: dict | None = None,
    **tables,
) -> None:
    """Hand one destructive edit's inverse to the journal.

    A thin adapter and nothing more — it exists so the five call sites read as
    one line each. ``was`` is the section as it stood, the argument the two
    section editors have in common.

    ⚠ It does NOT centralise ``MapRestore``'s field names, whatever an earlier
    version of this docstring said. They appear in five places
    (``RESTORE_ORDER``, ``remove_record``'s dispatch, ``fingerprint``'s
    ``live`` map, ``_replay``'s ``writers``, ``_UNDO_DECODERS``) and four of
    them are keyed off ``RESTORE_ORDER``, so a new table raises ``KeyError``
    there. The fifth used to fail SILENTLY — ``fingerprint`` filtered its
    result by ``if key in known`` — and that filter is gone, so a scope key
    nothing produced now raises instead of quietly narrowing the check.
    """
    if was is not None:
        tables.setdefault("sections", (was,))
    record(
        journal, map_store, shelves, library, kind=kind, tag=tag,
        restore=MapRestore(
            shelves=tuple(shelves_before),
            created=tuple(shelf.id for shelf in created),
            **{name: tuple(value) for name, value in tables.items()},
        ),
        # ⚠ **This argument was accepted and dropped**, from P6.4b until
        # P6.4c found it. Five call sites computed `_wrote(...)` and handed it
        # over; this adapter took it into a parameter it never forwarded, so
        # `record` always got `None` and `fingerprint` always fell back to
        # re-reading. The whole fix a data-integrity review measured — another
        # tab's change committed between the edit's last write and the
        # journal's read, digested as "the state the edit left" and therefore
        # invisible to the undo — was inert the entire time, behind a
        # docstring in `fingerprint` saying it was closed. There is now a test
        # that holds that window open (`test_map_edit.py`,
        # `..._is_digested_from_what_the_edit_WROTE`); it fails without this
        # line, which is the only thing that makes the sentence true.
        wrote=wrote,
    )


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
    *,
    protect=None,
) -> tuple[SlotRemoval, tuple[Shelf, ...]]:
    """Let go of a set of slots: detach what is occupied, delete what is not.

    The one place either half happens, so the rule cannot be half-applied by
    one caller and not another.

    Returns the removal AND **the rows as they stood when it acted** — the
    inverse P6.4b's journal records. Returned rather than re-read by the
    caller because by the time the caller has the removal the rows are gone:
    an id is not enough to put a shelf back, and the only moment the whole row
    exists is here.

    ``protect`` is an extra *"do not destroy this one"* test, applied to the
    shelf as it stands **at the moment of the delete**. :func:`apply_gaps`
    passes one, and a data-integrity review measured why it has to be here
    rather than only upstream: the caller's check runs one query earlier, and
    this loop re-read only OCCUPANCY, so a label typed on the phone in that
    window was deleted outright with the route answering 200 and reporting
    nothing detached. Measured, with the window held open:

        label typed in the window : deleted=('id-5',) detached=()  -> gone
        book shelved in the window: deleted=()        detached=('id-5',)

    A protected shelf is DETACHED, exactly like an occupied one — the same
    smaller loss, and the same reason: half-applying the edit is worse.
    """
    losing = list(losing)
    occupied = deepest_occupied_depths(shelves, books, library, losing)
    removal = plan_slot_removal(losing, occupied_ids=occupied.keys())
    by_id = {s.id: s for s in losing}
    # Re-read ONCE, before anything is written, and now UNCONDITIONALLY — the
    # `protect` path below always needed it, and P6.4b's journal needs it for
    # every path. The inverse recorded for an undo has to be the row as it
    # stands at the moment it is destroyed, not as the caller last saw it: a
    # label typed in the window between the two (the case measured below) is
    # otherwise remembered in its OLD form, and an undo months later would put
    # the stale row back over work nobody asked it to touch. The fingerprint
    # cannot catch that one, because it is taken after this point and agrees
    # with itself.
    fresh: dict[str, Shelf] = {}
    for section_id in {s.address.section_id for s in losing if s.address}:
        fresh.update({sh.id: sh for sh in
                      shelves.list_shelves_in_section(library, section_id)})
    before = tuple(fresh.get(s.id) or s for s in losing)
    for shelf_id in removal.detached:
        # It keeps its label, its photos and its books. What it loses is a
        # location the owner has just erased from the drawing — a smaller loss
        # than the shelf, and the only one that was asked for.
        #
        # ⚠ Unbind the FRESH row, not the caller's snapshot. Same window and
        # the same loss the `protect` argument was added for, one branch over:
        # writing back `by_id[...]` reverts a label typed since the caller
        # looked, so the detach quietly destroys the very thing detaching was
        # meant to preserve. Found while hoisting the re-read for P6.4b's
        # journal — the fix costs nothing now that `fresh` is always built.
        shelves.save_shelf(library,
                           unbind_shelf(fresh.get(shelf_id) or by_id[shelf_id]))
    deleted: list[str] = []
    detached = list(removal.detached)
    # `fresh` above is that re-read, and it is ONE listing per section rather
    # than a `get_shelf` per shelf: the latter is a connection per shelf in
    # the SQLite adapter, the cost `_losing` and `_fill` both exist to avoid.
    # Measured over 400 cells: 807 connections asking one at a time, 408
    # listing the sections once.
    for shelf_id in removal.deleted:
        current = fresh.get(shelf_id) or by_id[shelf_id]
        if protect is not None and protect(current):
            shelves.save_shelf(library, unbind_shelf(current))
            detached.append(shelf_id)
            continue
        try:
            shelves.delete_shelf(library, shelf_id)
            deleted.append(shelf_id)
        except ShelfHasAliases:
            # ⚠ P6.4a. Other identities resolve to this shelf, so destroying
            # it would put every book that arrived with them out of reach —
            # and the planner's own rule for "must not be destroyed" is
            # DETACH. Caught here rather than allowed to escape: it is a
            # `StoreError`, so no router translates it, and letting it out of
            # this loop left three of four shelves destroyed with no journal
            # entry and the bookcase permanently undeletable. Measured.
            shelves.save_shelf(library, unbind_shelf(current))
            detached.append(shelf_id)
        except ShelfNotEmpty:
            # It gained a photograph after the occupancy query and before the
            # delete. The store is right to refuse, and the planner's own rule
            # says an occupied shelf is DETACHED — so do that instead of
            # propagating, which is what left a half-applied edit behind.
            shelves.save_shelf(library, unbind_shelf(current))
            detached.append(shelf_id)
    return SlotRemoval(deleted=tuple(deleted), detached=tuple(detached)), before


def bind_shelf_to_slot(
    shelves: ShelfStore,
    library: LibraryRef,
    shelf: Shelf,
    section: Section,
    address: ShelfAddress,
) -> Shelf:
    """Put an unaddressed shelf into a free slot (P6.4c, MAP_PLAN §3.14).

    **The safe half of §3.11**, and it is safe by what it refuses rather than
    by what it does: nothing is destroyed, nothing is moved, no two identities
    join. A shelf that stood nowhere now stands somewhere, and the inverse is
    :func:`unbind_shelf_from_map` — which is why this records no undo, the
    same argument ``set_gaps`` makes for switching a cell back ON.

    ⚠ **The refusal is checked AND caught.** ``plan_bind`` asks whether the
    slot is free; ``shelves_by_slot`` is what makes it true. Between the two
    there is a window a second tab fits into, and without the translation
    below it answers ``DuplicateShelfSlot`` — a `StoreError`, which no router
    turns into anything, so the owner would get a 500 for the ordinary race
    the whole feature is about. It is re-read rather than guessed at, because
    the occupant a refusal names has to be the one that is actually there.
    """
    bound = plan_bind(shelf, section, address,
                      shelves.get_shelf_at(library, address))
    try:
        shelves.save_shelf(library, bound)
    except DuplicateShelfSlot as exc:
        occupant = shelves.get_shelf_at(library, address)
        if occupant is None:
            # The index refused and nothing is there: not this race. Let the
            # store error travel, rather than inventing a refusal about an
            # occupant that does not exist.
            raise
        raise slot_taken(address, occupant) from exc
    return bound


def unbind_shelf_from_map(
    map_store: MapStore,
    shelves: ShelfStore,
    library: LibraryRef,
    shelf: Shelf,
    *,
    journal: Journal,
) -> Shelf:
    """Take a shelf off the drawing, keeping the shelf (P6.4c).

    The address goes; the books, the photographs, the label and the id all
    stay — ``unbind_shelf``'s own docstring, and the same clamp
    ``plan_slot_removal`` applies when a column is erased under an occupied
    shelf. What is left behind is a slot the section still describes with
    nothing in it, which is the state ``apply_slot_change`` already documents
    as *"an unphotographed bookcase"*.

    **It records an undo, and bind does not.** They are inverses, so this
    looks asymmetric until you ask what is lost: binding loses nothing, and
    unbinding loses an ADDRESS — the one thing about this shelf that a person
    read off a drawing and might not remember. §3.15's list is *destroy or
    detach*, and every other detach in this module is journalled; the same
    outcome reached by a deliberate gesture rather than as a side effect of
    erasing a column is not a smaller loss.

    **A shelf that stands nowhere is a no-op, not a refusal.** The retry a
    dropped response provokes must not answer 409 — and, more sharply, an
    entry whose restore is a shelf row that did not change would sit at the
    head of a one-deep journal doing nothing, which is the same as deleting
    the real undo standing behind it.
    """
    if shelf.address is None:
        return shelf
    detached = unbind_shelf(shelf)
    shelves.save_shelf(library, detached)
    _record(journal, map_store, shelves, library, kind="unbind_shelf",
            tag=f"shelf:{shelf.id}", shelves_before=(shelf,),
            wrote={f"shelves:{shelf.id}": detached})
    return detached


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


def _losing(
    shelves: ShelfStore,
    library: LibraryRef,
    change: SlotChange,
) -> list[Shelf]:
    """The shelves standing in the slots this change takes away.

    **One query, whatever the size of the change** — the same lesson `_fill`
    below records, arriving at the destructive end of the same pipeline. The
    per-address version asked ``get_shelf_at`` once per dropped slot, and the
    SQLite adapter opens a connection per operation: a security review
    measured one 400-cell gap request costing 800 of them, because
    :func:`apply_gaps` resolved the list and then :func:`apply_slot_change`
    resolved the identical list again.

    Shared by both for that reason, rather than passed down from one to the
    other: an argument would be a second way to answer *"which shelves are
    losing their slot?"*, and this file already carries the scar of an
    argument that could be stale (``occupied_ids``).

    ⚠ **Against the section the change LEAVES BEHIND, not against
    ``change.dropped``**, and a data-integrity review measured the difference.
    ``_change`` diffs the section the handler read; if another request commits
    in between, ``dropped`` omits addresses only that other request created,
    nothing ever releases them, and a ``Shelf`` is left addressed to a cell
    the section no longer describes. Measured, two tabs, one restoring a
    gapped cell while the other shrank that column:

        extent=(2, 4)  slots=[(1,1),(1,2),(2,1)…]
        shelves=[(1,1),(1,2),(1,4),(2,1)…]      consistent=False

    That stray is the *"shelf nothing can render"* :func:`apply_slot_change`
    says its write order exists to prevent, and it does not heal: every later
    ``dropped`` is computed from ``addresses``, which no longer contains that
    cell, so ``delete_bookcase`` counts it forever. Asking *"which shelves are
    NOT in the section's address set?"* heals it on the next edit — the
    destructive mirror of what ``_fill`` already does creatively.

    Pre-existing (two tabs resizing one column reach it with no gap anywhere),
    but P6.3.2 adds an innocuous-looking second way in: restoring a TV cell
    does not read like a resize.
    """
    keep = set(change.section.addresses)
    return [
        shelf
        for shelf in shelves.list_shelves_in_section(library,
                                                     change.section.id)
        if shelf.address is not None and shelf.address not in keep
    ]


def _fill(
    shelves: ShelfStore,
    library: LibraryRef,
    section: Section,
    addresses: tuple[ShelfAddress, ...],
    *,
    ids: IdGen,
    clock: Clock,
) -> tuple[Shelf, ...]:
    """Create one empty shelf per address that has none yet.

    Returns the shelves it MINTED, not a count of them — P6.4b needs their
    ids, because an edit that both drops a column and fills a restored cell
    has to be undone in both directions, and a shelf that did not exist
    before the edit must not exist after the undo either.

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
    return fresh
