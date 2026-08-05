# -*- coding: utf-8 -*-
"""Re-match a stored run with the CURRENT matcher and score it.

    python tools/rescore.py <run_no> [<run_no> ...]

OCR is the expensive stage (~10s/spine) but it is also *pure input* to
matching: changing match.py cannot change what Tesseract or Vision read. So
tuning the matcher never needs a re-run — replay the stored per-spine OCR text
through the current code and score against ground_truth.json. Seconds instead
of minutes, and the OCR is held identical so the comparison is controlled.

Catalog lookups are cached on disk (work/nli_cache), so repeated sweeps are
also cheap and hit NLI only for queries never seen before.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent
for line in (REPO / ".env").read_text(encoding="utf-8").splitlines() \
        if (REPO / ".env").exists() else []:
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from booksnap.config import CONFIG                      # noqa: E402
from booksnap.types import OcrResult                    # noqa: E402
from booksnap.match import (candidates_for_spine, resolve_assignment,  # noqa: E402
                            match_spine, resolve_duplicates)
from booksnap.scoring import load_ground_truth, score_predictions  # noqa: E402

STORE = CONFIG.paths.work_dir / "store.json"


def _catalog():
    backend = os.environ.get("BOOKSNAP_CATALOG_BACKEND", "nli").lower()
    if backend == "nli":
        from booksnap.nli_catalog import NLICatalog
        return NLICatalog(cache_dir=CONFIG.paths.work_dir / "nli_cache")
    from booksnap.catalog import LocalCatalog
    return LocalCatalog.from_json(REPO / "sample_catalog.json")


def rescore(run_no: int, catalog, gt) -> None:
    store = json.loads(STORE.read_text(encoding="utf-8"))
    run = next((r for r in store["runs"].values() if r["run_no"] == run_no), None)
    if not run:
        print(f"run #{run_no}: not found")
        return
    runs_dir = CONFIG.paths.work_dir / "runs" / run["run_id"]

    for img_id in run.get("images", {}):
        name = (store["images"].get(img_id) or {}).get("name") or ""
        truth = gt.get(name)
        if truth is None:
            print(f"run #{run_no} {name}: no ground truth, skipped")
            continue
        recs = json.loads((runs_dir / f"{img_id}.json").read_text(encoding="utf-8"))
        ocrs = [OcrResult(spine_id=r["spine_id"],
                          text=(r.get("ocr") or {}).get("text", ""),
                          lines=(r.get("ocr") or {}).get("lines", []) or [])
                for r in recs]

        for label, use_assign in (("per-spine (old)", False), ("assignment", True)):
            if use_assign:
                matches = resolve_assignment(
                    [candidates_for_spine(o, catalog) for o in ocrs])
            else:
                matches = resolve_duplicates([match_spine(o, catalog) for o in ocrs])
            for tiers, tname in (({"AUTO", "REVIEW"}, "auto+review"), ({"AUTO"}, "auto")):
                preds = [{"title": m.title, "author": m.author, "score": m.score}
                         for m in matches if m and m.tier in tiers]
                s = score_predictions(preds, truth, image=name)
                print(f"  run#{run_no} {name:16} {label:16} {tname:11} "
                      f"P {s.precision:.2f}  R {s.recall:.2f}  F1 {s.f1:.2f}  "
                      f"({len(s.tp)} ok / {len(s.fp)} phantom / {len(s.fn)} missed)")
            if use_assign:
                phantom = [m.title for m in matches if m and m.tier in ("AUTO", "REVIEW")]
                s = score_predictions([{"title": t} for t in phantom], truth, name)
                if s.fp:
                    print(f"      phantoms: {', '.join(s.fp[:10])}")


def main(argv):
    if not argv:
        print(__doc__)
        return
    catalog, gt = _catalog(), load_ground_truth()
    for a in argv:
        rescore(int(a), catalog, gt)


if __name__ == "__main__":
    main(sys.argv[1:])
