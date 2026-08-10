# -*- coding: utf-8 -*-
"""Run the commit gate's checks CONCURRENTLY, and report all of them.

The gate is a set of independent things — per APPLICATION, which is the shape
that matters now that there are two clients and two services:

    --product   the household's server: the python rings + both API contracts
    --web       the household's client: its ring + its typecheck
    --admin     the operator's console: its ring + its typecheck. Its SERVICE
                (`app/staff_api/`) is tested by `tests/test_staff_api.py`,
                which rides in the python rings — see the note in `_checks`
    --ui        the shared client library: its own ring + typecheck
    --accuracy  the recognition core: the sweep + the spotchecks

⚠ ``--ui`` is not self-sufficient and is not meant to be. A change to the
shared library is a change to BOTH clients, and only their rings can prove it
— so the pre-commit hook, seeing anything staged under ``app/ui/``, asks for
``--web`` and ``--admin`` too. The shared ring proves the SHARED rules (the
sort control's reset, the status ladder, the token contract); it cannot prove
that a screen still renders.

Run one after another they add up to minutes even after each was made fast;
run together they cost about as long as the slowest. Nothing here shares
state, so there was never a reason to queue them behind each other.

Two properties that matter more than the speed:

  - **every check runs, even after one fails.** A gate that stops at the first
    red hides the other three, so a fix-and-rerun cycle discovers them one at a
    time. Failures are collected and printed together, in the order declared;
  - **output is captured per check and replayed whole.** Four processes writing
    to one terminal interleave into something nobody can read.

Usage::

    python tools/check.py                # everything that applies to the repo
    python tools/check.py --product      # the python rings + the API contracts
    python tools/check.py --web          # the product client's ring + typecheck
    python tools/check.py --admin        # the console's ring + typecheck
    python tools/check.py --ui           # the shared client library
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
ADMIN = REPO_ROOT / "app" / "admin"
UI = REPO_ROOT / "app" / "ui"


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


def _client(name: str, where: Path, npm: str) -> list[Check]:
    """One client package's two checks — the ring and the typecheck.

    Both self-skip without `node_modules`, the rule the whole gate follows: a
    check that cannot run on this machine is SKIPPED, never failed, or it
    becomes a gate people disable.
    """
    return [
        Check(f"{name} ring", [npm, "run", "test", "--silent"],
              where, cores=2, needs=where / "node_modules"),
        Check(f"{name} typecheck", [npm, "run", "typecheck", "--silent"],
              where, needs=where / "node_modules"),
    ]


def _checks(product: bool, web: bool, admin: bool, ui: bool,
            accuracy: bool) -> list[Check]:
    # Declared slowest-first: the scheduler admits in this order, and a long
    # check drawn last is exactly how a pool ends with idle cores.
    out: list[Check] = []
    npm = _npm()
    rings, typechecks = [], []
    if npm:
        for wanted, name, where in ((web, "web", WEB),
                                    (admin, "admin", ADMIN),
                                    (ui, "ui", UI)):
            if wanted:
                ring, typecheck = _client(name, where, npm)
                rings.append(ring)
                typechecks.append(typecheck)
    out += rings
    if product:
        out.append(Check("python rings", [_python(), "tests/run_all.py", "-j2"],
                         REPO_ROOT, cores=2))
    # ⚠ There is no separate staff-service check, and that is a SETTLED answer
    # rather than an omission. `tests/test_staff_api.py` rides in the python
    # rings above, so it runs on `--product`.
    #
    # Two sessions reached that from opposite directions and it is worth
    # recording. One folded the suite into `tests/` for the runner's sake (a
    # `unittest.TestCase` module is collected as ZERO tests by `run_all.py` and
    # still reports `ok`). The other kept it separate — the operator's tests
    # apart from the household's — and a data-integrity review then found the
    # hole that created: the staff read model duplicates the product's SCHEMA
    # on purpose, so the change that breaks it is a MIGRATION, made on the
    # product side, which never ran the console's gate. It was reproduced by
    # renaming `books.sort_author`: product ring green, console dead at startup
    # with `SchemaMismatch`.
    #
    # Ownership and dependency point in opposite directions. The suite belongs
    # to the console; what it DEPENDS on is the product's schema and domain.
    # Running it with the product is what makes the dependency the thing that
    # decides.
    out += typechecks
    if product:
        out.append(Check("api contracts",
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
    ALL = ("--product", "--web", "--admin", "--ui", "--accuracy")
    unknown = [a for a in argv if a.startswith("--") and a not in ALL + ("--serial",)]
    if unknown:
        # ⚠ An unrecognised flag used to be IGNORED, which meant a typo
        # (`--acuracy`) silently ran the whole gate and read as a pass of the
        # thing you asked for. Refuse instead.
        print(f"unknown option(s): {' '.join(unknown)}\nknown: {' '.join(ALL)}")
        return 2
    picked = {a for a in argv if a in ALL}
    if not picked:
        picked = set(ALL)

    checks = _checks("--product" in picked, "--web" in picked,
                     "--admin" in picked, "--ui" in picked,
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
