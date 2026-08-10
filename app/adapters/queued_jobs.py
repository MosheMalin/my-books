# -*- coding: utf-8 -*-
"""QueuedJobRunner (P3.4) — a bounded worker pool with per-tenant fairness.

Replaces the thread-per-job ``InProcessJobRunner`` (P2.4). What changes is
capacity discipline, not meaning: a fixed pool of daemon workers drains a
queue instead of every submit minting its own thread, so ten reads pressed at
once become ten queued jobs on two workers rather than ten concurrent engine
runs fighting for four cores (or ten concurrent paid LLM calls).

Fairness is round-robin ACROSS tenants, FIFO within one: the scheduler keeps
one deque per tenant and a ring of tenant keys, takes the head job of the
ring's next non-empty tenant, and sends that tenant to the back of the ring.
One library submitting a burst therefore waits behind its own work, never
ahead of another library's single read — the plan's own test case ("two
concurrent reads in two libraries do not observe each other") plus the
starvation half.

Still in-process, on purpose. A separate queue PROCESS (or a broker) is a
deployment decision that belongs with P4.4; this adapter is the semantics —
bounded, fair, stoppable, restartable-by-retry — behind the same port, so
that later swap changes wiring in ``app/main.py`` and nothing else.

Every mutable bit lives on ``self`` (H2/§1.3), same as the runner it
replaces; two ``QueuedJobRunner()``s share nothing. Workers are started
lazily on first submit — a runner an app builds and never uses costs no
threads, which also keeps the API ring's hundreds of app builds cheap.

⚠ **A stopped-while-queued job still RUNS, with stop already set.** The
alternative — settling it from the scheduler — would mean the runner marking
a job "stopped" that never executed, while the caller's own durable record
(the ``Read`` saved as ``running`` before submit) waits for ``fn`` to settle
it. The contract stays one-sided on purpose: the runner never knows what the
work is, so the work must run to write its own ending. ``fn`` sees
``should_stop()`` true on its first poll and settles in milliseconds.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from app.ports.jobs import JobHandle, JobStatus

#: Queue-position progress, reported for a job no worker has picked up yet.
#: A dict (not None) so a poller distinguishes "waiting for a worker" from
#: "running but nothing reported yet" without a fifth job state.
_QUEUED_PROGRESS = {"stage": "queued"}


@dataclass
class _Job:
    fn: Callable[[JobHandle], None]
    tenant: str
    retries_left: int
    stop_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    state: str = "running"          # the port's four states; queued shows in progress
    picked_up: bool = False
    progress: dict | None = None
    error: str | None = None


class _Handle:
    """Implements ``app.ports.jobs.JobHandle`` for one job."""

    def __init__(self, job: _Job) -> None:
        self._job = job

    def should_stop(self) -> bool:
        return self._job.stop_event.is_set()

    def report_progress(self, progress: dict) -> None:
        with self._job.lock:
            self._job.progress = progress


class QueuedJobRunner:
    """Implements ``app.ports.jobs.JobRunner``. See the module note."""

    def __init__(self, workers: int = 2) -> None:
        if workers < 1:
            raise ValueError("a queue with no workers never runs anything")
        self._target = workers
        self._guard = threading.Lock()
        self._wake = threading.Condition(self._guard)
        self._jobs: dict[str, _Job] = {}
        self._queues: dict[str, deque[str]] = {}
        self._ring: deque[str] = deque()
        self._threads: list[threading.Thread] = []

    # --- the port ---------------------------------------------------------

    def submit(
        self,
        job_id: str,
        fn: Callable[[JobHandle], None],
        *,
        tenant: str = "",
        retries: int = 0,
    ) -> None:
        job = _Job(fn=fn, tenant=tenant, retries_left=max(0, retries),
                   progress=dict(_QUEUED_PROGRESS))
        with self._wake:
            self._jobs[job_id] = job
            self._enqueue_locked(job_id, tenant)
            self._spawn_workers_locked()
            self._wake.notify()

    def status(self, job_id: str) -> JobStatus | None:
        with self._guard:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        with job.lock:
            return JobStatus(state=job.state, progress=job.progress,
                             error=job.error)

    def stop(self, job_id: str) -> bool:
        with self._guard:
            job = self._jobs.get(job_id)
        if job is None:
            return False
        with job.lock:
            if job.state != "running":
                return False
        job.stop_event.set()
        return True

    # --- scheduling -------------------------------------------------------

    def _enqueue_locked(self, job_id: str, tenant: str) -> None:
        queue = self._queues.get(tenant)
        if queue is None:
            queue = self._queues[tenant] = deque()
        if tenant not in self._ring:
            self._ring.append(tenant)
        queue.append(job_id)

    def _spawn_workers_locked(self) -> None:
        # Lazily, and never more than the target: dead threads are not
        # replaced mid-flight because a worker only dies with the process
        # (its loop catches everything), so pruning is bookkeeping, not
        # recovery.
        self._threads = [t for t in self._threads if t.is_alive()]
        while len(self._threads) < self._target:
            t = threading.Thread(target=self._worker, daemon=True)
            self._threads.append(t)
            t.start()

    def _next_locked(self) -> str | None:
        """Round-robin: head job of the next non-empty tenant, that tenant to
        the back of the ring. An emptied tenant leaves the ring (and its
        deque is dropped) so an idle library costs nothing to skip."""
        for _ in range(len(self._ring)):
            tenant = self._ring.popleft()
            queue = self._queues.get(tenant)
            if not queue:
                del self._queues[tenant]
                continue
            job_id = queue.popleft()
            if queue:
                self._ring.append(tenant)
            else:
                del self._queues[tenant]
            return job_id
        return None

    def _worker(self) -> None:
        while True:
            with self._wake:
                job_id = self._next_locked()
                while job_id is None:
                    self._wake.wait()
                    job_id = self._next_locked()
                job = self._jobs[job_id]
            with job.lock:
                job.picked_up = True
                # Leave a stale "queued" behind the moment a worker has it;
                # fn's own first report overwrites this again.
                if job.progress == _QUEUED_PROGRESS:
                    job.progress = None
            try:
                job.fn(_Handle(job))
            except Exception as exc:
                with self._wake:
                    with job.lock:
                        if job.retries_left > 0 and not job.stop_event.is_set():
                            job.retries_left -= 1
                            job.progress = dict(_QUEUED_PROGRESS)
                            self._enqueue_locked(job_id, job.tenant)
                            self._wake.notify()
                            continue
                        job.state = "failed"
                        job.error = str(exc)
                continue
            with job.lock:
                if job.state == "running":
                    job.state = ("stopped" if job.stop_event.is_set()
                                 else "done")
