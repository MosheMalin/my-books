# -*- coding: utf-8 -*-
"""Discover and run every ``tests/test_*.py`` module, with a real exit code.

Why this exists: the original suites are self-running scripts whose
``__main__`` block prints PASS/FAIL and then exits 0 regardless. That is fine
when a human is reading the output and useless as a commit gate. This runner
imports each module, calls every ``test_*`` function, and **exits non-zero if
anything failed** — which is what lets the pre-commit hook block on a red test.

No pytest dependency on purpose: the repo has never had one, and the accuracy
gate already runs on bare python.

**It runs in parallel across processes.** Serially the suite took 80s, which is
long enough that people stop running it before committing — and a gate nobody
waits for is not a gate. A job is a *shard* of one module: the worker imports
the module, enumerates its tests itself, and runs every n-th one.

⚠ **Discovery happens in the worker, never in the parent, and never from the
source text.** The obvious plan — parse the files, hand each worker a list of
names — is wrong twice over. It costs 12s of serial imports before the first
test runs, and `test_store_contract.py` *generates* 192 of its 202 tests at
import time (one spec × every implementation), so an AST walk finds 10 and the
other 192 vanish without a word. Sharding by stride over the module's own
``vars()`` keeps the discovery rule identical to the serial path, and the
parent still checks that every shard of a module agreed on the total and that
the shards between them ran all of it.

⚠ Processes, never threads, and every test in a worker runs SEQUENTIALLY.
Several tests here mutate process-wide state and restore it —
``test_reader_wiring`` swaps ``BOOKSNAP_CATALOG_BACKEND``, ``test_api`` pops
Google/NLI credentials out of ``os.environ`` — which is safe against another
*process* and silently wrong against another thread in the same one. The same
constraint is what makes ``tests/_fastclient.py``'s shared event-loop portal
safe. Do not "improve" this into a thread pool.

Per-test durations are remembered in ``tests/.durations.json`` (gitignored)
purely to decide how finely to shard each module and in what order. A missing
or stale file costs a little balance, never correctness.

Usage::

    python tests/run_all.py                 # everything, in parallel
    python tests/run_all.py test_layering   # one module (name or path)
    python tests/run_all.py -j 1            # serial (also: --serial)
    python tests/run_all.py -v              # per-test PASS lines
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(TESTS_DIR))

DURATIONS = TESTS_DIR / ".durations.json"
# A module's import cost is recorded under this pseudo-test name. Not a legal
# python identifier, so it can never collide with a real one.
IMPORT_KEY = "<import>"

# Shards to aim for per worker. More shards balance better (a worker that draws
# a fast one comes back for another) and cost more module imports, since a
# worker pays an import once per module it happens to be handed. 3 measured
# best on a 4-core box; it is not a delicate number.
SHARDS_PER_WORKER = 3

_LOADED: dict[str, object] = {}


def _load(path: Path):
    """Import a test module, once per process."""
    key = str(path)
    if key not in _LOADED:
        spec = importlib.util.spec_from_file_location(f"_tests_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        # Registered before exec so dataclasses/typing lookups inside resolve.
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _LOADED[key] = module
    return _LOADED[key]


def _test_names(module) -> list[str]:
    """The discovery rule, in one place. Same list, serial or parallel."""
    return [k for k, v in sorted(vars(module).items())
            if k.startswith("test_") and callable(v)]


# --- the unit of work ------------------------------------------------------

def run_shard(job: tuple[str, int, int]) -> dict:
    """Run every ``shard``-th test of one module. Returns a plain-dict result.

    Everything the parent needs to print is in the return value — including the
    module's captured stdout — because a worker's own stdout would interleave
    with three others' into noise. Captured output is reported only when
    something failed, which is the only time anyone wants it.
    """
    path_str, shard, shards = job
    path = Path(path_str)
    started = time.perf_counter()
    buf = io.StringIO()

    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            t_import = time.perf_counter()
            module = _load(path)
            t_import = time.perf_counter() - t_import
    except BaseException:
        return {
            "module": path.name, "shard": shard, "total": None, "import": 0.0,
            "passed": 0, "failed": 1,
            "failures": [(f"<import {path.name}>", traceback.format_exc())],
            "tests": [], "output": buf.getvalue(),
            "seconds": time.perf_counter() - started,
        }

    names = _test_names(module)
    mine = names[shard::shards]
    # Optional per-module teardown. A module defines `after_each()` when it has
    # something to reclaim between tests — `test_api` recycles the FastAPI apps
    # a test built, which it cannot do from the client's `__exit__` because
    # plenty of tests never open one as a context manager. A failure here is
    # reported as a failure, never swallowed: silent teardown is how one test's
    # leftovers become another test's mystery.
    after_each = getattr(module, "after_each", None)

    passed = 0
    failures: list[tuple[str, str]] = []
    results: list[tuple[str, float, str | None]] = []
    for name in mine:
        fn = getattr(module, name)
        t0 = time.perf_counter()
        try:
            with redirect_stdout(buf), redirect_stderr(buf):
                fn()
                if after_each is not None:
                    after_each()
        except BaseException:                # AssertionError and anything else
            failures.append((name, traceback.format_exc()))
            results.append((name, time.perf_counter() - t0, "fail"))
        else:
            passed += 1
            results.append((name, time.perf_counter() - t0, None))

    return {
        "module": path.name, "shard": shard, "total": len(names),
        "import": t_import,
        "passed": passed, "failed": len(failures), "failures": failures,
        "tests": results, "output": buf.getvalue(),
        "seconds": time.perf_counter() - started,
    }


# --- scheduling ------------------------------------------------------------

def _load_durations() -> dict[str, float]:
    try:
        return json.loads(DURATIONS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_durations(times: dict[str, float]) -> None:
    try:
        DURATIONS.write_text(json.dumps(times, indent=0, sort_keys=True),
                             encoding="utf-8")
    except OSError:
        pass                                     # a cache, never a requirement


def _plan(paths: list[Path], workers: int) -> list[tuple[str, int, int]]:
    """Decide how many shards each module gets, heaviest module first.

    Weights come from the last full run. With no cache every module gets
    ``workers`` shards — still parallel, just less well packed — so a fresh
    clone is fast on its first run and optimal on its second.

    ⚠ Two ceilings stop a module being split past the point where it pays,
    and both were measured rather than guessed:

      - **a shard re-imports the module.** ``test_integrations`` costs 4.1s, of
        which 4.0s is one test that pulls in scipy + cv2; split in two, both
        halves imported the CV stack and the module went from 4.1s to 7.7s.
        A module is only split while each shard would still be doing more work
        than the import it repays.
      - **a shard cannot be smaller than one test.** Splitting five ways a
        module whose cost is a single 4s case just adds four empty processes.
    """
    known = _load_durations()
    per_module: dict[str, float] = {}
    imports: dict[str, float] = {}
    slowest: dict[str, float] = {}
    for key, secs in known.items():
        mod, _, test = key.partition("::")
        if test == IMPORT_KEY:
            imports[mod] = secs
            continue
        per_module[mod] = per_module.get(mod, 0.0) + secs
        slowest[mod] = max(slowest.get(mod, 0.0), secs)

    budget = workers * SHARDS_PER_WORKER
    weights = {p: per_module.get(p.name, 0.0) for p in paths}
    total = sum(weights.values())

    plan: list[tuple[float, str, int]] = []
    for p in paths:
        w = weights[p]
        if total > 0:
            n = round(budget * w / total)
            imp = imports.get(p.name, 0.0)
            if imp > 0:
                n = min(n, int(w // imp) or 1)   # each shard out-earns its import
            top = slowest.get(p.name, 0.0)
            if top > 0:
                n = min(n, int(-(-w // top)))    # never more shards than tests-worth
        else:
            n = workers
        plan.append((w, str(p), max(1, min(n, budget))))

    # Heaviest module's shards dispatched first: a long job drawn last is
    # exactly how a pool finishes with three idle workers. Keeping a module's
    # shards adjacent also gives rough worker affinity, so a heavy import is
    # more often reused than repaid.
    plan.sort(reverse=True, key=lambda x: x[0])
    return [(path, i, n) for _, path, n in plan for i in range(n)]


# --- reporting -------------------------------------------------------------

def _report(results: list[dict], verbose: bool) -> tuple[int, int]:
    by_module: dict[str, dict] = {}
    for r in results:
        m = by_module.setdefault(
            r["module"], {"passed": 0, "failed": 0, "failures": [],
                          "output": [], "tests": [], "totals": set()})
        m["passed"] += r["passed"]
        m["failed"] += r["failed"]
        m["failures"] += r["failures"]
        m["tests"] += r["tests"]
        if r["total"] is not None:
            m["totals"].add(r["total"])
        if r["output"]:
            m["output"].append(r["output"])

    total_pass = total_fail = 0
    for name in sorted(by_module):
        m = by_module[name]
        ran = m["passed"] + m["failed"]
        # The guard that makes worker-side discovery trustworthy: every shard
        # saw the same module and, between them, they ran all of it. A silent
        # shortfall here would look exactly like a smaller suite passing.
        if len(m["totals"]) > 1:
            m["failed"] += 1
            m["failures"].append(
                ("<sharding>", f"shards disagreed on the test count: "
                               f"{sorted(m['totals'])}"))
        elif m["totals"] and ran != next(iter(m["totals"])):
            missing = next(iter(m["totals"])) - ran
            m["failed"] += 1
            m["failures"].append(
                ("<sharding>", f"{missing} test(s) of {name} were never run"))

        total_pass += m["passed"]
        total_fail += m["failed"]
        mark = "FAIL" if m["failed"] else "ok  "
        print(f"{mark}  {name:<28} {m['passed']}/{m['passed'] + m['failed']} passed")
        if verbose:
            for tname, secs, bad in sorted(m["tests"]):
                print(f"        {'FAIL' if bad else 'PASS'}  {tname} "
                      f"({secs * 1000:.0f}ms)")
        if m["failed"]:
            # Only a failing module's captured output is worth reading.
            for chunk_out in m["output"]:
                if chunk_out.strip():
                    print("  --- captured output ---")
                    for line in chunk_out.rstrip().splitlines():
                        print(f"  | {line}")
            for tname, tb in m["failures"]:
                print(f"\n  FAIL  {name}::{tname}")
                for line in tb.rstrip().splitlines():
                    print(f"      {line}")
    return total_pass, total_fail


# --- entry point -----------------------------------------------------------

def main(argv: list[str]) -> int:
    verbose = False
    workers = min(os.cpu_count() or 1, 8)
    names: list[str] = []

    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-v", "--verbose"):
            verbose = True
        elif a == "--serial":
            workers = 1
        elif a == "-j":
            i += 1
            workers = max(1, int(argv[i]))
        elif a.startswith("-j"):
            workers = max(1, int(a[2:]))
        else:
            names.append(a)
        i += 1

    if names:
        paths = []
        for name in names:
            p = Path(name)
            if not p.exists():
                p = TESTS_DIR / (name if name.endswith(".py") else f"{name}.py")
            if not p.exists():
                print(f"no such test module: {name}")
                return 2
            paths.append(p)
    else:
        paths = sorted(TESTS_DIR.glob("test_*.py"))

    started = time.perf_counter()

    if workers == 1:
        results = [run_shard((str(p), 0, 1)) for p in paths]
    else:
        jobs = _plan(paths, workers)
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            results = list(pool.map(run_shard, jobs, chunksize=1))

    elapsed = time.perf_counter() - started
    total_pass, total_fail = _report(results, verbose)

    # Remember what each test cost, for the next run's balancing.
    if not names:                            # only a full run sees everything
        times = {f"{r['module']}::{n}": round(s, 4)
                 for r in results for n, s, _ in r["tests"]}
        # The cheapest shard's import is the least contended, so it is the
        # honest measure of what an import costs a worker.
        for r in results:
            key = f"{r['module']}::{IMPORT_KEY}"
            cost = round(r.get("import", 0.0), 4)
            if cost and cost < times.get(key, float("inf")):
                times[key] = cost
        if times:
            _save_durations(times)

    print(f"\n{'=' * 40}")
    print(f"TOTAL: {total_pass} passed, {total_fail} failed "
          f"({len(paths)} modules) in {elapsed:.1f}s "
          f"on {workers} worker{'s' if workers != 1 else ''}")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
