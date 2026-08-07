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

    ``reads`` is scoped to ``(shelf_id, depth)`` by the caller (the natural
    result of ``ReadStore.list_reads(..., depth=depth)``, §5.7 #1's own
    scoping) — any read that does not match is ignored defensively rather
    than raised on, since a caller that already narrowed by depth has no way
    to pass a foreign one except by a wiring bug this function is not the
    place to diagnose.

    A read that happened BEFORE this copy ever stood at this location tells
    us nothing about it and does not count against it — otherwise a copy
    added yesterday would inherit a "not seen in 40 reads" streak from
    photographs taken long before it existed here.
    """
    here = (shelf_id, depth)
    sighted_run_ids = {p.run_id for p in copy.provenance if p.location == here}
    first_sighted_at = min(
        (p.captured_at for p in copy.provenance
         if p.location == here and p.captured_at is not None),
        default=None,
    )
    if not sighted_run_ids:
        # Never confirmed at THIS exact (shelf, depth) at all — the real
        # caller (`shelf_books`) only ever asks about a copy it already
        # found located here, so this is a defensive case, not the normal
        # path. There is no sighting to count a streak of misses SINCE, and
        # reporting one anyway would blame the copy for reads that happened
        # at a location it was never placed at in the first place.
        return 0

    relevant = sorted(
        (r for r in reads
         if r.shelf_id == shelf_id and r.depth == depth
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
        streak += 1
    return streak


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
