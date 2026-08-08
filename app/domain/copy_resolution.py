# -*- coding: utf-8 -*-
"""Copy resolution (P2.6, §5.4) — the fire/never-fire table, the durable
"duplicates to resolve" queue entity, and the two cheap wins.

Three things live here, all pure:

  1. **The fire table.** §5.4 is explicit that the prompt "must fire RARELY,
     or it becomes review fatigue and gets click-through-approved — which is
     worse than not having it." `reconcile()` (P2.5) already produces the
     RIGHT behaviour for every situation in the table below — this module
     does not change a single branch of it. What it adds is the table as
     DATA, so the mapping from "situation" to "ask or not" is one place
     someone reads and tests, not a fact that has to be reverse-engineered
     from `reconcile.py`'s control flow. :func:`fires` is the load-bearing
     part: `app.reconcile_apply` consults it (not a hardcoded string compare)
     when deciding whether an unanswered claim belongs in the durable queue,
     so a table edited without a matching change to `reconcile()` — or the
     reverse — is a loud mismatch, not a silent drift.
  2. **`DuplicateQuestion`** — one open §5.4 ask, durable across sessions.
     `reconcile()`'s own `needs_decision` is a SNAPSHOT of one read; this is
     what survives after that read's response has come and gone, so the
     "duplicates to resolve" queue on the Books tab has something to filter
     on (plan P2.6, deferred explicitly by P2.5's own docstring).
  3. **The two cheap wins** — :func:`pick_default_copy` and :func:`build_prompt`,
     which decide (a) which copy a multi-copy book's prompt defaults to, and
     (b) whether the sharper "is it back?" question replaces the plain
     three-way prompt when that default copy is lent out. Both are
     PRESELECTIONS for a human to confirm or override — never applied on
     their own; `book._resolve_copy` still refuses to guess when a bare read
     tries to resolve more than one candidate with no human answer.

No I/O, no framework, no store. The only import out of ``booksnap`` this
package is allowed is ``normalize()`` (see ``app/domain/text.py``); this
module needs neither.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.book import Book, Copy, DomainError
from app.domain.reconcile import DecisionKind

# --- the fire/never-fire table (§5.4) --------------------------------------


class FireDecision(str, Enum):
    """Whether §5.4's three-way prompt should ask, for one named situation."""

    NEVER_ASK = "never_ask"
    ASK = "ask"


@dataclass(frozen=True)
class FireRule:
    """One row of §5.4's table, verbatim.

    ``reconcile_reason`` ties the row to the ACTUAL `ClaimOutcome.reason`
    string `app.domain.reconcile.reconcile` produces for that situation —
    the thing that makes this table more than documentation. Two rows may
    share one reason (rows 1 and 3 below both resolve through the exact same
    within-depth dedup mechanism once a Read is scoped to one (shelf, depth) —
    see `reconcile._classify_all`), and they must agree on the decision;
    :func:`fires` is built from this table and a mismatch would make the
    table self-contradictory, so ``tests/test_domain.py`` asserts they never
    do.
    """

    situation: str
    reconcile_reason: str
    decision: FireDecision
    why: str


FIRE_TABLE: tuple[FireRule, ...] = (
    FireRule(
        situation="Two spines, same shelf, same run",
        reconcile_reason="duplicate_within_depth",
        decision=FireDecision.NEVER_ASK,
        why="a mis-assignment, not a genuine duplicate — dup_drop_frac "
            "already drops the weaker claim in the matcher, and "
            "reconcile()'s own within-depth dedup collapses the pair to one "
            "outcome before a question could ever be asked about either "
            "spine (§5.4 row 1)",
    ),
    FireRule(
        situation="Same shelf AND same depth, re-photographed in a later run",
        reconcile_reason="same_location",
        decision=FireDecision.NEVER_ASK,
        why="the SAME physical copy, seen again — append provenance, "
            "update last-seen, and say nothing (§5.4 row 2, §5.6 row 1)",
    ),
    FireRule(
        situation="Overlapping captures of one shelf at the same depth",
        reconcile_reason="duplicate_within_depth",
        decision=FireDecision.NEVER_ASK,
        why="capture-overlap dedup (§5.3) — mechanically identical to the "
            "same-run case above once a Read is scoped to one (shelf, "
            "depth): two claims naming the same book collapse to one before "
            "reconcile() asks anything about either (§5.4 row 3)",
    ),
    FireRule(
        situation="A different shelf, a different row of the same shelf "
                  "(§5.7 #3), or a different physical library",
        reconcile_reason="ambiguous_location",
        decision=FireDecision.ASK,
        why="the one real ambiguity: a claim collides with a book already "
            "confirmed somewhere ELSE, and the collision could be a genuine "
            "second copy, the same copy that moved, or simply the wrong "
            "book — the confirmed library sits at the head of the "
            "retrieval chain, so this is exactly the kind of match that is "
            "most available to be wrong (§5.4 row 4)",
    ),
)

# Built from FIRE_TABLE, not hand-duplicated — see FireRule's own docstring
# for why two rows may share a reason (they do, above) and must agree.
_BY_REASON: dict[str, FireDecision] = {
    rule.reconcile_reason: rule.decision for rule in FIRE_TABLE
}


def fires(reason: str) -> FireDecision:
    """Should §5.4's prompt ask, for a `ClaimOutcome.reason` reconcile() gave?

    Scoped STRICTLY to the four situations in :data:`FIRE_TABLE` — a reason
    outside them (``new_book_unconfirmed``, ``manual_add``, ``rejected``,
    ``wrong_book``, ``no_identity``, ``relinked_by_decision``,
    ``new_copy_by_decision``, ...) answers a DIFFERENT question `reconcile()`
    handles on its own (is this a real book at all? has a human already
    decided? is this claim identity-less?) and was never a candidate for
    §5.4's ask in the first place. Raising here rather than guessing keeps a
    typo'd or renamed reason LOUD — a caller that assumed an unrecognised
    reason means "never ask" would silently stop surfacing a real ambiguity
    the moment `reconcile()` was refactored to spell it differently.
    """
    if reason not in _BY_REASON:
        raise DomainError(
            f"{reason!r} is not one of §5.4's fire/never-fire situations "
            f"({sorted(_BY_REASON)}); it answers a different question and "
            "must not be checked against this table"
        )
    return _BY_REASON[reason]


# --- the two cheap wins (§5.4) ---------------------------------------------


def pick_default_copy(book: Book) -> Copy | None:
    """§5.4's second cheap win: *"if the library already holds several
    copies, the user picks which one this is; default to the copy that has
    no shelf assigned, or the least-recently-seen."*

    A PRESELECTION only — the human still picks, same as every other default
    in this file. Two tiers, exactly as worded:

      1. an unlocated copy (no ``shelf_id``) — the obvious candidate, since
         relinking IT costs nothing a located copy doesn't already have and
         it is the one most likely to be "this exact object, not yet
         re-shelved". The first such copy in acquisition order, for a stable
         answer across calls;
      2. otherwise every copy is located, so the LEAST-RECENTLY-SEEN one —
         the copy whose last confirmed sighting is oldest is the one most
         plausibly the one that just reappeared somewhere new. A copy with
         NO provenance at all (declared by hand via "I have another copy",
         P1.7, never actually read) sorts first: it has literally never
         been seen, which is the extreme case of "least recently seen".

    Returns ``None`` only for a book with no copies at all, which
    `Book.__post_init__` already refuses to construct — kept total rather
    than partial so a caller never has to special-case "impossible".
    """
    if not book.copies:
        return None
    unlocated = [c for c in book.copies if c.shelf_id is None]
    if unlocated:
        return unlocated[0]

    def _last_seen(c: Copy) -> str:
        # '' sorts before any real ISO timestamp, so a copy with no
        # provenance (or a sighting with no captured_at) is the most
        # "least recently seen" of all.
        return c.last_seen.captured_at if c.last_seen and c.last_seen.captured_at else ""

    return min(book.copies, key=lambda c: (_last_seen(c), c.id))


class PromptKind(str, Enum):
    """Which flavour of §5.4's prompt to show. The three ANSWERS never
    change (already listed / another copy / wrong book) — this only picks
    the QUESTION's wording, and only for the already-listed candidate."""

    THREE_WAY = "three_way"
    LENT_OUT_RETURN = "lent_out_return"


@dataclass(frozen=True)
class CopyResolutionPrompt:
    """What to show for one ambiguous claim, computed FRESH against the
    book's current state — never stored, same reasoning as `reconcile()`'s
    own diff being recomputed on every call rather than cached."""

    kind: PromptKind
    candidate_copy_id: str | None
    lent_to: str | None = None


def build_prompt(book: Book) -> CopyResolutionPrompt:
    """§5.4's first cheap win: *"if the existing copy is marked lent out and
    now shows up on a shelf, ask the better question: 'you lent this to
    Dana — is it back?'"*

    Built on top of :func:`pick_default_copy` — the SAME candidate that
    would be preselected for an ordinary "already listed" answer is the one
    checked for a live loan, so the two cheap wins can never disagree about
    which copy they are talking about.
    """
    candidate = pick_default_copy(book)
    if candidate is not None and candidate.lending is not None and candidate.lending.is_out:
        return CopyResolutionPrompt(
            kind=PromptKind.LENT_OUT_RETURN,
            candidate_copy_id=candidate.id,
            lent_to=candidate.lending.lent_to,
        )
    return CopyResolutionPrompt(
        kind=PromptKind.THREE_WAY,
        candidate_copy_id=candidate.id if candidate is not None else None,
    )


# --- the default answer, when nobody answers (§5.4) ------------------------

DEFAULT_RESOLUTION: DecisionKind = DecisionKind.ALREADY_LISTED
"""§5.4, verbatim: *"Default when the question is skipped or the run is
never reviewed: 'already listed copy' — one copy, relinked."* The asymmetry
is the same one that governs everything else in this file: a missed
duplicate means you own two and the catalog says one — mildly wrong, and
trivially fixed later by "I have another copy". An INVENTED duplicate is a
phantom, and phantoms rot silently. Never `ANOTHER_COPY` by default.

Consulted in exactly ONE place — the queue's explicit "skip" action
(`app/api/routers/duplicates.py`, "I'm not answering this now, use the safe
default and stop asking") — and nowhere else. Every other resolution comes
from a real human `AnswerKind` (`app.reconcile_apply`); this constant is not
a fallback `apply_diff` reaches for on its own, because §5.4 already made
that mistake impossible by construction — an UNANSWERED question simply
stays open in the queue (`app/reconcile_apply.py`'s queue bookkeeping) and
creates nothing until something — a human answer, or this default — actually
resolves it.
"""


# --- the durable queue entity -----------------------------------------------


@dataclass(frozen=True)
class DuplicateQuestion:
    """One open §5.4 ask, durable across sessions (P2.6).

    Identity is ``(library, shelf, depth, book_key)`` — the SAME composite
    key as `app.domain.reconcile.Decision`, deliberately: a question and its
    eventual answer are two states of one fact ("is <book_key>, seen again
    at (shelf, depth), the same copy or a new one?"). Once a `Decision`
    exists at this exact key the question is answered FOR GOOD, so
    answering it deletes the row here rather than marking it resolved —
    the mirror image of `DecisionStore.delete_decision`'s "undo of a
    mis-click" (that one clears an answer to re-open the question; this one
    clears the open question because an answer now exists).

    Carries enough of the ORIGINAL claim to render §5.4's prompt and to
    build a fresh `Provenance` when it is finally answered, without a second
    lookup into a read that may be long finished by then — the same
    reasoning `ClaimOutcome` follows for `reconcile()`'s own callers.
    """

    id: str
    library_id: str
    shelf_id: str
    depth: int
    book_key: str
    read_id: str
    spine_id: str
    claim_title: str
    claim_author: str
    existing_book_id: str
    opened_at: str
    captured_at: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise DomainError("a duplicate question needs an id")
        if not self.library_id:
            raise DomainError("a duplicate question must belong to a library (H2)")
        if not self.shelf_id:
            raise DomainError("a duplicate question must name the shelf it was asked at")
        if self.depth < 1:
            raise DomainError("depth is 1-based")
        if not self.book_key:
            raise DomainError("a duplicate question must name the book in question")


def open_or_refresh(
    existing: DuplicateQuestion | None,
    *,
    new_id: str,
    library_id: str,
    shelf_id: str,
    depth: int,
    book_key: str,
    read_id: str,
    spine_id: str,
    claim_title: str,
    claim_author: str,
    existing_book_id: str,
    when: str,
    captured_at: str | None,
) -> DuplicateQuestion:
    """Upsert semantics for the queue, computed here (pure) rather than in
    the store, so the RULE — what survives a refresh — lives in the domain.

    Preserves ``id`` and ``opened_at`` from ``existing`` when this EXACT
    question (same shelf, depth, book_key) is already open: a re-skip on a
    later read must not reset how long it has been waiting, and a stable id
    keeps the same queue row's URL valid across refreshes. ``new_id`` is
    supplied by the caller (an `IdGen`) rather than minted here — this
    function stays pure, and the id is simply unused when there is nothing
    to open fresh.
    """
    if existing is not None:
        return DuplicateQuestion(
            id=existing.id, library_id=library_id, shelf_id=shelf_id,
            depth=depth, book_key=book_key, read_id=read_id, spine_id=spine_id,
            claim_title=claim_title, claim_author=claim_author,
            existing_book_id=existing_book_id, opened_at=existing.opened_at,
            captured_at=captured_at,
        )
    return DuplicateQuestion(
        id=new_id, library_id=library_id, shelf_id=shelf_id, depth=depth,
        book_key=book_key, read_id=read_id, spine_id=spine_id,
        claim_title=claim_title, claim_author=claim_author,
        existing_book_id=existing_book_id, opened_at=when, captured_at=captured_at,
    )
