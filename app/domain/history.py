# -*- coding: utf-8 -*-
"""A shelf's read history, derived — never stored twice (P2.8, §5.5/§5.6).

Two small, pure functions over data that already exists elsewhere (a Copy's
own append-only provenance, and a shelf's `Read` archive), so neither needs a
store of its own:

  - :func:`not_seen_streak` — the soft *"not seen in the last N reads"* badge
    (§5.6 option 2), the piece `app.domain.reconcile`'s own module docstring
    explicitly leaves for this item: *"this module only reports THIS read's
    NotSeenEntry list — persisting and thresholding a streak is P2.8's"*;
  - :func:`depth_staleness` — the shelf-detail screen's soft staleness line
    (UI_PLAN §3: *"rows 2, 3 not read since 11.3.2026"*).

Both are named in the plan's H5 checklist by implication of §5.6's central
rule (*never auto-remove an unseen book*): neither function below ever
touches a `Book`/`Copy`/store — a streak is a number for a badge, not an
instruction. The rule that actually enforces "never remove" lives in
`app.domain.reconcile._not_seen_here` (P2.5) and stays exactly as strict as
it already is; nothing here may weaken it, and nothing here CAN, since these
two functions have no way to delete anything — they take reads and copies and
return counts.

No I/O, no framework, no store — same rule as the rest of ``app/domain``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.domain.alias import ShelfAlias
from app.domain.book import Copy
from app.domain.read import Read, ReadStatus

# A read counts as evidence about what stood on a shelf only once it settled
# with real (possibly partial) claims — a `failed` read may have blown up
# before producing anything reliable, so it neither resets nor extends a
# streak, and it is not a "last read" for staleness either.
_COUNTS_AS_EVIDENCE = (ReadStatus.DONE, ReadStatus.STOPPED)


def _when(read: Read) -> str | None:
    return read.finished_at or read.started_at


def not_seen_streak(
    copy: Copy,
    shelf_id: str,
    depth: int,
    reads: Sequence[Read],
    aliases: Sequence[ShelfAlias] = (),
) -> int:
    """How many of the most recent finished reads of ``(shelf_id, depth)``
    did NOT reconfirm this copy — the count behind §5.6's soft badge
    (*"not seen in the last 3 reads of this shelf — still there?"*).

    Derived from the copy's OWN provenance rather than by re-running
    `app.domain.reconcile.reconcile` against today's state: each
    `Provenance` entry already names the read (``run_id``) that produced it,
    so "was this copy reconfirmed by read R" is a plain membership check —
    no library-wide state needs reconstructing, and there is nothing here
    that could ever remove the copy (see the module docstring).

    ``reads`` is scoped to ``(shelf_id, depth)`` by the caller — plus, since
    P6.4e, the reads of every identity this shelf answers for. Any read that
    matches neither is ignored defensively rather than raised on.

    A read that happened BEFORE this copy ever stood at this location tells
    us nothing about it and does not count against it — otherwise a copy
    added yesterday would inherit a "not seen in 40 reads" streak from
    photographs taken long before it existed here.

    ⚠⚠ **`aliases` is §3.16, and without it a merge silently zeroes every
    badge it touches.** Nothing is rewritten when two shelves become one
    (§3.11), so a copy that arrived with the absorbed identity still names IT
    in its provenance — and this function, asked about the survivor, found no
    sighting at all and returned 0. Measured: a book last actually seen in
    January reported the same 0 as one seen this morning, on the day the owner
    was reorganising, because 0 means BOTH *reconfirmed by the most recent
    read* and *never sighted here at all*.

    Pass ``ShelfStore.aliases_of(shelf_id)`` and the reads of every identity
    in the closure.

    **What makes a read EVIDENCE about this copy**, which is the whole of
    §3.16 and took two reviews to get right:

      - a read of the identity this copy most recently stood at — its own
        wood. Not *any* identity it has ever stood at: a copy photographed on
        the left half in January and on the right half since February is not
        answerable to the left half's later reads, and counting them
        manufactures evidence of absence, which is the failure §3.16 is
        named after. Measured at three units of it;
      - **any read of the survivor from the merge onwards.** After a merge
        the captures are refiled, so a read of the survivor covers the whole
        merged shelf by construction — including the half this copy came
        from. Without this clause the badge FROZE at the merge: every future
        read is a survivor read, none of them vouched, and the number stayed
        0 forever. Measured — the fix survived exactly until the owner
        re-photographed the shelf they had just merged, which is the next
        thing they do.

    Anything else is SKIPPED, not counted and not fatal. §3.16's wording is
    *"stops at the first read whose coverage cannot be vouched for"*, and a
    literal stop was the first implementation: because ``relevant`` is newest
    first, it threw away every older read that WAS evidence, which is how the
    freeze above happened. Skipping is what the sentence means — a read of the
    other half is not evidence either way.

    It reduces exactly to the pre-P6.4e behaviour when the closure is one
    shelf: every read then belongs to that shelf, which is both the survivor
    and the copy's home, so nothing is ever skipped.
    """
    closure = (shelf_id,) + tuple(a.alias_id for a in aliases)
    joined = {a.alias_id: a.merged_at for a in aliases}
    at_depth = [p for p in copy.provenance
                if p.location is not None and p.location[1] == depth
                and p.location[0] in closure]
    sighted_run_ids = {p.run_id for p in at_depth}
    if not sighted_run_ids:
        # Never confirmed at THIS exact (shelf, depth) at all — the real
        # caller (`shelf_books`) only ever asks about a copy it already
        # found located here, so this is a defensive case, not the normal
        # path. There is no sighting to count a streak of misses SINCE, and
        # reporting one anyway would blame the copy for reads that happened
        # at a location it was never placed at in the first place.
        return 0

    # ⚠ The identity it MOST RECENTLY stood at, not every one it has visited.
    # A `captured_at` of `None` sorts first, so a dated sighting always wins.
    home = max(at_depth, key=lambda p: (p.captured_at or "",)).location[0]
    # From this moment on, a read of the survivor covers this copy's half too.
    since = _instant(joined.get(home)) if home != shelf_id else ""
    first_sighted_at = min(
        (p.captured_at for p in at_depth if p.captured_at is not None),
        default=None,
    )

    relevant = sorted(
        (r for r in reads
         if r.shelf_id in closure and r.depth == depth
         and r.status in _COUNTS_AS_EVIDENCE),
        key=lambda r: (_when(r) or "", r.id),
        reverse=True,
    )

    streak = 0
    for r in relevant:
        when = _when(r)
        if first_sighted_at is not None and when is not None \
                and when < first_sighted_at:
            break  # this read predates the copy ever standing here
        if r.id in sighted_run_ids:
            break  # reconfirmed — the streak resets to 0 as of this read
        covered = r.shelf_id == home or (
            r.shelf_id == shelf_id and _instant(when) >= since)
        if not covered:
            # A read of the other half of the merged shelf, from before the
            # merge. It never covered this copy, so it is not evidence —
            # neither of presence nor of absence.
            continue
        streak += 1
    return streak


def _instant(value: str | None) -> str:
    """A timestamp in a form two of them can be compared in.

    ⚠ `merged_at` comes from ``Clock.now_iso`` (``+00:00``) while a read's
    time may carry ``Z`` from an import or a fixture, and ``"…+00:00" <
    "…Z"`` for the very same instant. Only the two forms are normalised: a
    NAIVE timestamp is left alone and therefore sorts before both, so a read
    carrying one is treated as older than the merge — which makes it
    unvouched and skipped rather than counted. Conservative in the direction
    §3.16 cares about, and stated rather than pretended away.
    """
    return (value or "").replace("Z", "+00:00")


@dataclass(frozen=True)
class DepthStatus:
    """One row's last-read date, and whether it is stale relative to the
    shelf's OWN freshest row — never against a clock. See
    :func:`depth_staleness`."""

    depth: int
    last_read_at: str | None
    is_stale: bool


def depth_staleness(
    depth_count: int,
    reads: Sequence[Read],
) -> tuple[DepthStatus, ...]:
    """Per-depth last-read date for the shelf-detail screen's soft staleness
    line (UI_PLAN §3: *"rows 2, 3 not read since 11.3.2026"*).

    A depth is STALE relative to the shelf's own freshest depth, never to a
    clock: this shelf's owner photographed part of it more recently than
    this row, which is exactly the honest, low-stakes nudge worth showing —
    never an error, and never automatic (§5.7's own closing note: marking a
    partially-read shelf is "more honest; it also nags" and stays a soft
    line, not a warning icon).

    ``reads`` need not be pre-filtered to one depth (unlike
    :func:`not_seen_streak`) — this function's whole job is comparing across
    every declared depth of ONE shelf, so it takes the shelf's full read
    list and buckets it itself.
    """
    by_depth: dict[int, str | None] = {d: None for d in range(1, depth_count + 1)}
    for r in reads:
        if r.status not in _COUNTS_AS_EVIDENCE or r.depth not in by_depth:
            continue
        when = _when(r)
        if when is None:
            continue
        current = by_depth[r.depth]
        if current is None or when > current:
            by_depth[r.depth] = when

    freshest = max((v for v in by_depth.values() if v is not None), default=None)
    return tuple(
        DepthStatus(
            depth=d,
            last_read_at=by_depth[d],
            is_stale=freshest is not None and (by_depth[d] is None or by_depth[d] < freshest),
        )
        for d in sorted(by_depth)
    )
