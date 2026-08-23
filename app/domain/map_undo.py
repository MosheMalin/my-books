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
    #: ⚠ The half a bag of old rows cannot express, and it is not
    #: hypothetical: switching a cell back ON mints a shelf, so an undo that
    #: only restored the old ``gaps`` mask would leave that shelf standing in
    #: a cell the mask now says is empty — a section whose extent and mask
    #: disagree, which ``Section.__post_init__`` cannot catch because the
    #: contradiction is in a different table. Removal goes through
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
    return tuple(sorted(set(keys)))


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
