# -*- coding: utf-8 -*-
"""Discover and run every ``tests/test_*.py`` module, with a real exit code.

Why this exists: the original suites are self-running scripts whose
``__main__`` block prints PASS/FAIL and then exits 0 regardless. That is fine
when a human is reading the output and useless as a commit gate. This runner
imports each module, calls every ``test_*`` function, and **exits non-zero on
the first failure count above zero** — which is what lets the pre-commit hook
block on a red test.

No pytest dependency on purpose: the repo has never had one, and the accuracy
gate already runs on bare python.

Usage::

    python tests/run_all.py                 # everything
    python tests/run_all.py test_layering   # one module (name or path)
"""
from __future__ import annotations

import importlib.util
import sys
import traceback
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"_tests_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    # Registered before exec so dataclasses/typing lookups inside resolve.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_module(path: Path) -> tuple[int, int]:
    """Run one test module. Returns (passed, failed)."""
    print(f"\n=== {path.name} ===")
    try:
        module = _load(path)
    except Exception:
        print(f"  ERROR  could not import {path.name}")
        traceback.print_exc()
        return 0, 1

    fns = [v for k, v in sorted(vars(module).items())
           if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in fns:
        try:
            fn()
        except Exception as exc:  # AssertionError and anything else
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            passed += 1
            print(f"  PASS  {fn.__name__}")
    print(f"  {passed}/{passed + failed} passed")
    return passed, failed


def main(argv: list[str]) -> int:
    if argv:
        paths = []
        for name in argv:
            p = Path(name)
            if not p.exists():
                p = TESTS_DIR / (name if name.endswith(".py") else f"{name}.py")
            if not p.exists():
                print(f"no such test module: {name}")
                return 2
            paths.append(p)
    else:
        paths = sorted(TESTS_DIR.glob("test_*.py"))

    total_pass = total_fail = 0
    for p in paths:
        ok, bad = run_module(p)
        total_pass += ok
        total_fail += bad

    print(f"\n{'=' * 40}")
    print(f"TOTAL: {total_pass} passed, {total_fail} failed "
          f"({len(paths)} modules)")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
