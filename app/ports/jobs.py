# -*- coding: utf-8 -*-
"""JobRunner — the background-job seam (P2.4, queued at P3.4), explicitly NOT
the shape ``booksnap/server.py`` uses.

That server keeps job state in a module-level ``_job`` dict and a single
module-level ``_stop_event`` (its "background job" section) — correct for one
person using one process, and exactly what H2/§1.3 forbids for the product:
two members starting a read at once would overwrite each other's job. So this
port's one real requirement is that every implementation keeps its state on
an INSTANCE, constructed once in ``app/main.py``'s composition root and
handed to the reads router like every other port.

P3.4 made the one implementation a bounded QUEUE
(``app/adapters/queued_jobs.py``) rather than a thread per job: a fixed pool
of workers, per-tenant round-robin fairness (one library submitting ten reads
must not starve another's one), optional retry, and the same cooperative-stop
contract ``Pipeline.run`` has always polled. Still in-process — a separate
queue PROCESS is a deployment decision that belongs with P4.4, and nothing
above this port would change meaning then either.

May import ``app.domain`` only (H1).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class JobStatus:
    """What a caller polling a job can learn about it.

    ``progress`` is deliberately NOT persisted anywhere (contrast the
    ``Read`` itself, which the caller saves to ``ReadStore``) — it is a
    fast-changing, purely operational number (image 3 of 5, spine 8 of 22)
    that means nothing once the job ends, so keeping it live-only avoids a
    second place that could disagree with the stored ``Read`` about whether
    the job is done.
    """

    state: str                    # "running" | "done" | "stopped" | "failed"
    progress: dict | None = None
    error: str | None = None


class JobHandle(Protocol):
    """What a running job's callable is handed — its half of the contract
    with the runner."""

    def should_stop(self) -> bool:
        """Cooperative stop, polled the same way ``Pipeline.run`` polls its
        own ``should_stop``. True once ``JobRunner.stop`` has been called for
        this job."""

    def report_progress(self, progress: dict) -> None:
        """Publish the latest progress dict; overwrites the previous one.
        Shape is the caller's business — the runner only stores and returns
        whatever was last reported."""


class JobRunner(Protocol):
    """Runs one callable per job, in the background, on an instance."""

    def submit(
        self,
        job_id: str,
        fn: Callable[[JobHandle], None],
        *,
        tenant: str = "",
        retries: int = 0,
    ) -> None:
        """Enqueue ``fn`` to run in the background. ``fn`` receives a
        ``JobHandle`` and is responsible for polling ``should_stop`` and
        reporting progress itself — the runner does not know what the work
        IS, only that it runs.

        ``tenant`` is the fairness key (P3.4): pending jobs are drained
        round-robin ACROSS tenants, FIFO within one, so one library's burst
        cannot starve another's single read. It is an opaque string to the
        runner — the reads router passes ``library.id`` — and ``""`` is a
        legal tenant of its own (single-user callers and old tests), not a
        special case.

        ``retries`` is how many times an exception escaping ``fn`` re-enqueues
        it before the job is marked "failed". ⚠ The reads job deliberately
        passes 0: it handles its own failure (``fail_read`` + save), and a
        runner-level retry would re-run the ENGINE — paying for the same
        photos twice on, say, a store hiccup during the final save. Retry is
        for callables that are cheap and idempotent end to end; the option
        exists so P3.4's queue is complete, not so reads use it.

        While a job waits for a worker its :meth:`status` reports state
        ``"running"`` with progress ``{"stage": "queued"}`` — a fifth state
        would ripple a distinction into every poller that none of them can
        act on, and "the engine has not reached photo 1 of N yet" is exactly
        what queued means to the person watching.

        An exception escaping the final attempt marks the job "failed"
        (operationally, for :meth:`status`) with the exception's message.
        ``fn`` is expected to handle its OWN domain-level failure first —
        e.g. saving a ``Read`` via ``fail_read`` — because the job's
        operational "failed" state is never read back into a ``Read``;
        nothing else does that translation.
        """

    def status(self, job_id: str) -> JobStatus | None:
        """Current state, or ``None`` if no job was ever submitted under this
        id."""

    def stop(self, job_id: str) -> bool:
        """Request a cooperative stop. ``False`` if the job is unknown or
        already finished — stopping is a REQUEST, not a guarantee, so it never
        raises on a race with the job finishing on its own."""
