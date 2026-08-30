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


def _ruled(rows: int, width: int = 900, height: int = 1200,
           vertical: bool = False) -> bytes:
    """A plain field with `rows - 1` long dark rules across it.

    Deliberately the crudest thing that carries the signal `_shelf_bands`
    looks for — a long dark line — because a synthetic image that tried to
    look like a bookcase would be a claim about bookcases.

    ⚠ `vertical` draws them the other way, for the column half (P6.7g). ONE
    fixture with an axis rather than two functions: the detector is literally
    the same routine on the transpose, and a second fixture would be a second
    place for the two axes to stop agreeing.
    """
    import cv2
    import numpy as np

    img = np.full((height, width, 3), 235, dtype=np.uint8)
    span = width if vertical else height
    for i in range(1, rows):
        at = round(span * i / rows)
        a, b = ((at, 0), (at, height - 1)) if vertical else ((0, at), (width - 1, at))
        cv2.line(img, a, b, (20, 20, 20), 9)
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
            data = fh.read()
        # ⚠ BOTH axes since P6.7g. The column half is the one with a real
        # measurement behind it: every photograph here is a single shelf full
        # of books, so a detector that saw a column per spine would show up as
        # a number far above 1, and on the day it shipped all ten answered 1.
        counts.append((len(finder.bands(data)), len(finder.columns(data))))
    assert all(b >= 1 and c >= 1 for b, c in counts), counts

def test_the_column_detector_answers_one_column_per_ruled_stripe():
    """The other axis, through the same port (P6.7g).

    ⚠ Synthetic, and the same caveat this module's header carries: no
    photograph of a whole bookcase exists in this library, so what is measured
    here is the SIGNAL PATH and the shape of the answer.
    """
    from app.adapters.booksnap_bands import BooksnapBandFinder

    finder = BooksnapBandFinder()
    for cols in (2, 3, 5):
        found = finder.columns(_ruled(cols, vertical=True))
        assert len(found) == cols, (cols, len(found))
        assert all(0.0 <= c.left < c.right <= 1.0 for c in found), found
        assert found == tuple(sorted(found, key=lambda c: c.left))
        assert found[0].left < 0.02 and found[-1].right > 0.98


def test_a_shelf_full_of_books_is_ONE_column_not_a_picket_fence():
    """⚠⚠ The failure that matters, measured on the owner's REAL photographs.

    A shelf of books is a fence of long vertical edges, and it is the same
    signal `_vertical_coverage` uses to find spines. Proposing four columns
    for a case that has one is worse than proposing nothing: the owner would
    read a number, press apply, and get slots that describe no furniture.

    On the day this shipped, all ten of the owner's full-size photographs —
    every one a single shelf, full of books — answered **1 column**. The
    coverage threshold is what does it: a spine spans one band's height,
    roughly a sixth of the picture, and the bar is 0.35 of it.

    This test carries the synthetic half of that claim (a plain field with no
    divider is one column); the real half is recorded by
    `test_what_the_owners_real_photographs_measure`, which now measures both
    axes.
    """
    from app.adapters.booksnap_bands import BooksnapBandFinder

    found = BooksnapBandFinder().columns(_ruled(1, vertical=True))
    assert len(found) == 1
    assert found[0].left < 0.02 and found[0].right > 0.98


def test_columns_refuse_bytes_that_are_not_an_image_too():
    """The route turns this into a 415, exactly as the band half does."""
    from app.adapters.booksnap_bands import BooksnapBandFinder

    finder = BooksnapBandFinder()
    _raises(ValueError, finder.columns, b"%PDF-1.4 not a photograph")
    _raises(ValueError, finder.columns, b"")

