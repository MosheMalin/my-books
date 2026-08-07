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

from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    current_library,
    get_blob_store,
    get_book_store,
    get_clock,
    get_decision_store,
    get_id_gen,
    get_job_runner,
    get_read_store,
    get_reader,
    get_shelf_store,
)
from app.api.dto import ApplyDiffRequest, DiffDTO, ReadCreate, ReadDTO, ReadSummaryDTO
from app.domain import (
    Capture,
    Claim,
    ClaimTier,
    LibraryRef,
    Read,
    ReadStatus,
    Shelf,
    append_claim,
    fail_read,
    finish_read,
    new_read,
    reconcile,
    stop_read,
)
from app.domain.book import DomainError
from app.domain.shelf import UnknownDepth
from app.ports import Clock, IdGen
from app.ports.blobs import BlobStore
from app.ports.decisions import DecisionStore
from app.ports.jobs import JobHandle, JobRunner
from app.ports.reader import Reader, ReadRequest
from app.ports.store import BookStore, ReadStore, ShelfStore
from app.reconcile_apply import Answer, AnswerKind, UnresolvedAnswer, apply_diff

router = APIRouter(prefix="/shelves/{shelf_id}/reads", tags=["reads"])

# A `reconcile()` call needs to know about a matching book anywhere in the
# library (§5.4 — the ask fires on a match on ANOTHER shelf), not only this
# depth's occupants, so the diff endpoints load the whole library rather than
# a filtered slice. `BookStore.list` has no shelf/depth filter to narrow with
# (P2.5 did not add one — see `app.domain.reconcile`'s own module docstring
# for the honest O(library) trade this accepts, same one `books.py`'s
# `EXPORT_MAX` already makes for the export route).
_FULL_LIBRARY_SCAN_LIMIT = 100_000


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
    library: LibraryRef = Depends(current_library),
    shelves: ShelfStore = Depends(get_shelf_store),
    reads: ReadStore = Depends(get_read_store),
    reader: Reader = Depends(get_reader),
    jobs: JobRunner = Depends(get_job_runner),
    blobs: BlobStore = Depends(get_blob_store),
    clock: Clock = Depends(get_clock),
    ids: IdGen = Depends(get_id_gen),
) -> ReadDTO:
    """Start reading a shelf at one depth.

    **202**, not 201 or 200: the read keeps running after this call returns,
    and the body is a snapshot of "just started" — poll ``GET`` to watch it
    settle into ``done``/``stopped``/``failed``.
    """
    shelf = _load_shelf(shelves, library, shelf_id)
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

    jobs.submit(read.id, _job(read, library, captures, reads, reader, blobs,
                              ids, clock))
    return ReadDTO.of(read)


@router.get("", response_model=list[ReadSummaryDTO])
def list_reads(
    shelf_id: str,
    depth: int | None = Query(
        None, ge=1,
        description="Narrow to one row front-to-back — §5.7 #1 scopes a "
                    "read's history to the depth it actually covered.",
    ),
    library: LibraryRef = Depends(current_library),
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
    library: LibraryRef = Depends(current_library),
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
    library: LibraryRef = Depends(current_library),
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

def _diff_for(
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
    rather than a stale snapshot."""
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
    library: LibraryRef = Depends(current_library),
    shelves: ShelfStore = Depends(get_shelf_store),
    reads: ReadStore = Depends(get_read_store),
    books: BookStore = Depends(get_book_store),
    decisions: DecisionStore = Depends(get_decision_store),
) -> DiffDTO:
    """What this read changes on the shelf's durable book list (§5.6): added
    / corrected / unchanged / not-seen, plus whatever §5.4 asks are still
    open. Read-only — nothing here is written until ``POST .../apply``."""
    _, diff = _diff_for(shelf_id, read_id, library, shelves, reads, books,
                        decisions)
    return DiffDTO.of(diff)


_ANSWER_KINDS = {k.value: k for k in AnswerKind}


@router.post("/{read_id}/apply", response_model=DiffDTO)
def apply_read_diff(
    shelf_id: str,
    read_id: str,
    body: ApplyDiffRequest,
    library: LibraryRef = Depends(current_library),
    shelves: ShelfStore = Depends(get_shelf_store),
    reads: ReadStore = Depends(get_read_store),
    books: BookStore = Depends(get_book_store),
    decisions: DecisionStore = Depends(get_decision_store),
    clock: Clock = Depends(get_clock),
    ids: IdGen = Depends(get_id_gen),
) -> DiffDTO:
    """Persist a read's diff (§5.6): every ``added``/``unchanged``/
    ``corrected`` claim writes through unconditionally — those are rules
    `reconcile()` already settled, not questions — and ``body.answers``
    resolves whichever ``needs_decision`` claims the caller is answering now.
    An unanswered one simply stays open; nothing is lost, it just shows up
    again next time the diff is asked for (P2.6 owns making that durable
    across sessions rather than per-call).

    Returns the diff RECOMPUTED after writing, so a resolved claim moves out
    of ``needs_decision`` in the same response that resolved it.
    """
    read, diff = _diff_for(shelf_id, read_id, library, shelves, reads, books,
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
                              copy_id=a.copy_id))
    try:
        apply_diff(diff, library=library, books=books, shelves=shelves,
                  decisions=decisions, clock=clock, ids=ids,
                  captured_at=read.finished_at, answers=tuple(answers))
    except UnresolvedAnswer as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    _, fresh = _diff_for(shelf_id, read_id, library, shelves, reads, books,
                         decisions)
    return DiffDTO.of(fresh)


# --- the job --------------------------------------------------------------

def _job(
    read: Read,
    library: LibraryRef,
    captures: Sequence[Capture],
    reads: ReadStore,
    reader: Reader,
    blobs: BlobStore,
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
                )
                current = append_claim(current, claim)
            current = (
                stop_read(current, finished_at=clock.now_iso())
                if handle.should_stop()
                else finish_read(current, finished_at=clock.now_iso())
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
