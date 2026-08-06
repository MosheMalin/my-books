# -*- coding: utf-8 -*-
"""E2: mode='llmpage' end-to-end — Claude reads, NLI retrieves, gates verify.

Runs the real pipeline (ClaudePageReader + NLICatalog + matcher) on the
labelled shelves and scores against fixtures/ground_truth.json. Retrieval is recorded
(RecordingCatalog) so the run is replayable later.

Usage: python tools/llmpage_run.py [IMG_6082.jpeg IMG_7849.jpeg]
Needs ANTHROPIC_API_KEY and NLI_API_KEY in .env or the environment.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def load_env() -> None:
    env = REPO / ".env"
    if not env.exists():
        return
    import os
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    load_env()
    from booksnap.config import CONFIG
    from booksnap.llmreader import ClaudePageReader
    from booksnap.nli_catalog import NLICatalog
    from booksnap.pipeline import Pipeline
    from booksnap.replay import RecordingCatalog
    from booksnap.scoring import load_ground_truth, score_predictions

    out_dir = REPO / "work" / "llm_probe"
    out_dir.mkdir(parents=True, exist_ok=True)

    catalog = RecordingCatalog(NLICatalog(cache_dir=CONFIG.paths.work_dir / "nli_cache"))
    reader = ClaudePageReader()
    pipe = Pipeline(catalog=catalog, page_reader=reader,
                    crops_dir=out_dir / "e2_crops")

    gt = load_ground_truth()
    images = sys.argv[1:] or ["IMG_6082.jpeg", "IMG_7849.jpeg"]

    for name in images:
        t0 = time.time()
        records = pipe.run([REPO / "samples" / name], mode="llmpage")
        dt = round(time.time() - t0, 1)
        if reader.errors:
            print(f"  (tile errors: {reader.errors})")

        rows = [r.to_dict() for r in records]
        (out_dir / f"e2_{Path(name).stem}.records.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        (out_dir / f"e2_{Path(name).stem}.candidates.json").write_text(
            json.dumps(catalog.log, ensure_ascii=False), encoding="utf-8")

        matched = [r for r in records if r.match]
        unmatched = [r for r in records if not r.match]
        print(f"\n=== {name}  llmpage ({CONFIG.llm.model}) — {dt}s, "
              f"{len(records)} blocks -> {len(matched)} matched ===")
        for r in matched:
            m = r.match
            print(f"  {m.tier:6} {m.score:5.1f}  {m.title}  |  {m.author}"
                  f"   <- \"{r.ocr.text[:38]}\"")
        for r in unmatched:
            print(f"  ----          (unverified) \"{r.ocr.text[:60]}\"")

        truth = gt.get(name)
        if not truth:
            continue
        for tiers in ({"AUTO"}, {"AUTO", "REVIEW"}):
            preds = [{"title": r.match.title, "author": r.match.author,
                      "score": r.match.score}
                     for r in matched if r.match.tier in tiers]
            s = score_predictions(preds, truth, image=name).to_dict()
            label = "+".join(sorted(tiers))
            print(f"  [{label:11}] P {s['precision']:.2f} R {s['recall']:.2f} "
                  f"F1 {s['f1']:.2f}  ({len(s['correct'])}/{s['n_truth']} correct, "
                  f"{len(s['phantom'])} phantom)")
            if s["phantom"]:
                print(f"      phantom: {' | '.join(s['phantom'])}")
            if s["missed"]:
                print(f"      missed:  {' | '.join(s['missed'])}")


if __name__ == "__main__":
    main()
