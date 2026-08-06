# -*- coding: utf-8 -*-
"""FastAPI backend + static review UI.

    uvicorn booksnap.server:app --port 8756

Wraps the pipeline in a web app: upload shelf photos, pick which to process,
watch progress, and browse the resulting titles.

Two design constraints shape this module.

1. OCR costs ~10s/spine, so a shelf photo takes minutes. Runs happen on a
   background worker thread; the UI polls /api/job. A run can be stopped
   mid-way and the spines already read are kept.

2. This project is in a tune-and-measure loop, so every run is archived rather
   than overwritten. A result set is only interpretable next to the *inputs*
   that produced it, so each run also snapshots the code version (git sha +
   dirty flag), the full tunable config, and the catalog it matched against.
   Without that, "run 3 was better" is unattributable.

Layout under the work dir:
    store.json              image + run index (small, always loaded)
    library/                uploaded originals
    thumbs/                 upload thumbnails
    runs/<run_id>/<image_id>.json    full per-spine records for that run
    runs/<run_id>/crops/            spine crops as that run segmented them

Catalog path comes from BOOKSNAP_CATALOG (default: sample_catalog.json).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import cv2
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .catalog import LocalCatalog
from .config import CONFIG, REPO_ROOT
from .pipeline import Pipeline

def _load_dotenv() -> None:
    """Read REPO_ROOT/.env into os.environ (existing vars win).

    Keeps credentials in one gitignored file instead of the shell environment,
    so `uvicorn booksnap.server:app` just works. Deliberately tiny — no
    dependency, and it never logs or echoes a value.
    """
    path = REPO_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()

WORK = CONFIG.paths.work_dir
LIBRARY = WORK / "library"
THUMBS = WORK / "thumbs"
RUNS = WORK / "runs"
STORE = WORK / "store.json"
THUMB_WIDTH = 480
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

app = FastAPI(title="booksnap")


# --------------------------------------------------------------------------
# persistence — a small JSON store; no DB dependency for a single-user tool
# --------------------------------------------------------------------------
_store_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _blank() -> dict[str, Any]:
    return {"images": {}, "runs": {}, "next_run_no": 1}


def _load() -> dict[str, Any]:
    if STORE.exists():
        try:
            data = json.loads(STORE.read_text(encoding="utf-8"))
            for k, v in _blank().items():
                data.setdefault(k, v)
            return data
        except json.JSONDecodeError:
            pass
    return _blank()


def _save(data: dict[str, Any]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STORE)   # atomic: a crash mid-write can't corrupt the store


def _update(fn) -> Any:
    """Read-modify-write the store under a lock."""
    with _store_lock:
        data = _load()
        result = fn(data)
        _save(data)
        return result


# --------------------------------------------------------------------------
# run provenance — what a result set has to be interpreted against
# --------------------------------------------------------------------------
def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                             text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _code_version() -> dict[str, Any]:
    """Git sha + dirty flag. `dirty` matters: while tuning, the interesting
    changes are usually uncommitted, so a sha alone would alias two runs."""
    return {"sha": _git("rev-parse", "--short", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(_git("status", "--porcelain"))}


def _jsonable(v: Any) -> Any:
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, (set, frozenset)):
        return sorted(v)
    if isinstance(v, tuple):
        return list(v)
    return v


def _config_snapshot() -> dict[str, Any]:
    """Every tunable, as it stood for this run — the experiment variables."""
    return asdict(CONFIG, dict_factory=lambda kv: {k: _jsonable(v) for k, v in kv})


# --------------------------------------------------------------------------
# background job — one run at a time (OCR already saturates the CPU)
# --------------------------------------------------------------------------
_job_lock = threading.Lock()
_job: dict[str, Any] = {"state": "idle"}
_stop_event = threading.Event()


def _set_job(**kw) -> None:
    with _job_lock:
        _job.update(kw)


def _get_job() -> dict[str, Any]:
    with _job_lock:
        return dict(_job)


def _catalog_path() -> Path:
    return Path(os.environ.get("BOOKSNAP_CATALOG", REPO_ROOT / "sample_catalog.json"))


def _build_catalog():
    """Catalog backend for a run: `local` (default) or `nli`.

    Which catalog a run used is an experiment variable on par with the config,
    so the metadata returned here is stored with the run.
    """
    backend = os.environ.get("BOOKSNAP_CATALOG_BACKEND", "local").lower()
    if backend == "simania":
        # Retrieval chain, precise -> broad, each source only on-empty:
        # Simania (edition-true spellings, series metadata) -> NLI (legal
        # deposit authority) -> used-book shops (out-of-print residue like
        # old SF that neither of the first two carries).
        from .extra_catalogs import (BooksferCatalog, ChainCatalog,
                                     RebooksCatalog, UnionCatalog)
        from .simania_catalog import SimaniaCatalog
        primaries = [SimaniaCatalog(cache_dir=WORK / "simania_cache")]
        parts = ["simania"]
        if os.environ.get("NLI_API_KEY"):
            from .nli_catalog import NLICatalog
            primaries.append(NLICatalog(cache_dir=WORK / "nli_cache"))
            parts.append("nli")
        # primaries are ALWAYS unioned (see UnionCatalog: thin-union let junk
        # block exact hits); the shop tail joins only when the union is thin
        chain = [UnionCatalog(primaries),
                 RebooksCatalog(cache_dir=WORK / "rebooks_cache"),
                 BooksferCatalog(cache_dir=WORK / "booksefer_cache")]
        parts += ["rebooks", "booksefer"]
        # confirmed library AUGMENTS the chain (union, never a gate): a book
        # the owner confirmed once matches instantly on every later shelf
        from .library import ConfirmedCatalog, LibraryFirstCatalog
        cat = LibraryFirstCatalog(ConfirmedCatalog(), ChainCatalog(chain))
        return cat, {
            "backend": "library+" + "+".join(parts), "entries": None,
            "note": "confirmed library union, then on-empty cascade"}
    if backend == "nli":
        from .nli_catalog import NLICatalog
        key = os.environ.get("NLI_API_KEY", "")
        if not key:
            raise RuntimeError(
                "BOOKSNAP_CATALOG_BACKEND=nli but NLI_API_KEY is not set. "
                "Get a free key at https://api2.nli.org.il/signup/ .")
        cat = NLICatalog(cache_dir=WORK / "nli_cache")
        # never store the key itself in the run record
        return cat, {"backend": "nli", "entries": None,
                     "note": "live search API; candidates fetched per spine"}
    cat_path = _catalog_path()
    cat = LocalCatalog.from_json(cat_path)
    return cat, {"backend": "local", "path": str(cat_path), "entries": len(cat)}


def _build_fallback():
    """Stronger-engine fallback for spines deterministic OCR can't read.

    Off unless BOOKSNAP_FALLBACK=google_vision. Only unmatched spines are ever
    sent (see Pipeline.run), so a shelf costs a handful of billable images.
    """
    name = os.environ.get("BOOKSNAP_FALLBACK", "none").lower()
    if name in ("", "none", "null"):
        return None, {"provider": "none"}
    if name == "google_vision":
        from google.cloud import vision
        from .fallback import GoogleVisionFallback
        client = vision.ImageAnnotatorClient()      # picks up ADC
        return (GoogleVisionFallback(client, image_ctor=vision.Image),
                {"provider": "google_vision"})
    raise RuntimeError(f"unknown BOOKSNAP_FALLBACK={name!r}")


def _build_page_reader(mode: str = "fullpage"):
    """Whole-page reader: Google Vision for 'fullpage', Claude for 'llmpage'."""
    if mode == "llmpage":
        from .llmreader import ClaudePageReader
        return ClaudePageReader()
    from google.cloud import vision
    from .pagereader import GoogleVisionPageReader
    return GoogleVisionPageReader(vision.ImageAnnotatorClient(),
                                  image_ctor=vision.Image)


def _summarise(records: list[dict]) -> dict[str, Any]:
    auto = sum(1 for r in records if (r.get("match") or {}).get("tier") == "AUTO")
    review = sum(1 for r in records if (r.get("match") or {}).get("tier") == "REVIEW")
    ocr_ms = [(r.get("ocr") or {}).get("ms") or 0 for r in records]
    return {"spines": len(records), "auto": auto, "review": review,
            "unmatched": len(records) - auto - review,
            "matched": auto + review,
            "ocr_ms_total": sum(ocr_ms),
            "ocr_ms_median": sorted(ocr_ms)[len(ocr_ms) // 2] if ocr_ms else 0}


def _run_dir(run_id: str) -> Path:
    return RUNS / run_id


def _records_path(run_id: str, img_id: str) -> Path:
    return _run_dir(run_id) / f"{img_id}.json"


def _run_job(run_id: str, image_ids: list[str], mode: str = "spines") -> None:
    """Worker body: process each selected image, saving results as they land."""
    started = time.monotonic()
    try:
        catalog, cat_meta = _build_catalog()
        fallback, fb_meta = _build_fallback()
        page_reader = (_build_page_reader(mode)
                       if mode in ("fullpage", "llmpage") else None)
        # Record retrieval so this run can be replayed exactly later; without
        # it a live search backend makes past runs impossible to reproduce.
        from .replay import RecordingCatalog
        catalog = RecordingCatalog(catalog)
        pipe = Pipeline(catalog=catalog, fallback=fallback,
                        page_reader=page_reader,
                        crops_dir=_run_dir(run_id) / "crops")
    except Exception as exc:                       # bad catalog/credentials
        _update(lambda d: d["runs"][run_id].update(
            status="error", error=f"setup: {exc}", finished_at=_now()))
        _set_job(state="idle", error=f"setup: {exc}")
        return

    use_fallback = fallback is not None
    _update(lambda d: d["runs"][run_id].update(catalog=cat_meta, fallback=fb_meta))

    stopped = False
    for n, img_id in enumerate(image_ids, start=1):
        if _stop_event.is_set():
            stopped = True
            break
        data = _load()
        rec = data["images"].get(img_id)
        if not rec:
            continue
        path = Path(rec["path"])
        img_started = time.monotonic()
        _set_job(state="running", run_id=run_id, image_id=img_id, name=rec["name"],
                 image_no=n, image_total=len(image_ids), done=0, spines=0,
                 phase=None,      # else the previous image's phase mislabels
                 error=None, stopping=_stop_event.is_set())
        _update(lambda d: d["images"][img_id].update(status="running", error=None))

        detected = {"n": 0}

        def on_progress(ev: dict) -> None:
            st = ev.get("stage")
            if st in ("segmented", "page_read"):
                detected["n"] = ev["spines"]
                _set_job(spines=ev["spines"])
            elif st in ("reading", "matching", "ocr"):
                # page modes have two long phases (LLM tile reads, then
                # catalog lookups per block) — surface which one is running
                # so the bar moves instead of stalling at "spine 1/N"
                _set_job(phase=st, done=ev["done"], spines=ev["total"])

        try:
            records = [r.to_dict() for r in pipe.run(
                [path], use_fallback=use_fallback, progress=on_progress,
                should_stop=_stop_event.is_set, mode=mode)]
        except Exception as exc:
            msg = str(exc)
            _update(lambda d, e=msg: (d["images"][img_id].update(status="error", error=e),
                                      d["runs"][run_id]["images"].__setitem__(
                                          img_id, {"status": "error", "error": e})))
            continue

        _run_dir(run_id).mkdir(parents=True, exist_ok=True)
        _records_path(run_id, img_id).write_text(
            json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
        catalog.save(_run_dir(run_id) / "candidates" / f"{img_id}.json")
        # AUTO claims join the confirmed library (status "auto", reversible);
        # REVIEW claims wait for a human decision in the review flow
        from .library import absorb_auto_claims
        absorb_auto_claims(run_id, records)

        was_stopped = _stop_event.is_set()
        summary = _summarise(records)
        img_status = "stopped" if was_stopped else "done"
        entry = {"status": img_status, "error": None, "summary": summary,
                 "spines_detected": detected["n"],
                 "spines_processed": len(records),
                 "duration_s": round(time.monotonic() - img_started, 1)}
        _update(lambda d, e=entry, s=img_status: (
            d["runs"][run_id]["images"].__setitem__(img_id, e),
            d["images"][img_id].update(status=s, error=None,
                                       latest_run_id=run_id, summary=e["summary"],
                                       processed_at=_now())))
        if was_stopped:
            stopped = True
            break

    _update(lambda d: d["runs"][run_id].update(
        status="stopped" if stopped else "completed",
        finished_at=_now(), duration_s=round(time.monotonic() - started, 1)))
    _stop_event.clear()
    _set_job(state="idle", run_id=run_id, image_id=None, name=None, stopping=False)


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------
@app.post("/api/images")
async def upload_images(files: list[UploadFile] = File(...)) -> dict:
    LIBRARY.mkdir(parents=True, exist_ok=True)
    THUMBS.mkdir(parents=True, exist_ok=True)
    added, rejected = [], []

    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            rejected.append({"name": f.filename, "reason": "unsupported type"})
            continue
        img_id = uuid.uuid4().hex[:12]
        # Store under the id, not the original name: two uploads may share a
        # filename, and spine ids (and therefore crop filenames) derive from it.
        dest = LIBRARY / f"{img_id}{suffix}"
        dest.write_bytes(await f.read())

        img = cv2.imread(str(dest))
        if img is None:                            # not a decodable image
            dest.unlink(missing_ok=True)
            rejected.append({"name": f.filename, "reason": "unreadable image"})
            continue
        h, w = img.shape[:2]
        scale = THUMB_WIDTH / w
        if scale < 1:
            img = cv2.resize(img, (THUMB_WIDTH, max(1, round(h * scale))),
                             interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(THUMBS / f"{img_id}.jpg"), img)

        entry = {"id": img_id, "name": f.filename, "path": str(dest),
                 "width": w, "height": h, "uploaded_at": _now(),
                 "status": "new", "error": None, "summary": None,
                 "latest_run_id": None, "processed_at": None}
        _update(lambda d, e=entry: d["images"].__setitem__(img_id, e))
        added.append({"id": img_id, "name": f.filename})

    return {"added": added, "rejected": rejected}


def _public(rec: dict) -> dict:
    # "records" is a pre-run-history leftover: results now live in per-run files
    return {k: v for k, v in rec.items() if k not in ("path", "records")}


@app.get("/api/images")
def list_images() -> dict:
    data = _load()
    images = sorted(data["images"].values(), key=lambda r: r["uploaded_at"])
    return {"images": [_public(r) for r in images]}


@app.delete("/api/images/{img_id}")
def delete_image(img_id: str) -> dict:
    if _get_job().get("image_id") == img_id:
        raise HTTPException(409, "image is currently being processed")

    def drop(d):
        rec = d["images"].pop(img_id, None)
        if rec is None:
            raise HTTPException(404, "no such image")
        for run in d["runs"].values():           # keep run history consistent
            run["images"].pop(img_id, None)
        return rec

    rec = _update(drop)
    Path(rec["path"]).unlink(missing_ok=True)
    (THUMBS / f"{img_id}.jpg").unlink(missing_ok=True)
    for p in RUNS.glob(f"*/{img_id}.json"):
        p.unlink(missing_ok=True)
    return {"deleted": img_id}


@app.get("/api/images/{img_id}/thumb")
def image_thumb(img_id: str):
    p = THUMBS / f"{img_id}.jpg"
    if not p.exists():
        raise HTTPException(404, "no thumbnail")
    return FileResponse(p, media_type="image/jpeg")


@app.get("/api/images/{img_id}/full")
def image_full(img_id: str):
    rec = _load()["images"].get(img_id)
    if not rec:
        raise HTTPException(404, "no such image")
    return FileResponse(rec["path"])


@app.get("/api/runs/{run_id}/crops/{spine_id}")
def spine_crop(run_id: str, spine_id: str):
    """Serve a spine crop as *that run* segmented it."""
    root = (_run_dir(run_id) / "crops").resolve()
    p = (root / f"{spine_id}.jpg").resolve()
    if root not in p.parents or not p.exists():        # block path traversal
        raise HTTPException(404, "no such crop")
    return FileResponse(p, media_type="image/jpeg")


# --------------------------------------------------------------------------
# runs
# --------------------------------------------------------------------------
@app.post("/api/run")
def start_run(payload: dict = Body(...)) -> dict:
    image_ids = payload.get("image_ids") or []
    mode = (payload.get("mode") or "spines").lower()
    if not image_ids:
        raise HTTPException(400, "no images selected")
    if mode not in ("spines", "fullpage", "llmpage"):
        raise HTTPException(400, f"unknown mode {mode!r}")
    if mode == "fullpage" and os.environ.get("BOOKSNAP_FALLBACK", "").lower() \
            != "google_vision":
        raise HTTPException(
            400, "fullpage mode needs Google Vision: set "
                 "BOOKSNAP_FALLBACK=google_vision and restart the server")
    if mode == "llmpage" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            400, "llmpage mode needs ANTHROPIC_API_KEY in the environment/.env")
    if _get_job().get("state") == "running":
        raise HTTPException(409, "a run is already in progress")

    known = _load()["images"]
    unknown = [i for i in image_ids if i not in known]
    if unknown:
        raise HTTPException(404, f"unknown image ids: {unknown}")

    run_id = uuid.uuid4().hex[:12]

    def create(d):
        no = d["next_run_no"]
        d["next_run_no"] = no + 1
        d["runs"][run_id] = {
            "run_id": run_id, "run_no": no, "label": "", "note": "",
            "started_at": _now(), "finished_at": None, "status": "running",
            "error": None, "duration_s": None,
            "code_version": _code_version(),
            "config": _config_snapshot(),
            "catalog": None,
            "mode": mode,
            "image_ids": image_ids,
            "image_names": [known[i]["name"] for i in image_ids],
            "images": {},
        }
        return no

    run_no = _update(create)
    _stop_event.clear()
    _set_job(state="running", run_id=run_id, run_no=run_no, image_no=0,
             image_total=len(image_ids), done=0, spines=0, error=None,
             image_id=None, name=None, stopping=False, mode=mode)
    threading.Thread(target=_run_job, args=(run_id, image_ids, mode),
                     daemon=True).start()
    return {"run_id": run_id, "run_no": run_no, "mode": mode,
            "started": image_ids}


@app.post("/api/stop")
def stop_run() -> dict:
    """Ask the worker to stop after the spine it is currently reading.

    Cooperative rather than a kill: the spines already read are matched and
    saved, so a stopped run is still a usable (partial) result set.
    """
    if _get_job().get("state") != "running":
        raise HTTPException(409, "nothing is running")
    _stop_event.set()
    _set_job(stopping=True)
    return {"stopping": True}


@app.get("/api/job")
def job_status() -> dict:
    return _get_job()


def _run_public(run: dict) -> dict:
    """Run metadata without the bulky config blob (fetched on demand)."""
    totals = {"spines": 0, "auto": 0, "review": 0, "unmatched": 0, "matched": 0}
    for entry in run.get("images", {}).values():
        s = entry.get("summary") or {}
        for k in totals:
            totals[k] += s.get(k, 0)
    return {**{k: v for k, v in run.items() if k != "config"}, "totals": totals}


@app.get("/api/runs")
def list_runs() -> dict:
    runs = sorted(_load()["runs"].values(), key=lambda r: r["run_no"], reverse=True)
    return {"runs": [_run_public(r) for r in runs]}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = _load()["runs"].get(run_id)
    if not run:
        raise HTTPException(404, "no such run")
    return {**_run_public(run), "config": run.get("config")}


@app.patch("/api/runs/{run_id}")
def annotate_run(run_id: str, payload: dict = Body(...)) -> dict:
    """Label/annotate a run, so it can be referred to later ('v3: wider gates')."""
    def apply(d):
        run = d["runs"].get(run_id)
        if not run:
            raise HTTPException(404, "no such run")
        for k in ("label", "note"):
            if k in payload:
                run[k] = str(payload[k])[:400]
        return _run_public(run)
    return _update(apply)


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str) -> dict:
    if _get_job().get("run_id") == run_id and _get_job().get("state") == "running":
        raise HTTPException(409, "run is in progress")

    def drop(d):
        if d["runs"].pop(run_id, None) is None:
            raise HTTPException(404, "no such run")
        for img in d["images"].values():          # forget dangling pointers
            if img.get("latest_run_id") == run_id:
                img["latest_run_id"] = None
    _update(drop)
    shutil.rmtree(_run_dir(run_id), ignore_errors=True)
    return {"deleted": run_id}


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------
def _latest_run_id(data: dict) -> Optional[str]:
    finished = [r for r in data["runs"].values() if r.get("images")]
    if not finished:
        return None
    return max(finished, key=lambda r: r["run_no"])["run_id"]


@app.get("/api/results")
def results(run_id: Optional[str] = None, image_id: Optional[str] = None) -> dict:
    """Found titles for one run (default: the most recent run with results)."""
    data = _load()
    rid = run_id or _latest_run_id(data)
    if rid is None:
        return {"run": None, "found": [], "unique_titles": [],
                "totals": {"spines": 0, "auto": 0, "review": 0,
                           "unmatched": 0, "unique_titles": 0}}
    run = data["runs"].get(rid)
    if not run:
        raise HTTPException(404, "no such run")

    img_ids = [image_id] if image_id else list(run.get("images", {}).keys())
    found: list[dict] = []
    for iid in img_ids:
        p = _records_path(rid, iid)
        if not p.exists():
            continue
        img_meta = data["images"].get(iid) or {}
        name = img_meta.get("name") or run.get("image_names", [""])[0]
        for r in json.loads(p.read_text(encoding="utf-8")):
            m = r.get("match")
            ocr = r.get("ocr") or {}
            loc = r.get("location") or {}
            found.append({
                "spine_id": r["spine_id"],
                # readable locator: spine_id carries the storage uuid, but a
                # human referring to "that spine" wants image + band/position
                "band": loc.get("band"),
                "index": loc.get("index"),
                "image_id": iid,
                "image_name": name,
                "title": (m or {}).get("title"),
                "author": (m or {}).get("author"),
                "tier": (m or {}).get("tier"),
                "score": (m or {}).get("score"),
                "ocr_text": (ocr.get("text") or "").strip(),
                "ocr_score": ocr.get("score"),
                "rotation": ocr.get("rotation"),
                "ms": ocr.get("ms"),
            })

    titles = [f for f in found if f["title"]]
    unique = sorted({(f["title"], f["author"] or "") for f in titles})
    return {
        "run": _run_public(run),
        "found": found,
        "totals": {
            "spines": len(found),
            "auto": sum(1 for f in titles if f["tier"] == "AUTO"),
            "review": sum(1 for f in titles if f["tier"] == "REVIEW"),
            "unmatched": len(found) - len(titles),
            "unique_titles": len(unique),
        },
        "unique_titles": [{"title": t, "author": a} for t, a in unique],
    }


@app.get("/api/runs/{run_id}/score")
def score_run_endpoint(run_id: str) -> dict:
    """Precision/recall for every labelled image in this run.

    AUTO/REVIEW counts can't tell "found more" from "invented more"; this can.
    Images with no ground-truth entry are skipped rather than guessed at.
    """
    from .scoring import load_ground_truth, score_run
    data = _load()
    run = data["runs"].get(run_id)
    if not run:
        raise HTTPException(404, "no such run")
    try:
        gt = load_ground_truth()
    except FileNotFoundError:
        return {"scored": [], "note": "no ground_truth.json"}

    payload = results(run_id=run_id)
    out, unlabelled = [], []
    for iid in run.get("images", {}):
        name = (data["images"].get(iid) or {}).get("name") or ""
        if name not in gt:
            unlabelled.append(name)
            continue
        rows = [f for f in payload["found"] if f["image_id"] == iid]
        for tier_set, label in (({"AUTO", "REVIEW"}, "auto+review"),
                                ({"AUTO"}, "auto_only")):
            s = score_run(rows, name, gt, tiers=tier_set)
            if s:
                out.append({**s.to_dict(), "tiers": label})
    return {"run_no": run.get("run_no"), "mode": run.get("mode"),
            "scored": out, "unlabelled_images": unlabelled}


def _find_record(run_id: str, spine_id: str) -> dict:
    run = _load()["runs"].get(run_id)
    if not run:
        raise HTTPException(404, "no such run")
    for iid in run.get("images", {}):
        p = _records_path(run_id, iid)
        if not p.exists():
            continue
        for r in json.loads(p.read_text(encoding="utf-8")):
            if r["spine_id"] == spine_id:
                return r
    raise HTTPException(404, "no such spine in this run")


@app.get("/api/runs/{run_id}/explain/{spine_id}")
def explain_spine(run_id: str, spine_id: str) -> dict:
    """Why did this spine match (or fail to match) a title?

    NOTE: the ranking is recomputed with the CURRENT code and config, not the
    snapshot the run was produced with. That is usually what you want while
    tuning ("would my change have fixed this spine?"), but it means the answer
    can disagree with an old run's stored result. The UI says so.
    """
    record = _find_record(run_id, spine_id)

    from .match import explain
    # explain against the SAME retrieval the runs use (was: always the local
    # sample catalog, which silently disagreed with chain-backend runs)
    catalog, _ = _build_catalog()
    ocr = record.get("ocr") or {}
    texts = [t for t in [ocr.get("text"), *(ocr.get("lines") or [])] if t]
    # the matcher scores the joined text and each line separately; explain the
    # joined text, which is what usually wins
    result = explain(texts[0], catalog) if texts else {"candidates": [], "query_tokens": []}
    return {"spine_id": spine_id,
            "ocr_text": ocr.get("text", ""),
            "ocr_lines": ocr.get("lines", []),
            "stored_match": record.get("match"),
            "explained_with": "current code/config",
            "code_version": _code_version(),
            **result}


# --------------------------------------------------------------------------
# review flow -> the confirmed library (see library.py for the semantics)
# --------------------------------------------------------------------------
@app.get("/api/library")
def get_library() -> dict:
    from .library import load_library
    books = (load_library().get("books") or {})
    return {"count": len(books),
            "books": sorted(books.values(), key=lambda b: b["title"])}


@app.get("/api/runs/{run_id}/decisions")
def get_decisions(run_id: str) -> dict:
    from .library import load_decisions
    return {"decisions": load_decisions(run_id)}


@app.post("/api/review")
def review(payload: dict = Body(...)) -> dict:
    """One review decision: approve / reject_ignore / replace / manual_add /
    clear (undo a stored decision without touching the library)."""
    from .library import (add_book, clear_decision, record_decision,
                          remove_book)
    run_id = payload.get("run_id") or ""
    spine_id = payload.get("spine_id") or ""
    action = payload.get("action")
    title = (payload.get("title") or "").strip()
    author = (payload.get("author") or "").strip()
    old = payload.get("old") or {}

    if action not in ("approve", "reject_ignore", "replace", "manual_add",
                      "clear"):
        raise HTTPException(400, f"unknown action {action!r}")
    if action == "clear":
        return {"ok": True, "cleared": clear_decision(run_id, spine_id)}
    if action in ("approve", "replace", "manual_add") and not title:
        raise HTTPException(400, f"{action} needs a title")

    decision = {"action": action, "title": title, "author": author}
    if action == "approve":
        add_book(title, author, "approved",
                 {"run_id": run_id, "spine_id": spine_id})
    elif action == "manual_add":
        add_book(title, author, "approved",
                 {"run_id": run_id, "spine_id": spine_id, "manual": True})
    elif action == "reject_ignore":
        if old.get("title"):
            remove_book(old["title"], old.get("author", ""))
        decision.update(rejected_title=old.get("title", ""),
                        rejected_author=old.get("author", ""))
    elif action == "replace":
        if old.get("title"):
            remove_book(old["title"], old.get("author", ""))
        add_book(title, author, "approved",
                 {"run_id": run_id, "spine_id": spine_id,
                  "replaced": old.get("title", "")})
        decision.update(rejected_title=old.get("title", ""),
                        rejected_author=old.get("author", ""))
    if spine_id:
        record_decision(run_id, spine_id, decision)
    return {"ok": True, "decision": decision}


@app.get("/api/runs/{run_id}/alternatives/{spine_id}")
def alternatives(run_id: str, spine_id: str, exclude: str = "") -> dict:
    """Ranked replacement candidates for a rejected claim ('find better').

    Recomputes with the CURRENT retrieval chain and gates; `exclude` is a
    comma-separated list of normalized titles already rejected for this spine.
    """
    from .catalog import normalize
    from .match import explain
    record = _find_record(run_id, spine_id)
    ocr = record.get("ocr") or {}
    texts = [t for t in [ocr.get("text"), *(ocr.get("lines") or [])] if t]
    if not texts:
        return {"candidates": []}
    catalog, _ = _build_catalog()
    # exclusion is by title+author PAIR: excluding by title alone hid exactly
    # the wanted alternative when two books share a title (שהות by Salvatore
    # vs the rejected שהות by Stiefvater). `exclude` is a JSON list of
    # {title, author}; bare comma-separated titles still accepted.
    from .library import book_key
    try:
        pairs = json.loads(exclude) if exclude.strip().startswith("[") else None
    except json.JSONDecodeError:
        pairs = None
    if pairs is not None:
        excluded = {book_key(p.get("title", ""), p.get("author", ""))
                    for p in pairs}
        def is_excluded(c):
            return book_key(c["title"], c.get("author", "")) in excluded
    else:
        titles = {normalize(t) for t in exclude.split(",") if t.strip()}
        def is_excluded(c):
            return normalize(c["title"]) in titles
    out = []
    for c in explain(texts[0], catalog, limit=12)["candidates"]:
        if c["rejected"] or is_excluded(c):
            continue
        out.append({"title": c["title"], "author": c["author"],
                    "score": round(c["score"], 1)})
        if len(out) >= 5:
            break
    return {"candidates": out}


def _lan_url(port: int = 8756) -> str | None:
    """This machine's LAN address, for phone access on the same Wi-Fi.

    The UDP-connect trick: no packet is sent; the OS just picks the outbound
    interface, which is the address other devices on the network can reach.
    """
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return f"http://{ip}:{port}"
    except OSError:
        return None


@app.get("/api/health")
def health() -> dict:
    cat = _catalog_path()
    backend = os.environ.get("BOOKSNAP_CATALOG_BACKEND", "local").lower()
    return {"ok": True,
            "lan_url": _lan_url(),
            "catalog_backend": backend,
            "catalog": str(cat) if backend == "local" else "NLI search API",
            "catalog_exists": cat.exists() if backend == "local" else True,
            "nli_key_set": bool(os.environ.get("NLI_API_KEY")),
            "fallback": os.environ.get("BOOKSNAP_FALLBACK", "none").lower(),
            "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "work_dir": str(WORK), "code_version": _code_version()}


@app.on_event("startup")
def _reconcile_orphans() -> None:
    """Mark runs left mid-flight by a crash/restart as interrupted.

    Nothing is running when the process starts, so any run still recorded as
    "running" belongs to a dead worker and would otherwise sit there forever
    blocking new runs.
    """
    def fix(d):
        n = 0
        for run in d["runs"].values():
            if run.get("status") == "running":
                run.update(status="interrupted", finished_at=_now(),
                           error="server restarted while this run was in progress")
                n += 1
        for img in d["images"].values():
            if img.get("status") == "running":
                img["status"] = "new" if not img.get("summary") else "stopped"
        return n
    if _update(fix):
        pass


# Static UI last: mounting at "/" would otherwise shadow the API routes.
_STATIC = Path(__file__).resolve().parent / "static"
_STATIC.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=_STATIC, html=True), name="static")
