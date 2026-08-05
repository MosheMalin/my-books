# -*- coding: utf-8 -*-
"""Stage 1 — segmentation.

Detect shelf bands, then spine boundaries within each band by combining three
column signals (long vertical edges, colour change, shadow creases), and emit
one tight crop per spine.
"""
from __future__ import annotations
import cv2
import numpy as np
from pathlib import Path
from scipy.signal import find_peaks

from .config import CONFIG, SegmentConfig
from .types import Spine


def _shelf_bands(gray: np.ndarray, cfg: SegmentConfig) -> list[tuple[int, int]]:
    """Split the image into horizontal shelf bands via long horizontal lines."""
    H, W = gray.shape
    edges = cv2.Canny(gray, 40, 120)
    kern = cv2.getStructuringElement(cv2.MORPH_RECT, (max(31, W // 12), 1))
    horiz = cv2.morphologyEx(edges, cv2.MORPH_OPEN, kern)
    horiz = cv2.morphologyEx(
        horiz, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (W // 6, 3)))
    cov = (horiz > 0).sum(axis=1) / W
    ys, i = [], 0
    while i < H:
        if cov[i] > 0.35:
            j = i
            while j < H and cov[j] > 0.35:
                j += 1
            ys.append((i + j) // 2)
            i = j
        else:
            i += 1
    merged: list[int] = []
    for y in ys:
        if merged and y - merged[-1] < H * 0.04:
            merged[-1] = (merged[-1] + y) // 2
        else:
            merged.append(y)
    edges_y = [0] + merged + [H - 1]
    return [(a, b) for a, b in zip(edges_y, edges_y[1:])
            if (b - a) > H * cfg.min_band_frac]


def _vertical_coverage(band_gray: np.ndarray) -> np.ndarray:
    """Fraction of band height covered by long vertical edges, per column."""
    H, W = band_gray.shape
    edges = cv2.Canny(band_gray, 30, 100)
    kern = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(11, H // 30)))
    vert = cv2.morphologyEx(edges, cv2.MORPH_OPEN, kern)
    vert = cv2.dilate(vert, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1)))
    vert = cv2.morphologyEx(
        vert, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(21, H // 8))))
    cov = (vert > 0).sum(axis=0) / H
    return np.convolve(cov, np.ones(7) / 7, mode="same")


def _trim_band(band_gray: np.ndarray, band_color: np.ndarray, cfg: SegmentConfig):
    """Trim empty space above/below the actual books within a band."""
    H, W = band_gray.shape
    edges = cv2.Canny(band_gray, 30, 100)
    kern = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(11, H // 30)))
    vert = cv2.morphologyEx(edges, cv2.MORPH_OPEN, kern)
    rowcov = (vert > 0).sum(axis=1) / W
    rows = np.where(rowcov > cfg.row_ink_frac)[0]
    if len(rows) < H * 0.1:
        return None
    r0, r1 = int(rows.min()), int(rows.max())
    if r1 - r0 < H * 0.2:
        return None
    return band_gray[r0:r1], band_color[r0:r1], r0


def _boundaries(band_gray, band_color, cfg: SegmentConfig, work_w: int) -> list[int]:
    """Column x-positions of spine boundaries within a (trimmed) band."""
    H, W = band_gray.shape
    cov = _vertical_coverage(band_gray)
    if cov.max() < 0.18:
        return []

    colmean = band_color.reshape(H, W, 3).mean(axis=0).astype(np.float32)
    dcol = np.abs(np.diff(colmean, axis=0)).sum(axis=1)
    dcol = np.convolve(dcol, np.ones(9) / 9, mode="same")
    dcol = np.pad(dcol, (0, W - len(dcol)))

    darkness = 255 - band_gray.mean(axis=0)
    darkness = np.convolve(darkness, np.ones(9) / 9, mode="same")

    def norm(v):
        v = v - v.min()
        return v / (v.max() + 1e-6)

    signal = (cfg.w_coverage * norm(cov)
              + cfg.w_colour * norm(dcol)
              + cfg.w_darkness * norm(darkness))
    min_spine = int(work_w * cfg.min_spine_frac)
    peaks, _ = find_peaks(signal, distance=min_spine,
                          prominence=cfg.peak_prominence * signal.max())
    bounds = sorted(int(p) for p in peaks)
    if len(bounds) < 2:
        return []
    if bounds[0] > min_spine * 2:
        bounds.insert(0, 0)
    if bounds[-1] < W - min_spine * 2:
        bounds.append(W - 1)
    return bounds


def segment_image(path: str | Path, crops_dir: Path,
                  debug_dir: Path | None = None,
                  cfg: SegmentConfig = CONFIG.segment) -> list[Spine]:
    """Segment one shelf photo into spines, writing crops. Returns Spine list."""
    path = Path(path)
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(path)
    scale = cfg.work_width / img.shape[1]
    small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.createCLAHE(2.0, (8, 8)).apply(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
    Hs, Ws = gray.shape

    dbg = small.copy() if debug_dir else None
    spines: list[Spine] = []
    for bi, (y0, y1) in enumerate(_shelf_bands(gray, cfg)):
        trimmed = _trim_band(gray[y0:y1], small[y0:y1], cfg)
        if trimmed is None:
            continue
        tg, tc, roff = trimmed
        bounds = _boundaries(tg, tc, cfg, cfg.work_width)
        if not bounds:
            continue
        by0, by1 = y0 + roff, y0 + roff + tg.shape[0]
        if dbg is not None:
            cv2.rectangle(dbg, (2, by0), (Ws - 3, by1), (0, 255, 0), 3)
            for x in bounds:
                cv2.line(dbg, (x, by0), (x, by1), (0, 0, 255), 3)
        for si, (xa, xb) in enumerate(zip(bounds, bounds[1:])):
            X0, X1 = int(xa / scale), int(xb / scale)
            Y0, Y1 = int(by0 / scale), int(by1 / scale)
            pad = int((X1 - X0) * cfg.crop_pad_frac)
            crop = img[Y0:Y1, max(0, X0 - pad):min(img.shape[1], X1 + pad)]
            sp = Spine(image=path.name, band=bi, index=si,
                       x0=X0, x1=X1, y0=Y0, y1=Y1)
            cpath = crops_dir / f"{sp.spine_id}.jpg"
            cv2.imwrite(str(cpath), crop)
            sp.crop_path = str(cpath)
            spines.append(sp)
    if dbg is not None:
        cv2.imwrite(str(Path(debug_dir) / f"{path.stem}_seg.jpg"),
                    cv2.resize(dbg, None, fx=0.7, fy=0.7))
    return spines
