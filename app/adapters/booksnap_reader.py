# -*- coding: utf-8 -*-
"""BooksnapReader — the Reader port implemented over ``booksnap.Pipeline``
(P2.4).

Modelled on ``booksnap/server.py``'s ``_build_catalog`` / ``_build_fallback``
/ ``_build_page_reader`` / ``_run_job`` — copied, not imported. Plan P2.4 says
"strangle, don't refactor": the tuning server is the accuracy asset, and this
file must never be able to break it by editing ``booksnap/*``. Two copies of
"build a retrieval chain for a read" is the intended cost.

The engine takes image PATHS on disk; ``BlobStore`` gives BYTES. Every call to
:meth:`read` materialises each request's bytes into a temp file, runs the
pipeline, and cleans up — the engine never learns that "the filesystem" here
is actually a content-addressed blob store.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Sequence

from booksnap.catalog import LocalCatalog
from booksnap.config import CONFIG, REPO_ROOT
from booksnap.pipeline import Pipeline

from app.domain import LibraryRef
from app.ports.blobs import BlobStore
from app.ports.reader import ReadClaim, ReadRequest

# booksnap.types.Match.tier -> this port's lower-case vocabulary. A spine
# with no match at all (`match is None`) is "unmatched", handled below rather
# than in this table.
_TIER = {"AUTO": "auto", "REVIEW": "review"}


class BooksnapReader:
    """Implements ``app.ports.reader.Reader``."""

    def __init__(self, blob_store: BlobStore) -> None:
        self.blob_store = blob_store

    # --- Reader ------------------------------------------------------------

    def read(
        self,
        library: LibraryRef,
        requests: Sequence[ReadRequest],
        *,
        mode: str,
        progress: Callable[[dict], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[ReadClaim]:
        if not requests:
            return []
        catalog, fallback, page_reader = self._build(mode)

        with tempfile.TemporaryDirectory(prefix="booksnap-read-") as tmp:
            tmp_dir = Path(tmp)
            paths: list[Path] = []
            by_stem: dict[str, str] = {}   # temp file stem -> capture_id
            for req in requests:
                blob = self.blob_store.stat(library, req.image_key)
                data = self.blob_store.read(library, req.image_key)
                if blob is None or data is None:
                    # A capture whose photo was deleted (P2.3's recorded gap)
                    # — skip it rather than fail the whole read; the other
                    # captures at this depth are still real evidence.
                    continue
                ext = blob.key.rsplit(".", 1)[-1] if "." in blob.key else "jpg"
                # capture_id becomes the stem, so a SpineRecord's
                # `spine.image` (booksnap names it after the source file) maps
                # straight back to the capture that produced it — no side
                # channel needed. IdGen-minted ids never contain a dot.
                p = tmp_dir / f"{req.capture_id}.{ext}"
                p.write_bytes(data)
                paths.append(p)
                by_stem[p.stem] = req.capture_id

            crops_dir = tmp_dir / "crops"
            pipe = Pipeline(catalog=catalog, fallback=fallback,
                            page_reader=page_reader, config=CONFIG,
                            crops_dir=crops_dir)
            records = pipe.run(
                paths, use_fallback=fallback is not None, progress=progress,
                should_stop=should_stop, mode=mode,
            )

            claims: list[ReadClaim] = []
            for rec in records:
                stem = rec.spine.image.rsplit(".", 1)[0]
                capture_id = by_stem.get(stem, stem)
                crop = None
                if rec.spine.crop_path and Path(rec.spine.crop_path).exists():
                    crop = Path(rec.spine.crop_path).read_bytes()
                match = rec.match
                claims.append(ReadClaim(
                    spine_id=rec.spine.spine_id,
                    capture_id=capture_id,
                    text=rec.ocr.text if rec.ocr else "",
                    title=match.title if match else "",
                    author=match.author if match else "",
                    tier=(_TIER.get(match.tier, "unmatched") if match
                          else "unmatched"),
                    score=match.score if match else 0.0,
                    catalog_id=match.catalog_id if match else None,
                    crop=crop,
                    box=(rec.spine.x0, rec.spine.y0, rec.spine.x1, rec.spine.y1),
                ))
            return claims

    def code_version(self) -> dict[str, Any]:
        """Git sha + dirty flag — same shape and reasoning as
        ``booksnap/server.py``'s ``_code_version``: while developing, the
        interesting changes are usually uncommitted, so a sha alone would
        alias two reads that behaved differently."""
        return {"sha": self._git("rev-parse", "--short", "HEAD"),
                "branch": self._git("rev-parse", "--abbrev-ref", "HEAD"),
                "dirty": bool(self._git("status", "--porcelain"))}

    def config_snapshot(self) -> dict[str, Any]:
        """Every tunable, as it stood for this read — same idea as the
        tuning server's per-run config snapshot (CLAUDE.md "Run history")."""
        return asdict(CONFIG, dict_factory=lambda kv: {k: _jsonable(v) for k, v in kv})

    # --- internals -----------------------------------------------------------

    @staticmethod
    def _git(*args: str) -> str:
        try:
            out = subprocess.run(["git", *args], cwd=REPO_ROOT,
                                 capture_output=True, text=True, timeout=5)
            return out.stdout.strip() if out.returncode == 0 else ""
        except Exception:
            return ""

    def _build(self, mode: str):
        """Retrieval chain + fallback + page reader for one read.

        Deliberately NARROWER than ``booksnap/server.py``'s
        ``_build_catalog``: that function also wires an experimental
        Simania/Rebooks/Booksefer chain (``BOOKSNAP_CATALOG_BACKEND=simania``)
        that is prototype-grade and not part of the measured baseline
        CLAUDE.md documents. Copying it here would duplicate untested surface
        for no product benefit; the two backends that ARE documented as
        measured (``local``, ``nli``) are what this reads. Promote the wider
        chain here the same way CLAUDE.md says to promote any new retrieval
        source into ``_build_catalog``'s baseline — after a measured win, not
        by default. (Judgment call — flag if the product needs the wider
        chain sooner than accuracy work promotes it.)
        """
        backend = os.environ.get("BOOKSNAP_CATALOG_BACKEND", "local").lower()
        if backend == "nli":
            from booksnap.nli_catalog import NLICatalog
            key = os.environ.get("NLI_API_KEY", "")
            if not key:
                raise RuntimeError(
                    "BOOKSNAP_CATALOG_BACKEND=nli but NLI_API_KEY is not set."
                )
            catalog = NLICatalog(cache_dir=CONFIG.paths.work_dir / "nli_cache")
        else:
            cat_path = Path(os.environ.get(
                "BOOKSNAP_CATALOG", REPO_ROOT / "sample_catalog.json"))
            catalog = LocalCatalog.from_json(cat_path)

        fallback = None
        fb_name = os.environ.get("BOOKSNAP_FALLBACK", "none").lower()
        if fb_name == "google_vision":
            from google.cloud import vision
            from booksnap.fallback import GoogleVisionFallback
            fallback = GoogleVisionFallback(vision.ImageAnnotatorClient(),
                                            image_ctor=vision.Image)

        page_reader = None
        if mode == "llmpage":
            from booksnap.llmreader import ClaudePageReader
            page_reader = ClaudePageReader()
        elif mode == "fullpage":
            from google.cloud import vision
            from booksnap.pagereader import GoogleVisionPageReader
            page_reader = GoogleVisionPageReader(vision.ImageAnnotatorClient(),
                                                 image_ctor=vision.Image)

        return catalog, fallback, page_reader


def _jsonable(v: Any) -> Any:
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, (set, frozenset)):
        return sorted(v)
    if isinstance(v, tuple):
        return list(v)
    return v
