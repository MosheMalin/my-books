# -*- coding: utf-8 -*-
"""Whole-photo reading with a vision LLM (mode='llmpage').

Implements the same `PageReader` seam as pagereader.py, so `Pipeline.run_page`
drives it unchanged: each proposed book becomes a PageBlock whose text is
"<title> <author>", and the matcher + NLI verification downstream decide what
is real. The LLM is a CANDIDATE GENERATOR here, never an authority — a
confabulated title has to survive catalog retrieval and the evidence gates
before it can reach the user, and even then lands in REVIEW at worst.

Preprocessing is load-bearing (measured, see LlmReaderConfig): the photo is
rotated 90° so vertical spine text reads horizontally, and split into
overlapping tiles so each spine keeps near-native resolution instead of being
downscaled into illegibility.

The API call is injected (`send`), so this module is unit-testable offline and
never touches credentials itself; the default transport reads
ANTHROPIC_API_KEY from the environment via the anthropic SDK.
"""
from __future__ import annotations

import base64
import io
import json
from typing import Callable, Optional

from .config import CONFIG, LlmReaderConfig
from .catalog import normalize
from .pagereader import PageBlock

PROMPT = (
    "This is part of a photograph of a bookshelf holding printed Hebrew (and "
    "occasionally English) books. Read the book spines and list every distinct "
    "book you can actually read: the title and, if printed and legible, the "
    "author, exactly as they appear on the spine. Rules: (1) only include a "
    "book if you can genuinely read its title on the spine — never guess or "
    "complete a title from your knowledge of what book it might be; (2) if the "
    "author is not visible, use an empty string; (3) publisher names and series "
    "names are not titles; (4) stylised or decorative lettering still counts if "
    "you can read it; (5) one entry per physical book; (6) multi-volume sets "
    "sit side by side with near-identical spines. When you see two or more "
    "adjacent spines with the same title, they are separate physical volumes: "
    "output one entry PER SPINE, and hunt for the volume marker that tells "
    "them apart — a number, a Roman numeral (I/II), asterisks (* / **), or "
    "כרך/חלק with a letter or number. These markers are usually SMALL and "
    "printed near the top or bottom end of the spine, away from the title — "
    "check both ends of each such spine before concluding there is none, and "
    "append the marker to that entry's title exactly as printed."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "books": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "author": {"type": "string"},
                },
                "required": ["title", "author"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["books"],
    "additionalProperties": False,
}


def default_send(cfg: LlmReaderConfig) -> Callable[[bytes], str]:
    """Build the real Anthropic transport. Imported lazily so the package
    works without the SDK installed unless llmpage mode is actually used."""
    import anthropic
    client = anthropic.Anthropic()

    def send(jpeg: bytes) -> str:
        resp = client.messages.create(
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": "image/jpeg",
                                "data": base64.standard_b64encode(jpeg).decode()}},
                    {"type": "text", "text": PROMPT},
                ],
            }],
        )
        if resp.stop_reason == "refusal":
            return '{"books": []}'
        return next((b.text for b in resp.content if b.type == "text" and b.text),
                    '{"books": []}')

    return send


def _unrotate_box(box: tuple[int, int, int, int], rotate: str,
                  orig_w: int, orig_h: int) -> tuple[int, int, int, int]:
    """Map a box in rotated-image coordinates back to original-image pixels.

    'cw' rotation (PIL ROTATE_270) maps original (x, y) -> (H - y, x); 'ccw'
    (ROTATE_90) maps (x, y) -> (y, W - x). These are the inverses.
    """
    x0, y0, x1, y1 = box
    if rotate == "cw":
        return (y0, orig_h - x1, y1, orig_h - x0)
    if rotate == "ccw":
        return (orig_w - y1, x0, orig_w - y0, x1)
    return box


class ClaudePageReader:
    """Reads a shelf photo with a vision LLM; PageReader-compatible.

    Blocks carry the TILE's bounding box (in original-photo coordinates), not
    a per-book box — the model isn't asked for geometry, so the review UI
    shows the tile a title came from rather than the exact spine. Coarse but
    honest; per-book boxes are a possible later refinement.
    """

    engine_name = "claude_page"

    def __init__(self, send: Optional[Callable[[bytes], str]] = None,
                 cfg: LlmReaderConfig = CONFIG.llm):
        self.cfg = cfg
        self._send = send          # built lazily so tests never need the SDK
        self.errors: list[str] = []      # per-tile failures from the last read
        self.usage: dict = {}
        # optional callable(dict) — reading is the long phase (~5s/tile), so
        # a driver (the server) can show real per-tile progress
        self.progress: Optional[Callable[[dict], None]] = None

    def _encode(self, img) -> bytes:
        from PIL import Image
        w, h = img.size
        if max(w, h) > self.cfg.max_edge:
            s = self.cfg.max_edge / max(w, h)
            img = img.resize((round(w * s), round(h * s)), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=self.cfg.jpeg_quality)
        return buf.getvalue()

    def _tile_boxes(self, w: int, h: int) -> list[tuple[int, int, int, int]]:
        rows, cols = self.cfg.grid_rows, self.cfg.grid_cols
        tw, th = w / cols, h / rows
        ox, oy = tw * self.cfg.tile_overlap_frac, th * self.cfg.tile_overlap_frac
        return [(max(0, round(c * tw - ox)), max(0, round(r * th - oy)),
                 min(w, round((c + 1) * tw + ox)), min(h, round((r + 1) * th + oy)))
                for r in range(rows) for c in range(cols)]

    def read_page(self, image_path: str) -> list[PageBlock]:
        from PIL import Image
        if self._send is None:
            self._send = default_send(self.cfg)
        self.errors = []

        orig = Image.open(image_path)
        orig_w, orig_h = orig.size
        # 'both' reads the photo in BOTH 90° rotations: Hebrew spines are
        # printed in either direction (the Tesseract path always tried both),
        # and a spine printed against the pass direction reads as reversed
        # noise that the gates discard — so the second pass adds recall at
        # 2x read cost. Measured on IMG_8125: the cw-only pass never read
        # סליחה שניצחנו at all.
        rotations = ("cw", "ccw") if self.cfg.rotate == "both" \
            else (self.cfg.rotate,)

        blocks: list[PageBlock] = []
        best: dict[str, int] = {}      # normalized title -> index into blocks
        n_tiles = len(rotations) * self.cfg.grid_rows * self.cfg.grid_cols
        tile_no = 0
        for rot in rotations:
            if rot == "cw":
                img = orig.transpose(Image.ROTATE_270)
            elif rot == "ccw":
                img = orig.transpose(Image.ROTATE_90)
            else:
                img = orig
            for tbox in self._tile_boxes(*img.size):
                tile_no += 1
                if self.progress:
                    self.progress({"stage": "reading", "done": tile_no,
                                   "total": n_tiles})
                try:
                    raw = self._send(self._encode(img.crop(tbox)))
                    books = json.loads(raw).get("books") or []
                except Exception as e:  # one bad tile must not sink the photo
                    self.errors.append(f"tile {rot}/{tbox}: {e}")
                    continue
                obox = _unrotate_box(tbox, rot, orig_w, orig_h)
                for b in books:
                    title = (b.get("title") or "").strip()
                    author = (b.get("author") or "").strip()
                    if not title:
                        continue
                    key = normalize(title)
                    text = f"{title} {author}".strip()
                    prev = best.get(key)
                    if prev is None:
                        best[key] = len(blocks)
                        blocks.append(PageBlock(
                            text=text, x0=obox[0], y0=obox[1],
                            x1=obox[2], y1=obox[3], confidence=0.9))
                    elif len(text) > len(blocks[prev].text):
                        # same title seen again (overlapping tile or second
                        # rotation) — keep the richer read
                        blocks[prev] = PageBlock(
                            text=text, x0=obox[0], y0=obox[1],
                            x1=obox[2], y1=obox[3], confidence=0.9)
        if not blocks and self.errors:
            raise RuntimeError("llmpage: every tile failed: "
                               + "; ".join(self.errors))
        return blocks
