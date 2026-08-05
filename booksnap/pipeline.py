# -*- coding: utf-8 -*-
"""Pipeline orchestrator — the single entrypoint that ties the stages together.

    from booksnap.pipeline import Pipeline
    from booksnap.catalog import LocalCatalog
    pipe = Pipeline(catalog=LocalCatalog.from_json("sample_catalog.json"))
    records = pipe.run(["shelf1.jpg", "shelf2.jpg"])
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Callable, Iterable, Optional

from .config import CONFIG, Config
from .catalog import Catalog
from .fallback import Fallback, NullFallback
from .segment import segment_image
from .ocr import ocr_spine
from .match import (match_spine, match_candidate, resolve_duplicates,
                    candidates_for_spine, resolve_assignment)
from .types import Spine, OcrResult, SpineRecord


_TRUNCATION_MARKS = ("...", "…")     # how LLM reads mark a cut-off title


def _is_truncated(text: str) -> bool:
    return any(m in text for m in _TRUNCATION_MARKS)


class Pipeline:
    def __init__(self, catalog: Catalog,
                 fallback: Fallback | None = None,
                 config: Config = CONFIG,
                 debug: bool = False,
                 crops_dir: str | Path | None = None,
                 page_reader=None):
        self.catalog = catalog
        self.fallback = fallback or NullFallback()
        # optional PageReader (see pagereader.py) enabling mode="fullpage"
        self.page_reader = page_reader
        self.cfg = config
        self.debug = debug
        # Callers keeping a run history point this at a per-run directory:
        # segmentation changes between runs, so a shared crops dir would
        # overwrite the crops an earlier run's results refer to.
        self.crops_dir = Path(crops_dir) if crops_dir else self.cfg.paths.work_dir / "crops"
        self.cfg.paths.ensure()

    # -- individual stages, exposed for testing / partial runs ---------------
    def segment(self, image_path: str | Path):
        debug_dir = self.cfg.paths.work_dir / "debug" if self.debug else None
        self.crops_dir.mkdir(parents=True, exist_ok=True)
        return segment_image(image_path, self.crops_dir, debug_dir, self.cfg.segment)

    def ocr(self, spine):
        return ocr_spine(spine.crop_path, spine.spine_id, self.cfg.ocr)

    def match(self, ocr):
        return match_spine(ocr, self.catalog, self.cfg.match)

    def match_all(self, ocrs) -> list:
        """Match a whole photo's spines together.

        Global assignment when enabled (spines compete for catalog entries),
        otherwise the original per-spine best + duplicate demotion.
        """
        if self.cfg.match.use_assignment:
            return resolve_assignment(
                [candidates_for_spine(o, self.catalog, self.cfg.match) for o in ocrs],
                self.cfg.match)
        return resolve_duplicates(
            [match_spine(o, self.catalog, self.cfg.match) for o in ocrs],
            self.cfg.match)

    def run_fallback(self, record: SpineRecord) -> SpineRecord:
        fr = self.fallback.read_spine(record.spine.crop_path)
        if fr.title:                       # structured provider
            from .types import Match
            record.match = Match(title=fr.title, author=fr.author or "",
                                 tier="REVIEW", score=0.0,
                                 matched_text=f"[{fr.provider}]")
        elif fr.text:                      # text provider -> re-match
            m = match_candidate(fr.text, self.catalog, self.cfg.match)
            if m:
                m.matched_text = f"[{fr.provider}] {fr.text[:40]}"
                record.match = m
        record.needs_fallback = record.match is None
        return record

    # -- whole-page mode -----------------------------------------------------
    def run_page(self, image_path: str | Path,
                 progress: Optional[Callable[[dict], None]] = None
                 ) -> list[SpineRecord]:
        """One OCR call for the whole photo; each text block becomes a record.

        Measured to beat per-spine cropping on both accuracy and cost (see
        pagereader.py). Vision's bounding boxes are cropped back out of the
        original image so the review UI still has a picture per title.
        """
        import cv2
        if self.page_reader is None:
            raise RuntimeError(
                "page mode needs a page_reader (fullpage: set "
                "BOOKSNAP_FALLBACK=google_vision; llmpage: set ANTHROPIC_API_KEY)")

        image_path = Path(image_path)
        # reading is the first long phase — let a reader that supports it
        # report per-tile progress instead of one silent multi-minute gap
        if progress and hasattr(self.page_reader, "progress"):
            self.page_reader.progress = progress
        blocks = self.page_reader.read_page(str(image_path))
        if progress:
            progress({"stage": "page_read", "image": str(image_path),
                      "spines": len(blocks)})

        img = cv2.imread(str(image_path))
        H, W = (img.shape[:2] if img is not None else (0, 0))
        self.crops_dir.mkdir(parents=True, exist_ok=True)

        records: list[SpineRecord] = []
        matches_in: list = []
        spines: list[Spine] = []
        ocrs: list[OcrResult] = []

        for i, b in enumerate(blocks):
            spine = Spine(image=image_path.name, band=0, index=i,
                          x0=b.x0, y0=b.y0, x1=b.x1, y1=b.y1)
            if img is not None:
                pad = 6
                y0, y1 = max(0, b.y0 - pad), min(H, b.y1 + pad)
                x0, x1 = max(0, b.x0 - pad), min(W, b.x1 + pad)
                if y1 > y0 and x1 > x0:
                    crop = img[y0:y1, x0:x1]
                    p = self.crops_dir / f"{spine.spine_id}.jpg"
                    cv2.imwrite(str(p), crop)
                    spine.crop_path = str(p)
            spines.append(spine)
            ocrs.append(OcrResult(
                spine_id=spine.spine_id, text=b.text, lines=[b.text],
                score=round(b.confidence * 100),
                engine=getattr(self.page_reader, "engine_name",
                               "google_vision_page")))
        from .match import (match_spine, resolve_duplicates,
                            resolve_near_duplicates, suppress_author_fragments,
                            suppress_fragment_reads)
        # matching is the second long phase (catalog lookups per block, each
        # rate-limited) — report per-block progress rather than stalling
        if self.cfg.match.use_assignment:
            matches = self.match_all(ocrs)
        else:
            matches = []
            for i, o in enumerate(ocrs):
                matches.append(match_spine(o, self.catalog, self.cfg.match))
                if progress:
                    progress({"stage": "matching", "image": str(image_path),
                              "done": i + 1, "total": len(ocrs)})
            matches = resolve_duplicates(matches, self.cfg.match)
        # page-mode extras (tile overlap + block fragmentation, see match.py):
        # a weaker claim naming the same book via a different catalog edition
        # is dropped; a partial re-read of an already-matched spine can't
        # claim its own record; a read that is purely another book's author
        # name cannot claim a title of its own.
        texts = [o.text for o in ocrs]
        matches = resolve_near_duplicates(matches)
        matches = suppress_fragment_reads(texts, matches)
        matches = suppress_author_fragments(texts, matches)
        for spine, ocr, match in zip(spines, ocrs, matches):
            # A read the model itself marked as cut off ("כל הדברים... נבונים
            # כמופ...") is real evidence but partial evidence: on the E2
            # measurement every truncated read that went AUTO matched a wrong
            # (shorter) title. Cap them at REVIEW — a human confirms partials.
            if match and match.tier == "AUTO" and _is_truncated(ocr.text):
                match.tier = "REVIEW"
            records.append(SpineRecord(spine=spine, ocr=ocr, match=match,
                                       needs_fallback=match is None))
        return records

    # -- full pipeline -------------------------------------------------------
    def run(self, image_paths: Iterable[str | Path],
            use_fallback: bool = False,
            progress: Optional[Callable[[dict], None]] = None,
            should_stop: Optional[Callable[[], bool]] = None,
            mode: str = "spines") -> list[SpineRecord]:
        """Run every stage over `image_paths`.

        `progress`, if given, is called with small dicts as work completes.
        OCR dominates the runtime (~10s/spine), so a long-running caller (the
        server) needs per-spine feedback rather than one result at the end.

        `should_stop`, if given, is polled between spines; when it turns true
        the run ends early and the spines already read are matched and
        returned. Partial results are real results — a stopped run still
        yields usable rows for every spine it got to.
        """
        from .match import resolve_duplicates

        def emit(**ev):
            if progress:
                progress(ev)

        stop = should_stop or (lambda: False)

        if mode in ("fullpage", "llmpage"):
            # same whole-photo path; only the injected page_reader differs
            # (Google Vision paragraphs vs LLM tile reading)
            records = []
            for img in image_paths:
                if stop():
                    break
                records += self.run_page(img, progress=progress)
            return records
        if mode != "spines":
            raise ValueError(
                f"unknown mode {mode!r} (use 'spines', 'fullpage' or 'llmpage')")

        from .ocr import ensure_tesseract
        ensure_tesseract()      # preflight: a broken install must not look like
                                # a shelf full of unreadable spines

        records: list[SpineRecord] = []
        for img in image_paths:
            if stop():
                break
            spines = self.segment(img)
            emit(stage="segmented", image=str(img), spines=len(spines))
            ocrs = []
            for i, s in enumerate(spines):
                if stop():
                    emit(stage="stopped", image=str(img),
                         done=len(ocrs), total=len(spines))
                    break
                ocrs.append(self.ocr(s))
                emit(stage="ocr", image=str(img), done=i + 1, total=len(spines))
            # only the spines actually read take part in matching/dedup
            done_spines = spines[:len(ocrs)]
            matches = self.match_all(ocrs)
            for spine, ocr, match in zip(done_spines, ocrs, matches):
                rec = SpineRecord(spine=spine, ocr=ocr, match=match,
                                  needs_fallback=match is None)
                if use_fallback and rec.needs_fallback:
                    rec = self.run_fallback(rec)
                records.append(rec)
        return records

    @staticmethod
    def save(records: list[SpineRecord], path: str | Path) -> None:
        Path(path).write_text(
            json.dumps([r.to_dict() for r in records], ensure_ascii=False, indent=1),
            encoding="utf-8")
