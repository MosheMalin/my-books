# -*- coding: utf-8 -*-
"""Shared datatypes passed between pipeline stages."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, Any


@dataclass
class Spine:
    """One detected book spine: its location and crop path."""
    image: str            # source photo filename
    band: int             # shelf band index within the photo
    index: int            # spine index within the band
    x0: int
    x1: int
    y0: int
    y1: int
    crop_path: str = ""

    @property
    def spine_id(self) -> str:
        stem = self.image.rsplit(".", 1)[0]
        return f"{stem}_b{self.band}_s{self.index:02d}"


@dataclass
class OcrResult:
    """OCR output for one spine."""
    spine_id: str
    text: str = ""                        # all lines joined
    lines: list[str] = field(default_factory=list)
    score: int = 0                        # confidence*heb-chars, summed
    rotation: Optional[str] = None        # 'cw' or 'ccw'
    engine: str = "tesseract"             # which engine produced this
    words: list[tuple[str, int]] = field(default_factory=list)
    ms: int = 0                           # wall-clock cost of this spine's OCR


@dataclass
class Match:
    """A catalog match for one spine."""
    title: str
    author: str
    tier: str                             # 'AUTO' or 'REVIEW'
    score: float
    matched_text: str = ""                # the OCR candidate that triggered it
    catalog_id: Optional[str] = None


@dataclass
class SpineRecord:
    """Everything known about one spine after the full pipeline."""
    spine: Spine
    ocr: Optional[OcrResult] = None
    match: Optional[Match] = None
    needs_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "spine_id": self.spine.spine_id,
            "location": {"image": self.spine.image, "band": self.spine.band,
                         "index": self.spine.index,
                         "box": [self.spine.x0, self.spine.y0,
                                 self.spine.x1, self.spine.y1]},
            "crop_path": self.spine.crop_path,
            "ocr": asdict(self.ocr) if self.ocr else None,
            "match": asdict(self.match) if self.match else None,
            "needs_fallback": self.needs_fallback,
        }
