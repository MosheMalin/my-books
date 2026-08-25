# -*- coding: utf-8 -*-
"""Absorbing one shelf identity into another (P6.4d, MAP_PLAN §3.11-§3.13).

The fifth port-only top-level module, and it is here for the reason
``reconcile_apply.py``, ``map_edit.py``, ``blob_lifecycle.py`` and
``map_undo.py`` all give: this work needs BOTH ``app.domain``
(:mod:`app.domain.merge` — what a merge would write) and ``app.ports`` (six of
them), and neither the pure domain (H1) nor a router belongs across that seam.

**Two verbs.** :func:`preview` writes nothing and answers *what would this
cost*; :func:`merge` does it and journals its own inverse. §3.15 keeps both:
the preview is not a substitute for undo but the other half of the same
courtesy.

**The order of the writes is the safety argument.** There is no transaction
across ports — the SQLite adapter opens a connection per operation by design —
so what stands in for one is a sequence in which every interruption leaves a
state the system already handles, and a retry finishes the job:

    1. refuse, on everything knowable before the first write;
    2. move the books, then the photographs, then the answers. Each of these
       is idempotent by its own key, so a retry rewrites rather than doubles;
    3. deepen the survivor (§3.12);
    4. **absorb** — re-point what already answered to the absorbed shelf and
       write the alias, in ONE store transaction;
    5. delete the absorbed shelf's row;
    6. journal the inverse.

⚠ Step 4 before step 5, and the window between them is deliberate: the library
briefly holds an alias whose ``alias_id`` is still a live shelf.
``deepest_occupied_depths`` was written for exactly that state (its own ⚠ says
so), and a retry finds the alias already there and finishes at step 5. The
other order loses the identity outright if the process dies in between — the
one thing §3.11 exists to prevent.

⚠ Step 6 last, and outside everything: a failure there loses the UNDO, never
the merge. That asymmetry is the right way round and it is ``record``'s own
argument.

⚠ It may import ``app.domain`` and ``app.ports``; it must NOT import
``app.adapters``, and it is imported BY ``app.api``, never the reverse —
``tests/test_layering.py`` enforces both.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from app.domain import (
    CopyPlacement,
    LibraryRef,
    MergePlan,
    MergeRefused,
    Shelf,
    StripOrder,
    plan_merge,
    refile_copy,
)
from app.domain.alias import ShelfAlias, resolve
from app.domain.map_undo import MapRestore
from app.map_undo import Journal, record
from app.ports import Clock
from app.ports.decisions import DecisionStore
from app.ports.duplicates import DuplicateQueue
from app.ports.map import MapStore
from app.ports.store import BookStore, ReadStore, ShelfStore


@dataclass(frozen=True)
class Shelves:
    """The six ports a merge touches, as one argument.

    Same reasoning as :class:`app.map_undo.Journal`, and the same payoff: a
    function that cannot be called without everything it needs is a function
    nobody can half-wire. Seven positional stores at every call site is the
    version that grows a bug the day one of them is optional.
    """

    map_store: MapStore
    shelves: ShelfStore
    books: BookStore
    reads: ReadStore
    decisions: DecisionStore
    duplicates: DuplicateQueue


@dataclass(frozen=True)
class MergeOutcome:
    """What happened, for the route and for the screen.

    ``already`` is the no-op: §3.15 requires *A already resolves to B* to
    answer 200 rather than a refusal, so a retry provoked by a dropped
    response cannot half-merge and cannot look like a new failure.
    """

    survivor: Shelf
    plan: MergePlan | None = None
    already: bool = False


def gather(
    ports: Shelves, library: LibraryRef, absorbed: Shelf, survivor: Shelf,
) -> dict:
    """Everything standing at either shelf, in a handful of queries.

    Separated from :func:`plan` so that the preview and the merge read the
    same way — a preview computed from one set of queries and a merge from
    another is a screen that can promise what the write does not do.
    """
    where = (absorbed.id, survivor.id)
    copies = tuple(
        CopyPlacement(book_id=book.id, copy_id=copy.id,
                      shelf_id=copy.shelf_id, depth=copy.depth or 1)
        for book in ports.books.books_on_shelf(library, where)
        for copy in book.copies if copy.shelf_id in where)
    captures = tuple(c for shelf_id in where
                     for c in ports.shelves.list_captures(library, shelf_id))
    depths = {c.depth for c in copies} | {c.depth for c in captures}
    depths.update(absorbed.depths)
    depths.update(survivor.depths)
    decisions = tuple(d for shelf_id in where for depth in sorted(depths)
                      for d in ports.decisions.list_decisions(
                          library, shelf_id, depth))
    questions = tuple(q for shelf_id in where
                      for q in ports.duplicates.list_open_questions(
                          library, shelf_id=shelf_id))
    return dict(copies=copies, captures=captures, decisions=decisions,
                questions=questions,
                aliases=ports.shelves.list_aliases(library))


def plan(
    ports: Shelves,
    library: LibraryRef,
    absorbed: Shelf,
    survivor: Shelf,
    *,
    strip: StripOrder,
) -> MergePlan:
    """The pure plan, plus the refusals only a store can see.

    Three of them, and each is a different sentence:

      - **the survivor has itself been absorbed** — somebody merged it while
        this screen was open, so the offer names a shelf that no longer
        answers for itself. Refused rather than followed, because following it
        would silently merge into a third identity nobody chose;
      - **a read of either identity is still running** (§3.11) — its diff will
        be applied against a shelf that is about to stop existing;
      - **another identity already remembers this slot** — two aliases may not
        claim one former address (owner, 2026-08-23), because the
        address→survivor lookup must have exactly one answer.

    The third is checked here rather than left to the store's unique index for
    the reason every refusal in this project is: an owner pressing *merge*
    deserves a sentence, not a driver error two statements into a write that
    has already moved books.
    """
    standing = ports.shelves.list_aliases(library)
    if resolve(survivor.id, standing) != survivor.id:
        raise MergeRefused(
            "survivor_absorbed",
            f"{survivor.id} has itself been absorbed; merge into the shelf "
            "that answers for it")
    for shelf in (absorbed, survivor):
        for read in ports.reads.list_reads(library, shelf.id):
            if not read.status.is_terminal:
                raise MergeRefused(
                    "read_running",
                    f"a read of {shelf.id} is still running; merging now "
                    "would apply its findings to a shelf that has stopped "
                    "existing")
    if absorbed.address is not None and any(
        a.address == absorbed.address for a in standing
    ):
        raise MergeRefused(
            "address_taken",
            f"another identity already remembers the slot "
            f"{absorbed.address}")
    return plan_merge(absorbed, survivor, strip=strip,
                      **gather(ports, library, absorbed, survivor))


def preview(
    ports: Shelves,
    library: LibraryRef,
    absorbed: Shelf,
    survivor: Shelf,
    *,
    strip: StripOrder,
) -> MergePlan:
    """What the merge would move. Writes nothing, and that is asserted."""
    return plan(ports, library, absorbed, survivor, strip=strip)


def merge(
    ports: Shelves,
    library: LibraryRef,
    absorbed: Shelf,
    survivor: Shelf,
    *,
    strip: StripOrder,
    journal: Journal,
    clock: Clock,
) -> MergeOutcome:
    """Absorb ``absorbed`` into ``survivor``, and journal the inverse.

    ⚠ **A retry is a no-op, not a second merge.** §3.15 requires it, and the
    shape that delivers it is the alias: once ``absorbed`` resolves to
    ``survivor``, everything below has already happened or is being finished
    by the branch above it, and the answer is 200 with what stands now.
    """
    if absorbed.id == survivor.id:
        # ⚠ Before the no-op branch, not after. `resolve` answers with the id
        # it was handed when nothing has absorbed it, so *A resolves to B* is
        # trivially true for A == B — and merging a shelf into itself answered
        # 200 `already: true` while `plan_merge`'s refusal never ran. The
        # idempotent branch is for a RETRY; a retry of a refusal is a refusal.
        raise MergeRefused(
            "same_shelf", "a shelf cannot be merged into itself")
    standing = ports.shelves.list_aliases(library)
    if resolve(absorbed.id, standing) == survivor.id:
        # Already merged. If the row is still there, the previous attempt died
        # between step 4 and step 5 — finish it rather than leaving a shelf
        # that no screen lists and every query folds into another one.
        if ports.shelves.get_shelf(library, absorbed.id) is not None:
            ports.shelves.delete_shelf(library, absorbed.id)
        return MergeOutcome(
            survivor=ports.shelves.get_shelf(library, survivor.id) or survivor,
            already=True)

    todo = plan(ports, library, absorbed, survivor, strip=strip)
    wrote: dict[str, object] = {}

    for placement in todo.copies:
        book = ports.books.get(library, placement.book_id)
        if book is None:
            continue
        ports.books.save(library, refile_copy(
            book, placement.copy_id, shelf_id=placement.shelf_id,
            depth=placement.depth))
        wrote[f"copies:{placement.copy_id}"] = placement
    for capture in todo.captures:
        ports.shelves.save_capture(library, capture)
        wrote[f"captures:{capture.id}"] = capture
    for shelf_id, depth, book_key in todo.drop_decisions:
        ports.decisions.delete_decision(library, shelf_id, depth, book_key)
        wrote[f"decisions:{shelf_id}:{depth}:{book_key}"] = None
    for decision in todo.decisions:
        ports.decisions.save_decision(library, decision)
        wrote[f"decisions:{decision.shelf_id}:{decision.depth}:"
              f"{decision.book_key}"] = decision
    for shelf_id, depth, book_key in todo.drop_questions:
        ports.duplicates.delete_question(library, shelf_id, depth, book_key)
        wrote[f"questions:{shelf_id}:{depth}:{book_key}"] = None
    for question in todo.questions:
        ports.duplicates.save_question(library, question)
        wrote[f"questions:{question.shelf_id}:{question.depth}:"
              f"{question.book_key}"] = question

    ports.shelves.save_shelf(library, todo.survivor)
    wrote[f"shelves:{todo.survivor.id}"] = todo.survivor

    alias = ShelfAlias(alias_id=absorbed.id, library_id=library.id,
                       shelf_id=survivor.id, merged_at=clock.now_iso(),
                       address=absorbed.address, label=absorbed.label)
    # ⚠ What it ACTUALLY re-pointed, not what the plan expected to. The two
    # differ exactly when somebody merged something else into the absorbed
    # shelf between the plan and here — and the journal has to remember the
    # rows the write moved, not the rows a read a moment earlier saw.
    moved = ports.shelves.absorb_shelf(library, alias)
    wrote[f"aliases:{alias.alias_id}"] = alias
    for identity in moved:
        wrote[f"aliases:{identity.alias_id}"] = replace(
            identity, shelf_id=survivor.id)

    ports.shelves.delete_shelf(library, absorbed.id)
    wrote[f"shelves:{absorbed.id}"] = None

    record(
        journal, ports.map_store, ports.shelves, library,
        kind="merge_shelves",
        # ⚠ A tag nothing in `CONTINUES` names, so a merge never coalesces
        # with anything. Two merges into one survivor are two decisions, and
        # `record all, undo the head` is what makes the second one takeable
        # back on its own.
        tag=f"merge:{absorbed.id}->{survivor.id}",
        restore=_inverse(absorbed, survivor, todo, moved),
        wrote=wrote,
    )
    return MergeOutcome(
        survivor=ports.shelves.get_shelf(library, survivor.id)
        or todo.survivor,
        plan=todo)


def _inverse(
    absorbed: Shelf,
    survivor: Shelf,
    todo: MergePlan,
    moved: tuple[ShelfAlias, ...],
) -> MapRestore:
    """The rows as they stood, and the three things that had no "before".

    ``shelves`` carries BOTH: the absorbed shelf exactly as it was (address,
    label, depth and all — it is about to be deleted) and the survivor as it
    was BEFORE it was deepened, because §3.12's ladder is part of the edit and
    an undo that left the survivor deep would leave a declared row of nothing.

    ``minted_*`` are the keys that did not exist before this merge: the alias
    it wrote, and every answer that landed where nothing was answered. Their
    inverse is a deletion, which no bag of old rows can express.
    """
    answered_before = {(d.shelf_id, d.depth, d.book_key)
                       for d in todo.was_decisions}
    asked_before = {(q.shelf_id, q.depth, q.book_key)
                    for q in todo.was_questions}
    return MapRestore(
        shelves=(absorbed, survivor),
        copies=todo.was_copies,
        captures=todo.was_captures,
        decisions=todo.was_decisions,
        questions=todo.was_questions,
        aliases=moved,
        minted_aliases=(absorbed.id,),
        minted_decisions=tuple(
            (d.shelf_id, d.depth, d.book_key) for d in todo.decisions
            if (d.shelf_id, d.depth, d.book_key) not in answered_before),
        minted_questions=tuple(
            (q.shelf_id, q.depth, q.book_key) for q in todo.questions
            if (q.shelf_id, q.depth, q.book_key) not in asked_before),
    )
