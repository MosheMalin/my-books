# -*- coding: utf-8 -*-
"""Taking back a destructive map edit (P6.4b, MAP_PLAN §3.15).

The fourth port-only top-level module, and it is here for the reason
``reconcile_apply.py`` and ``map_edit.py`` both give: this work needs BOTH
``app.domain`` (:mod:`app.domain.map_undo` — what an inverse is, and when it
is still valid) and ``app.ports`` (``MapUndoStore``, ``MapStore``,
``ShelfStore``, ``Clock``, ``IdGen``), and neither the pure domain (H1) nor a
router belongs across that seam.

**Three verbs.** :func:`record` is called by :mod:`app.map_edit` at the moment
of the edit, because that is the only place the world before it still exists.
:func:`offer` answers *what would undo do, and may it* without writing.
:func:`undo` replays, or refuses.

**The refusal is the feature.** §3.15: *"An undo that cannot prove the world
is still as it left it refuses, and says why."* Everything below is arranged
so that the proof is cheap and exact — a digest of the rows the undo would
overwrite, taken when the edit happened and taken again now. There is no
expiry and no age check anywhere in this module, deliberately (owner,
2026-08-24): a mis-tap noticed a week later is still a mis-tap, and a clock is
not evidence about rows.

⚠ It may import ``app.domain`` and ``app.ports``; it must NOT import
``app.adapters``, and it is imported BY ``app.api``, never the reverse —
``tests/test_layering.py`` enforces both.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain import LibraryRef
from app.domain.map_undo import (
    ABSENT,
    RESTORE_ORDER,
    MapRestore,
    MapUndoEntry,
    absorbed,
    changed_targets,
    partner_for,
    digest_ordinals,
    digest_row,
    digest_shape,
    digest_slots,
    merge_restores,
    parents_of,
    sections_touched,
    target_keys,
)
from app.ports import Clock, IdGen
from app.ports.map import MapStore
from app.ports.map_undo import MapUndoStore
from app.ports.store import (
    BookStore,
    ShelfHasAliases,
    ShelfNotEmpty,
    ShelfStore,
)


class UndoRefused(Exception):
    """The world moved under the entry, so the undo did not run.

    Carries the targets that changed, because *"something changed"* is the
    refusal §3.15 explicitly does not want — it says the undo must say WHY.
    """

    def __init__(self, message: str, changed: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.changed = changed


@dataclass(frozen=True)
class Journal:
    """The journal and the two things writing to it needs.

    One object rather than three parameters, because :mod:`app.map_edit`'s
    destructive functions take it as a REQUIRED argument — that is the
    invariant, and it is worth one small dataclass: a destructive edit cannot
    be written without being handed somewhere to record its inverse, so a new
    one cannot forget the way a new route could. ``clear_bookcase_slots`` and
    ``clear_section_slots`` had no ``ids``/``clock`` of their own, and giving
    them three arguments each to make the point would have been the version
    nobody keeps.
    """

    store: MapUndoStore
    ids: IdGen
    clock: Clock


@dataclass(frozen=True)
class UndoOffer:
    """What a press of undo would do — the answer ``GET /map/undo`` gives.

    ``available`` is the only field a caller needs to decide whether to show
    the control; the rest is what it should say. ``reason`` is populated
    exactly when ``available`` is false, and the three values are three
    different sentences: nothing was ever recorded, the last one has already
    been taken back, or the world moved.
    """

    available: bool
    kind: str = ""
    recorded_at: str = ""
    restores: dict[str, int] | None = None
    reason: str = ""
    changed: tuple[str, ...] = ()


# --- the fingerprint, gathered ---------------------------------------------

def fingerprint(
    map_store: MapStore,
    shelves: ShelfStore,
    library: LibraryRef,
    restore: MapRestore,
    wrote: dict[str, object] | None = None,
) -> dict[str, str]:
    """Digest the world over exactly the rows ``restore`` would overwrite.

    Called twice per entry with the same restore: once just after the edit,
    once when somebody presses undo. Equality means nothing moved.

    ⚠ ``wrote`` is what the EDIT ITSELF left, keyed the same way, and passing
    it closes a window that otherwise makes the whole design a lie. Recording
    happens after the edit and used to re-READ every row — so anything
    committed between the edit's last write and that read was digested as "the
    state the edit left behind" and became invisible to the undo. Measured
    with the interleaving held open: another tab's change to a section's depth
    default was reverted by an undo reporting ``available: true`` and an empty
    ``changed``. That is precisely the silently-wrong undo the fingerprint was
    chosen over an invalidation table to avoid.

    A value of ``None`` means the edit made that row ABSENT. Keys not in
    ``wrote`` still fall back to a read — the slot maps do, and their window
    stays open, which is stated here rather than pretended away.

    ⚠ **Bounded queries, not one per row.** The shelf rows come from a single
    ``list_shelves`` and the slot maps from one listing per touched section,
    so a cleared 400-slot bookcase costs a handful of reads. The naive shape —
    ``get_shelf`` per remembered id — is 400 connections in the SQLite
    adapter, the same cost ``_release`` and ``_fill`` in :mod:`app.map_edit`
    both exist to avoid, and it would land on the page that draws the map.
    """
    known: dict[str, str] = {}
    wrote = wrote or {}

    # ONE `load_map`, not a `get_*` per row. It is the same query count as a
    # single lookup and it serves the row digests, the parent checks and the
    # ordinal spaces together — which the per-row shape could not, since a
    # parent may be a table this restore never names.
    drawing = map_store.load_map(library)
    live = {
        "sites": {r.id: r for r in drawing.sites},
        "floors": {r.id: r for r in drawing.floors},
        "places": {r.id: r for r in drawing.places},
        "bookcases": {r.id: r for r in drawing.bookcases},
        "sections": {r.id: r for r in drawing.sections},
    }
    for name, standing in live.items():
        for record in getattr(restore, name):
            current = standing.get(record.id)
            known[f"{name}:{record.id}"] = (
                digest_row(current) if current is not None else ABSENT)

    # Presence only: what matters about a parent is that it is still there to
    # hang something on. Its own fields are somebody else's business.
    for name, parent_id in parents_of(restore):
        known[f"exists:{name}:{parent_id}"] = (
            "yes" if parent_id in live[name] else ABSENT)

    for section in restore.sections:
        known[f"ordinals:{section.bookcase_id}"] = digest_ordinals(
            r for r in drawing.sections
            if r.bookcase_id == section.bookcase_id)

    if restore.shelves or restore.created:
        # include_virtual, so that "not there" always means not there. A map
        # edit cannot touch the wishlist (§5.7 forbids it an address), but a
        # filter deciding what the word ABSENT means is a filter that can be
        # wrong about it.
        #
        # ⚠ Its own name. This used to REBIND `live`, which was the map's
        # five tables — harmless while nothing read them again, and a
        # `KeyError` the moment the shape keys below did.
        standing_shelves = {s.id: s for s in shelves.list_shelves(
            library, include_virtual=True)}
        watched = [shelf.id for shelf in restore.shelves]
        # The created ids are watched the same way and for the same reason
        # read backwards: the undo will DELETE these, so a row that has
        # changed since the edit is one somebody has worked on, and deleting
        # it is exactly what a refusal is for.
        watched.extend(restore.created)
        for shelf_id in watched:
            current = standing_shelves.get(shelf_id)
            known[f"shelves:{shelf_id}"] = (
                digest_row(current) if current is not None else ABSENT)

    for section_id in sections_touched(restore):
        known[f"slots:{section_id}"] = digest_slots(
            shelves.list_shelves_in_section(library, section_id))
        known[f"shape:{section_id}"] = digest_shape(
            live["sections"].get(section_id))

    # What the edit wrote WINS over what a later read says, for the reason in
    # the docstring: the read can already be somebody else's work.
    for key, value in wrote.items():
        known[key] = digest_row(value) if value is not None else ABSENT
        # ⚠ A section the edit wrote decides its own SHAPE key too. Without
        # this the row digest comes from `wrote` and the shape digest comes
        # from a read taken after it — two answers about one section, from two
        # moments, inside one entry. `apply_slot_change` is the whole reason:
        # it is the edit that CHANGES a shape, so it is the one whose shape
        # key must not be re-read.
        if key.startswith("sections:"):
            known[f"shape:{key.split(':', 1)[1]}"] = digest_shape(value)

    # Every key the domain says this restore covers, and no other. Computing
    # the scope in one place and the values in another is how the two drift
    # into an entry that checks one set of rows and writes a different one.
    #
    # ⚠ No `if key in known` filter: a key the scope names and nothing
    # produced is a bug in one of the two, and it used to be swallowed here.
    return {key: known[key] for key in target_keys(restore)}


# --- recording -------------------------------------------------------------

def record(
    journal: Journal,
    map_store: MapStore,
    shelves: ShelfStore,
    library: LibraryRef,
    *,
    kind: str,
    tag: str,
    restore: MapRestore,
    wrote: dict[str, object] | None = None,
) -> MapUndoEntry | None:
    """Write one destructive edit's inverse. ``None`` if there was nothing to
    take back.

    Called AFTER the edit has been written, because the fingerprint is a
    digest of what the edit left behind — but with a ``restore`` captured
    BEFORE it, which is why this cannot be a decorator or a middleware and
    lives inside :mod:`app.map_edit` instead.

    **An edit that changed nothing records nothing.** Removing a column that
    had no shelves in it is not an undoable event, and an entry for it would
    push a real one off the head — which, in a one-deep journal, is the same
    as deleting it.

    ⚠ It is not in the edit's transaction, and cannot be: the SQLite adapter
    opens a connection per operation by design. So a failure here loses the
    UNDO, never the edit. That asymmetry is the right way round — the owner
    keeps what they asked for and loses only the ability to take it back —
    and it is the reason this call is last.
    """
    if restore.is_empty():
        return None

    # ⚠ A WINDOW, not the single newest entry, and searched by tag. Two
    # bookcases removed in one flush interleave — the client sends four
    # requests — so the newest entry when `delete_bookcase` records can be the
    # other case's clearing. `partner_for` looks for what it is rather than
    # where it sits, so coalescing survives an interleave. Eight is generous:
    # a two-request operation's partner is at most a few entries back, and
    # `coalesces_with` still refuses anything that is not its own half.
    previous = partner_for(journal.store.recent(library, limit=8), tag, kind)
    if previous is not None:
        # The fingerprint is computed over the MERGED restore — the union is
        # what the one surviving entry will put back, so it is the scope that
        # has to be proved unchanged. Digesting only the second half would
        # leave the first half's rows unwatched inside an entry that restores
        # them.
        union = merge_restores(previous.restore, restore)
        merged = absorbed(
            previous, kind, restore,
            _coalesced_fingerprint(map_store, shelves, library, previous,
                                   union, restore, wrote),
            journal.clock.now_iso(),
        )
        journal.store.record(library, merged)
        return merged

    entry = MapUndoEntry(
        id=journal.ids.new_id(),
        library_id=library.id,
        kind=kind,
        tag=tag,
        recorded_at=journal.clock.now_iso(),
        restore=restore,
        fingerprint=fingerprint(map_store, shelves, library, restore,
                                wrote),
    )
    journal.store.record(library, entry)
    return entry


def _coalesced_fingerprint(
    map_store: MapStore,
    shelves: ShelfStore,
    library: LibraryRef,
    previous: MapUndoEntry,
    union: MapRestore,
    restore: MapRestore,
    wrote: dict[str, object] | None,
) -> dict[str, str]:
    """The union's digest, with the first half's keys taken from the first
    half's own entry rather than re-read.

    ⚠⚠ **The widest window in this module, and it was the last one open.**
    ``wrote`` closes the gap between an edit's write and the journal's read —
    two store calls. The coalescing branch computed the union's fingerprint
    with only the SECOND half's ``wrote``, so every key belonging to the
    first half fell back to a live read taken a full HTTP round trip later.
    Measured: clear a bookcase's slots, rename a detached shelf from another
    tab, delete the bookcase; the entry recorded the NEW label as its own
    work, answered ``available: true`` with an empty ``changed``, and the undo
    destroyed the rename.

    That is the commonest entry in the journal, not a corner: ``push.ts``
    sends *clear slots* and *delete* as a pair for every bookcase and every
    section removal, so a coalesced entry is what removing furniture always
    produces.

    ``previous.fingerprint`` is already the right answer for those keys — it
    was computed from the first half's own ``wrote``, at the moment that half
    wrote. A key the SECOND half touches must come from the fresh digest, and
    ``target_keys(restore)`` is exactly that set; everything else the union
    adds is the first half's, and the entry beside it remembers it correctly.
    """
    fresh = fingerprint(map_store, shelves, library, union, wrote)
    owned = set(target_keys(restore))
    return {
        key: (fresh[key] if key in owned or key not in previous.fingerprint
              else previous.fingerprint[key])
        for key in fresh
    }


# --- reading and replaying -------------------------------------------------

def offer(
    journal: Journal,
    map_store: MapStore,
    shelves: ShelfStore,
    library: LibraryRef,
) -> UndoOffer:
    """What a press of undo would do. Writes nothing.

    Checks the fingerprint too, so the control can be honest BEFORE it is
    pressed rather than only after — and so the sentence it shows is the same
    sentence :func:`undo` would raise.
    """
    entry = _head(journal, library)
    if entry is None:
        return UndoOffer(available=False, reason="nothing_recorded")
    if not entry.is_live:
        return UndoOffer(available=False, reason="already_undone",
                         kind=entry.kind, recorded_at=entry.recorded_at)

    changed = changed_targets(
        entry.fingerprint,
        fingerprint(map_store, shelves, library, entry.restore),
    )
    if changed:
        return UndoOffer(available=False, reason="world_moved",
                         kind=entry.kind, recorded_at=entry.recorded_at,
                         changed=changed)
    return UndoOffer(available=True, kind=entry.kind,
                     recorded_at=entry.recorded_at,
                     restores=entry.restore.counts())


def undo(
    journal: Journal,
    map_store: MapStore,
    shelves: ShelfStore,
    books: BookStore,
    library: LibraryRef,
) -> MapUndoEntry:
    """Replay the head, or raise :class:`UndoRefused`.

    Only the head, ever, and only once: *record all, undo the head* (owner,
    2026-08-24). Taking one back does NOT expose the edit before it — that is
    the n-deep stack this item deliberately is not, and it can arrive later by
    changing this function rather than the schema.
    """
    entry = _head(journal, library)
    if entry is None:
        raise UndoRefused("there is no map edit to take back")
    if not entry.is_live:
        raise UndoRefused(
            "the last map edit has already been taken back; there is no redo")

    changed = changed_targets(
        entry.fingerprint,
        fingerprint(map_store, shelves, library, entry.restore),
    )
    if changed:
        raise UndoRefused(
            f"{len(changed)} of the things this would put back have changed "
            "since; taking the edit back now would overwrite work done after "
            "it",
            changed,
        )

    _replay(map_store, shelves, books, library, entry.restore)
    journal.store.mark_undone(library, entry.id, journal.clock.now_iso())
    return entry


def _head(journal: Journal, library: LibraryRef) -> MapUndoEntry | None:
    entries = journal.store.recent(library, limit=1)
    return entries[0] if entries else None


def _replay(
    map_store: MapStore,
    shelves: ShelfStore,
    books: BookStore,
    library: LibraryRef,
    restore: MapRestore,
) -> None:
    """Put the remembered rows back, parents first.

    ``RESTORE_ORDER`` is the dependency order and the foreign keys are the
    reason: a floor needs its site, a section needs its bookcase, a shelf
    needs its section. Writing shelves first would fail on a restore that
    brings a whole deleted bookcase back, which is exactly the restore that
    matters most.

    Every write is an upsert, so a row that never went away is written back
    as it was — and the fingerprint has already proved that is a no-op rather
    than a silent overwrite of somebody's work.

    ⚠ A refusal raised by the removals below happens after some of them have
    already run, so an undo can stop half-way. What it leaves is empty slots
    in a section that still describes them — the same state
    ``apply_slot_change`` documents as *"an unphotographed bookcase, a state
    the model already allows and every screen already handles"*, and ``_fill``
    heals it on the next edit. The alternative is a can-I-delete query per
    shelf before the first write, which is the per-shelf connection cost this
    module goes out of its way to avoid, for a branch nothing but a race
    reaches.
    """
    # ⚠ Removals FIRST. A shelf the edit created may be standing in a slot a
    # remembered one is about to reclaim, and `shelves_by_slot` is unique —
    # so upserting before deleting turns a legitimate undo into an integrity
    # error at the store, which is a 500 where the operation was fine.
    #
    # ⚠⚠ And the whole removal set is JUDGED before any of it happens. The
    # first version raised on the first `ShelfNotEmpty`, after earlier
    # deletions had committed — so a refusal left the entry live, its
    # fingerprint permanently mismatched against a world the aborted replay
    # had itself changed, and the refusal NAMED a shelf that changed because
    # the undo deleted it. Measured, with no concurrency at all: an entry dead
    # forever, blaming the wrong row. It also claimed a pre-check would cost a
    # query per shelf, which was simply wrong —
    # `deepest_occupied_depths` answers it for an arbitrary set in two.
    if restore.created:
        # ⚠ Imported HERE because `map_edit` imports this module — the
        # destructive functions take a `Journal` — so a module-level import
        # would be a cycle. Not duplicated: `deepest_occupied_depths` is the
        # rule that a shelf is occupied by BOOKS as well as photographs, and
        # its own ⚠ says a second copy is how the two answers drift into one
        # that deletes a shelf somebody's books are standing on.
        from app.map_edit import deepest_occupied_depths

        standing = tuple(
            shelf for shelf in
            (shelves.get_shelf(library, i) for i in restore.created)
            if shelf is not None)
        occupied = deepest_occupied_depths(shelves, books, library, standing)
        if occupied:
            raise UndoRefused(
                f"{len(occupied)} of the shelves this would remove are no "
                "longer empty; taking the edit back now would destroy what is "
                "standing on them",
                tuple(sorted(f"shelves:{i}" for i in occupied)),
            )
    for shelf_id in restore.created:
        try:
            shelves.delete_shelf(library, shelf_id)
        except ShelfHasAliases:
            # Something has been merged INTO a shelf this undo would remove.
            # Skipping is right for the same reason the pre-check exists: the
            # shelf survives with what arrived on it, and the alternative is
            # the half-applied replay that leaves an entry dead forever
            # blaming a row the undo itself changed. Measured before this
            # clause: two of three created shelves gone, nothing restored,
            # the entry still live.
            continue
        except ShelfNotEmpty:
            # Only reachable if something landed between the check above and
            # here. Skipping is right: the shelf survives with what arrived on
            # it, which is the smaller loss, and the alternative is the
            # half-applied replay this pre-check exists to abolish.
            continue

    writers = {
        "sites": map_store.save_site,
        "floors": map_store.save_floor,
        "places": map_store.save_place,
        "bookcases": map_store.save_bookcase,
        "sections": map_store.save_section,
    }
    for name in RESTORE_ORDER:
        remembered = getattr(restore, name)
        if not remembered:
            continue
        if name == "shelves":
            # ONE unit, for the reason `ShelfStore.save_shelves` is a required
            # method rather than a convenience: a cleared bookcase is 400
            # shelves, and 400 connections is a request that times out on the
            # phone it was pressed from.
            shelves.save_shelves(library, tuple(remembered))
        else:
            for record in remembered:
                writers[name](library, record)
