# -*- coding: utf-8 -*-
"""/api/v1/shelves/{shelf_id}/reads — starting, polling and stopping a read
of one shelf at one depth (P2.4).

THIN by rule (H3): the entities and their rules live in ``app/domain/read.py``,
the actual engine work lives behind the ``Reader`` port, and the background
execution lives behind the ``JobRunner`` port. What is here is the HTTP shape
plus the one piece of orchestration that has nowhere else to live — wiring
"start a job" to "the job calls the Reader, then persists the Read" — because
that wiring touches four ports at once and none of them may depend on the
others (H1). It stays a plain function chaining port calls, the same shape as
``books.py``'s ``create_copy`` chaining a domain op and a store save; nothing
here is a rule.

Reads are a sub-resource of a shelf, not a run root (plan P2.9's direction,
already followed here even though P2.9 itself is a later item): there is no
``/reads/{id}`` at the top level, and nothing here takes a bare ``run_id`` as
a resource's own identity.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Sequence
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    get_blob_store,
    get_book_store,
    get_clock,
    get_decision_store,
    get_duplicate_queue,
    get_id_gen,
    get_job_runner,
    get_read_store,
    get_reader,
    get_shelf_store,
)
from app.api.dto import (
    ApplyDiffRequest,
    DiffDTO,
    FindingMatchDTO,
    ManualFindingIn,
    ReadCreate,
    ReadDTO,
    ReadSummaryDTO,
)
from app.api.policy import require
from app.domain import (
    Alternative,
    Capability,
    Capture,
    Claim,
    ClaimTier,
    LibraryRef,
    Read,
    ReadAlreadyFinished,
    ReadStatus,
    Shelf,
    add_manual_claim,
    append_claim,
    fail_read,
    finish_read,
    new_read,
    reconcile,
    stop_read,
    summarize,
    with_diff_summary,
)
from app.domain.book import DomainError
from app.domain.search import TextEntry, haystack, matches, parse, score
from app.domain.shelf import UnknownDepth
from app.ports import Clock, IdGen
from app.ports.blobs import BlobStore
from app.ports.decisions import DecisionStore
from app.ports.duplicates import DuplicateQueue
from app.ports.jobs import JobHandle, JobRunner
from app.ports.reader import Reader, ReadRequest
from app.ports.store import BookStore, ReadStore, ShelfStore
from app.reconcile_apply import (
    Answer,
    AnswerKind,
    UnresolvedAnswer,
    apply_diff,
    retract_finding,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shelves/{shelf_id}/reads", tags=["reads"])

# A `reconcile()` call needs to know about a matching book anywhere in the
# library (§5.4 — the ask fires on a match on ANOTHER shelf), not only this
# depth's occupants, so the diff endpoints load the whole library rather than
# a filtered slice. `BookStore.list` has no shelf/depth filter to narrow with
# (P2.5 did not add one — see `app.domain.reconcile`'s own module docstring
# for the honest O(library) trade this accepts, same one `books.py`'s
# `EXPORT_MAX` already makes for the export route).
_FULL_LIBRARY_SCAN_LIMIT = 100_000

# P3.6 (§1.2): the per-library run rate cap — ONE number, not a metering
# system (that is pillar 5). It guards against a retry loop or a 400-photo
# burst, never against family: 30 read starts in a rolling hour is more
# cataloguing than the owner has ever done in a day, and a stuck client
# re-POSTing hits it in minutes. Env-overridable for the day a real burst is
# legitimate (a first whole-house scan), read once at startup like every
# other env knob in this codebase.
RUN_RATE_CAP_PER_HOUR = int(os.environ.get("BOOKSNAP_RUN_RATE_CAP", "30"))
_RATE_WINDOW = timedelta(hours=1)


def _check_run_rate(reads: ReadStore, library: LibraryRef, clock: Clock) -> None:
    """429 when this library already started the cap's worth of reads in the
    rolling window.

    Counts EVERY status, deliberately: a retry loop's reads mostly fail, and
    failures cost the engine work the cap exists to protect. The honest
    O(reads-in-library) scan is the same trade the diff endpoints make with
    `_FULL_LIBRARY_SCAN_LIMIT` — measure before optimising a route a human
    presses a few times an hour.
    """
    try:
        cutoff = datetime.fromisoformat(clock.now_iso()) - _RATE_WINDOW
    except ValueError:
        return
    recent = 0
    for read in reads.list_all_reads(library):
        if not read.started_at:
            continue
        try:
            if datetime.fromisoformat(read.started_at) < cutoff:
                continue
        except (ValueError, TypeError):
            continue
        recent += 1
    if recent >= RUN_RATE_CAP_PER_HOUR:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"this library already started {recent} reads in the last hour "
            f"(cap {RUN_RATE_CAP_PER_HOUR}, §1.2 — a guard against a retry "
            "loop, not a quota). Wait a while, or raise BOOKSNAP_RUN_RATE_CAP "
            "and restart if this burst is intentional.",
        )


def _check_mode_is_usable(reader: Reader, mode: str) -> None:
    """409 before starting, rather than a read that fails a minute later.

    The ANSWER comes from the Reader, not from this module: which credential
    which engine needs is the adapter's knowledge, and encoding it here would
    couple the route to whichever adapter is bound (and would make the API ring
    depend on an environment it deliberately does not have).
    """
    why = reader.unavailable(mode)
    if why:
        raise HTTPException(status.HTTP_409_CONFLICT, why)


def _load_shelf(store: ShelfStore, library: LibraryRef, shelf_id: str) -> Shelf:
    shelf = store.get_shelf(library, shelf_id)
    if shelf is None:
        # Absent and foreign are the same answer, deliberately (§4.2).
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such shelf")
    return shelf


def _load_read(store: ReadStore, library: LibraryRef, shelf_id: str,
               read_id: str) -> Read:
    read = store.get_read(library, read_id)
    # A read id from ANOTHER shelf is a real record, just not one this URL
    # names — treated the same as absent rather than serving one shelf's
    # evidence at another shelf's address.
    if read is None or read.shelf_id != shelf_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such read")
    return read


@router.post("", response_model=ReadDTO, status_code=status.HTTP_202_ACCEPTED)
def start_read(
    shelf_id: str,
    body: ReadCreate,
    library: LibraryRef = Depends(require(Capability.CAPTURE)),
    shelves: ShelfStore = Depends(get_shelf_store),
    reads: ReadStore = Depends(get_read_store),
    reader: Reader = Depends(get_reader),
    jobs: JobRunner = Depends(get_job_runner),
    blobs: BlobStore = Depends(get_blob_store),
    books: BookStore = Depends(get_book_store),
    decisions: DecisionStore = Depends(get_decision_store),
    duplicates: DuplicateQueue = Depends(get_duplicate_queue),
    clock: Clock = Depends(get_clock),
    ids: IdGen = Depends(get_id_gen),
) -> ReadDTO:
    """Start reading a shelf at one depth.

    **202**, not 201 or 200: the read keeps running after this call returns,
    and the body is a snapshot of "just started" — poll ``GET`` to watch it
    settle into ``done``/``stopped``/``failed``.
    """
    shelf = _load_shelf(shelves, library, shelf_id)
    _check_run_rate(reads, library, clock)
    _check_mode_is_usable(reader, body.mode)
    try:
        shelf.check_depth(body.depth)
    except UnknownDepth as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    captures = shelves.list_captures(library, shelf_id, depth=body.depth)
    if not captures:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"shelf {shelf_id} has no photos at depth {body.depth} to read",
        )
    if not any(c.image_id for c in captures):
        # Every capture at this depth exists but has no uploaded photo yet
        # (P2.2's recorded gap) — a clearer 409 than letting the job run and
        # silently produce zero claims.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"shelf {shelf_id} has captures at depth {body.depth}, but none "
            "of them have an uploaded photo yet",
        )
    try:
        read = new_read(
            shelf, captures, id=ids.new_id(), depth=body.depth, mode=body.mode,
            code_version=reader.code_version(), config=reader.config_snapshot(),
            started_at=clock.now_iso(),
        )
    except DomainError as exc:      # defence in depth; see new_read's checks
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    reads.save_read(library, read)

    # tenant= is the fairness key (P3.4): pending reads drain round-robin
    # across libraries. retries stays 0 ON PURPOSE — the job settles its own
    # failure (`fail_read` + save), and a runner-level retry would re-run the
    # ENGINE, paying for the same photos twice because the final save
    # hiccuped. See JobRunner.submit's own ⚠.
    jobs.submit(read.id, _job(read, shelf, library, captures, reads, shelves,
                              reader, blobs, books, decisions, duplicates,
                              ids, clock),
                tenant=library.id)
    return ReadDTO.of(read)


@router.get("", response_model=list[ReadSummaryDTO])
def list_reads(
    shelf_id: str,
    depth: int | None = Query(
        None, ge=1,
        description="Narrow to one row front-to-back — §5.7 #1 scopes a "
                    "read's history to the depth it actually covered.",
    ),
    library: LibraryRef = Depends(require(Capability.BROWSE)),
    shelves: ShelfStore = Depends(get_shelf_store),
    reads: ReadStore = Depends(get_read_store),
) -> list[ReadSummaryDTO]:
    """A shelf's reads, most recent first."""
    _load_shelf(shelves, library, shelf_id)   # 404 for a foreign or absent shelf
    return [ReadSummaryDTO.of(r)
            for r in reads.list_reads(library, shelf_id, depth=depth)]


@router.get("/{read_id}", response_model=ReadDTO)
def get_read(
    shelf_id: str,
    read_id: str,
    library: LibraryRef = Depends(require(Capability.BROWSE)),
    reads: ReadStore = Depends(get_read_store),
    jobs: JobRunner = Depends(get_job_runner),
) -> ReadDTO:
    """One read, with every claim it produced so far. While the read is still
    ``running`` the live progress from the job runner rides along in
    ``progress`` — the stored claims themselves only land once the read
    settles (see ``_job`` below)."""
    read = _load_read(reads, library, shelf_id, read_id)
    live = jobs.status(read_id)
    progress = live.progress if live and live.state == "running" else None
    return ReadDTO.of(read, progress=progress)


@router.post("/{read_id}/stop", response_model=ReadDTO,
             status_code=status.HTTP_202_ACCEPTED)
def stop(
    shelf_id: str,
    read_id: str,
    library: LibraryRef = Depends(require(Capability.CAPTURE)),
    reads: ReadStore = Depends(get_read_store),
    jobs: JobRunner = Depends(get_job_runner),
) -> ReadDTO:
    """Cooperative stop. **202**: the request is accepted, not honoured yet —
    the worker notices between spines (the same shape as ``Pipeline.run``'s
    ``should_stop``), so the read this returns may still say ``running``;
    poll ``GET`` until it settles to ``stopped``. The claims already
    collected are kept — a stopped read is a real partial result, not a
    failure (§ app.domain.read)."""
    read = _load_read(reads, library, shelf_id, read_id)
    jobs.stop(read_id)
    return ReadDTO.of(read)


# --- reconciliation (P2.5) --------------------------------------------------

def diff_for(
    shelf_id: str,
    read_id: str,
    library: LibraryRef,
    shelves: ShelfStore,
    reads: ReadStore,
    books: BookStore,
    decisions: DecisionStore,
):
    """Load a read and reconcile its claims against the library's CURRENT
    state — recomputed fresh on every call (never cached), so GET and POST
    .../apply always see the same reality the store holds right now, and so
    "would this claim resolve differently now" is a real, answerable question
    rather than a stale snapshot.

    Not prefixed ``_`` (unlike this module's other helpers): P2.6's
    ``app/api/routers/duplicates.py`` calls it too, to re-derive the SAME
    outcome a queued question was raised from before answering it — the
    queue stores a `(shelf_id, read_id, book_key)`, not a snapshot, for
    exactly this reason.
    """
    shelf = _load_shelf(shelves, library, shelf_id)
    read = _load_read(reads, library, shelf_id, read_id)
    if read.status is ReadStatus.RUNNING:
        # Applying (or even just diffing) a read that might still append
        # claims would be comparing against a moving target, and an APPLY
        # here would write provenance for a read the job could still be
        # mutating underneath it (H2/§1.3's concurrency concern, one layer
        # up). Poll GET .../reads/{id} until it settles first.
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"read {read_id} is still running")
    library_books = {b.key: b for b in
                     books.list(library, limit=_FULL_LIBRARY_SCAN_LIMIT).items}
    decision_rows = decisions.list_decisions(library, shelf_id, read.depth)
    diff = reconcile(shelf, read.depth, read.claims, library_books,
                     decision_rows, read_id=read.id)
    return read, diff


@router.get("/{read_id}/diff", response_model=DiffDTO)
def get_diff(
    shelf_id: str,
    read_id: str,
    library: LibraryRef = Depends(require(Capability.BROWSE)),
    shelves: ShelfStore = Depends(get_shelf_store),
    reads: ReadStore = Depends(get_read_store),
    books: BookStore = Depends(get_book_store),
    decisions: DecisionStore = Depends(get_decision_store),
) -> DiffDTO:
    """What this read changes on the shelf's durable book list (§5.6): added
    / corrected / unchanged / not-seen, plus whatever §5.4 asks are still
    open. Read-only — nothing here is written until ``POST .../apply``."""
    _, diff = diff_for(shelf_id, read_id, library, shelves, reads, books,
                        decisions)
    return DiffDTO.of(diff)


_ANSWER_KINDS = {k.value: k for k in AnswerKind}


@router.post("/{read_id}/apply", response_model=DiffDTO)
def apply_read_diff(
    shelf_id: str,
    read_id: str,
    body: ApplyDiffRequest,
    library: LibraryRef = Depends(require(Capability.REVIEW)),
    shelves: ShelfStore = Depends(get_shelf_store),
    reads: ReadStore = Depends(get_read_store),
    books: BookStore = Depends(get_book_store),
    decisions: DecisionStore = Depends(get_decision_store),
    duplicates: DuplicateQueue = Depends(get_duplicate_queue),
    clock: Clock = Depends(get_clock),
    ids: IdGen = Depends(get_id_gen),
) -> DiffDTO:
    """Persist a read's diff (§5.6): every ``added``/``unchanged``/
    ``corrected`` claim writes through unconditionally — those are rules
    `reconcile()` already settled, not questions — and ``body.answers``
    resolves whichever ``needs_decision`` claims the caller is answering now.
    An unanswered ``ambiguous_location`` one is opened in the durable
    "duplicates to resolve" queue (P2.6, §5.4) rather than simply lost — see
    ``GET /duplicates`` to answer it later, from the Books tab, without
    re-running anything.

    Returns the diff RECOMPUTED after writing, so a resolved claim moves out
    of ``needs_decision`` in the same response that resolved it.
    """
    read, diff = diff_for(shelf_id, read_id, library, shelves, reads, books,
                           decisions)
    answers = []
    for a in body.answers:
        kind = _ANSWER_KINDS.get(a.kind)
        if kind is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"unknown answer kind {a.kind!r}; expected one of "
                f"{sorted(_ANSWER_KINDS)}",
            )
        answers.append(Answer(claim_id=a.claim_id, kind=kind,
                              copy_id=a.copy_id, title=a.title,
                              author=a.author))
    try:
        apply_diff(diff, library=library, books=books, shelves=shelves,
                  decisions=decisions, duplicates=duplicates, clock=clock,
                  ids=ids, captured_at=read.finished_at,
                  answers=tuple(answers))
    except UnresolvedAnswer as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    _, fresh = diff_for(shelf_id, read_id, library, shelves, reads, books,
                         decisions)
    return DiffDTO.of(fresh)


# --- the image workspace: acting on a settled finding (P2.10) ---------------
#
# §12.2 #10: the Capture tab is a WORKSPACE, not a pipeline — a finding stays
# actionable after its read settled, so a processed photo never has to be
# re-read just to see (or fix) what it found. *Approve* and *edit* are
# ordinary book routes (`POST /books/{id}/approve`, `PATCH /books/{id}`); the
# two below are the ones that need the READ's context, because a retraction is
# scoped to the (shelf, depth) the claim was read at (§5.6/§5.7 #1), not to
# the book.
#
# Both return the diff RECOMPUTED after writing — the same contract as
# `POST .../apply`, so the client replaces one object and every badge on the
# screen follows.

def _mint_spine_id(read: Read, body: ManualFindingIn) -> str:
    """A spine id for a hand-added finding — see the route's docstring.

    The counter is over the claims that already carry this parent's prefix, so
    splitting the same finding twice keeps producing distinct, ordered ids
    rather than colliding on ``~m1``.
    """
    parent = (body.after_spine_id or "").strip()
    if not parent:
        return f"manual-{uuid4().hex[:12]}"
    prefix = f"{parent}~m"
    n = sum(1 for c in read.claims if c.spine_id.startswith(prefix)) + 1
    return f"{prefix}{n}"


@router.get("/{read_id}/findings/lookup", response_model=list[FindingMatchDTO])
def lookup_findings(
    shelf_id: str,
    read_id: str,
    q: str = Query("", description="What the owner is typing."),
    limit: int = Query(3, ge=1, le=20),
    library: LibraryRef = Depends(require(Capability.BROWSE)),
    reads: ReadStore = Depends(get_read_store),
) -> list[FindingMatchDTO]:
    """*"Did this read already find this book?"* — asked while the owner is
    typing one in by hand (P2.10, owner 2026-08-09).

    Straight out of `booksnap/server.py:lookup`, whose docstring names the
    error it exists for: *"the review flow's expensive human error is adding
    a book by hand that the run DID find and the eye simply skipped (a 40-row
    shelf in a language read right-to-left)."* Same error, same answer.

    **Server-side for the reason the engine's version gives** — it reuses the
    project's own normalisation and ranking (`app.domain.search`, P1.5's
    measured Hebrew search: nikud stripped, final letters folded, in-word
    geresh deleted, leading particles tolerated) rather than growing a second,
    subtly different implementation in TypeScript. The client has every
    finding loaded already; what it cannot reproduce is *what matching means
    here*.

    Scope is this read's claims, ALL of them — including ones already
    approved, corrected or removed. A book you removed a moment ago is
    exactly the one you might be about to re-add by hand, and staying silent
    about it would be the unhelpful half of honest.
    """
    read = _load_read(reads, library, shelf_id, read_id)
    query = parse(q)
    if not query:
        # An empty or too-short query means "match nothing", never "match
        # everything" — `Query.__bool__`'s own contract.
        return []

    hits = [(c, TextEntry(title=c.title, author=c.author)) for c in read.claims]
    hits = [(c, e) for c, e in hits if matches(query, haystack(e))]
    # Same total order `search()` uses — relevance, then title, then id — so a
    # tie cannot reorder itself between two keystrokes.
    hits.sort(key=lambda pair: (-score(query, pair[1]),
                                pair[1].normalized_title, pair[0].id))
    return [FindingMatchDTO(claim_id=c.id, title=c.title, author=c.author,
                            tier=c.tier.value)
            for c, _ in hits[:limit]]


@router.post("/{read_id}/findings", response_model=DiffDTO,
             status_code=status.HTTP_201_CREATED)
def add_a_finding_by_hand(
    shelf_id: str,
    read_id: str,
    body: ManualFindingIn,
    library: LibraryRef = Depends(require(Capability.EDIT_BOOKS)),
    shelves: ShelfStore = Depends(get_shelf_store),
    reads: ReadStore = Depends(get_read_store),
    books: BookStore = Depends(get_book_store),
    decisions: DecisionStore = Depends(get_decision_store),
    duplicates: DuplicateQueue = Depends(get_duplicate_queue),
    clock: Clock = Depends(get_clock),
    ids: IdGen = Depends(get_id_gen),
) -> DiffDTO:
    """*"The engine missed this book"* — add one to this photo by hand.

    Files a MANUAL-tier :class:`~app.domain.read.Claim` on the read (see
    ``app.domain.read.add_manual_claim`` for why a settled read accepts this
    one kind of late claim and nothing else), then applies, so the book lands
    at its (shelf, depth) immediately: unlike a machine claim it needs no
    approval, because typing the title IS the approval.

    The ``spine_id`` is minted rather than left blank — `Provenance.sighting`
    is ``(run_id, spine_id)``, so a blank one would make every hand-added book
    on a single read look like the same sighting, and `observe()`'s
    idempotency would silently swallow the second.

    With ``after_spine_id`` it is minted as ``<that spine>~m<n>``, which is
    how a volume ends up next to the volume it was split from instead of at
    the bottom of the photo. The structure IS in the string, the same way the
    engine's own ``IMG_1234_b0_s07`` encodes a band and a position that
    `shelves.py` parses back out — honest for ordering, and no new column for
    a relationship nothing else needs to query.
    """
    read = _load_read(reads, library, shelf_id, read_id)
    try:
        claim = Claim(id=ids.new_id(), spine_id=_mint_spine_id(read, body),
                      # A hand-added book belongs to the photo the owner is
                      # looking at; a read of one (shelf, depth) may cover
                      # several, and the first is the only honest default the
                      # server can pick without being told which.
                      capture_id=read.capture_ids[0], title=body.title.strip(),
                      author=body.author.strip(), tier=ClaimTier.MANUAL)
        read = add_manual_claim(read, claim)
    except ReadAlreadyFinished as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    reads.save_read(library, read)

    _, diff = diff_for(shelf_id, read_id, library, shelves, reads, books,
                        decisions)
    apply_diff(diff, library=library, books=books, shelves=shelves,
              decisions=decisions, duplicates=duplicates, clock=clock, ids=ids,
              captured_at=read.finished_at, answers=())
    _, fresh = diff_for(shelf_id, read_id, library, shelves, reads, books,
                         decisions)
    return DiffDTO.of(fresh)


def _outcome_for(diff, claim_id: str):
    """The claim's CURRENT classification, from a freshly recomputed diff.

    Searches every bucket, including ``rejected`` (that is where a retracted
    finding lands, and it is what ``restore`` acts on) and ``ignored``.
    """
    for group in (diff.added, diff.corrected, diff.unchanged,
                  diff.needs_decision, diff.rejected, diff.ignored):
        for outcome in group:
            if outcome.claim.id == claim_id:
                return outcome
    raise HTTPException(status.HTTP_404_NOT_FOUND,
                        f"read has no finding {claim_id!r}")


@router.post("/{read_id}/findings/{claim_id}/retract", response_model=DiffDTO)
def retract_a_finding(
    shelf_id: str,
    read_id: str,
    claim_id: str,
    library: LibraryRef = Depends(require(Capability.REVIEW)),
    shelves: ShelfStore = Depends(get_shelf_store),
    reads: ReadStore = Depends(get_read_store),
    books: BookStore = Depends(get_book_store),
    decisions: DecisionStore = Depends(get_decision_store),
    duplicates: DuplicateQueue = Depends(get_duplicate_queue),
    clock: Clock = Depends(get_clock),
) -> DiffDTO:
    """*"✕ — this finding is wrong"*, on a claim already applied.

    Always records the standing decision (§5.6: a rejected book must not be
    re-added by a later run — without it the next read of this row puts it
    straight back). What happens to the library RECORD is
    `app.domain.retract.plan_retraction`'s rule: a book only a read ever
    claimed, standing only here, is deleted; anything a human approved,
    edited, or holds a second copy of is merely taken off this shelf
    (UI_PLAN §5's two-destructive-actions separation).
    """
    read, diff = diff_for(shelf_id, read_id, library, shelves, reads, books,
                           decisions)
    outcome = _outcome_for(diff, claim_id)
    if not outcome.book_key:
        # A claim with no title has no identity to record a decision AT
        # (`reconcile()`'s `no_identity`) — there is nothing to suppress and
        # nothing that could ever be re-added.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"finding {claim_id!r} resolved to no book at all; there is "
            "nothing to retract",
        )
    retract_finding(outcome, library=library, shelf_id=shelf_id,
                    depth=diff.depth, read=read, books=books,
                    decisions=decisions, clock=clock, duplicates=duplicates)

    _, fresh = diff_for(shelf_id, read_id, library, shelves, reads, books,
                         decisions)
    return DiffDTO.of(fresh)


@router.post("/{read_id}/findings/{claim_id}/restore", response_model=DiffDTO)
def restore_a_finding(
    shelf_id: str,
    read_id: str,
    claim_id: str,
    library: LibraryRef = Depends(require(Capability.REVIEW)),
    shelves: ShelfStore = Depends(get_shelf_store),
    reads: ReadStore = Depends(get_read_store),
    books: BookStore = Depends(get_book_store),
    decisions: DecisionStore = Depends(get_decision_store),
    duplicates: DuplicateQueue = Depends(get_duplicate_queue),
    clock: Clock = Depends(get_clock),
    ids: IdGen = Depends(get_id_gen),
) -> DiffDTO:
    """*"↩ — undo that"*: clear the standing decision suppressing this
    finding here, then let the read apply itself again.

    Composed from two things that already exist rather than a third write
    path: ``DecisionStore.delete_decision`` (its own docstring calls this
    "the undo of a mis-click", and is explicit that clearing an answer never
    itself adds anything back) followed by the ordinary
    ``apply_diff(answers=())`` — so an AUTO claim returns as the book it was,
    and a REVIEW-tier one returns to the open question it was, decided by the
    same `reconcile()` rules as any other apply. Nothing here re-reads the
    photo or invents a book.

    **409** when the finding is not actually suppressed: there is no decision
    to undo, and silently doing nothing would look identical to success.
    """
    read, diff = diff_for(shelf_id, read_id, library, shelves, reads, books,
                           decisions)
    outcome = _outcome_for(diff, claim_id)
    if not decisions.delete_decision(library, shelf_id, diff.depth,
                                     outcome.book_key):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"finding {claim_id!r} is not suppressed at this shelf and row; "
            "there is nothing to undo",
        )
    _, reopened = diff_for(shelf_id, read_id, library, shelves, reads, books,
                            decisions)
    apply_diff(reopened, library=library, books=books, shelves=shelves,
              decisions=decisions, duplicates=duplicates, clock=clock, ids=ids,
              captured_at=read.finished_at, answers=())

    _, fresh = diff_for(shelf_id, read_id, library, shelves, reads, books,
                         decisions)
    return DiffDTO.of(fresh)


# --- the job --------------------------------------------------------------

def _job(
    read: Read,
    shelf: Shelf,
    library: LibraryRef,
    captures: Sequence[Capture],
    reads: ReadStore,
    shelves: ShelfStore,
    reader: Reader,
    blobs: BlobStore,
    books: BookStore,
    decisions: DecisionStore,
    duplicates: DuplicateQueue,
    ids: IdGen,
    clock: Clock,
):
    """Build the callable ``JobRunner.submit`` runs on its background thread.

    Everything it needs is captured in this closure at submit time — no
    module state, no re-resolving dependencies from an HTTP request that will
    be long gone by the time the engine finishes (H2/§1.3).

    Captures with no ``image_id`` (P2.2's recorded gap — a capture can exist
    before its photo is uploaded) are silently excluded from what the Reader
    is asked to read; the other captures at this depth are still real work.
    """
    requests = [ReadRequest(capture_id=c.id, image_key=c.image_id)
               for c in captures if c.image_id]

    def run(handle: JobHandle) -> None:
        current = read
        try:
            claims = reader.read(
                library, requests, mode=read.mode,
                progress=handle.report_progress, should_stop=handle.should_stop,
            )
            for rc in claims:
                crop_key = blobs.put(library, rc.crop).key if rc.crop else None
                claim = Claim(
                    id=ids.new_id(), spine_id=rc.spine_id,
                    capture_id=rc.capture_id, text=rc.text, title=rc.title,
                    author=rc.author, tier=ClaimTier(rc.tier), score=rc.score,
                    catalog_id=rc.catalog_id, crop_key=crop_key, box=rc.box,
                    alternatives=tuple(
                        Alternative(title=a.title, author=a.author,
                                   score=a.score, reason=a.reason)
                        for a in rc.alternatives
                    ),
                )
                current = append_claim(current, claim)
            current = (
                stop_read(current, finished_at=clock.now_iso())
                if handle.should_stop()
                else finish_read(current, finished_at=clock.now_iso())
            )
            # P2.8's snapshot (§5.5/§5.6): one reconcile() call, right now,
            # against the library exactly as it stood before this read's own
            # `apply` (if any) has had a chance to touch it — the archived
            # "what did THIS read change" a history row shows forever. NOT
            # taken for a `failed` read: `current.claims` may be an arbitrary
            # partial slice from whatever blew up mid-spine, and a summary
            # over that is not evidence worth freezing.
            if current.status in (ReadStatus.DONE, ReadStatus.STOPPED):
                library_books = {b.key: b for b in
                                 books.list(library, limit=_FULL_LIBRARY_SCAN_LIMIT).items}
                decision_rows = decisions.list_decisions(library, read.shelf_id,
                                                          read.depth)
                diff = reconcile(shelf, read.depth, current.claims,
                                 library_books, decision_rows, read_id=current.id)
                current = with_diff_summary(current, summarize(diff))

                # Apply SERVER-SIDE, right here where the read settles (fixing
                # the bug this exists for: completing a catalogue update used
                # to depend on the owner's browser staying open long enough to
                # notice the read finished and POST .../apply itself — a
                # mobile tab backgrounded mid-read, or refreshed, meant claims
                # sat stored forever with no book ever added, which
                # contradicts §5.6's own inversion: "a read is an event that
                # UPDATES the list", not an event that waits to be told to).
                #
                # Reuses the SAME `diff` object `with_diff_summary` above just
                # summarised — never recomputes one. `diff` is already a
                # frozen snapshot of `reconcile()` against the library as it
                # stood the moment `library_books` was read, a few lines up,
                # BEFORE any write below — so the archived summary is safe
                # regardless of textual order down here. What would corrupt
                # it is refetching `books.list(...)` and calling `reconcile()`
                # a second time AFTER `apply_diff` for "fresher" data: that
                # second diff would see the book this very apply just added
                # and call it `unchanged`, silently rewriting "this read
                # added 3 books" into "this read changed nothing" the moment
                # it settles. Don't.
                #
                # `answers=()` is not a placeholder for future wiring, it is
                # the whole point: only the buckets `reconcile()` already
                # settled with no human input (added/unchanged/corrected) are
                # written. A `needs_decision` claim is NEVER auto-resolved
                # here (§5.4) — an `ambiguous_location` one is opened in the
                # duplicates queue exactly as it would be if a human had
                # loaded the review screen and closed it without answering,
                # and a `new_book_unconfirmed` one simply stays open. This is
                # the identical operation the client's own `commitDiff`
                # performs (`app/web/src/capture/useCapture.ts`) — calling it
                # from both places is intentional and safe, not a race:
                # `observe()`'s `Provenance.sighting` idempotency
                # (`app/domain/book.py`) means a claim already applied here
                # reconciles as `unchanged` the second time, so the client's
                # later call (it still makes one) writes nothing new.
                try:
                    apply_diff(
                        diff, library=library, books=books, shelves=shelves,
                        decisions=decisions, duplicates=duplicates, clock=clock,
                        ids=ids, captured_at=current.finished_at, answers=(),
                    )
                except Exception:
                    # A read is a real record of an attempt even when the
                    # automatic follow-up fails (the shelf was deleted mid-
                    # read; a store hiccup) — `current` (claims + summary) is
                    # kept exactly as computed above and still gets saved
                    # below. Logged, not re-raised — and this local catch is
                    # not merely tidy, it is LOAD-BEARING: `current.status` is
                    # already terminal by this point (`finish_read`/`stop_read`
                    # ran above, before this whole block), so letting the
                    # exception reach the `except Exception as exc:` below
                    # would call `fail_read` on an ALREADY-terminal read,
                    # which raises `ReadAlreadyFinished` right back out —
                    # uncaught, killing the job thread before it ever reaches
                    # `reads.save_read` at the bottom, leaving the read stuck
                    # showing `running` forever. That is a WORSE bug than the
                    # one this file exists to fix (verified: temporarily
                    # removing this try/except reproduces exactly that hang).
                    # The client's own `commitDiff` (still called on every
                    # settle) is the retry path for the failed apply itself.
                    logger.exception(
                        "read %s settled as %s but its diff failed to apply "
                        "automatically; the read and its claims are saved "
                        "regardless — the client's own apply-on-settle is "
                        "the fallback",
                        current.id, current.status.value,
                    )
        except Exception as exc:
            # A read is a real record of an attempt even when the attempt
            # failed (a bad catalog, no engine credentials, ...) — see
            # `app.domain.read.fail_read`. Whatever claims were appended
            # before the failure are kept on `current`.
            current = fail_read(current, error=str(exc),
                                finished_at=clock.now_iso())
        reads.save_read(library, current)

    return run
