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
from booksnap.match import explain
from booksnap.pipeline import Pipeline

from app.domain import LibraryRef
from app.ports.blobs import BlobStore
from app.ports.reader import ReadAlternative, ReadClaim, ReadRequest
from app.ports.store import BookStore

# booksnap.types.Match.tier -> this port's lower-case vocabulary. A spine
# with no match at all (`match is None`) is "unmatched", handled below rather
# than in this table.
_TIER = {"AUTO": "auto", "REVIEW": "review"}

# How many ranked candidates the review UI's "why?" panel gets per claim.
# explain()'s own default (6) minus the winner, kept modest — this rides on
# every claim in a Read's JSON, so it is payload, not just computation.
_MAX_ALTERNATIVES = 5


class BooksnapReader:
    """Implements ``app.ports.reader.Reader``."""

    def __init__(self, blob_store: BlobStore,
                 book_store: BookStore | None = None) -> None:
        self.blob_store = blob_store
        # Optional so a caller that only wants `code_version()`/`unavailable()`
        # need not build one. Without it the confirmed library simply does not
        # join the retrieval chain — a measurable loss, not a broken read.
        self.book_store = book_store

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
        catalog, fallback, page_reader = self._build(mode, library)

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
                    alternatives=self._alternatives(rec, catalog, match),
                ))
            return claims

    @staticmethod
    def _alternatives(rec, catalog, match) -> tuple[ReadAlternative, ...]:
        """Ranked runners-up for one spine's OCR text, for the review UI's
        "why?" (P2.7, UI_PLAN §4).

        Re-runs `booksnap.match.explain()` against the SAME query text
        `pipe.run` already sent this `catalog` — for `NLICatalog` that means
        `catalog.candidates(text)` answers from its on-disk query cache
        (CLAUDE.md), never a second live lookup, which is what keeps this
        free under the "deterministic first" cost philosophy. No OCR text, no
        candidates to explain.
        """
        if rec.ocr is None or not rec.ocr.text:
            return ()
        info = explain(rec.ocr.text, catalog, limit=_MAX_ALTERNATIVES + 1)
        winner_id = match.catalog_id if match else None
        out = []
        for c in info["candidates"]:
            if winner_id is not None and c["id"] == winner_id:
                continue   # the accepted match is shown as the claim itself
            out.append(ReadAlternative(
                title=c["title"], author=c["author"], score=c["score"],
                reason=c["rejected"] or "",
            ))
            if len(out) >= _MAX_ALTERNATIVES:
                break
        return tuple(out)

    # What each mode needs from the environment, and the sentence the owner
    # sees if it is missing. This adapter is the ONLY place that knows the
    # mapping: the route asks `unavailable()` and prints the answer, so it
    # never learns which engine wants which key.
    #
    # `spines` is absent on purpose — Tesseract is the free offline path, and
    # it stays the answer when no credential exists at all.
    _CREDENTIALS: dict[str, tuple[str, str]] = {
        "llmpage": (
            "ANTHROPIC_API_KEY",
            "LLM reading needs ANTHROPIC_API_KEY — put it in .env at the repo "
            "root and restart the server. Until then, use 'split to spines' "
            "(free, offline).",
        ),
        "fullpage": (
            "GOOGLE_APPLICATION_CREDENTIALS",
            "Whole-photo reading needs GOOGLE_APPLICATION_CREDENTIALS — put "
            "the path to the service-account JSON in .env at the repo root "
            "and restart the server. Until then, use 'split to spines' (free, "
            "offline).",
        ),
    }

    def unavailable(self, mode: str) -> str | None:
        """Why ``mode`` cannot run, or ``None``. See the port for the why.

        Checked against the environment as it stands NOW rather than cached at
        construction: `.env` is read at import, but a key can also be exported
        into a running shell, and a preflight that lies is worse than none.
        """
        if mode not in ("spines", "fullpage", "llmpage"):
            return (f"unknown reading mode {mode!r} — "
                    "expected 'spines', 'fullpage' or 'llmpage'")
        needed = self._CREDENTIALS.get(mode)
        if needed and not os.environ.get(needed[0]):
            return needed[1]
        return None

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

    def _build(self, mode: str, library: LibraryRef | None = None):
        """Retrieval chain + fallback + page reader for one read.

        A COPY of ``booksnap/server.py``'s ``_build_catalog``, not an import —
        the product must not import the tuning server (H1). Kept deliberately
        in step with it: the chain IS the measured baseline, so the two must
        not drift.

        ⚠ **This is what "no books" looked like.** An earlier version had only
        ``nli`` and a ``local`` fallthrough, on the reading that the
        Simania/Rebooks/Booksefer chain was "prototype-grade and not part of
        the measured baseline". That was backwards: `local` is
        ``sample_catalog.json``, the **57-entry hand-typed stand-in** from
        early prototyping, and the simania chain is exactly what every measured
        number in CLAUDE.md was produced with (`sweep --live --sources
        simania,nli,...`, baseline row 20260806-142543). So a correctly-set
        ``BOOKSNAP_CATALOG_BACKEND=simania`` fell through to a 57-book catalog
        and a real shelf of 69 read spines matched **nothing**. The engine was
        never at fault; the product handed it a toy catalog.

        Two rules fall out of that and are worth keeping:

          - the DEFAULT is the real chain. A product whose out-of-the-box
            catalog is a 57-entry stand-in is broken for its actual purpose,
            and `local` is now opt-in for offline/dev work;
          - an unrecognised backend **raises**. Silently degrading to the
            stand-in is what turned a one-line config gap into an afternoon of
            "why does the engine find nothing".
        """
        backend = os.environ.get("BOOKSNAP_CATALOG_BACKEND", "simania").lower()
        if backend == "simania":
            catalog = self._chain(library)
        elif backend == "nli":
            from booksnap.nli_catalog import NLICatalog
            key = os.environ.get("NLI_API_KEY", "")
            if not key:
                raise RuntimeError(
                    "BOOKSNAP_CATALOG_BACKEND=nli but NLI_API_KEY is not set."
                )
            catalog = NLICatalog(cache_dir=CONFIG.paths.work_dir / "nli_cache")
        elif backend == "local":
            cat_path = Path(os.environ.get(
                "BOOKSNAP_CATALOG", REPO_ROOT / "sample_catalog.json"))
            catalog = LocalCatalog.from_json(cat_path)
        else:
            raise RuntimeError(
                f"BOOKSNAP_CATALOG_BACKEND={backend!r} is not a backend this "
                "reads (expected 'simania', 'nli' or 'local'). Refusing rather "
                "than falling back to the 57-entry sample catalog, which reads "
                "a real shelf as zero books."
            )

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

    def _chain(self, library: LibraryRef | None):
        """The measured retrieval chain, precise -> broad, each source
        on-empty. Copied from ``booksnap/server.py:_build_catalog``.

        Simania (edition-true Hebrew spellings, series metadata) -> NLI (legal
        deposit authority) -> the used-book shops (out-of-print residue like
        old SF that neither of the first two carries).

        The primaries are ALWAYS unioned rather than cascaded: a thin union let
        junk block exact hits (see ``UnionCatalog``). The shop tail joins only
        when that union comes back thin.

        The confirmed library is unioned in FRONT of all of it — a book the
        owner confirmed once should match instantly on every later shelf — but
        via the product's OWN books (``ProductLibraryCatalog``), never
        ``booksnap.library.ConfirmedCatalog``, which reads the tuning server's
        ``work/library.json``. Same idea, correct store.
        """
        from booksnap.extra_catalogs import (BooksferCatalog, ChainCatalog,
                                             RebooksCatalog, UnionCatalog)
        from booksnap.library import LibraryFirstCatalog
        from booksnap.simania_catalog import SimaniaCatalog

        work = CONFIG.paths.work_dir
        primaries = [SimaniaCatalog(cache_dir=work / "simania_cache")]
        if os.environ.get("NLI_API_KEY"):
            from booksnap.nli_catalog import NLICatalog
            primaries.append(NLICatalog(cache_dir=work / "nli_cache"))

        chain = ChainCatalog([
            UnionCatalog(primaries),
            RebooksCatalog(cache_dir=work / "rebooks_cache"),
            BooksferCatalog(cache_dir=work / "booksefer_cache"),
        ])
        if self.book_store is None or library is None:
            return chain
        from app.adapters.library_catalog import ProductLibraryCatalog
        return LibraryFirstCatalog(
            ProductLibraryCatalog(self.book_store, library), chain)


def _jsonable(v: Any) -> Any:
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, (set, frozenset)):
        return sorted(v)
    if isinstance(v, tuple):
        return list(v)
    return v
