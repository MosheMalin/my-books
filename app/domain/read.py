# -*- coding: utf-8 -*-
"""Read and Claim — the record of one engine pass over one (shelf, depth)
(P2.4).

The pipeline (segmentation, OCR, catalog lookups — everything that imports
cv2, shells out to tesseract, or calls a paid vision API) happens entirely
behind ``app.ports.reader.Reader``. This module only holds what a read *is*,
once it has happened, or partly happened: pure Python, no I/O, no framework,
no store — same rule as the rest of ``app/domain``.

Two rules from the plan shape everything here:

  - **a Read is scoped to exactly one (shelf, depth)** (§5.7 #1). "Not seen in
    this read" and "add a row behind" both only mean something against the
    row that was actually photographed — a Read spanning several depths would
    let §2.5's reconciliation compare a claim from one row against books
    shelved on another and call the mismatch "missing". ``new_read`` is the
    only constructor and it enforces the scoping structurally, by taking the
    ``Shelf`` and its ``Capture``s rather than bare ids — the same shape as
    ``shelf.new_capture`` checking depth against the shelf it belongs to;
  - **a stopped read is a REAL partial result, not a failure**
    (``Pipeline.run``'s own docstring, echoed here): ``ReadStatus`` has three
    distinct terminal values, not two, so a caller checking "did this fail"
    cannot accidentally discard a read the owner stopped on purpose. Whatever
    claims were collected before the stop stay on the read exactly as they
    would if it had finished normally.

And one that is new to this module: **claims are never mutated after a read
finishes.** ``append_claim`` refuses once ``status`` is terminal
(:class:`ReadAlreadyFinished`) — the archived record of "what this read saw"
must mean what it said at the moment it stopped meaning anything new, or a
race between a slow last spine and a stop request could silently rewrite
history. Same append-only reasoning as ``Copy.provenance``, for the same
reason.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Sequence

from app.domain.book import DomainError
from app.domain.shelf import Capture, Shelf


class ReadAlreadyFinished(DomainError):
    """A claim, or a second finish/stop/fail, arrived after a read had
    already reached a terminal status. See the module docstring — this is
    what keeps a Read's claims append-only."""


class ClaimTier(str, Enum):
    """What one claim is worth, straight out of ``booksnap.types.Match.tier``
    — lower-cased to match this codebase's other status enums (``Status.AUTO``
    is ``"auto"``, not ``"AUTO"``) — plus two values the engine has no notion
    of:

    ``UNMATCHED`` — a spine the matcher had nothing to say about. booksnap
    represents that as ``match is None``; a :class:`Claim` always exists once a
    spine was read (it is the record of the attempt), so it needs its own tier
    value rather than a null one.

    ``MANUAL`` — a book the OWNER added to a photo by hand, because the engine
    missed it (P2.10, owner 2026-08-09). It is a claim like any other — it is
    an assertion about what is in this photograph — but its evidence is a
    person, not a reader, which is why it is a tier and not a flag: everything
    downstream already dispatches on tier, and a human's word outranks every
    machine tier (§5.1's ladder). In particular it is the ONE tier that enters
    the library without an approval step, because typing the title IS the
    approval.
    """

    AUTO = "auto"
    REVIEW = "review"
    UNMATCHED = "unmatched"
    MANUAL = "manual"


@dataclass(frozen=True)
class Alternative:
    """One ranked candidate `booksnap.match.explain()` considered for a claim's
    OCR text, kept for the review UI's *"why?"* affordance (P2.7, UI_PLAN §4).

    Deliberately thin: title/author/score are what a human scans a ranked
    list for, and ``reason`` is the gate that refused the candidate — empty
    for one that passed the matcher's own gates (a real runner-up), non-empty
    for one `explain()` rejected and says why. This is display data, not a
    domain rule of its own; the matcher already decided everything it means
    (booksnap philosophy: deterministic first) — this only carries the
    reasoning to the screen that asks for it.
    """

    title: str
    author: str = ""
    score: float = 0.0
    reason: str = ""


class ReadStatus(str, Enum):
    """``running`` settles into exactly one of ``done`` / ``stopped`` /
    ``failed`` — see the module docstring for why ``stopped`` is not folded
    into ``failed``."""

    RUNNING = "running"
    DONE = "done"
    STOPPED = "stopped"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self is not ReadStatus.RUNNING


# --- entities ---------------------------------------------------------------

@dataclass(frozen=True)
class Claim:
    """What one read asserts about one spine.

    Frozen and never edited after creation: correcting a claim is not this
    module's job. P2.5's reconciliation reads a Read's claims to produce a
    diff against shelf state, and P2.6 is where a human accepts or rejects
    one — editing the claim itself would blur "what the engine said" with
    "what a human decided", which are two different records for two
    different rules (the same reasoning that keeps ``Provenance`` append-only
    rather than corrected in place).

    ``crop_key`` is a ``BlobStore`` key (P2.3), not bytes — the review UI
    fetches the picture the same way it fetches every other photo, at
    ``GET /images/{crop_key}/thumb|full``. It is optional because a whole-page
    read's block may already BE the crop of the source capture, and a mode
    that fails before segmenting has no crop to offer at all.
    """

    id: str
    spine_id: str
    capture_id: str
    text: str = ""
    title: str = ""
    author: str = ""
    tier: ClaimTier = ClaimTier.UNMATCHED
    score: float = 0.0
    catalog_id: str | None = None
    crop_key: str | None = None
    box: tuple[int, int, int, int] | None = None   # x0, y0, x1, y1
    alternatives: tuple[Alternative, ...] = ()

    def __post_init__(self) -> None:
        if not self.spine_id:
            raise DomainError("a claim must name the spine it is about")
        if not self.capture_id:
            raise DomainError("a claim must name the capture it came from")


@dataclass(frozen=True)
class DiffSummary:
    """Headline diff counts (§5.6: *"+3 added · 1 corrected · 12 unchanged ·
    1 not seen"*), captured ONCE when a read settles into ``done`` or
    ``stopped`` — a snapshot, never recomputed (P2.8).

    Why a snapshot and not a live recomputation, unlike every other diff view
    in this codebase: ``app.reconcile_apply``'s ``diff_for`` deliberately
    recomputes ``reconcile()`` fresh against CURRENT library state on every
    call, and says so in its own docstring — right for the ONE active,
    not-yet-applied read that every review screen shows, because "would this
    claim resolve differently now" is exactly the live question that screen
    answers. A read's place in HISTORY is a different question. Recompute an
    ALREADY-APPLIED read's diff today and every one of its ``added`` claims
    now shows as ``unchanged`` — the book it added is, by definition,
    already standing at that (shelf, depth) the moment you ask again — which
    would silently rewrite "this read added 3 books" into "this read changed
    nothing", forever, the instant the read was reviewed. So the four
    headline counts (plus the three transparency buckets) are captured once
    and archived, the same shape as a run's own config snapshot
    (CLAUDE.md, "Run history": *"THIS IS THE EXPERIMENT VARIABLE"*).

    Deliberately plain ints, not the ``ClaimOutcome`` list `Diff` carries —
    the archived record a history view needs is "how many", not a second
    copy of every claim already sitting in ``Read.claims``.
    """

    added: int = 0
    corrected: int = 0
    unchanged: int = 0
    needs_decision: int = 0
    not_seen: int = 0
    rejected: int = 0
    ignored: int = 0


@dataclass(frozen=True)
class Read:
    """One engine pass over one (shelf, depth) — the audit trail P2.5's
    reconciliation and P2.6's copy resolution both read from.

    ``mode`` is whatever ``booksnap.Pipeline.run`` accepts (``"spines"``,
    ``"fullpage"``, ``"llmpage"``) — modes are the engine's own (plan P2.4),
    not redefined here, so a new one needs no change to this module.

    ``code_version`` and ``config`` mirror ``booksnap/server.py``'s per-run
    archive (git sha + dirty flag, and the full tunable snapshot): a Read is
    only interpretable next to the code and config that produced it, same
    reasoning, same shape, second copy on purpose (H1 — this module must not
    import the tuning server to share the logic).

    ``diff_summary`` is ``None`` until the read settles (P2.8) — see
    :class:`DiffSummary`. Still ``None`` forever for a ``failed`` read: there
    is no reliable diff to summarise over claims that may have stopped mid
    spine because setup itself blew up.
    """

    id: str
    library_id: str
    shelf_id: str
    depth: int
    capture_ids: tuple[str, ...]
    mode: str
    status: ReadStatus = ReadStatus.RUNNING
    claims: tuple[Claim, ...] = ()
    code_version: dict | None = None
    config: dict | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    diff_summary: DiffSummary | None = None

    def __post_init__(self) -> None:
        if not self.library_id:
            raise DomainError("a read must belong to a library (H2)")
        if not self.shelf_id:
            raise DomainError("a read must name the shelf it reads (§5.7 #1)")
        if self.depth < 1:
            raise DomainError("depth is 1-based")
        if not self.capture_ids:
            raise DomainError("a read needs at least one capture")
        if not self.mode:
            raise DomainError("a read must name its engine mode")


# --- operations --------------------------------------------------------------

def new_read(
    shelf: Shelf,
    captures: Sequence[Capture],
    *,
    id: str,
    depth: int,
    mode: str,
    code_version: dict | None = None,
    config: dict | None = None,
    started_at: str | None = None,
) -> Read:
    """Start a read of ONE (shelf, depth).

    Takes the ``Shelf`` and its ``Capture``s, not bare ids, precisely so an
    inconsistent read — a capture from another shelf, or another row of this
    one — cannot enter the system. §5.7 #1: "not seen in this read" is only
    meaningful scoped to the depth actually photographed, and §5.7 #2
    separately forbids merging overlaps across depths; both rules assume a
    Read never straddles more than one.
    """
    shelf.check_depth(depth)
    if not captures:
        raise DomainError(
            f"shelf {shelf.id} has no captures at depth {depth} to read"
        )
    for c in captures:
        if c.shelf_id != shelf.id:
            raise DomainError(
                f"capture {c.id} belongs to shelf {c.shelf_id!r}, not "
                f"{shelf.id!r} — a read is scoped to one shelf (§5.7 #1)"
            )
        if c.depth != depth:
            raise DomainError(
                f"capture {c.id} is at depth {c.depth}, not {depth} — a "
                f"read is scoped to one depth (§5.7 #1)"
            )
    return Read(
        id=id, library_id=shelf.library_id, shelf_id=shelf.id, depth=depth,
        capture_ids=tuple(c.id for c in captures), mode=mode,
        code_version=code_version, config=config, started_at=started_at,
    )


def append_claim(read: Read, claim: Claim) -> Read:
    """One spine's evidence, added while the read is still running.

    Refused once the read is terminal — see :class:`ReadAlreadyFinished`. A
    cooperative stop (the job runner polls between spines, same shape as
    ``Pipeline.run``'s ``should_stop``) always calls :func:`stop_read` before
    its worker exits, so in the normal path this can never race; the check
    exists for the abnormal one, where it is the only thing stopping a slow
    last spine from writing into a read the API has already told a caller is
    finished.
    """
    if read.status.is_terminal:
        raise ReadAlreadyFinished(
            f"read {read.id} is already {read.status.value}; claims are "
            "never appended after a read finishes"
        )
    return replace(read, claims=read.claims + (claim,))


def add_manual_claim(read: Read, claim: Claim) -> Read:
    """The owner's own finding about this photo — *"the engine missed this
    book"* (P2.10, owner 2026-08-09).

    The ONE way a claim may join a read after it has finished, and the
    exception is deliberately narrow rather than a loosening of
    :func:`append_claim`'s rule. That rule protects the ENGINE's record from a
    slow last spine writing into a read the API has already reported as
    finished — a race between two machine writers. This is not that: it is a
    human, minutes or days later, adding what they can see in the photograph
    and the reader could not. Refusing it would mean either losing the book or
    inventing a second place for "books in this image", and the image is
    exactly what this record is about.

    Two guards keep the distinction real:

      - the claim must be :attr:`ClaimTier.MANUAL` — the engine's own tiers
        stay unreachable through this door, so nothing here can forge machine
        evidence;
      - the read must NOT be running. A settled read is the only one a human
        has finished looking at, and it also restores the exact race guarantee
        `append_claim` exists for.
    """
    if claim.tier is not ClaimTier.MANUAL:
        raise DomainError(
            "only a MANUAL-tier claim may be added to a read by hand; "
            f"got {claim.tier.value!r} — engine evidence goes through "
            "append_claim while the read is running"
        )
    if not read.status.is_terminal:
        raise ReadAlreadyFinished(
            f"read {read.id} is still running; wait for it to settle before "
            "adding a book to this photo by hand"
        )
    return replace(read, claims=read.claims + (claim,))


def _end(read: Read, *, status: ReadStatus, finished_at: str,
         error: str | None = None) -> Read:
    if read.status.is_terminal:
        raise ReadAlreadyFinished(f"read {read.id} is already {read.status.value}")
    return replace(read, status=status, finished_at=finished_at, error=error)


def finish_read(read: Read, *, finished_at: str) -> Read:
    """Every capture was read and matched. The ordinary ending."""
    return _end(read, status=ReadStatus.DONE, finished_at=finished_at)


def stop_read(read: Read, *, finished_at: str) -> Read:
    """The owner asked it to stop.

    NOT a failure (see the module docstring): the claims already collected
    are real evidence and stay on the read exactly as :func:`finish_read`
    would leave them. A caller distinguishing "trust these claims" from
    "discard this read" checks ``status``, never the presence of an error.
    """
    return _end(read, status=ReadStatus.STOPPED, finished_at=finished_at)


def fail_read(read: Read, *, error: str, finished_at: str) -> Read:
    """Setup blew up (a bad catalog, missing engine credentials, ...) before
    or during the read. Whatever claims exist are kept — the same
    "partial result over none" reasoning as :func:`stop_read` — but ``error``
    records that this ending was not requested."""
    return _end(read, status=ReadStatus.FAILED, finished_at=finished_at, error=error)


def with_diff_summary(read: Read, summary: DiffSummary) -> Read:
    """Attach the diff snapshot (P2.8) the moment the read settles.

    Not guarded by ``is_terminal`` the way :func:`append_claim` is: a
    summary is metadata ABOUT a finished read, computed and set by the same
    caller that just finished it (``app/api/routers/reads.py``'s job), never
    something a later, independent write races against. What must never
    happen — recomputing this later against a changed library and
    overwriting the archived snapshot — is a caller discipline (only the job
    that just finished the read calls this), not a fact this function alone
    can enforce from a `Read`'s own state.
    """
    return replace(read, diff_summary=summary)
