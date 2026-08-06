# -*- coding: utf-8 -*-
"""Replay owner-flagged spines through the current match rules.

`fixtures/spotchecks/<name>.json` encodes review feedback the owner gave on a
specific run — wrong books, missing books, must-stay-ambiguous books — as
checkable expectations against that run's STORED reads and candidates
recording. Where fixtures/ground_truth.json labels whole shelves, a spotcheck file
labels only the flagged spines, so feedback on unlabelled shelves still
becomes a permanent, re-runnable measurement instead of a one-off fix.

    python tools/spotcheck.py run16          # replay + verdicts
    python tools/spotcheck.py run16 --diff   # also list every spine whose
                                             # match changed vs the stored run

Fully offline (ReplayCatalog over the run's recording); complements, never
replaces, tools/sweep.py — a rule change must pass BOTH the GT sweep and the
spotchecks.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from booksnap.config import CONFIG                                 # noqa: E402
from booksnap.replay import ReplayCatalog                          # noqa: E402
from booksnap.types import OcrResult                               # noqa: E402

sys.path.insert(0, str(REPO / "tools"))
from sweep import match_shelf                                      # noqa: E402

WORK = CONFIG.paths.work_dir
FIXDIR = REPO / "fixtures" / "spotchecks"


def load_shelf(run_id: str, image_id: str):
    rd = WORK / "runs" / run_id
    rows = json.loads((rd / f"{image_id}.json").read_text(encoding="utf-8"))
    ocrs = [OcrResult(spine_id=r["spine_id"],
                      text=(r.get("ocr") or {}).get("text", ""),
                      lines=(r.get("ocr") or {}).get("lines") or [])
            for r in rows]
    stored = [(r["spine_id"], r.get("match")) for r in rows]
    catalog = ReplayCatalog.from_file(rd / "candidates" / f"{image_id}.json")
    return ocrs, stored, catalog


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", help="spotcheck fixture name, e.g. run16")
    ap.add_argument("--diff", action="store_true",
                    help="list every spine whose match differs from the stored run")
    args = ap.parse_args()

    fx = json.loads((FIXDIR / f"{args.name}.json").read_text(encoding="utf-8"))
    run_id = fx["run"]
    if not (WORK / "runs" / run_id).exists():
        # fresh clone / another machine: the run's reads+recording aren't
        # committed, so there is nothing to measure — skip, don't block
        print(f"spotcheck {args.name}: skipped (run {run_id} not on this machine)")
        return
    passed = failed = 0

    for shelf, spec in fx["shelves"].items():
        ocrs, stored, catalog = load_shelf(run_id, spec["image_id"])
        matches = match_shelf(ocrs, catalog)
        claimed = {m.catalog_id: m for m in matches if m}
        print(f"== {shelf} ({len(ocrs)} reads, "
              f"{sum(1 for m in matches if m)} matched, "
              f"{len(catalog.misses)} unrecorded queries)")

        for chk in spec["checks"]:
            ok, detail = True, []
            for cid in chk.get("forbid", []):
                if cid in claimed:
                    m = claimed[cid]
                    ok = False
                    detail.append(f"claimed {m.tier} {m.title!r} ({cid})")
            want = chk.get("want", [])
            if want and not any(cid in claimed for cid in want):
                ok = False
                detail.append(f"none of {want} claimed")
            for cid in chk.get("not_auto", []):
                if cid in claimed and claimed[cid].tier == "AUTO":
                    ok = False
                    detail.append(f"{claimed[cid].title!r} is AUTO ({cid})")
            mark = "PASS" if ok else "FAIL"
            passed += ok
            failed += not ok
            print(f"  {mark}  {chk['name']}" + ("" if ok else f"  -- {'; '.join(detail)}"))

        if args.diff:
            for (sid, old), new in zip(stored, matches):
                old_id = (old or {}).get("catalog_id")
                old_tier = (old or {}).get("tier")
                new_id = new.catalog_id if new else None
                new_tier = new.tier if new else None
                if (old_id, old_tier) != (new_id, new_tier):
                    o = f"{old_tier} {(old or {}).get('title')!r}" if old else "unmatched"
                    n = f"{new_tier} {new.title!r}" if new else "unmatched"
                    print(f"  diff {sid}: {o} -> {n}")

    print(f"\nspotcheck {args.name}: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
