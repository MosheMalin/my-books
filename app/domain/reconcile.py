# -*- coding: utf-8 -*-
"""Reconciliation — a PURE function turning one read into a diff (P2.5, §5.6).

> A shelf **has** books. A read is an **event that updates** that list.

That inversion is the whole point of this module. Before P2.5, "results" were
a run's own output; after it, a read's claims are compared against the shelf's
DURABLE state and the outcome is a *diff* — added / corrected / unchanged /
not-seen / needs-decision — never a replacement. Nothing here writes anything;
:func:`reconcile` takes plain values and returns plain values, so every rule in
this file is testable in milliseconds with no store, no clock and no ids.
That purity is deliberate and load-bearing (plan P2.5, H5's "highest-risk
logic in the product" — reversible only because it is exhaustively testable).

**Why this needs more than "the books at this (shelf, depth)"** (contrast the
plan's one-line summary). §5.4's ask fires when a claimed book is already
confirmed *somewhere else* in the library, so the pure function needs the
whole library's current books, keyed by :func:`app.domain.text.book_key`, not
only this location's occupants — the caller (`app.reconcile_apply`) builds
that map once via ``BookStore.list`` per read; §6's library sizes make that an
honest O(library) cost, same trade `app.domain.search` already documents for
the SQL `LIKE` scan.

**Where the RULES live vs where they get EXECUTED.** This module classifies —
it decides which bucket a claim belongs in and, when the answer is "apply a
stored decision automatically", *which* domain operation that implies. It does
NOT mint ids, does not read a clock, and does not call `new_book`/`observe`/
`add_copy` itself — those need an :class:`app.ports.IdGen` and produce a fresh
`Book`, which would make this function impure. `app.reconcile_apply` is the
thin layer that turns a classified :class:`ClaimOutcome` into an actual
`Book` and persists it — "keep the RULES in the pure function; that part only
persists" is the plan's own phrasing for the split.

Two DELIBERATELY OUT-OF-SCOPE things, named so they are not mistaken for gaps:

  - **the "not seen in the last N reads" soft badge** (§5.6 option 2) needs a
    streak counted across several reads. This module only reports THIS read's
    :class:`NotSeenEntry` list — persisting and thresholding a streak is P2.8's
    "shelf view + read history" item, which has the read archive to count from;
  - **the "duplicates to resolve" queue** (§5.4) that keeps a skipped ask alive
    across sessions is P2.6's item. `needs_decision` here is a snapshot of one
    read's asks; making it durable and filterable on the Books tab is P2.6's.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from app.domain.book import Book, Copy, DomainError
from app.domain.read import Claim, ClaimTier, DiffSummary
from app.domain.shelf import Shelf
from app.domain.text import book_key


class DecisionKind(str, Enum):
    """A human's STANDING answer, persisted so a later read never asks twice.

    ``REJECTED``       — §5.6 row 4: this claim is not a real book. Scoped to
                          a claim whose key was NOT already in the library —
                          the "new book, but no" answer.
    ``WRONG_BOOK``      — §5.4's third option for the AMBIGUOUS case: the key
                          IS an existing library book, but this spine is not
                          it. Operationally identical to ``REJECTED`` (suppress
                          here, forever, until cleared) but kept as a separate
                          value because the two arise from different prompts
                          and an audit trail should say which.
    ``ALREADY_LISTED``  — §5.4's default answer: the same physical copy, seen
                          on a new shelf/row. Replay relinks it without asking.
    ``ANOTHER_COPY``    — §5.4's second answer: a genuine second object. Replay
                          creates it without asking — see :mod:`app.reconcile_apply`
                          for why this does not violate "the matcher never
                          auto-creates a copy" (§5.1): the copy is gated behind
                          an actual recorded human decision, never a default.

    Deliberately NO ``CONFIRMED`` value: confirming a REVIEW-tier claim for a
    brand-new book creates the `Book` itself, and that Book's existence is
    already the durable record — a future read of the same spot resolves via
    the ordinary "already listed on this shelf" path (unchanged) without ever
    needing to consult a stored decision again. Only the SUPPRESSING answers
    (reject / wrong book) need to persist, because nothing else would remember
    "no" on their behalf.
    """

    REJECTED = "rejected"
    WRONG_BOOK = "wrong_book"
    ALREADY_LISTED = "already_listed"
    ANOTHER_COPY = "another_copy"


@dataclass(frozen=True)
class Decision:
    """One human answer, permanently scoped to WHERE it was asked.

    Identity is ``(library, shelf, depth, book_key)`` — not a book id, and not
    a claim id. §5.6's "previously rejected HERE" is a (shelf, depth) fact, not
    a library-wide one: this exact catalog entry might be a perfectly real,
    correctly-catalogued book on some OTHER shelf, and a library-wide
    suppression would hide it there too. ``book_key`` rather than a title
    string for the same reason `Book.key` exists: an edited title must not
    orphan the decision that was made about it.
    """

    library_id: str
    shelf_id: str
    depth: int
    book_key: str
    kind: DecisionKind
    copy_id: str | None = None
    decided_at: str | None = None

    def __post_init__(self) -> None:
        if not self.library_id:
            raise DomainError("a decision must belong to a library (H2)")
        if not self.shelf_id:
            raise DomainError("a decision must name the shelf it was made at")
        if self.depth < 1:
            raise DomainError("depth is 1-based")
        if not self.book_key:
            raise DomainError("a decision must name the book it is about")


class OutcomeKind(str, Enum):
    """What one claim resolves to. Five are the plan's named buckets
    (``added``/``corrected``/``unchanged``/``needs_decision``, plus
    ``not_seen`` which is not per-claim — see :class:`NotSeenEntry`); two more
    exist so every claim gets a place to land, which is what makes the diff a
    complete account of the read rather than one that silently drops rows:

    ``REJECTED`` — excluded from the library on purpose (a standing decision
    said so, or this exact claim is being freshly recorded as one). Visible
    here so "why isn't my book showing up" has an honest answer instead of the
    claim just vanishing.
    ``IGNORED``  — no book identity at all (blank title) or a within-read
    duplicate of another claim (§5.7 #2) — never a rule violation, just
    nothing to reconcile.
    """

    ADDED = "added"
    UNCHANGED = "unchanged"
    CORRECTED = "corrected"
    NEEDS_DECISION = "needs_decision"
    REJECTED = "rejected"
    IGNORED = "ignored"


@dataclass(frozen=True)
class ClaimOutcome:
    """One claim, classified. Carries enough context that
    ``app.reconcile_apply`` never has to re-derive anything this module
    already worked out, and enough that a review UI can render §5.4's prompt
    (title/author/current location) without a second lookup.

    ``existing_book`` is the CURRENT, unmodified `Book` this claim resolves
    against (for ``unchanged``/``corrected``/``needs_decision``) — reconcile()
    never mutates it; that is ``app.reconcile_apply``'s job, with a real
    `IdGen`/`Clock` in hand.

    ``existing_copy_id`` names the copy the outcome concerns where one is
    already known: the copy already standing at (shelf, depth) for
    ``unchanged``, or the copy being relinked for a ``corrected`` /
    ``ALREADY_LISTED`` outcome. ``None`` for ``added`` (no copy exists yet) and
    for a ``corrected`` / ``ANOTHER_COPY`` outcome (a NEW copy is about to be
    minted, so there is no id to name yet).
    """

    claim: Claim
    kind: OutcomeKind
    book_key: str = ""
    existing_book: Book | None = None
    existing_copy_id: str | None = None
    decision: Decision | None = None
    reason: str = ""
    superseded_by: str | None = None   # the winning claim's id, for IGNORED/duplicate


@dataclass(frozen=True)
class NotSeenEntry:
    """A copy that stood at this (shelf, depth) before this read and that this
    read's claims did not reconfirm.

    NEVER a removal (§5.6's central rule: measured recall is 0.78-0.83, so one
    read's silence is weak evidence). This is the raw fact only — streak
    counting and the soft "not seen in the last 3 reads" surfacing are P2.8's,
    which has the read archive to count across; this module only knows about
    the ONE read in front of it.
    """

    book: Book
    copy_id: str


@dataclass(frozen=True)
class Diff:
    """The result of reconciling one read against one shelf's state at one
    depth (§5.7 #1 — everything here is already scoped to that single row;
    there is no depth parameter left to get wrong downstream).

    Five named buckets, per the plan; ``rejected``/``ignored`` are extras kept
    for transparency — see :class:`OutcomeKind` for why they exist. A caller
    that only wants the plan's headline counts (``+3 added · 1 corrected ·
    12 unchanged · 1 not seen``) reads the first four lengths and ignores the
    rest.
    """

    library_id: str
    shelf_id: str
    depth: int
    read_id: str
    added: tuple[ClaimOutcome, ...] = ()
    corrected: tuple[ClaimOutcome, ...] = ()
    unchanged: tuple[ClaimOutcome, ...] = ()
    needs_decision: tuple[ClaimOutcome, ...] = ()
    not_seen: tuple[NotSeenEntry, ...] = ()
    rejected: tuple[ClaimOutcome, ...] = ()
    ignored: tuple[ClaimOutcome, ...] = ()


# --- the pure function -----------------------------------------------------

def reconcile(
    shelf: Shelf,
    depth: int,
    claims: Sequence[Claim],
    library_books: Mapping[str, Book],
    decisions: Sequence[Decision],
    *,
    read_id: str,
) -> Diff:
    """Classify a read's claims against the library's current state.

    :param shelf: the shelf this read is of. Only used to validate ``depth``
        (§5.7 — a read of an undeclared row is a bug, not new information) and
        to key the diff; the shelf's OWN claims of what stands on it come
        entirely from ``library_books``, never from the `Shelf` object itself.
    :param depth: the ONE row this read covers (§5.7 #1). Every rule below —
        "already listed here", "not seen this time", overlap dedup — is scoped
        to this single depth, which is what stops a front-row re-read from
        flagging the other rows' books as missing.
    :param claims: the read's claims, in any order. A claim with no title (the
        raw text did not resolve to anything, i.e. `ClaimTier.UNMATCHED` in the
        normal case) carries no book identity and is reported as
        :data:`OutcomeKind.IGNORED`.
    :param library_books: EVERY book currently in this library, keyed by
        :func:`app.domain.text.book_key`. Not narrowed to this shelf: §5.4's
        ask needs to know about a match on ANOTHER shelf, which is the whole
        reason this parameter is broader than "the books already here".
    :param decisions: prior :class:`Decision`\\ s for this EXACT (shelf, depth)
        — every one is validated to belong to it, so passing a decision from
        another location is a caller bug and raises loudly rather than being
        silently ignored or, worse, silently applied to the wrong claim.
    :param read_id: the read these claims came from — carried onto the diff
        and (via `app.reconcile_apply`) onto the `Provenance` this read writes.
    """
    shelf.check_depth(depth)
    for d in decisions:
        if d.shelf_id != shelf.id or d.depth != depth:
            raise DomainError(
                f"decision for ({d.shelf_id!r}, {d.depth}) passed to a "
                f"reconcile() call for ({shelf.id!r}, {depth}) — decisions "
                "must be pre-scoped by the caller (§5.6)"
            )
    decisions_by_key = {d.book_key: d for d in decisions}

    outcomes = _classify_all(claims, shelf.id, depth, library_books,
                             decisions_by_key, read_id)

    added = tuple(o for o in outcomes if o.kind is OutcomeKind.ADDED)
    corrected = tuple(o for o in outcomes if o.kind is OutcomeKind.CORRECTED)
    unchanged = tuple(o for o in outcomes if o.kind is OutcomeKind.UNCHANGED)
    needs_decision = tuple(o for o in outcomes if o.kind is OutcomeKind.NEEDS_DECISION)
    rejected = tuple(o for o in outcomes if o.kind is OutcomeKind.REJECTED)
    ignored = tuple(o for o in outcomes if o.kind is OutcomeKind.IGNORED)

    reconfirmed_copy_ids = {
        o.existing_copy_id for o in (*unchanged, *corrected)
        if o.existing_copy_id is not None
    }
    not_seen = _not_seen_here(shelf, depth, library_books, reconfirmed_copy_ids)

    return Diff(
        library_id=shelf.library_id, shelf_id=shelf.id, depth=depth,
        read_id=read_id, added=added, corrected=corrected, unchanged=unchanged,
        needs_decision=needs_decision, not_seen=not_seen, rejected=rejected,
        ignored=ignored,
    )


# --- classification ---------------------------------------------------------

def _sightings_here(
    library_books: Mapping[str, Book], shelf_id: str, depth: int, read_id: str,
) -> dict[str, tuple[Book, str]]:
    """``spine_id -> (book, copy_id)`` for every copy standing at this
    (shelf, depth) that THIS read has already been recorded as sighting.

    The index behind :func:`_resolved_by_its_own_sighting` — built once per
    reconcile() call rather than scanned per claim. One pass over the library's
    copies and their provenance; the caller already pays O(library) to build
    ``library_books`` at all, so this changes the order of nothing.
    """
    here = (shelf_id, depth)
    out: dict[str, tuple[Book, str]] = {}
    for book in library_books.values():
        for copy in book.copies:
            if copy.location != here:
                continue
            for prov in copy.provenance:
                if prov.run_id == read_id:
                    out[prov.spine_id] = (book, copy.id)
    return out


def _classify_all(
    claims: Sequence[Claim],
    shelf_id: str,
    depth: int,
    library_books: Mapping[str, Book],
    decisions_by_key: Mapping[str, Decision],
    read_id: str,
) -> list[ClaimOutcome]:
    identified: list[tuple[str, Claim]] = []
    out: list[ClaimOutcome] = []
    for claim in claims:
        key = _identity(claim)
        if key is None:
            out.append(ClaimOutcome(claim=claim, kind=OutcomeKind.IGNORED,
                                    reason="no_identity"))
        else:
            identified.append((key, claim))

    # §5.7 #2: overlap dedup is WITHIN this depth only — automatically true
    # here, because every claim `reconcile()` ever sees belongs to one read,
    # and a Read is already scoped to one (shelf, depth) by `new_read`. Two
    # captures of one shelf whose fields of view overlap can each produce a
    # claim for the SAME physical spine; grouping by key and keeping one
    # winner is what stops that from reading as two sightings — or worse, an
    # AMBIGUOUS "second copy" prompt for a book that never left the shelf.
    by_key: dict[str, list[Claim]] = {}
    for key, claim in identified:
        by_key.setdefault(key, []).append(claim)

    sighted = _sightings_here(library_books, shelf_id, depth, read_id)

    for key, group in by_key.items():
        primary = _pick_primary(group)
        for claim in group:
            if claim is not primary:
                out.append(ClaimOutcome(
                    claim=claim, kind=OutcomeKind.IGNORED, book_key=key,
                    reason="duplicate_within_depth", superseded_by=primary.id,
                ))
        out.append(_classify_one(primary, key, shelf_id, depth, library_books,
                                 decisions_by_key, sighted))
    return out


def _pick_primary(group: Sequence[Claim]) -> Claim:
    """Deterministic winner among claims that name the same book at this
    depth: AUTO over REVIEW (real matcher confidence over a guess), then the
    higher score, then the lower spine_id so two ties still pick the same
    claim on every run rather than depending on dict/set ordering."""
    # MANUAL outranks every machine tier — if the owner typed a book onto this
    # photo and the reader also found it, the human's text is the one to keep
    # (§5.1's ladder). `rank.get` rather than `rank[...]` would hide a future
    # tier from this ordering, so every value is listed on purpose.
    rank = {ClaimTier.MANUAL: 3, ClaimTier.AUTO: 2, ClaimTier.REVIEW: 1,
            ClaimTier.UNMATCHED: 0}
    return min(group, key=lambda c: (-rank[c.tier], -c.score, c.spine_id))


def _identity(claim: Claim) -> str | None:
    if not claim.title.strip():
        return None
    return book_key(claim.title, claim.author)


def _classify_one(
    claim: Claim,
    key: str,
    shelf_id: str,
    depth: int,
    library_books: Mapping[str, Book],
    decisions_by_key: Mapping[str, Decision],
    sighted: Mapping[str, tuple[Book, str]],
) -> ClaimOutcome:
    # ⚠ FIRST, before anything keyed on the claim's own text: has THIS claim
    # already produced a book standing here?
    #
    # A claim's identity is `book_key(claim.title, claim.author)` — the text
    # the ENGINE read, frozen forever because it is evidence. But a human may
    # have answered the claim with DIFFERENT text: approving it as corrected,
    # picking one of `explain()`'s runners-up, or editing the book's title
    # afterwards. The book that answered then lives under a different key, and
    # keying alone would report the claim as still unanswered — leaving the
    # finding pending forever and creating a SECOND book on the next click.
    # Found live, by correcting a title and watching the row stay pending.
    #
    # `Provenance.sighting` is `(run_id, spine_id)`, so "which book did this
    # spine produce" is a fact the data already carries. The location check is
    # part of the rule, not an optimisation: a copy that has since MOVED is
    # genuinely not here any more, and §5.7 #1 says so.
    recorded = sighted.get(claim.spine_id)
    if recorded is not None:
        book, copy_id = recorded
        return ClaimOutcome(claim=claim, kind=OutcomeKind.UNCHANGED,
                            book_key=book.key, existing_book=book,
                            existing_copy_id=copy_id, reason="same_location")

    existing = library_books.get(key)
    here = _copy_at(existing, shelf_id, depth) if existing is not None else None
    if here is not None:
        # §5.6 row 1, unconditionally: identity is already established at
        # THIS exact (shelf, depth). A weaker read this time, or even a stale
        # WRONG_BOOK/REJECTED decision left over from before the book existed
        # here, changes nothing — the copy that is standing here now wins.
        return ClaimOutcome(claim=claim, kind=OutcomeKind.UNCHANGED,
                            book_key=key, existing_book=existing,
                            existing_copy_id=here.id, reason="same_location")

    decision = decisions_by_key.get(key)
    if decision is not None and decision.kind in (DecisionKind.REJECTED,
                                                   DecisionKind.WRONG_BOOK):
        return ClaimOutcome(claim=claim, kind=OutcomeKind.REJECTED,
                            book_key=key, decision=decision,
                            reason=decision.kind.value)

    if existing is None:
        # Not in the library at all.
        #
        # ⚠ REVERSED 2026-08-09 (owner). This branch used to auto-enter an
        # AUTO-tier claim, mirroring `booksnap/library.py::absorb_auto_claims`.
        # The owner watched a real photo put fourteen books into the library
        # without ever being asked and called it wrong: **nothing enters the
        # library until a human approves it.** UI_PLAN §6 already lists
        # "auto-approve AUTO" as a Settings toggle; until that setting exists,
        # its value is OFF, and this is where that lives.
        #
        # So tier no longer decides ENTRY, only how the finding is presented:
        # both AUTO and REVIEW land in the same pending bucket, which is also
        # what lets the review UI give them the same controls (owner's item 7
        # in the same round of feedback). The claim is not lost by waiting —
        # it is on the read forever, and the read is reachable from its photo
        # (P2.10's workspace).
        if claim.tier is ClaimTier.MANUAL:
            # ...except a book the owner typed in themselves. There is no one
            # left to ask (§5.1: a person's word is the strongest evidence the
            # system ever gets), so it enters at once, at MANUAL.
            return ClaimOutcome(claim=claim, kind=OutcomeKind.ADDED,
                                book_key=key, reason="manual_add")
        return ClaimOutcome(claim=claim, kind=OutcomeKind.NEEDS_DECISION,
                            book_key=key, reason="new_book_unconfirmed")

    # The book is real and confirmed, but not standing HERE (§5.4's actual
    # ambiguous case: another shelf, or another row of this one, per §5.7 #3).
    if decision is not None and decision.kind is DecisionKind.ALREADY_LISTED:
        copy_id = _resolve_already_listed(existing, decision)
        if copy_id is not None:
            return ClaimOutcome(claim=claim, kind=OutcomeKind.CORRECTED,
                                book_key=key, existing_book=existing,
                                existing_copy_id=copy_id, decision=decision,
                                reason="relinked_by_decision")
        # The stored decision no longer resolves cleanly (its copy_id is gone,
        # or a new copy has appeared since and it is ambiguous again) — fall
        # through to asking again rather than guessing.
    elif decision is not None and decision.kind is DecisionKind.ANOTHER_COPY:
        return ClaimOutcome(claim=claim, kind=OutcomeKind.CORRECTED,
                            book_key=key, existing_book=existing,
                            existing_copy_id=None, decision=decision,
                            reason="new_copy_by_decision")

    return ClaimOutcome(claim=claim, kind=OutcomeKind.NEEDS_DECISION,
                        book_key=key, existing_book=existing,
                        reason="ambiguous_location")


def _copy_at(book: Book, shelf_id: str, depth: int) -> Copy | None:
    """The copy of ``book`` already standing at ``(shelf_id, depth)``, if any.

    At most one is expected in the normal flow — `book.observe` refuses to
    create a second one at an occupied location — but a decision-replayed
    ``ANOTHER_COPY`` can legitimately place a second physical object at the
    SAME spot (two copies kept side by side), so this takes the first rather
    than asserting uniqueness.
    """
    here = (shelf_id, depth)
    for copy in book.copies:
        if copy.location == here:
            return copy
    return None


def _resolve_already_listed(book: Book, decision: Decision) -> str | None:
    if decision.copy_id is not None:
        return decision.copy_id if any(c.id == decision.copy_id
                                       for c in book.copies) else None
    # No copy_id recorded: only safe to auto-resolve when there was exactly
    # one candidate at decision time. A second copy having appeared since
    # would make that resolution wrong today, so re-check the count now
    # rather than trusting the (possibly stale) absence of an id.
    return book.copies[0].id if book.copy_count == 1 else None


def _not_seen_here(
    shelf: Shelf,
    depth: int,
    library_books: Mapping[str, Book],
    reconfirmed_copy_ids: set,
) -> tuple[NotSeenEntry, ...]:
    here = (shelf.id, depth)
    out = []
    for book in library_books.values():
        for copy in book.copies:
            if copy.location == here and copy.id not in reconfirmed_copy_ids:
                out.append(NotSeenEntry(book=book, copy_id=copy.id))
    return tuple(out)


# --- the P2.8 snapshot -------------------------------------------------------

def summarize(diff: Diff) -> DiffSummary:
    """Headline counts for `app.domain.read.Read.diff_summary` — see
    :class:`~app.domain.read.DiffSummary` for why these are captured once, by
    the caller that just finished a read, rather than derived again later
    from a re-run of :func:`reconcile`. Deliberately a plain count of each
    bucket's length, nothing more: the `ClaimOutcome`\\ s themselves already
    live on the read that produced them (``Read.claims``); this is only the
    number a history row needs to render.
    """
    return DiffSummary(
        added=len(diff.added), corrected=len(diff.corrected),
        unchanged=len(diff.unchanged), needs_decision=len(diff.needs_decision),
        not_seen=len(diff.not_seen), rejected=len(diff.rejected),
        ignored=len(diff.ignored),
    )
