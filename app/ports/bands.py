# -*- coding: utf-8 -*-
"""The BandFinder port — one photograph's horizontal shelf surfaces (P6.6).

`booksnap.segment` already detects shelf bands: it is stage 1 of the reading
pipeline, deterministic, free, and tuned on this owner's own shelves. VISION §7
names reusing it as approach B's strongest use — *"detect the bookcase's shelf
rows from a photo; the user confirms or adjusts"* — and UI_PLAN §3 repeats it.
This Protocol is that one capability behind a seam, for the same reason
``Reader`` is: the adapter imports cv2 and numpy, and ``app/api`` may not.

⚠ **It is separate from ``Reader`` on purpose.** A read is a JOB — queued,
rate-capped, chargeable, answered later with claims. This is a synchronous
question about geometry that costs a Canny and a morphology pass, writes
nothing, stores nothing, and can never produce a Book. Folding it into the
reader would put a free local measurement behind a bounded pool and a 30/hr
account cap, and would make every future cost-metering hook count it.

⚠ **What it answers is a fact about a PHOTOGRAPH, never about furniture.**
MAP_PLAN §3.14: the map may propose; only an explicit ✓ binds. §3.14's ban on
proposing from image content is about IDENTITY — which shelf a photo is of —
because nothing in a picture says that. How many horizontal surfaces a
bookcase has is the one thing a picture does say, which is exactly why VISION
§7 singles it out.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Band:
    """One horizontal shelf surface, as FRACTIONS of the photo's height.

    Fractions rather than pixels because the caller draws them over an image it
    has already scaled to fit a phone; a pixel count is a fact about a file the
    caller no longer holds. Both are in ``[0, 1]`` and ``top < bottom``.
    """

    top: float
    bottom: float


class BandFinder(Protocol):
    """Something that can count the shelf surfaces in one photograph."""

    def bands(self, image: bytes) -> tuple[Band, ...]:
        """Every band this photo shows, top to bottom.

        Takes BYTES rather than a blob key, unlike ``ReadRequest`` — this
        answers about a photo that has not been stored and never will be. A
        proposal is transient by design: nothing enters the library
        unapproved, and an image kept "just for the proposal" would be the
        first blob with no owner and no lifecycle.

        Raises ``ValueError`` for bytes that are not a decodable image. One
        band is a normal answer and means *no horizontal line divides this
        picture* — which is what a photo of a SINGLE shelf looks like, and
        what all 11 of the owner's photographs measured when this port was
        written.
        """
        ...
