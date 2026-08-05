# -*- coding: utf-8 -*-
"""Stage 2 — OCR (line-based Tesseract).

For each spine crop: try both 90-degree rotations; within each, detect text
lines, crop tight, normalise height, binarise, and OCR each line with PSM 7
using the best-quality Hebrew models. Keep the rotation with the higher total
score.
"""
from __future__ import annotations
import os
import re
import time
import cv2
import numpy as np
import pytesseract
from pytesseract import Output
from skimage.filters import threshold_sauvola

from .config import CONFIG, OcrConfig
from .types import OcrResult

_HEB = re.compile(r"[\u0590-\u05FF]")


def _find_text_lines(gray: np.ndarray) -> list[tuple[int, int]]:
    """Row bands (y0, y1) likely to contain a text line, on a horizontal image."""
    H, W = gray.shape
    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    _, ink = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE,
                           cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1)))
    prof = (ink > 0).sum(axis=1) / W
    thr = max(0.06, prof.mean() * 0.8)
    lines, i = [], 0
    while i < H:
        if prof[i] > thr:
            j = i
            while j < H and prof[j] > thr * 0.5:
                j += 1
            if (j - i) >= 8:
                lines.append((max(0, i - 4), min(H, j + 4)))
            i = j
        else:
            i += 1
    merged: list[list[int]] = []
    for a, b in lines:
        if merged and a - merged[-1][1] < 6:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged if (b - a) >= 10]


def _prep(line: np.ndarray, kind: str) -> np.ndarray:
    if kind == "sauvola":
        t = threshold_sauvola(line, window_size=25, k=0.2)
        out = (line > t).astype(np.uint8) * 255
    elif kind == "clahe":
        out = cv2.createCLAHE(3.0, (8, 8)).apply(line)
    else:
        out = line
    return cv2.copyMakeBorder(out, 12, 12, 20, 20, cv2.BORDER_CONSTANT, value=255)


def _polarity(line: np.ndarray) -> np.ndarray:
    """Ensure dark text on light background."""
    return 255 - line if line.mean() < 110 else line


def _score(d: dict, cfg: OcrConfig) -> tuple[float, list[tuple[str, int]]]:
    total, words = 0.0, []
    for txt, conf in zip(d["text"], d["conf"]):
        txt = txt.strip()
        if not txt or conf == -1:
            continue
        hc = len(_HEB.findall(txt))
        if hc >= cfg.min_heb_chars and conf > cfg.min_word_conf:
            total += conf * hc
            words.append((txt, int(conf)))
    return total, words


def _set_tessdata_prefix() -> None:
    # TESSDATA_PREFIX (inherited by the tesseract subprocess via os.environ)
    # instead of a "--tessdata-dir <path>" config string: pytesseract splits
    # that string with shlex.split(config, posix=not_windows), and on Windows
    # posix=False does NOT strip quotes, so a quoted path is passed to
    # tesseract literally quotes-and-all and fails to open. Unquoted it breaks
    # on POSIX paths containing spaces. The env var has no quoting problem.
    os.environ["TESSDATA_PREFIX"] = str(CONFIG.paths.tessdata_best)
    pytesseract.pytesseract.tesseract_cmd = CONFIG.paths.tesseract_cmd


def ensure_tesseract() -> str:
    """Fail loudly if the engine or the Hebrew models are missing.

    Without this a broken install is indistinguishable from a blank shelf:
    the per-variant `except Exception: continue` below would swallow every
    error and each spine would quietly return empty text.
    """
    _set_tessdata_prefix()
    try:
        version = str(pytesseract.get_tesseract_version())
    except Exception as exc:
        raise RuntimeError(
            f"Tesseract not runnable at {CONFIG.paths.tesseract_cmd!r} ({exc}). "
            "Install it (setup.ps1 on Windows, setup.sh elsewhere) or set "
            "BOOKSNAP_TESSERACT to the binary path."
        ) from exc

    missing = [lang for lang in CONFIG.ocr.langs
               if not (CONFIG.paths.tessdata_best / f"{lang}.traineddata").exists()]
    if missing:
        raise RuntimeError(
            f"Missing Hebrew model(s) {missing} in {CONFIG.paths.tessdata_best}. "
            "Run setup.ps1 / setup.sh, or set BOOKSNAP_TESSDATA_BEST."
        )
    return version


def _ocr_line(line_gray: np.ndarray, cfg: OcrConfig) -> tuple[float, list]:
    best = (0.0, [])
    line_gray = _polarity(line_gray)
    h = line_gray.shape[0]
    _set_tessdata_prefix()
    for target_h in cfg.line_heights:
        f = target_h / h
        L = cv2.resize(line_gray, None, fx=f, fy=f,
                       interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC)
        for kind in ("clahe", "sauvola"):
            img = _prep(L, kind)
            for lang in cfg.langs:
                cfg_str = f"--psm {cfg.psm_line} -l {lang}"
                try:
                    d = pytesseract.image_to_data(img, config=cfg_str,
                                                  output_type=Output.DICT)
                except Exception:
                    continue
                s, w = _score(d, cfg)
                if s > best[0]:
                    best = (s, w)
        if best[0] > cfg.good_enough_score:
            break
    return best


def _ocr_strip(strip_gray: np.ndarray, cfg: OcrConfig) -> tuple[float, list]:
    """Whole-strip read with PSM 6. Complements line-based reads for titles
    that line-detection fragments. Uses one height + two binarizations."""
    best = (0.0, [])
    g = _polarity(strip_gray)
    h = g.shape[0]
    target_h = cfg.line_heights[-1]
    f = target_h / h
    L = cv2.resize(g, None, fx=f, fy=f,
                   interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC)
    _set_tessdata_prefix()
    for kind in ("clahe", "sauvola"):
        img = _prep(L, kind)
        for lang in cfg.langs:
            try:
                d = pytesseract.image_to_data(
                    img, config=f"--psm 6 -l {lang}",
                    output_type=Output.DICT)
            except Exception:
                continue
            s, w = _score(d, cfg)
            if s > best[0]:
                best = (s, w)
    return best


def ocr_spine(crop_path: str, spine_id: str,
              cfg: OcrConfig = CONFIG.ocr) -> OcrResult:
    started = time.monotonic()
    img = cv2.imread(str(crop_path))
    if img is None:
        return OcrResult(spine_id=spine_id)
    w = img.shape[1]
    if w > cfg.strip_max_width:
        f = cfg.strip_max_width / w
        img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)

    best: dict = {"score": 0.0, "lines": [], "words": [], "rot": None}
    for rot_name, rot_code in (("cw", cv2.ROTATE_90_CLOCKWISE),
                               ("ccw", cv2.ROTATE_90_COUNTERCLOCKWISE)):
        r = cv2.cvtColor(cv2.rotate(img, rot_code), cv2.COLOR_BGR2GRAY)
        total, all_words, texts = 0.0, [], []
        # (a) line-based reads: tight per-line crops, PSM 7
        for (a, b) in _find_text_lines(r):
            s, words = _ocr_line(r[a:b], cfg)
            if s > 0:
                total += s
                all_words += words
                texts.append(" ".join(w for w, _ in words))
        # (b) whole-strip read, PSM 6 — complementary; recovers titles that
        #     line-detection splits or merges badly (decorative fonts)
        s_strip, w_strip = _ocr_strip(r, cfg)
        if s_strip > 0:
            total += s_strip
            all_words += w_strip
            texts.append(" ".join(w for w, _ in w_strip))
        if total > best["score"]:
            best = {"score": total, "lines": texts, "words": all_words,
                    "rot": rot_name}
    # de-duplicate candidate lines while preserving order
    seen, uniq = set(), []
    for t in best["lines"]:
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    return OcrResult(
        spine_id=spine_id,
        text=" ".join(uniq),
        lines=uniq,
        score=round(best["score"]),
        rotation=best["rot"],
        words=[(w, c) for w, c in best["words"]],
        ms=round((time.monotonic() - started) * 1000),
    )
