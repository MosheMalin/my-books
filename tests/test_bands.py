# -*- coding: utf-8 -*-
"""Stage 1's band detector, as the product asks it (P6.6).

⚠ **What is measured here is PLUMBING, not accuracy**, and the distinction is
the honest half of this item. Accuracy on a real bookcase photograph is not
measured anywhere, because no such photograph exists to measure against: on
the day this shipped the owner's library held **11 full-size images, every one
of them a single shelf, every one answering 1 band** — which is the correct
answer for that input and tells us nothing about the input the feature is for.
`tools/sweep.py` cannot help either; it replays reads, and this is not a read.

So the fixture below is SYNTHETIC and says so. It draws N horizontal rules on
a plain field and asserts N + 1 bands come back — which proves the signal path
(read → grey → Canny → morphology → coverage → merge → fractions) and the
shape of the answer, and proves nothing about a photograph of furniture in a
room. CLAUDE.md's rule is "test the real input, not a fixture you invented";
the real input is not obtainable here, and the deviation is written down
rather than papered over.

The second test is the self-skipping one over `work/`, in the shape the MPO
lesson prescribes: it records what the owner's actual photographs say, so the
day a bookcase photo lands in there it starts saying something new.
"""
from __future__ import annotations

import glob
import os


def _raises(exc, fn, *a, **kw):
    """The repo's own idiom (`test_domain.py`) — there is no pytest here; the
    runner is `tests/run_all.py` and collects module-level `def test_*`."""
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"expected {exc.__name__}, nothing raised")


def _ruled(rows: int, width: int = 900, height: int = 1200) -> bytes:
    """A plain field with `rows - 1` long horizontal rules across it.

    Deliberately the crudest thing that carries the signal `_shelf_bands`
    looks for — a long dark horizontal line — because a synthetic image that
    tried to look like a bookcase would be a claim about bookcases.
    """
    import cv2
    import numpy as np

    img = np.full((height, width, 3), 235, dtype=np.uint8)
    for i in range(1, rows):
        y = round(height * i / rows)
        cv2.line(img, (0, y), (width - 1, y), (20, 20, 20), 9)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return bytes(buf)


def test_the_band_detector_answers_one_band_per_ruled_row():
    """The signal path, end to end, through the PORT the product uses."""
    from app.adapters.booksnap_bands import BooksnapBandFinder

    finder = BooksnapBandFinder()
    for rows in (2, 3, 5):
        bands = finder.bands(_ruled(rows))
        assert len(bands) == rows, (rows, len(bands))
        # Fractions, ordered, inside the image, and covering it without gaps
        # bigger than a rule's thickness.
        assert all(0.0 <= b.top < b.bottom <= 1.0 for b in bands), bands
        assert bands == tuple(sorted(bands, key=lambda b: b.top))
        assert bands[0].top < 0.02 and bands[-1].bottom > 0.98


def test_a_photo_of_one_shelf_is_one_band_not_zero():
    """The answer for the input the owner actually has.

    ⚠ **One is a real answer, not a failure**, and the client has to say so
    rather than showing "we found nothing": a photograph with no horizontal
    rule across it is a photograph of a single shelf, which is what every one
    of the owner's eleven images is. A detector that answered 0 here would
    make the proposal look broken on the commonest input in the library.
    """
    from app.adapters.booksnap_bands import BooksnapBandFinder

    bands = BooksnapBandFinder().bands(_ruled(1))
    assert len(bands) == 1
    assert bands[0].top < 0.02 and bands[0].bottom > 0.98


def test_bytes_that_are_not_an_image_are_refused_by_value():
    """The route turns this into a 415. A detector that returned an empty
    tuple for a PDF would let the client print *"1 level"* for a file that is
    not a picture."""
    from app.adapters.booksnap_bands import BooksnapBandFinder

    finder = BooksnapBandFinder()
    _raises(ValueError, finder.bands, b"%PDF-1.4 not a photograph")
    _raises(ValueError, finder.bands, b"")


def test_what_the_owners_real_photographs_measure():
    """Self-skipping, over `work/` — the MPO lesson's shape.

    It asserts nothing about a number, because the number is not a decision
    anybody made: it RECORDS that every real photograph currently in this
    checkout answers with at least one band and never raises. The day a
    bookcase photograph lands in `work/`, this is the test that starts
    exercising the multi-band path on real pixels.
    """
    blobs = sorted(
        f for f in glob.glob("work/product_blobs/**/*.jpg", recursive=True)
        if "~thumb" not in f and os.path.getsize(f) > 50_000
    )
    if not blobs:
        # ⚠ A self-SKIP, the repo's own shape: a fresh clone has no `work/`,
        # and a test that failed there would be a test about the checkout.
        return

    from app.adapters.booksnap_bands import BooksnapBandFinder

    finder = BooksnapBandFinder()
    counts = []
    for path in blobs[:12]:
        with open(path, "rb") as fh:
            counts.append(len(finder.bands(fh.read())))
    assert all(n >= 1 for n in counts), counts
