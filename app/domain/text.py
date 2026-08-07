# -*- coding: utf-8 -*-
"""Search keys — derived from the engine's ``normalize()``, never re-implemented.

This module imports `booksnap.catalog.normalize` deliberately. It is the one
place the product reaches into the recognition core, and the direction is
legal (plan H1: only ``booksnap -> app`` is forbidden; ``app/domain`` sits
below the core in the layer list). ``booksnap/catalog.py`` is stdlib-only, so
the domain stays pure and millisecond-fast.

**Do not copy the normalizer.** Two normalizers drift, and when they drift the
product's search keys stop agreeing with the matcher's keys — which is the
same class of bug `CLAUDE.md` records twice already (the scorer needing the
same prefix transform as the matcher; a bad ruler inventing work). One
function, one behaviour, one place to fix it.

What ``normalize()`` gives us, and why each matters for search (§6):
nikud stripped, final letters folded (ם→מ), geresh/gershayim DELETED in-word
(so הצ'ופצ'יק stays one token), punctuation dropped, whitespace collapsed.

What it does NOT do is fold the leading ה/ו/ב/ל/מ/ש/כ particles — measured as
*harmful* inside the matcher (`CLAUDE.md`: precision 0.62 -> 0.50) but
REQUIRED for a human typing a query. That asymmetry is P1.5's problem, and it
belongs in the query path, not in the stored key.
"""
from __future__ import annotations

from booksnap.catalog import normalize

__all__ = ["normalize", "book_key"]


def book_key(title: str, author: str) -> str:
    """The identity of a book within a library: ``normalize(t)|normalize(a)``.

    Byte-identical to `booksnap.library.book_key` on purpose, and asserted so
    in `tests/test_domain.py`. That is what makes P1.3's import of the
    existing 251-book `library.json` a 1:1 mapping instead of a re-keying
    exercise — and it is also the key §8.4 will use at global scale.
    """
    return f"{normalize(title)}|{normalize(author)}"
