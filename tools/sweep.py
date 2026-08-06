# -*- coding: utf-8 -*-
"""Measure the CURRENT matching rules against every ground-truth shelf.

The LLM reads are a paid, non-deterministic stage — but they are *stored* with
every run, so rule/threshold changes never need to call the model again. This
tool replays the stored reads for each GT-labelled shelf through the current
match pipeline (the same post-match path Pipeline.run_page uses), scores
against fixtures/ground_truth.json, and appends the result to an experiments ledger so
"did my change help?" is answerable against history.

Retrieval modes (the second frozen input):

  default (replay)      each shelf's own candidates recording (ReplayCatalog).
                        Fully offline+deterministic. Queries the recording
                        never saw are counted — a nonzero miss count means the
                        change altered *retrieval*, not just matching, and the
                        offline score can't be fully trusted.
  --live                real retrieval through the selected --sources
                        (disk-cached per query, so repeats are ~free). Use
                        when the change IS retrieval (new source, new query
                        code). Records everything it fetches so the sweep can
                        later be replayed exactly with --replay-exp.
  --replay-exp ID       replay a previous --live sweep's recording: a fixed
                        retrieval snapshot to compare rule variants against.

The confirmed library is deliberately NOT part of any sweep catalog: it is an
outcome of runs, not a source (owner decision, 2026-08-06). Note that shelf
recordings from runs 13+ were captured with the library head in the chain, so
its influence is frozen inside those recordings.

Ledger: one JSON line per sweep in work/experiments.jsonl (aggregate + per-
shelf scores + git sha/dirty + config hash + retrieval descriptor). Full
detail (config snapshot, phantom/missed lists) in work/experiments/<id>.json.

    python tools/sweep.py                       # replay sweep, log it
    python tools/sweep.py --note "wider gate"   # label the ledger row
    python tools/sweep.py --live --sources simania,nli
    python tools/sweep.py --replay-exp 20260806-141002
    python tools/sweep.py --dry                 # print only, no ledger row
    python tools/sweep.py --list                # show ledger history
    python tools/sweep.py --images IMG_8131.jpeg

Regression gate (wired into git pre-commit via tools/githooks/):

    python tools/sweep.py --check               # replay sweep vs committed
                                                # baseline; exit 1 on regression
    python tools/sweep.py --accept-baseline --note "why the trade-off is ok"
                                                # bless the current numbers

The baseline lives in tools/sweep_baseline.json (COMMITTED, unlike the
work/ ledger) so the gate travels with the code: a commit that regresses the
aggregate means is blocked until the owner either fixes it or explicitly
accepts the new numbers. The gate compares MEANS (auto P, auto F1, A+R F1,
tolerance 0.01) — per-shelf trade-offs are printed but don't block, because
accepted changes routinely trade a point on one shelf for gains elsewhere.

`--export` copies the sweep's inputs (reads + candidates, ~1MB JSON) into
fixtures/sweep/ for committing, so a fresh clone with no work/ directory
still runs the gate and reproduces the baseline. --accept-baseline
re-exports automatically to keep inputs and numbers in lockstep.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# .env before booksnap imports (NLI key etc.; only --live actually needs keys)
for _line in ((REPO / ".env").read_text(encoding="utf-8").splitlines()
              if (REPO / ".env").exists() else []):
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

from booksnap.config import CONFIG                                # noqa: E402
from booksnap.match import (match_spine, apply_second_pass,        # noqa: E402
                            postprocess_matches)
from booksnap.pipeline import _is_truncated                        # noqa: E402
from booksnap.replay import RecordingCatalog, ReplayCatalog        # noqa: E402
from booksnap.scoring import load_ground_truth, score_predictions  # noqa: E402
from booksnap.types import OcrResult                               # noqa: E402

WORK = CONFIG.paths.work_dir
STORE = WORK / "store.json"
LLM_PROBE = WORK / "llm_probe"
EXP_DIR = WORK / "experiments"
LEDGER = WORK / "experiments.jsonl"
BASELINE = REPO / "tools" / "sweep_baseline.json"
FIXTURES = REPO / "fixtures" / "sweep"     # committed export of the inputs

ALL_SOURCES = ("simania", "nli", "rebooks", "booksefer")

#: gated metrics (means across shelves) and the drop that blocks a commit
GATE_METRICS = (("auto", "p", "mean AUTO precision"),
                ("auto", "f1", "mean AUTO F1"),
                ("auto_review", "f1", "mean A+R F1"))
GATE_EPS = 0.01
SHELF_FLAG_EPS = 0.03      # per-shelf F1 moves worth printing (never blocking)


# -- fixtures: (reads, candidates recording) per GT shelf ---------------------

def find_fixtures() -> dict[str, dict]:
    """Map GT image name -> stored reads + candidates recording.

    Prefers the LATEST llmpage run containing the image (reads improve as the
    reader is tuned; the newest run is the reference input). Falls back to the
    E2 probe files in work/llm_probe for the two original fixture shelves,
    which never had an llmpage run in the store; and finally to the COMMITTED
    export in fixtures/sweep (see --export), which is what makes the
    pre-commit gate work on a machine that has no work/ data at all.
    """
    gt = load_ground_truth()
    fixtures: dict[str, dict] = {}
    store = (json.loads(STORE.read_text(encoding="utf-8"))
             if STORE.exists() else {"runs": {}, "images": {}})
    img_name = {i: (rec or {}).get("name", "")
                for i, rec in store.get("images", {}).items()}

    for run in sorted(store.get("runs", {}).values(),
                      key=lambda r: r.get("run_no", 0)):
        if run.get("mode") != "llmpage":
            continue
        rd = WORK / "runs" / run["run_id"]
        for img_id in run.get("images", {}):
            name = img_name.get(img_id, "")
            recs, cands = rd / f"{img_id}.json", rd / "candidates" / f"{img_id}.json"
            if name in gt and recs.exists() and cands.exists():
                # later runs overwrite earlier ones (sorted by run_no)
                fixtures[name] = {"records": recs, "candidates": cands,
                                  "origin": f"run#{run['run_no']}"}

    for name in gt:
        if name in fixtures:
            continue
        stem = Path(name).stem
        recs = LLM_PROBE / f"e2_{stem}.records.json"
        cands = LLM_PROBE / f"e2_{stem}.candidates.json"
        if recs.exists() and cands.exists():
            fixtures[name] = {"records": recs, "candidates": cands,
                              "origin": "e2-probe"}

    manifest_path = FIXTURES / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name in gt:
            if name in fixtures:
                continue
            recs = FIXTURES / f"{name}.records.json"
            cands = FIXTURES / f"{name}.candidates.json"
            if recs.exists() and cands.exists():
                src = (manifest.get("shelves", {}).get(name) or {}).get("origin", "?")
                fixtures[name] = {"records": recs, "candidates": cands,
                                  "origin": f"exp({src})"}
    return fixtures


def export_fixtures() -> None:
    """Copy each shelf's resolved reads + candidates into fixtures/sweep so
    the repo carries the sweep's inputs: a fresh clone (no work/) can then run
    the pre-commit gate and reproduce the baseline exactly. ~1MB of JSON.

    Refreshed automatically by --accept-baseline: the committed inputs and the
    committed baseline must describe the same experiment, or a new machine
    would 'regress' against numbers its data can't produce.
    """
    import shutil
    fixtures = find_fixtures()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    manifest = {"exported": datetime.now().isoformat(timespec="seconds"),
                "code": code_version(), "shelves": {}}
    for name, fx in sorted(fixtures.items()):
        for key, dest in (("records", FIXTURES / f"{name}.records.json"),
                          ("candidates", FIXTURES / f"{name}.candidates.json")):
            if fx[key].resolve() != dest.resolve():   # already the export
                shutil.copyfile(fx[key], dest)
        manifest["shelves"][name] = {
            "origin": fx["origin"],
            "records_sha": hashlib.sha256(
                fx["records"].read_bytes()).hexdigest()[:12],
            "candidates_sha": hashlib.sha256(
                fx["candidates"].read_bytes()).hexdigest()[:12]}
    (FIXTURES / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"exported {len(fixtures)} shelves -> {FIXTURES.relative_to(REPO)} "
          f"(commit this directory)")


def load_reads(path: Path) -> list[OcrResult]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [OcrResult(spine_id=r["spine_id"],
                      text=(r.get("ocr") or {}).get("text", ""),
                      lines=(r.get("ocr") or {}).get("lines") or [])
            for r in rows]


# -- catalogs -----------------------------------------------------------------

def build_live_catalog(sources: list[str]):
    """The baseline retrieval flow minus the confirmed library, with only the
    selected sources. Every source caches per-query on disk, so re-sweeping
    costs nothing new. The caller wraps this in a per-shelf RecordingCatalog
    to snapshot the sweep's retrieval for exact later replay (--replay-exp)."""
    from booksnap.extra_catalogs import (BooksferCatalog, ChainCatalog,
                                         RebooksCatalog, UnionCatalog)
    primaries = []
    if "simania" in sources:
        from booksnap.simania_catalog import SimaniaCatalog
        primaries.append(SimaniaCatalog(cache_dir=WORK / "simania_cache"))
    if "nli" in sources:
        from booksnap.nli_catalog import NLICatalog
        primaries.append(NLICatalog(cache_dir=WORK / "nli_cache"))
    chain: list = [UnionCatalog(primaries)] if primaries else []
    if "rebooks" in sources:
        chain.append(RebooksCatalog(cache_dir=WORK / "rebooks_cache"))
    if "booksefer" in sources:
        chain.append(BooksferCatalog(cache_dir=WORK / "booksefer_cache"))
    if not chain:
        raise SystemExit(f"no valid sources in {sources!r} "
                         f"(choose from {', '.join(ALL_SOURCES)})")
    return chain[0] if len(chain) == 1 else ChainCatalog(chain)


# -- the flow under test ------------------------------------------------------

def match_shelf(ocrs: list[OcrResult], catalog) -> list:
    """Exactly the post-match path of Pipeline.run_page — sweeping a different
    flow than the one that ships would measure the wrong system."""
    texts = [o.text for o in ocrs]
    if CONFIG.match.use_assignment:
        from booksnap.match import candidates_for_spine, resolve_assignment
        matches = postprocess_matches(texts, resolve_assignment(
            [candidates_for_spine(o, catalog, CONFIG.match) for o in ocrs],
            CONFIG.match), CONFIG.match)
    else:
        matches = [match_spine(o, catalog, CONFIG.match) for o in ocrs]
        matches = postprocess_matches(texts, matches, CONFIG.match)
        if CONFIG.match.second_pass_retrieval:
            matches = apply_second_pass(ocrs, matches, catalog, CONFIG.match)
    for o, m in zip(ocrs, matches):
        if m and m.tier == "AUTO" and _is_truncated(o.text):
            m.tier = "REVIEW"
    return matches


# -- ledger helpers -----------------------------------------------------------

def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def code_version() -> dict:
    return {"sha": _git("rev-parse", "--short", "HEAD"),
            "dirty": bool(_git("status", "--porcelain"))}


def config_snapshot() -> dict:
    def scrub(v):
        return v if isinstance(v, (int, float, str, bool, type(None), list)) \
            else str(v)
    return asdict(CONFIG, dict_factory=lambda kv: {k: scrub(v) for k, v in kv})


def show_history() -> None:
    if not LEDGER.exists():
        print("no experiments logged yet")
        return
    print(f"{'id':20} {'sha':9} {'retrieval':28} "
          f"{'AUTO P/R/F1':>16} {'A+R P/R/F1':>16}  note")
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        sha = row["code"]["sha"] + ("*" if row["code"]["dirty"] else " ")
        ret = row["retrieval"]["mode"]
        if row["retrieval"].get("sources"):
            ret += ":" + ",".join(row["retrieval"]["sources"])
        a, ar = row["aggregate"]["auto"], row["aggregate"]["auto_review"]
        print(f"{row['id']:20} {sha:9} {ret:28} "
              f"{a['p']:.2f}/{a['r']:.2f}/{a['f1']:.2f}".rjust(16) + " " +
              f"{ar['p']:.2f}/{ar['r']:.2f}/{ar['f1']:.2f}".rjust(16) +
              f"  {row.get('note', '')}")


# -- regression gate ----------------------------------------------------------

def check_against_baseline(aggregate: dict, per_shelf: list[dict],
                           total_misses: int) -> int:
    """Compare a replay sweep to the committed baseline. Returns exit code."""
    if not BASELINE.exists():
        print("check: no tools/sweep_baseline.json — run "
              "`python tools/sweep.py --accept-baseline` once to create it")
        return 1
    base = json.loads(BASELINE.read_text(encoding="utf-8"))

    failed = []
    for tier, metric, label in GATE_METRICS:
        was, now = base["aggregate"][tier][metric], aggregate[tier][metric]
        delta = now - was
        mark = "FAIL" if delta < -GATE_EPS else "ok  "
        if delta < -GATE_EPS:
            failed.append(label)
        print(f"  check {label:22} {was:.3f} -> {now:.3f} ({delta:+.3f}) {mark}")

    base_shelves = base.get("per_shelf_f1", {})
    for row in per_shelf:
        b = base_shelves.get(row["image"])
        if not b:
            print(f"  check {row['image']:16} not in baseline (new shelf)")
            continue
        for tier, key in (("auto", "auto"), ("auto_review", "ar")):
            d = row[tier]["f1"] - b[key]
            if abs(d) > SHELF_FLAG_EPS:
                print(f"  note  {row['image']:16} {tier:11} F1 "
                      f"{b[key]:.2f} -> {row[tier]['f1']:.2f} ({d:+.2f})")
    gone = set(base_shelves) - {r["image"] for r in per_shelf}
    for name in sorted(gone):
        print(f"  ⚠ baseline shelf {name} missing from this sweep "
              f"(fixtures unavailable?) — its score is unverified")

    if total_misses:
        print(f"  ⚠ {total_misses} queries not in the recordings: this change "
              f"affects RETRIEVAL, so the replay score above is not the whole "
              f"story — run `python tools/sweep.py --live` and judge manually")
    if failed:
        print(f"check: REGRESSION vs baseline "
              f"{base.get('accepted', '?')} ({', '.join(failed)})")
        return 1
    print(f"check: OK vs baseline {base.get('accepted', '?')}")
    return 0


def write_baseline(exp_id: str, note: str, aggregate: dict,
                   per_shelf: list[dict]) -> None:
    BASELINE.write_text(json.dumps({
        "accepted": exp_id,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "code": code_version(), "note": note,
        "aggregate": {t: {k: aggregate[t][k] for k in ("p", "r", "f1")}
                      for t in ("auto", "auto_review")},
        "per_shelf_f1": {r["image"]: {"auto": r["auto"]["f1"],
                                      "ar": r["auto_review"]["f1"]}
                         for r in per_shelf},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"baseline accepted -> {BASELINE.name} (commit this file)")


# -- main ---------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true",
                    help="live retrieval (disk-cached) instead of run recordings")
    ap.add_argument("--sources", default=",".join(ALL_SOURCES),
                    help=f"comma list for --live (default: all of "
                         f"{','.join(ALL_SOURCES)}); library is never included")
    ap.add_argument("--replay-exp", metavar="ID",
                    help="replay the recording of a previous --live sweep")
    ap.add_argument("--images", help="comma list of image names to sweep")
    ap.add_argument("--note", default="", help="label for the ledger row")
    ap.add_argument("--dry", action="store_true", help="don't write the ledger")
    ap.add_argument("--list", action="store_true", help="show ledger history")
    ap.add_argument("--check", action="store_true",
                    help="regression gate: replay sweep vs tools/"
                         "sweep_baseline.json; exit 1 on regression, no ledger")
    ap.add_argument("--accept-baseline", action="store_true",
                    help="bless this sweep's numbers as the committed baseline")
    ap.add_argument("--export", action="store_true",
                    help="copy the sweep inputs into fixtures/sweep so a "
                         "machine without work/ can run the gate")
    args = ap.parse_args()

    if args.list:
        show_history()
        return
    if args.export:
        export_fixtures()
        return
    if args.check and (args.live or args.replay_exp or args.images):
        raise SystemExit("--check is the deterministic full replay sweep; "
                         "it takes no retrieval or image filters")
    if args.accept_baseline and (args.live or args.replay_exp or args.images
                                 or args.dry):
        raise SystemExit("--accept-baseline must be a full, logged replay "
                         "sweep (no --live/--replay-exp/--images/--dry)")

    fixtures = find_fixtures()
    if args.images:
        want = {s.strip() for s in args.images.split(",")}
        fixtures = {k: v for k, v in fixtures.items() if k in want}
    if not fixtures:
        if args.check:
            # fresh clone without work/: nothing to measure — don't block
            print("check: skipped, no stored reads/recordings on this machine")
            return
        raise SystemExit("no GT shelf has stored reads + candidates")

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if args.live:
        retrieval = {"mode": "live", "sources": sources, "library": False}
        live_cat = build_live_catalog(sources)
    elif args.replay_exp:
        retrieval = {"mode": "replay-exp", "exp": args.replay_exp,
                     "library": False}
    else:
        retrieval = {"mode": "replay",
                     "note": "each shelf's own run recording"}

    exp_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    recorders: dict[str, RecordingCatalog] = {}
    per_shelf, agg = [], {"auto": [], "auto_review": []}
    tot = {"auto": [0, 0, 0], "auto_review": [0, 0, 0]}   # tp, fp, fn
    gt = load_ground_truth()

    print(f"sweep {exp_id}  retrieval={retrieval['mode']}"
          f"{'(' + ','.join(sources) + ')' if args.live else ''}"
          f"  shelves={len(fixtures)}")
    for name in sorted(fixtures):
        fx = fixtures[name]
        ocrs = load_reads(fx["records"])
        if args.live:
            # fresh recorder per shelf (shared inner catalog keeps the disk
            # caches) so --replay-exp can serve each image its own recording
            catalog = RecordingCatalog(live_cat)
            recorders[name] = catalog
        elif args.replay_exp:
            rec = EXP_DIR / args.replay_exp / "candidates" / f"{name}.json"
            if not rec.exists():
                print(f"  {name:16} -- no recording in exp {args.replay_exp}, skipped")
                continue
            catalog = ReplayCatalog.from_file(rec)
        else:
            catalog = ReplayCatalog.from_file(fx["candidates"])

        matches = match_shelf(ocrs, catalog)
        misses = len(getattr(catalog, "misses", []))
        row = {"image": name, "origin": fx["origin"], "reads": len(ocrs),
               "replay_misses": misses}
        line = f"  {name:16} [{fx['origin']:9}] "
        for key, tiers in (("auto", {"AUTO"}), ("auto_review", {"AUTO", "REVIEW"})):
            preds = [{"title": m.title, "author": m.author, "score": m.score}
                     for m in matches if m and m.tier in tiers]
            s = score_predictions(preds, gt[name], image=name)
            row[key] = s.to_dict()
            agg[key].append(s)
            for i, v in enumerate((len(s.tp), len(s.fp), len(s.fn))):
                tot[key][i] += v
            line += (f"{'AUTO' if key == 'auto' else 'A+R '} "
                     f"P {s.precision:.2f} R {s.recall:.2f} F1 {s.f1:.2f}   ")
        if misses:
            line += f"⚠ {misses} unrecorded queries"
        print(line)
        per_shelf.append(row)

    def mean(vals):
        return sum(vals) / len(vals) if vals else 0.0

    aggregate = {}
    for key in ("auto", "auto_review"):
        tp, fp, fn = tot[key]
        micro_p = tp / (tp + fp) if tp + fp else 0.0
        micro_r = tp / (tp + fn) if tp + fn else 0.0
        aggregate[key] = {
            "p": round(mean([s.precision for s in agg[key]]), 3),
            "r": round(mean([s.recall for s in agg[key]]), 3),
            "f1": round(mean([s.f1 for s in agg[key]]), 3),
            "micro_p": round(micro_p, 3), "micro_r": round(micro_r, 3),
            "tp": tp, "fp": fp, "fn": fn}
    a, ar = aggregate["auto"], aggregate["auto_review"]
    print(f"  {'MEAN':28} AUTO P {a['p']:.2f} R {a['r']:.2f} F1 {a['f1']:.2f}   "
          f"A+R  P {ar['p']:.2f} R {ar['r']:.2f} F1 {ar['f1']:.2f}")
    total_misses = sum(r["replay_misses"] for r in per_shelf)
    if total_misses and not args.live:
        print(f"  ⚠ {total_misses} queries not in the recording — this change "
              f"affects RETRIEVAL; confirm with --live before trusting the score")

    if args.check:
        sys.exit(check_against_baseline(aggregate, per_shelf, total_misses))

    cfg = config_snapshot()
    cfg_hash = hashlib.sha256(
        json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    ledger_row = {
        "id": exp_id, "ts": datetime.now().isoformat(timespec="seconds"),
        "note": args.note, "code": code_version(), "config_hash": cfg_hash,
        "retrieval": retrieval, "images": [r["image"] for r in per_shelf],
        "fixtures": {r["image"]: r["origin"] for r in per_shelf},
        "aggregate": aggregate,
        "per_shelf": {r["image"]: {"auto": {k: r["auto"][k] for k in
                                            ("precision", "recall", "f1")},
                                   "auto_review": {k: r["auto_review"][k] for k in
                                                   ("precision", "recall", "f1")},
                                   "replay_misses": r["replay_misses"]}
                      for r in per_shelf},
    }

    if args.dry:
        print("(--dry: not logged)")
        return

    # full detail (config snapshot + phantom/missed lists) beside the ledger
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    (EXP_DIR / f"{exp_id}.json").write_text(
        json.dumps({**ledger_row, "config": cfg, "detail": per_shelf},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    for name, rec in recorders.items():
        rec.save(EXP_DIR / exp_id / "candidates" / f"{name}.json")
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ledger_row, ensure_ascii=False) + "\n")
    print(f"logged -> {LEDGER.name} + experiments/{exp_id}.json"
          f"  (config {cfg_hash}, "
          f"sha {ledger_row['code']['sha']}{'*' if ledger_row['code']['dirty'] else ''})")
    if args.accept_baseline:
        write_baseline(exp_id, args.note, aggregate, per_shelf)
        # keep the committed inputs in lockstep with the committed numbers
        if FIXTURES.exists():
            export_fixtures()


if __name__ == "__main__":
    main()
