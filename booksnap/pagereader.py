# -*- coding: utf-8 -*-
"""Whole-page OCR seam (alternative to per-spine cropping).

Measured on IMG_6082 (see CLAUDE.md): sending the *whole shelf photo* to Google
Vision in one call read more books, and read them better, than 26 separate
per-spine calls — because a 190px-wide vertical strip throws away the page
layout context the engine relies on. It is also ~26x cheaper (one billable
unit per photo instead of one per spine).

This module defines the seam only: a `PageReader` protocol returning text
blocks with bounding boxes, plus a Google Vision implementation. Boxes matter —
they let the pipeline crop each detected book back out of the original photo,
so the review UI still shows a picture next to every title.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class PageBlock:
    """One text region found on a page, in original-image pixel coordinates."""
    text: str
    x0: int
    y0: int
    x1: int
    y1: int
    confidence: float = 0.0

    @property
    def is_vertical(self) -> bool:
        return (self.y1 - self.y0) > (self.x1 - self.x0)


def _overlap_frac(a: PageBlock, b: PageBlock) -> float:
    """Intersection area as a fraction of the SMALLER box."""
    ix = max(0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0, min(a.y1, b.y1) - max(a.y0, b.y0))
    inter = ix * iy
    if not inter:
        return 0.0
    small = min((a.x1 - a.x0) * (a.y1 - a.y0), (b.x1 - b.x0) * (b.y1 - b.y0))
    return inter / small if small else 0.0


def merge_overlapping(blocks: list[PageBlock], thresh: float = 0.35
                      ) -> list[PageBlock]:
    """Merge text blocks that occupy the same physical spine.

    Books are solid objects: two texts sharing a region of the photo are two
    parts of ONE spine, not two books. Vision routinely emits the author and
    the title as separate paragraphs, and imprint text as a third — which is
    how a 14-book shelf came back with 24 reported books. Merging first means
    those compete as one candidate string instead of each claiming its own
    title.

    Overlap is measured against the smaller box so a small imprint block fully
    inside a spine merges even though it covers little of the larger box.
    """
    out: list[PageBlock] = []
    for b in sorted(blocks, key=lambda z: (z.x0, z.y0)):
        for i, kept in enumerate(out):
            if _overlap_frac(kept, b) >= thresh:
                out[i] = PageBlock(
                    text=f"{kept.text} {b.text}".strip(),
                    x0=min(kept.x0, b.x0), y0=min(kept.y0, b.y0),
                    x1=max(kept.x1, b.x1), y1=max(kept.y1, b.y1),
                    confidence=max(kept.confidence, b.confidence))
                break
        else:
            out.append(b)
    return out


class PageReader(Protocol):
    def read_page(self, image_path: str) -> list[PageBlock]:
        """Read a whole photo and return its text blocks."""
        ...


class GoogleVisionPageReader:
    """Whole-image `DOCUMENT_TEXT_DETECTION`, grouped into paragraphs.

    On a shelf photo each spine's text typically lands in its own paragraph,
    so paragraphs map to books far more cleanly than our classical segmenter
    manages — and Vision handles the 90-degree rotation itself, so no
    pre-rotation is needed (verified: rotating the input changed nothing).

    `client` is injected, so this is unit-testable with no SDK installed: any
    object with `document_text_detection(image=...)` works.
    """

    def __init__(self, client, image_ctor=None, min_chars: int = 6,
                 merge_overlap: float = 0.35):
        self._client = client
        self._image_ctor = image_ctor
        self.min_chars = min_chars
        # 0 disables merging (kept so the effect can be A/B'd)
        self.merge_overlap = merge_overlap

    def read_page(self, image_path: str) -> list[PageBlock]:
        with open(image_path, "rb") as f:
            content = f.read()
        image = self._image_ctor(content=content) if self._image_ctor \
            else {"content": content}
        resp = self._client.document_text_detection(image=image)
        if getattr(getattr(resp, "error", None), "message", ""):
            raise RuntimeError(f"vision: {resp.error.message}")

        blocks: list[PageBlock] = []
        annotation = getattr(resp, "full_text_annotation", None)
        for page in getattr(annotation, "pages", []) or []:
            for block in getattr(page, "blocks", []) or []:
                for para in getattr(block, "paragraphs", []) or []:
                    text = _paragraph_text(para)
                    if len(text) < self.min_chars:
                        continue
                    xs, ys = _vertices(para)
                    if not xs:
                        continue
                    blocks.append(PageBlock(
                        text=text, x0=min(xs), y0=min(ys),
                        x1=max(xs), y1=max(ys),
                        confidence=float(getattr(para, "confidence", 0.0) or 0.0),
                    ))
        if self.merge_overlap > 0:
            blocks = merge_overlapping(blocks, self.merge_overlap)
        return blocks


def _paragraph_text(para) -> str:
    """Rebuild a paragraph's text from its symbols, honouring break hints."""
    out: list[str] = []
    for word in getattr(para, "words", []) or []:
        for sym in getattr(word, "symbols", []) or []:
            out.append(getattr(sym, "text", "") or "")
            brk = getattr(getattr(sym, "property", None), "detected_break", None)
            if brk is not None and getattr(brk, "type_", None):
                out.append(" ")
        out.append(" ")
    return " ".join("".join(out).split())


def _vertices(para):
    box = getattr(para, "bounding_box", None)
    verts = getattr(box, "vertices", None) or getattr(box, "normalized_vertices", None) or []
    xs = [int(getattr(v, "x", 0) or 0) for v in verts]
    ys = [int(getattr(v, "y", 0) or 0) for v in verts]
    return xs, ys
