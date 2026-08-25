# -*- coding: utf-8 -*-
"""The undo journal's pure half — what an inverse IS (P6.4b, MAP_PLAN §3.15).

Five map edits destroy or detach shelves behind nothing but a ``confirm()``:
removing a column, removing a section, deleting a bookcase, removing a site,
and — since P6.3.2 — switching cells off. §3.15 makes every one of them
undoable, and this module is the shape that promise takes.

**The inverse is the ROWS AS THEY WERE, and nothing cleverer.** §3.15 rejects
a derived inverse for a reason worth repeating where the code is: a book the
owner typed onto a shelf by hand has no provenance, so after the edit nothing
distinguishes it from one that was always there, and a GUESSED inverse moves
books that never moved. So :class:`MapRestore` carries whole entities captured
before the edit, and an undo is an upsert of a remembered past. One shape
serves all five edits — a removed column and a deleted site differ only in
which rows they put in the bag — which is why there is no per-kind inverse
here and no ``if kind ==`` anywhere downstream.

**The fingerprint is how an undo proves the world is unchanged** (owner,
2026-08-24, choosing against §3.15's literal "invalidated the moment anything
else touches those rows" — that shape puts the journal on the hot path of
every product write, and the one write path that forgets to consult it
produces a silently WRONG undo, which is worse than a refused one). Instead:

    at the edit  -> digest what the edit LEFT BEHIND, over a scope derived
                    from the restore itself
    at the undo  -> digest the same scope again; equal means nothing moved,
                    and a mismatch REFUSES, naming the targets that changed

Two properties make it honest rather than merely cheap. It is **exact** — it
compares rows, not timestamps, so it cannot be fooled by a clock and there is
deliberately no expiry (age is not evidence that an undo is unsafe; the
digest is evidence that it is). And it is **scoped to what the undo would
overwrite**: the rows being restored, plus — for every section they stand in
— that section's whole slot map. The slot map is the load-bearing half.
Without it, restoring a column into slots some other shelf has since been
bound into passes every row check and then violates ``shelves_by_slot`` at
the store, which is a 500 where a refusal was owed.

Pure (H1): dataclasses, a digest, and a comparison. Nothing here reads a
store — :mod:`app.map_undo` gathers, this module decides.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Iterable

from app.domain.book import DomainError
from app.domain.place import Bookcase, Floor, Place, Section, Site
from app.domain.shelf import Shelf

#: What an undo puts back, per table, in the order it must be written:
#: a floor needs its site, a section needs its bookcase, a shelf needs its
#: section. The undo replays this tuple in order and the foreign keys hold.
RESTORE_ORDER = ("sites", "floors", "places", "bookcases", "sections", "shelves")


@dataclass(frozen=True)
class MapRestore:
    """The rows as they stood before one destructive edit.

    Every field is entities, not ids and not diffs — see the module docstring.
    A field left empty is the normal case: removing a column fills ``shelves``
    and ``sections`` and nothing else.
    """

    sites: tuple[Site, ...] = ()
    floors: tuple[Floor, ...] = ()
    places: tuple[Place, ...] = ()
    bookcases: tuple[Bookcase, ...] = ()
    sections: tuple[Section, ...] = ()
    shelves: tuple[Shelf, ...] = ()

    #: Shelf ids the edit CREATED, to be removed again by the undo.
    #:
    #: ⚠ The half a bag of old rows cannot express, and it is reachable on an
    #: ORDINARY removal rather than in theory. ``_fill`` is handed the
    #: section's whole address set, so a removal also mints a shelf for any
    #: slot a concurrent edit left empty (its own ⚠ says so). An undo that put
    #: the old shape back and left that shelf standing would leave a section
    #: describing fewer slots than there are shelves addressed to it.
    #:
    #: (An earlier draft of this note claimed the case was un-gapping a cell.
    #: It is not: ``set_gaps`` carries one boolean, so an un-gapping edit is
    #: purely additive and records nothing at all — there is no entry for it
    #: to corrupt. A review caught the wrong reason, which in this codebase is
    #: worse than none.) Removal goes through
    #: ``ShelfStore.delete_shelf``, which refuses while anything stands on it,
    #: so this can never be the thing that loses a book.
    created: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not (any(getattr(self, name) for name in RESTORE_ORDER)
                    or self.created)

    def counts(self) -> dict[str, int]:
        """What this would put back, for a screen to say before it is pressed."""
        counts = {name: len(getattr(self, name)) for name in RESTORE_ORDER
                  if getattr(self, name)}
        if self.created:
            counts["removed"] = len(self.created)
        return counts


@dataclass(frozen=True)
class MapUndoEntry:
    """One journal row. ``undone_at`` set means it has been replayed already.

    ``tag`` is the coalescing key and the reason a bookcase deletion is ONE
    entry rather than two — see :func:`coalesces_with`.
    """

    id: str
    library_id: str
    kind: str
    tag: str
    recorded_at: str
    restore: MapRestore
    fingerprint: dict[str, str] = field(default_factory=dict)
    undone_at: str | None = None
    #: Which entry came last, per library. Assigned BY THE STORE, monotonic,
    #: and the only thing that orders this table.
    #:
    #: ⚠ Not `recorded_at`, and not because a timestamp is untidy: the
    #: production clock has second resolution and the id source is uuid4, so
    #: two entries in one second tie and the tie breaks at random. Measured at
    #: 165/500 undoing the wrong bookcase and 83/500 restoring an empty one —
    #: see `_V23` in `app/adapters/migrations.py` for the whole probe. "Which
    #: came last" is a question about ORDER, so it is answered by a counter.
    seq: int = 0

    def __post_init__(self) -> None:
        if not self.library_id:
            raise DomainError("a journal entry must belong to a library (H2)")
        if not self.kind:
            raise DomainError("a journal entry must say what it undoes")
        if self.restore.is_empty():
            raise DomainError(
                "a journal entry with nothing to restore is not an undo; the "
                "edit that changed nothing records nothing"
            )

    @property
    def is_live(self) -> bool:
        return self.undone_at is None


# --- the fingerprint ------------------------------------------------------

#: The value a target digests to when the row is not there. A real digest can
#: never collide with it: it is not hex.
ABSENT = "absent"


def _digest(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      default=str).encode("utf-8")
    # Twelve hex characters. This is a change detector between two rows we
    # wrote ourselves minutes apart, not a defence against a forger — and a
    # short value keeps a 400-shelf entry's fingerprint readable in the file.
    return hashlib.sha256(blob).hexdigest()[:12]


def digest_row(entity) -> str:
    """Digest one entity, every field of it.

    Every field on purpose: the undo will overwrite the whole row, so any
    field that has changed since is a change the undo would silently discard.
    A label typed on a detached shelf is the case that made this specific —
    ``_release`` in :mod:`app.map_edit` records a review measuring exactly
    that label being destroyed in a one-query window.
    """
    return _digest(asdict(entity))


def digest_slots(shelves: Iterable[Shelf]) -> str:
    """Digest a section's slot map — who stands where, not what they are named.

    Deliberately NOT the whole row: a label typed on some other shelf of the
    same section is none of this undo's business, and refusing over it would
    make the journal useless in a library somebody is actually using. What it
    catches is the thing that would break: a slot the undo means to refill
    that is no longer free.
    """
    return _digest(sorted(
        (s.address.col, s.address.level, s.id)
        for s in shelves if s.address is not None
    ))


def digest_shape(section: Section | None) -> str:
    """Digest a section's SHAPE — its extent and its mask, nothing else.

    ⚠ The half ``digest_slots`` cannot see, and the one that produced an
    undrawable shelf. ``digest_slots`` answers *who stands where*; this
    answers *which cells exist at all*, and an unbind's restore watches only
    the first. Measured, with no concurrency: take a shelf off the map, put a
    television in that cell (allowed — the cell is empty now), press undo. The
    offer says ``available: true``, and the shelf comes back addressed to a
    cell the drawing does not have. ``toPlan`` renders neither a gapped cell
    nor one outside the extent, and the picker lists only unaddressed
    shelves — so a shelf holding books is in NEITHER list, reachable from no
    screen, until the next section edit detaches it.

    The same hole with a shortened column, and the same for every kind: a
    section edit that releases no shelf records nothing (§3.15 is about
    destructive edits), so the unbind stays at the head while the shape moves
    underneath it.

    ⚠ Not the whole row, for ``digest_slots``'s reason one line up: a
    section's DEFAULTS changing is none of this undo's business. Its extent
    is, because an address the undo writes has to still name a slot.
    """
    if section is None:
        return ABSENT
    return _digest((list(section.column_levels), sorted(section.gaps)))


def target_keys(restore: MapRestore) -> tuple[str, ...]:
    """Everything the fingerprint must cover, derived from the restore itself.

    Derived rather than stored, so the scope and the inverse cannot drift
    apart into a journal entry that checks one set of rows and writes
    another.
    """
    keys: list[str] = []
    for name in RESTORE_ORDER:
        keys.extend(f"{name}:{record.id}" for record in getattr(restore, name))
    keys.extend(f"shelves:{shelf_id}" for shelf_id in restore.created)
    for section_id in sections_touched(restore):
        keys.append(f"slots:{section_id}")
        keys.append(f"shape:{section_id}")
    # ⚠ The PARENTS every restored row needs, and the ordinal space every
    # restored section lands in. Both were missing, and both were measured:
    #
    #   delete a bookcase, then the now-empty storey, then undo
    #     -> `UnknownParent`, out of a route that promised `available: true`
    #   delete a section, add another (additive, so nothing is recorded),
    #   then undo  -> `DuplicateSectionOrdinal` against `sections_by_bookcase`
    #
    # A row check cannot see either: the rows being restored are unchanged in
    # both cases. What changed is the SHAPE they are being put back into,
    # which is the same thing `slots:` already watches one level down.
    for name, parent in parents_of(restore):
        keys.append(f"exists:{name}:{parent}")
    for section in restore.sections:
        keys.append(f"ordinals:{section.bookcase_id}")
    return tuple(sorted(set(keys)))


def parents_of(restore: MapRestore) -> tuple[tuple[str, str], ...]:
    """``(table, id)`` for every row a restore needs to already exist.

    A floor needs its site, a place and a bookcase their floor, a section its
    bookcase, a shelf its section — and a bookcase may also name a place. Rows
    the restore brings back ITSELF are excluded: a deleted bookcase and its
    cascaded sections travel together, and demanding that the bookcase already
    exist would refuse the very undo that creates it.
    """
    own = {name: {record.id for record in getattr(restore, name)}
           for name in RESTORE_ORDER}
    needed: set[tuple[str, str]] = set()

    def need(table: str, parent_id: str | None) -> None:
        if parent_id and parent_id not in own[table]:
            needed.add((table, parent_id))

    for floor in restore.floors:
        need("sites", floor.site_id)
    for place in restore.places:
        need("floors", place.floor_id)
    for bookcase in restore.bookcases:
        need("floors", bookcase.floor_id)
        need("places", bookcase.place_id)
    for section in restore.sections:
        need("bookcases", section.bookcase_id)
    for shelf in restore.shelves:
        if shelf.address is not None:
            need("sections", shelf.address.section_id)
    return tuple(sorted(needed))


def digest_ordinals(sections: Iterable[Section]) -> str:
    """Digest one bookcase's ordinal space — who is number what.

    The exact analogue of :func:`digest_slots` one level up, and it guards the
    same kind of unique index (``sections_by_bookcase``). Not the whole row,
    for the same reason: a section's DEFAULTS changing is none of this undo's
    business, but its ordinal being taken is the thing that would break.
    """
    return _digest(sorted((s.ordinal, s.id) for s in sections))


def sections_touched(restore: MapRestore) -> tuple[str, ...]:
    """Every section whose slot map this restore would disturb.

    Both directions: sections being restored, and sections that restored
    shelves would stand in — which are not the same set. Removing a column
    restores shelves into a section that never went anywhere.
    """
    ids = {section.id for section in restore.sections}
    ids.update(shelf.address.section_id for shelf in restore.shelves
               if shelf.address is not None)
    return tuple(sorted(ids))


def changed_targets(
    recorded: dict[str, str], current: dict[str, str],
) -> tuple[str, ...]:
    """Which targets moved between the edit and the undo.

    Compared over the union of both key sets, so a target that has vanished
    from the world is as visible as one that changed — and the caller can
    name it. Empty means the undo may proceed.
    """
    return tuple(sorted(
        key for key in set(recorded) | set(current)
        if recorded.get(key, ABSENT) != current.get(key, ABSENT)
    ))


# --- coalescing -----------------------------------------------------------

#: The two-request operations, as ``{second half: first half}``.
#:
#: Deliberately a closed table rather than "any two edits sharing a tag". The
#: loose version was written first and a test caught it merging two
#: DELIBERATE column removals of one section into a single undo — same tag,
#: minutes apart, two things the owner separately did. What earns a merge is a
#: pair that was never two decisions: the client cannot delete a bookcase
#: without clearing its slots first, so those two requests are one operation,
#: and nothing else in the router is.
CONTINUES = {
    "delete_bookcase": "clear_bookcase",
    "delete_section": "clear_section",
}


def partner_for(recent: Iterable[MapUndoEntry], tag: str,
                kind: str) -> MapUndoEntry | None:
    """The live entry this edit continues, or ``None``.

    ⚠ Searched BY TAG rather than "is the newest entry a match", which is what
    it used to be. Two bookcases removed in one flush interleave — the client
    sends four requests — so the newest entry when `delete_bookcase` records
    can easily be the OTHER case's clearing. A review measured that as 83
    empty bookcases in 500: the two halves of one removal failed to coalesce
    and the undo restored a case with no shelves. Looking for the partner by
    what it is, rather than by where it happens to sit, cannot make that
    mistake even if the ordering is wrong.
    """
    for entry in recent:
        if coalesces_with(entry, tag, kind):
            return entry
    return None


def coalesces_with(head: MapUndoEntry | None, tag: str, kind: str) -> bool:
    """Does a new edit tagged ``tag`` belong to the entry already at the head?

    **This is what makes "delete a bookcase" one undo instead of two.** The
    client issues that as two requests — ``DELETE .../slots`` then ``DELETE
    .../bookcases/{id}`` (``app/web/src/map/push.ts``) — and a journal at one
    request per entry would answer a press of undo by restoring an EMPTY
    bookcase, having left its shelves detached. Section removal is the same
    two-step. So the grain of an entry is the OPERATION, not the request.

    It is not a stack, and it is the mechanism this project already trusts on
    the client: ``app/web/src/map/core/history.ts`` coalesces commits sharing
    a tag, so fourteen keystrokes of a room name are one undo. Here the tag is
    the thing being edited, so the two halves of one removal share it and two
    removals of two bookcases never do.

    Deliberately no time window — the same reason the journal has no expiry.
    Merging is correct whenever this exact pair meets, because the first half
    still holds the true prior state; a clock would only make it correct
    sometimes.
    """
    return (head is not None and head.is_live and bool(tag)
            and head.tag == tag and CONTINUES.get(kind) == head.kind)


def merge_restores(older: MapRestore, newer: MapRestore) -> MapRestore:
    """Union two restores, **older wins** on a collision.

    Older wins because it is the earlier state, and the earlier state is the
    one an undo is trying to reach: the shelf row captured before it was
    detached still has its address, and the row captured after does not.
    """
    merged = {}
    for name in RESTORE_ORDER:
        by_id = {record.id: record for record in getattr(newer, name)}
        by_id.update({record.id: record for record in getattr(older, name)})
        merged[name] = tuple(by_id.values())
    # A shelf the FIRST half created and the second half destroyed is in both
    # bags, and it must end up in neither: it did not exist before the
    # operation, so an undo neither restores nor deletes it. Dropping it from
    # `created` is what the second half already recorded by capturing its row;
    # dropping that row too is what keeps the undo a true inverse.
    restored = {record.id for record in merged["shelves"]}
    merged["created"] = tuple(
        shelf_id for shelf_id in dict.fromkeys(older.created + newer.created)
        if shelf_id not in restored)
    merged["shelves"] = tuple(
        record for record in merged["shelves"]
        if record.id not in set(older.created + newer.created))
    return MapRestore(**merged)


def absorbed(head: MapUndoEntry, kind: str, restore: MapRestore,
             fingerprint: dict[str, str], at: str) -> MapUndoEntry:
    """The head, having swallowed a later edit that shares its tag.

    Keeps the head's ``id`` and ``recorded_at`` — one entry, and the moment it
    remembers is the moment the operation STARTED, which is the state it
    restores. Takes the new ``kind`` and the freshly computed fingerprint,
    because what the world looks like now is the second edit's doing.
    """
    return replace(
        head,
        kind=kind,
        restore=merge_restores(head.restore, restore),
        fingerprint=fingerprint,
        recorded_at=head.recorded_at,
        undone_at=None,
    )
