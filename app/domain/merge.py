# -*- coding: utf-8 -*-
"""Two shelf identities becoming one (P6.4d, MAP_PLAN §3.11–§3.13).

The dangerous half of P6.4, and the one item of this pillar that can lose
books. §3.14 keeps it apart from *bind* for exactly that reason: binding an
unaddressed shelf into a free slot moves nothing, while this moves a
POPULATION of copies, joins two capture strips and overwrites human answers —
and it looks like success either way, because the map gets fuller.

**What this module is.** The pure half (H1): given both shelves and everything
standing on them, it says what the merge would write — in the ORDER it must be
written — and what it would overwrite. It reads nothing and writes nothing.
:mod:`app.map_merge` is the half that holds the ports.

**One sentence decides the six tables** (§3.13): *a row that governs a future
write moves; a row that records a past event stays.* So ``copies``,
``captures``, ``decisions`` and ``duplicate_questions`` move, while
``provenance`` and ``reads``/``claims`` stay exactly where they are — the
immutable archive VISION §5.5 and ``book.py`` both promise. A past read still
means *run R sighted this copy at identity A*, which is true, and is the
precedent ``list_reads_for_capture`` already set one level down.

⚠ **Depth NUMBERS are never remapped** (§3.12). Depth 2 of the absorbed shelf
is depth 2 of the survivor, because renumbering would move books without
moving books. The survivor DEEPENS to cover both — never shallows — and the
new count is the ladder §5.1 already applies: what either side declared, and
how far back anything actually stands.

⚠ **The order of a merged capture strip is DECLARED, not inferred** (§3.12).
Appending the absorbed shelf's photographs after the survivor's encodes a
claim — *its half is to the right* — that nothing measured. So
:class:`StripOrder` is a required argument with no default, and the caller is
a radio button.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from app.domain.alias import ShelfAlias
from app.domain.book import DomainError
from app.domain.copy_resolution import DuplicateQuestion
from app.domain.reconcile import Decision
from app.domain.shelf import Capture, Shelf


class StripOrder(str, Enum):
    """Which shelf's photographs come first on the merged strip.

    No default anywhere, on purpose. §5.7's rule is *declared, never
    detected*, and left-to-right order is a physical claim about wood that no
    photograph carries.
    """

    ABSORBED_FIRST = "absorbed_first"
    SURVIVOR_FIRST = "survivor_first"


class MergeRefused(DomainError):
    """The merge did not happen, and the sentence says which merge it was.

    ``reason`` is a stable code so a client can translate it; ``str(exc)`` is
    the English the API sends as ``detail``. Two fields rather than one
    because P6.4c ended with the opposite mistake filed against it — a 409
    that carried the occupant as prose, leaving the client to parse English
    out of a message or throw the whole thing away.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class CopyPlacement:
    """Where one copy stands — the only columns a merge writes on it.

    ⚠ **Not the whole ``Book``**, and that is the load-bearing choice rather
    than a shortcut. A merge writes ``shelf_id`` and ``depth`` on a copy and
    touches nothing else, so this is *the row as it stood* for the part the
    edit is responsible for. Remembering the whole book would make the undo
    put back a TITLE as well — reverting a rename somebody typed in between —
    and would make the fingerprint refuse an undo because a book was edited on
    a screen that has nothing to do with the map.
    """

    book_id: str
    copy_id: str
    shelf_id: str
    depth: int

    def __post_init__(self) -> None:
        if not self.book_id or not self.copy_id:
            raise DomainError("a placement names a book and one of its copies")
        if not self.shelf_id:
            raise DomainError("a placement names the shelf the copy stands on")
        if self.depth < 1:
            raise DomainError("depth is 1-based")


@dataclass(frozen=True)
class DecisionClash:
    """One ``(depth, book_key)`` a human answered on BOTH shelves.

    §3.13: the newer ``decided_at`` wins, which is the rule the table's own
    upsert already applies to a person changing their mind. What is new here
    is that the loser is a DIFFERENT person's answer at a different place, so
    the preview names every one of these rather than choosing silently.
    """

    depth: int
    book_key: str
    winner: str  # "absorbed" | "survivor"
    absorbed_kind: str
    survivor_kind: str


@dataclass(frozen=True)
class MergePlan:
    """What the merge would write, in the order it must be written.

    Every tuple is *what to do*; :attr:`overwritten` and the ``was_*`` tuples
    are *what it costs*, which is both what the preview shows and what the
    undo journal remembers. The two are built together here so a screen
    cannot be shown one and a journal written the other.
    """

    absorbed_id: str
    survivor_id: str
    #: The survivor's depth AFTER — never smaller than it was (§3.12).
    depth: int
    survivor: Shelf

    #: Copies to re-point, and where they stood before.
    copies: tuple[CopyPlacement, ...] = ()
    was_copies: tuple[CopyPlacement, ...] = ()

    #: Captures to write, IN ORDER. See :func:`plan_merge` for why the order
    #: is part of the answer rather than the caller's problem.
    captures: tuple[Capture, ...] = ()
    was_captures: tuple[Capture, ...] = ()

    #: Decisions to write at the survivor, and questions likewise.
    decisions: tuple[Decision, ...] = ()
    was_decisions: tuple[Decision, ...] = ()
    questions: tuple[DuplicateQuestion, ...] = ()
    was_questions: tuple[DuplicateQuestion, ...] = ()

    #: Keys to delete: ``(shelf_id, depth, book_key)``.
    drop_decisions: tuple[tuple[str, int, str], ...] = ()
    drop_questions: tuple[tuple[str, int, str], ...] = ()

    #: Identities that already resolved to the absorbed shelf and must be
    #: re-pointed at the survivor, as they stood.
    was_aliases: tuple[ShelfAlias, ...] = ()

    #: Every ``(depth, book_key)`` answered on both sides.
    clashes: tuple[DecisionClash, ...] = ()

    @property
    def books(self) -> int:
        """How many distinct books move — the number a person recognises."""
        return len({c.book_id for c in self.was_copies})

    @property
    def copies_per_depth(self) -> dict[int, int]:
        return _tally(c.depth for c in self.was_copies)

    @property
    def photos_per_depth(self) -> dict[int, int]:
        return _tally(c.depth for c in self.was_captures
                      if c.shelf_id == self.absorbed_id)


def _tally(values) -> dict[int, int]:
    out: dict[int, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def merged_depth(
    absorbed: Shelf,
    survivor: Shelf,
    copies: tuple[CopyPlacement, ...],
    captures: tuple[Capture, ...],
) -> int:
    """§3.12's ladder: the deepest thing either side declared or holds.

    Both DECLARATIONS matter and so do both realities. The survivor's
    ``depth_count`` is often a creation-time default copied from its section
    (§3.3) that nobody looked at, while the absorbed shelf's is usually a
    human answer to *"add a row behind this one"* — the one thing §5.7 says
    cannot be detected. Taking the survivor's number alone would silently
    un-declare it.

    Deepening is never refused and shallowing never happens here: a merge is
    not the place to discover that a row of books has nowhere to be.
    """
    return max(
        absorbed.depth_count,
        survivor.depth_count,
        max((c.depth for c in copies), default=1),
        max((c.depth for c in captures), default=1),
    )


def plan_merge(
    absorbed: Shelf,
    survivor: Shelf,
    *,
    copies: tuple[CopyPlacement, ...],
    captures: tuple[Capture, ...],
    decisions: tuple[Decision, ...],
    questions: tuple[DuplicateQuestion, ...],
    aliases: tuple[ShelfAlias, ...],
    strip: StripOrder,
) -> MergePlan:
    """What absorbing ``absorbed`` into ``survivor`` would do.

    Every collection is *everything standing at either shelf* — the caller
    fetches once and this decides. Refusals that are facts about the two
    shelves are raised here; the ones that are facts about the rest of the
    world (a read still running, a slot some other alias claims) belong to
    :mod:`app.map_merge`, which is what can see them.

    **The capture order is part of the answer, not the caller's problem.**
    ``(shelf, depth, order)`` is unique, so writing the merged strip in the
    wrong sequence raises ``DuplicateCaptureSlot`` half-way through an edit
    that has already moved books. With ``SURVIVOR_FIRST`` nothing of the
    survivor's moves and the absorbed strip lands after the highest order it
    already has. With ``ABSORBED_FIRST`` the survivor's own photographs shift
    up — written HIGHEST FIRST, so every target slot is free at the moment it
    is written, which is why this returns an ordered tuple rather than a set.
    """
    if absorbed.id == survivor.id:
        raise MergeRefused(
            "same_shelf", "a shelf cannot be merged into itself")
    if absorbed.library_id != survivor.library_id:
        raise MergeRefused(
            "other_library",
            "these two shelves belong to different libraries")
    if absorbed.virtual or survivor.virtual:
        # §5.7: the wishlist stands nowhere. Merging into or out of it would
        # give unowned books a location that exists, or take a located
        # population and file it under a shelf that is not furniture.
        raise MergeRefused(
            "wishlist",
            "the wishlist is not a shelf; it stands nowhere (§5.7)")

    was_copies = tuple(c for c in copies if c.shelf_id == absorbed.id)
    depth = merged_depth(absorbed, survivor, copies, captures)

    moved_copies = tuple(replace(c, shelf_id=survivor.id) for c in was_copies)

    was_captures, writes = _restrip(absorbed, survivor, captures, strip)

    (moves, drops, was_decisions,
     clashes) = _move_decisions(absorbed, survivor, decisions)
    (q_moves, q_drops, was_questions) = _move_questions(
        absorbed, survivor, questions,
        # ⚠ BOTH: the answers this merge moves, and the ones the survivor
        # already had. Built from the moving set alone, an absorbed question
        # could land on a key the survivor had decided long ago — the exact
        # pair `_move_questions` exists to forbid, reachable from the
        # direction its own test did not walk.
        moves + tuple(d for d in decisions if d.shelf_id == survivor.id))

    return MergePlan(
        absorbed_id=absorbed.id,
        survivor_id=survivor.id,
        depth=depth,
        survivor=replace(survivor, depth_count=depth),
        copies=moved_copies,
        was_copies=was_copies,
        captures=writes,
        was_captures=was_captures,
        decisions=moves,
        was_decisions=was_decisions,
        questions=q_moves,
        was_questions=was_questions,
        drop_decisions=drops,
        drop_questions=q_drops,
        was_aliases=tuple(a for a in aliases if a.shelf_id == absorbed.id),
        clashes=clashes,
    )


def _restrip(
    absorbed: Shelf,
    survivor: Shelf,
    captures: tuple[Capture, ...],
    strip: StripOrder,
) -> tuple[tuple[Capture, ...], tuple[Capture, ...]]:
    """The merged strip, per depth, as ``(rows as they stood, writes in order)``.

    ⚠ Only the rows that actually MOVE are returned as writes, and the ones
    that stand still are not remembered either. A survivor's photographs under
    ``SURVIVOR_FIRST`` keep their shelf, their depth and their order, so
    writing them back would be a no-op that the fingerprint then has to watch
    — an undo refused because somebody re-photographed an untouched shelf.

    ⚠⚠ **BOTH tuples are ordered, and for the same reason in opposite
    directions.** ``(shelf, depth, order)`` is unique, so a sequence that
    writes onto a slot whose occupant has not moved yet raises
    ``DuplicateCaptureSlot`` — forwards, in the middle of an edit that has
    already moved books; backwards, in the middle of an undo, which is worse
    because a half-replayed undo leaves an entry dead forever. Under
    ``ABSORBED_FIRST`` the two orders are not the reverse of each other: going
    forward the survivor's strip shifts UP and is written highest-first; coming
    back, the absorbed strip must LEAVE the survivor first (it is what occupies
    the low slots) and the survivor's rows then come down lowest-first.
    """
    mine = [c for c in captures if c.shelf_id == absorbed.id]
    theirs = [c for c in captures if c.shelf_id == survivor.id]
    was: list[Capture] = []
    writes: list[Capture] = []

    for depth in sorted({c.depth for c in mine + theirs}):
        here = sorted((c for c in mine if c.depth == depth),
                      key=lambda c: (c.order, c.id))
        there = sorted((c for c in theirs if c.depth == depth),
                       key=lambda c: (c.order, c.id))
        if strip is StripOrder.SURVIVOR_FIRST:
            start = max((c.order for c in there), default=-1) + 1
            was.extend(here)
            writes.extend(
                replace(c, shelf_id=survivor.id, order=start + n)
                for n, c in enumerate(here))
        else:
            if not here:
                # ⚠ Nothing of the absorbed shelf at this depth, so the shift
                # is zero and every write is a no-op — except that a
                # remembered row is a WATCHED row, so an untouched photograph
                # re-photographed later refused a legitimate undo. Measured.
                # This branch's own ⚠ already says rows that stand still are
                # not remembered; it was true of `SURVIVOR_FIRST` only.
                continue
            shift = len(here)
            # HIGHEST first: each target slot is vacated by the write before
            # it. Ascending would land on a row that has not moved yet.
            writes.extend(replace(c, order=c.order + shift)
                          for c in reversed(there))
            writes.extend(replace(c, shelf_id=survivor.id, order=n)
                          for n, c in enumerate(here))
            # Replay order, which is not the reverse: the absorbed strip has to
            # go home BEFORE the survivor's own rows come back down onto the
            # slots it is sitting in.
            was.extend(here)
            was.extend(there)
    return tuple(was), tuple(writes)


def _move_decisions(
    absorbed: Shelf,
    survivor: Shelf,
    decisions: tuple[Decision, ...],
) -> tuple[tuple[Decision, ...], tuple[tuple[str, int, str], ...],
           tuple[Decision, ...], tuple[DecisionClash, ...]]:
    """§3.13's load-bearing row, and why it moves.

    §5.6's rule is *"a book the user previously rejected here is not
    re-added"*, and *here* is ``(library, shelf, depth, book_key)``. Leave the
    absorbed shelf's rejections behind and the next read of the merged shelf
    **re-adds every phantom the owner ever rejected on that wood** — no row
    deleted, no key violated, nothing looking wrong.
    """
    standing = {(d.depth, d.book_key): d
                for d in decisions if d.shelf_id == survivor.id}
    moves: list[Decision] = []
    drops: list[tuple[str, int, str]] = []
    was: list[Decision] = []
    clashes: list[DecisionClash] = []

    for mine in sorted((d for d in decisions if d.shelf_id == absorbed.id),
                       key=lambda d: (d.depth, d.book_key)):
        was.append(mine)
        # Always: the row at the absorbed shelf goes either way, because its
        # key names a shelf that will not exist.
        drops.append((absorbed.id, mine.depth, mine.book_key))
        theirs = standing.get((mine.depth, mine.book_key))
        if theirs is None:
            moves.append(replace(mine, shelf_id=survivor.id))
            continue
        newer = (mine.decided_at or "") > (theirs.decided_at or "")
        clashes.append(DecisionClash(
            depth=mine.depth, book_key=mine.book_key,
            winner="absorbed" if newer else "survivor",
            absorbed_kind=mine.kind.value, survivor_kind=theirs.kind.value))
        if newer:
            # The survivor's row is about to be overwritten, so it is
            # remembered as it stood — the undo has nothing else to put back.
            was.append(theirs)
            moves.append(replace(mine, shelf_id=survivor.id))
    return tuple(moves), tuple(drops), tuple(was), tuple(clashes)


def _move_questions(
    absorbed: Shelf,
    survivor: Shelf,
    questions: tuple[DuplicateQuestion, ...],
    answered: tuple[Decision, ...],
) -> tuple[tuple[DuplicateQuestion, ...], tuple[tuple[str, int, str], ...],
           tuple[DuplicateQuestion, ...]]:
    """A to-do list, not a record (§3.13) — so it moves, and it closes.

    ⚠ The second half is an invariant this edit could break in silence: a
    question is open *until a Decision exists at the same key*. Move the
    absorbed shelf's decision onto a key where the survivor has an open
    question and the pair would coexist, which nothing else in the system ever
    produces. So a question whose key is now decided is dropped rather than
    carried, and remembered so the undo can re-open it.
    """
    decided = {(d.depth, d.book_key) for d in answered}
    standing = {(q.depth, q.book_key): q
                for q in questions if q.shelf_id == survivor.id}
    moves: list[DuplicateQuestion] = []
    drops: list[tuple[str, int, str]] = []
    was: list[DuplicateQuestion] = []

    for theirs in sorted(standing.values(), key=lambda q: (q.depth, q.book_key)):
        if (theirs.depth, theirs.book_key) in decided:
            was.append(theirs)
            drops.append((survivor.id, theirs.depth, theirs.book_key))

    for mine in sorted((q for q in questions if q.shelf_id == absorbed.id),
                       key=lambda q: (q.depth, q.book_key)):
        was.append(mine)
        drops.append((absorbed.id, mine.depth, mine.book_key))
        if (mine.depth, mine.book_key) in decided:
            continue
        theirs = standing.get((mine.depth, mine.book_key))
        if theirs is not None:
            if (mine.opened_at or "") <= (theirs.opened_at or ""):
                continue
            was.append(theirs)
        moves.append(replace(mine, shelf_id=survivor.id))
    return tuple(moves), tuple(drops), tuple(was)
