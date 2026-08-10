# -*- coding: utf-8 -*-
"""Runner for the staff-service suite, with a real exit code.

The same reasoning as `tests/run_all.py`: a `unittest.main()` in a `__main__`
block prints PASS/FAIL and is useless as a gate. Separate from that runner
only because this build could not touch `tests/` — see the suite's own
docstring. Fold both together when it can.

    python tests_staff/run.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def main() -> int:
    suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
