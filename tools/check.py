# -*- coding: utf-8 -*-
"""Run the commit gate's checks CONCURRENTLY, and report all of them.

The gate is four independent things — the python rings, the API contract, the
client rings, the client typecheck — plus the accuracy half. Run one after
another they add up to a minute even after each was made fast; run together
they cost about as long as the slowest. Nothing here shares state, so there
was never a reason to queue them behind each other.

Two properties that matter more than the speed:

  - **every check runs, even after one fails.** A gate that stops at the first
    red hides the other three, so a fix-and-rerun cycle discovers them one at a
    time. Failures are collected and printed together, in the order declared;
  - **output is captured per check and replayed whole.** Four processes writing
    to one terminal interleave into something nobody can read.

Usage::

    python tools/check.py                # everything that applies to the repo
    python tools/check.py --product      # the python rings + the API contract
    python tools/check.py --web          # the client rings + typecheck
    python tools/check.py --accuracy     # the sweep + the spotchecks
    python tools/check.py --serial       # one at a time (for a clean log)

Exit code is non-zero if any check failed — that is what the hook blocks on.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB = REPO_ROOT / "app" / "web"


@dataclass
class Check:
    name: str
    argv: list[str]
    cwd: Path
    # How many cores this check will use once it is running. ⚠ Load-bearing:
    # the first version of this file ran all eight at once and every one of
    # them got SLOWER — the python rings went from 19s to 52s — because two of
    # them fan out internally. Admitting checks against a core budget measured
    # 36s where the free-for-all measured 52s.
    cores: int = 1
    # A check that cannot run on this machine is SKIPPED, never failed — the
    # same rule the spotchecks and the client half already follow. A gate that
    # blocks on a missing toolchain is a gate people disable.
    needs: Path | None = None


def _python() -> str:
    return sys.executable or "python"


def _npm() -> str | None:
    return shutil.which("npm") or shutil.which("npm.cmd")


def _checks(product: bool, web: bool, accuracy: bool) -> list[Check]:
    # Declared slowest-first: the scheduler admits in this order, and a long
    # check drawn last is exactly how a pool ends with idle cores.
    out: list[Check] = []
    if web and _npm():
        out.append(Check("client rings", [_npm(), "run", "test", "--silent"],
                         WEB, cores=2, needs=WEB / "node_modules"))
    if product:
        out.append(Check("python rings", [_python(), "tests/run_all.py", "-j2"],
                         REPO_ROOT, cores=2))
    if web and _npm():
        out.append(Check("client typecheck",
                         [_npm(), "run", "typecheck", "--silent"],
                         WEB, needs=WEB / "node_modules"))
    if product:
        out.append(Check("api contract",
                         [_python(), "tools/api_contract.py", "--check"],
                         REPO_ROOT))
    if accuracy:
        out.append(Check("accuracy sweep", [_python(), "tools/sweep.py", "--check"],
                         REPO_ROOT))
        for fx in sorted((REPO_ROOT / "fixtures" / "spotchecks").glob("*.json")):
            out.append(Check(f"spotcheck {fx.stem}",
                             [_python(), "tools/spotcheck.py", fx.stem],
                             REPO_ROOT))
    return out


def _run(check: Check) -> tuple[Check, int, str, float]:
    if check.needs is not None and not check.needs.exists():
        return check, 0, f"skipped: {check.needs} is missing\n", 0.0
    t0 = time.perf_counter()
    proc = subprocess.run(check.argv, cwd=str(check.cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return (check, proc.returncode, (proc.stdout or "") + (proc.stderr or ""),
            time.perf_counter() - t0)


def _run_within_budget(checks: list[Check]) -> list[tuple[Check, int, str, float]]:
    """Run checks concurrently, never more than the machine's cores at once.

    Threads, not processes: each one only waits on a subprocess. A check is
    admitted when its declared `cores` fit in what is left, and a check wider
    than the whole machine still runs (alone) rather than deadlocking.
    """
    # ⚠ Cores PLUS TWO, measured. A strict core budget leaves the machine idle
    # whenever a check is waiting on npm's or python's startup I/O rather than
    # computing, and it queues the six short checks behind the two wide ones:
    # 47s at exactly-cores, 44s at cores+2, 46s at cores+4. Enough slack to
    # cover the waiting, not enough to thrash.
    budget = max(1, os.cpu_count() or 1) + 2
    free = budget
    lock = threading.Lock()
    space = threading.Condition(lock)
    results: list[tuple[Check, int, str, float]] = [None] * len(checks)  # type: ignore

    def worker(index: int, check: Check) -> None:
        want = min(check.cores, budget)
        with space:
            while free < want:
                space.wait()
            _take(want)
        try:
            results[index] = _run(check)
        finally:
            with space:
                _give(want)
                space.notify_all()

    def _take(n: int) -> None:
        nonlocal free
        free -= n

    def _give(n: int) -> None:
        nonlocal free
        free += n

    with ThreadPoolExecutor(max_workers=len(checks)) as pool:
        for i, c in enumerate(checks):
            pool.submit(worker, i, c)
    return results


def main(argv: list[str]) -> int:
    serial = "--serial" in argv
    picked = {a for a in argv if a in ("--product", "--web", "--accuracy")}
    if not picked:
        picked = {"--product", "--web", "--accuracy"}

    checks = _checks("--product" in picked, "--web" in picked,
                     "--accuracy" in picked)
    if not checks:
        print("nothing to check")
        return 0

    started = time.perf_counter()
    if serial:
        results = [_run(c) for c in checks]
    else:
        results = _run_within_budget(checks)

    failed = [(c, out) for c, rc, out, _ in results if rc != 0]
    print()
    for c, rc, out, secs in results:
        mark = "FAIL" if rc else "ok  "
        note = "  (skipped)" if out.startswith("skipped:") else ""
        print(f"{mark}  {c.name:<22} {secs:5.1f}s{note}")

    for c, out in failed:
        print(f"\n{'=' * 60}\nFAILED: {c.name}   ({' '.join(c.argv)})\n{'=' * 60}")
        print(out.rstrip())

    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed "
          f"in {time.perf_counter() - started:.1f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    os.chdir(REPO_ROOT)
    raise SystemExit(main(sys.argv[1:]))
