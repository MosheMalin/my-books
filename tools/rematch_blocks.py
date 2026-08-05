# -*- coding: utf-8 -*-
"""Controlled retrieval comparison on the stored E2 reads.

The LLM reads from tools/llmpage_run.py are held fixed (loaded from
work/llm_probe/e2_*.records.json); only retrieval + tiering vary:

  A0  NLI exactly as the E2 run saw it (ReplayCatalog)  — must reproduce E2
  A1  A0 + truncated-read demotion (the new gate, isolated)
  B   Simania-first -> NLI fallback + demotion          — the proposed stack

Usage: python tools/rematch_blocks.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.llmpage_run import load_env

load_env()

from booksnap.config import CONFIG
from booksnap.match import match_spine, resolve_duplicates
from booksnap.nli_catalog import NLICatalog
from booksnap.pipeline import _is_truncated
from booksnap.replay import ReplayCatalog
from booksnap.scoring import load_ground_truth, score_predictions
from booksnap.simania_catalog import FallbackCatalog, SimaniaCatalog
from booksnap.types import OcrResult

OUT = REPO / "work" / "llm_probe"


_RANK = {"AUTO": 2, "REVIEW": 1}


def rematch(ocrs: list[OcrResult], catalog, demote: bool):
    if isinstance(catalog, tuple):
        # best-of: match against each source independently, keep the stronger
        # verified match per read (tier first, then score)
        matches = []
        for o in ocrs:
            ms = [m for m in (match_spine(o, c) for c in catalog) if m]
            matches.append(max(ms, key=lambda m: (_RANK[m.tier], m.score))
                           if ms else None)
        matches = resolve_duplicates(matches)
    else:
        matches = resolve_duplicates([match_spine(o, catalog) for o in ocrs])
    if demote:
        for o, m in zip(ocrs, matches):
            if m and m.tier == "AUTO" and _is_truncated(o.text):
                m.tier = "REVIEW"
    return matches


def main() -> None:
    gt = load_ground_truth()
    for name in ("IMG_6082.jpeg", "IMG_7849.jpeg"):
        stem = Path(name).stem
        rows = json.loads((OUT / f"e2_{stem}.records.json").read_text(encoding="utf-8"))
        ocrs = [OcrResult(spine_id=r["spine_id"], text=(r.get("ocr") or {}).get("text", ""),
                          lines=(r.get("ocr") or {}).get("lines") or [])
                for r in rows]
        truth = gt[name]

        configs = {
            "A0 nli-replay        ": (ReplayCatalog.from_file(
                OUT / f"e2_{stem}.candidates.json"), False),
            "A1 nli-replay + gate ": (ReplayCatalog.from_file(
                OUT / f"e2_{stem}.candidates.json"), True),
            "B  simania+nli + gate": (FallbackCatalog(
                SimaniaCatalog(cache_dir=CONFIG.paths.work_dir / "simania_cache"),
                NLICatalog(cache_dir=CONFIG.paths.work_dir / "nli_cache")), True),
            "C  best-of both + gate": ((
                SimaniaCatalog(cache_dir=CONFIG.paths.work_dir / "simania_cache"),
                NLICatalog(cache_dir=CONFIG.paths.work_dir / "nli_cache")), True),
        }

        print(f"\n=== {name} ({len(ocrs)} stored reads) ===")
        for label, (cat, demote) in configs.items():
            matches = rematch(ocrs, cat, demote)
            line = []
            for tiers in ({"AUTO"}, {"AUTO", "REVIEW"}):
                preds = [{"title": m.title, "author": m.author, "score": m.score}
                         for m in matches if m and m.tier in tiers]
                s = score_predictions(preds, truth, image=name)
                line.append(f"{'+'.join(sorted(tiers)):11} "
                            f"P {s.precision:.2f} R {s.recall:.2f} F1 {s.f1:.2f}")
            print(f"  {label}  {line[0]}   |   {line[1]}")
            if label[0] in "BC":
                for tiers in ({"AUTO"}, {"AUTO", "REVIEW"}):
                    preds = [{"title": m.title, "author": m.author, "score": m.score}
                             for m in matches if m and m.tier in tiers]
                    d = score_predictions(preds, truth, image=name).to_dict()
                    lbl = "+".join(sorted(tiers))
                    if d["phantom"]:
                        print(f"      [{lbl}] phantom: {' | '.join(d['phantom'])}")
                    if d["missed"]:
                        print(f"      [{lbl}] missed:  {' | '.join(d['missed'])}")


if __name__ == "__main__":
    main()
