# -*- coding: utf-8 -*-
"""`BandFinder` over `booksnap.segment` (P6.6).

The only thing in the product allowed to import the engine for this, in the
same way `booksnap_reader` is for reads. It is deliberately tiny: the detection
is `segment.shelf_bands`, tuned and measured in the engine, and nothing here
re-tunes or second-guesses it.

⚠ **A temp file, and it is the engine's shape not a shortcut.**
`segment.shelf_bands` takes a path because every other entry point into that
module does — the pipeline works from files on disk throughout — so going
through a path is what keeps the product measuring a photograph exactly the
way a read does, byte for byte and decoder for decoder. Anything else here
would be a second way of turning bytes into pixels, in the one place whose
whole value is that it is the SAME stage 1.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from app.ports.bands import Band, Column


class BooksnapBandFinder:
    """Stage 1's band detector, and nothing else."""

    def bands(self, image: bytes) -> tuple[Band, ...]:
        # ⚠ REDUNDANT, and kept knowingly. `cv2.imread` on an empty file
        # answers None and `shelf_bands` raises `ValueError` for it anyway —
        # a mutation proved this line is not what makes the empty case safe.
        # It stays because it names the case at the door, where a reader looks;
        # redundant enforcement is a pattern here, and the honest thing is to
        # say which copy is load-bearing.
        if not image:
            raise ValueError("no image")
        # ⚠ Imported HERE, not at module scope. `booksnap.segment` pulls in cv2
        # and scipy, and CLAUDE.md's rule 4 is that no cheap path grows an
        # eager import of either — `app.main` composes this adapter on every
        # start, including the pre-commit hook's.
        from booksnap.segment import shelf_bands

        with tempfile.TemporaryDirectory(prefix="booksnap-bands-") as tmp:
            # ⚠ The suffix is for a HUMAN reading a stack trace, not for the
            # decoder. The first version of this comment said `cv2.imread`
            # picks its decoder from the extension and that a bare temp name
            # would decode nothing — a mutation removing the suffix left every
            # test green, because OpenCV sniffs the content. A wrong stated
            # reason is what makes the next reader delete the guard, so the
            # claim is corrected rather than the line.
            path = Path(tmp) / "bookcase.jpg"
            path.write_bytes(image)
            found = shelf_bands(path)
        return tuple(Band(top=top, bottom=bottom) for top, bottom in found)

    def columns(self, image: bytes) -> tuple[Column, ...]:
        """The same photograph, the other axis (P6.7g).

        A near-copy of `bands` above, and deliberately so rather than a shared
        private helper taking a function: the two differ only in which engine
        entry point they call, and threading that through a helper would hide
        the one line a reader comes here to check. Every ⚠ on `bands` applies
        unchanged — the empty-bytes guard is redundant, the suffix is for a
        human, and the import is late because cv2 is expensive.
        """
        if not image:
            raise ValueError("no image")
        from booksnap.segment import shelf_columns

        with tempfile.TemporaryDirectory(prefix="booksnap-bands-") as tmp:
            path = Path(tmp) / "bookcase.jpg"
            path.write_bytes(image)
            found = shelf_columns(path)
        return tuple(Column(left=left, right=right) for left, right in found)
