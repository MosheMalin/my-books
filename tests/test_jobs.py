# -*- coding: utf-8 -*-
"""P3.4 — the queued job runner's own contract.

Not a store, so it is not in ``test_store_contract``'s spec×implementations
grid; but the same standard applies — every test here pins a decision that
could be silently reversed: fairness across tenants, retry as an opt-in
budget, stop-while-queued still settling through the job's own code, and the
bound on concurrency being the worker count rather than the submit count.

All timing is event-gated, never sleep-calibrated: a worker is HELD at a gate
the test controls, so the assertion windows are deterministic and the suite
stays fast on the 4-core machine CLAUDE.md says to distrust for wall-clock.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.queued_jobs import QueuedJobRunner

_TIMEOUT = 5.0


def _wait_for(predicate, what: str, timeout: float = _TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError(f"timed out waiting for {what}")


def _settled(runner: QueuedJobRunner, job_id: str) -> bool:
    s = runner.status(job_id)
    return s is not None and s.state != "running"


def test_two_reads_in_two_libraries_do_not_observe_each_other():
    """The plan's own named test case. Two tenants' jobs run concurrently on
    two workers; each keeps its own progress, and stopping one leaves the
    other running and lets it finish as `done`."""
    runner = QueuedJobRunner(workers=2)
    release = {"a": threading.Event(), "b": threading.Event()}
    started = {"a": threading.Event(), "b": threading.Event()}

    def job(key):
        def run(handle):
            handle.report_progress({"who": key})
            started[key].set()
            _wait_for(lambda: release[key].is_set() or handle.should_stop(),
                      f"release of {key}")
        return run

    runner.submit("job-a", job("a"), tenant="lib-a")
    runner.submit("job-b", job("b"), tenant="lib-b")
    _wait_for(started["a"].is_set, "job-a to start")
    _wait_for(started["b"].is_set, "job-b to start")

    assert runner.status("job-a").progress == {"who": "a"}
    assert runner.status("job-b").progress == {"who": "b"}, \
        "one tenant's progress leaked into the other's job"

    assert runner.stop("job-a") is True
    _wait_for(lambda: _settled(runner, "job-a"), "job-a to settle")
    assert runner.status("job-a").state == "stopped"
    assert runner.status("job-b").state == "running", \
        "stopping one library's read touched the other's"
    release["b"].set()
    _wait_for(lambda: _settled(runner, "job-b"), "job-b to settle")
    assert runner.status("job-b").state == "done"


def test_one_librarys_burst_does_not_starve_anothers_single_read():
    """Round-robin across tenants, FIFO within one: with a single worker held
    at a gate, tenant A's backlog of two more jobs and tenant B's one job
    drain as A, B, A — B waits behind at most one of A's, never the burst."""
    runner = QueuedJobRunner(workers=1)
    gate = threading.Event()
    order: list[str] = []
    lock = threading.Lock()

    def gated(handle):
        _wait_for(gate.is_set, "the gate")

    def record(name):
        def run(handle):
            with lock:
                order.append(name)
        return run

    runner.submit("a1", gated, tenant="lib-a")
    # Everything below queues behind a1 on the one worker.
    runner.submit("a2", record("a2"), tenant="lib-a")
    runner.submit("a3", record("a3"), tenant="lib-a")
    runner.submit("b1", record("b1"), tenant="lib-b")
    gate.set()
    for job in ("a2", "a3", "b1"):
        _wait_for(lambda j=job: _settled(runner, j), f"{job} to settle")
    assert order.index("b1") < order.index("a3"), (
        f"tenant B starved behind tenant A's burst: {order}"
    )


def test_retry_is_an_optin_budget_and_failure_is_terminal_past_it():
    """`retries=N` re-enqueues an escaping exception N times; the default 0
    fails on the first — the reads job RELIES on that default, because a
    runner-level retry there would re-run a paid engine call."""
    runner = QueuedJobRunner(workers=1)
    calls = {"flaky": 0, "broken": 0}

    def flaky(handle):
        calls["flaky"] += 1
        if calls["flaky"] == 1:
            raise RuntimeError("transient")

    def broken(handle):
        calls["broken"] += 1
        raise RuntimeError("permanent")

    runner.submit("flaky", flaky, tenant="t", retries=1)
    _wait_for(lambda: _settled(runner, "flaky"), "flaky to settle")
    assert runner.status("flaky").state == "done"
    assert calls["flaky"] == 2, "the retry never re-ran the callable"

    runner.submit("broken", broken, tenant="t")
    _wait_for(lambda: _settled(runner, "broken"), "broken to settle")
    status = runner.status("broken")
    assert status.state == "failed"
    assert calls["broken"] == 1, "retries must default to zero"
    assert "permanent" in (status.error or "")


def test_stopping_a_queued_job_still_runs_it_with_stop_already_set():
    """The runner never settles a job from the scheduler — the WORK writes its
    own ending (the caller's durable Read is waiting on exactly that). A job
    stopped before any worker took it runs with `should_stop()` already true
    and settles as `stopped` in milliseconds."""
    runner = QueuedJobRunner(workers=1)
    gate = threading.Event()
    saw = {}

    def gated(handle):
        _wait_for(gate.is_set, "the gate")

    def victim(handle):
        saw["stop_at_entry"] = handle.should_stop()

    runner.submit("gate", gated, tenant="t")
    runner.submit("victim", victim, tenant="t")
    assert runner.stop("victim") is True, "a queued job must be stoppable"
    gate.set()
    _wait_for(lambda: _settled(runner, "victim"), "victim to settle")
    assert saw["stop_at_entry"] is True
    assert runner.status("victim").state == "stopped"


def test_stopping_a_queued_job_acknowledges_immediately_in_progress():
    """The person who pressed stop on a QUEUED job would otherwise watch
    "queued" until a worker frees up — indistinguishable from the tap not
    registering (review finding). The runner says "stopped" on the job's
    behalf the moment stop() is accepted, without waiting for any worker."""
    runner = QueuedJobRunner(workers=1)
    gate = threading.Event()
    runner.submit("gate", lambda h: _wait_for(gate.is_set, "the gate"),
                  tenant="t")
    runner.submit("victim", lambda h: None, tenant="t")
    assert runner.stop("victim") is True
    status = runner.status("victim")     # no worker has touched it yet
    assert status.state == "running"
    assert status.progress == {"stage": "stopped"}, (
        "a stopped-while-queued job kept claiming to be queued"
    )
    gate.set()
    _wait_for(lambda: _settled(runner, "victim"), "victim to settle")


def test_a_settled_job_releases_its_callable():
    """`self._jobs` never evicts, so a retained closure is a leak that grows
    for the process lifetime — each read's closure holds the Read, its
    captures and port references (review finding; the thread-per-job runner
    released it implicitly when the thread died)."""
    import weakref

    class Payload:
        pass

    runner = QueuedJobRunner(workers=1)
    payload = Payload()
    ref = weakref.ref(payload)
    runner.submit("job", lambda h, _p=payload: None, tenant="t")
    _wait_for(lambda: _settled(runner, "job"), "the job")
    del payload
    import gc
    gc.collect()
    assert ref() is None, "a settled job still holds its closure's world"


def test_a_waiting_job_reports_the_queued_stage_not_silence():
    """Progress `{"stage": "queued"}` while no worker has the job — the
    distinction a poller can actually show ("waiting" vs "running, nothing
    reported yet") without a fifth port state every caller would have to
    learn."""
    runner = QueuedJobRunner(workers=1)
    gate = threading.Event()
    runner.submit("gate", lambda h: _wait_for(gate.is_set, "the gate"),
                  tenant="t")
    runner.submit("waiting", lambda h: None, tenant="t")
    status = runner.status("waiting")
    assert status.state == "running"
    assert status.progress == {"stage": "queued"}
    gate.set()
    _wait_for(lambda: _settled(runner, "waiting"), "the waiting job")
    assert runner.status("waiting").progress != {"stage": "queued"}, \
        "a picked-up job still claimed to be queued"


def test_concurrency_is_bounded_by_the_worker_count_not_the_submit_count():
    runner = QueuedJobRunner(workers=2)
    release = threading.Event()
    active = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def job(handle):
        with lock:
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
        _wait_for(release.is_set, "release")
        with lock:
            active["now"] -= 1

    for i in range(5):
        runner.submit(f"j{i}", job, tenant=f"t{i}")
    _wait_for(lambda: active["peak"] >= 2, "two workers to engage")
    # Give a third worker-that-shouldn't-exist a moment to disprove itself.
    time.sleep(0.05)
    assert active["peak"] == 2, f"more jobs ran at once than workers: {active}"
    release.set()
    for i in range(5):
        _wait_for(lambda j=i: _settled(runner, f"j{j}"), f"j{i} to settle")


def test_two_runners_share_nothing():
    """H2/§1.3's instance-state rule, kept from the runner this one replaced:
    a job submitted to one runner is unknown to another."""
    one, two = QueuedJobRunner(workers=1), QueuedJobRunner(workers=1)
    one.submit("job", lambda h: None, tenant="t")
    assert two.status("job") is None
    assert two.stop("job") is False
    _wait_for(lambda: _settled(one, "job"), "the job")


def test_unknown_jobs_answer_none_and_false_never_raise():
    runner = QueuedJobRunner(workers=1)
    assert runner.status("ghost") is None
    assert runner.stop("ghost") is False


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))
