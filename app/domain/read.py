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
    is ``"auto"``, not ``"AUTO"``) — plus ``UNMATCHED`` for a spine the
    matcher had nothing to say about. booksnap represents that as
    ``match is None``; a :class:`Claim` always exists once a spine was read
    (it is the record of the attempt), so it needs its own tier value rather
    than a null one.
    """

    AUTO = "auto"
    REVIEW = "review"
    UNMATCHED = "unmatched"


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

    def __post_init__(self) -> None:
        if not self.spine_id:
            raise DomainError("a claim must name the spine it is about")
        if not self.capture_id:
            raise DomainError("a claim must name the capture it came from")


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
