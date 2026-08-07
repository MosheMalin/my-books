# -*- coding: utf-8 -*-
"""Thread-based JobRunner (P2.4).

Every mutable bit lives on ``self``, keyed by ``job_id`` — explicitly NOT
``booksnap/server.py``'s module-level ``_job``/``_stop_event`` pair (H2,
§1.3: that shape is exactly what a second tenant breaks). Building two
``InProcessJobRunner()``s (as the API tests do, one per app) never shares
state between them; ``tests/test_api.py``'s
``test_no_module_level_mutable_state_in_api`` is the meta-test that would
catch a regression back to a module dict.

Single-process, single-user by design (plan P2.4): one Python process, one
daemon thread per running job, no cross-process coordination. P3.4 swaps this
for a real queue when two tenants can press "read" at once; ``JobRunner`` is
the seam that makes it a swap.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from app.ports.jobs import JobHandle, JobStatus


@dataclass
class _Job:
    lock: threading.Lock = field(default_factory=threading.Lock)
    stop_event: threading.Event = field(default_factory=threading.Event)
    state: str = "running"
    progress: dict | None = None
    error: str | None = None
    thread: threading.Thread | None = None


class _Handle:
    """Implements ``app.ports.jobs.JobHandle`` for one running job."""

    def __init__(self, job: _Job) -> None:
        self._job = job

    def should_stop(self) -> bool:
        return self._job.stop_event.is_set()

    def report_progress(self, progress: dict) -> None:
        with self._job.lock:
            self._job.progress = progress


class InProcessJobRunner:
    """Implements ``app.ports.jobs.JobRunner``."""

    def __init__(self) -> None:
        # Instance state, never module state (H2/§1.3) — this dict dies with
        # the object.
        self._jobs: dict[str, _Job] = {}
        self._guard = threading.Lock()

    def submit(self, job_id: str, fn: Callable[[JobHandle], None]) -> None:
        job = _Job()
        with self._guard:
            self._jobs[job_id] = job
        handle = _Handle(job)

        def body() -> None:
            try:
                fn(handle)
            except Exception as exc:
                with job.lock:
                    job.state = "failed"
                    job.error = str(exc)
                return
            with job.lock:
                if job.state == "running":
                    job.state = "stopped" if job.stop_event.is_set() else "done"

        job.thread = threading.Thread(target=body, daemon=True)
        job.thread.start()

    def status(self, job_id: str) -> JobStatus | None:
        with self._guard:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        with job.lock:
            return JobStatus(state=job.state, progress=job.progress, error=job.error)

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
