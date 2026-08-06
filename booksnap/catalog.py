# -*- coding: utf-8 -*-
"""Catalog interface.

The matcher depends only on the `Catalog` protocol, so the local sample used
in development can be swapped for a Meilisearch index over an NLI/ULI dump
without touching matching logic. A real implementation lives behind the same
`candidates()` method.
"""
from __future__ import annotations
import json
import re
import unicodedata
from pathlib import Path
from typing import Protocol, Iterable

_NIKUD = re.compile(r"[\u0591-\u05C7]")
# geresh/gershayim (and their ASCII stand-ins) mark foreign sounds and
# acronyms INSIDE a word \u2014 \u05E6'\u05D5\u05E4\u05E6'\u05D9\u05E7, \u05E8\u05D9\u05E6'\u05E8\u05D3, \u05D6'\u05D5\u05DC, \u05D7\u05D6"\u05DC. They must be
# deleted, not replaced by a space: space-splitting shredded \u05D4\u05E6'\u05D5\u05E4\u05E6'\u05D9\u05E7 into
# the junk tokens \u05D4\u05E6/\u05D5\u05E4\u05E6/\u05D9\u05E7, and the entry's only usable title token was
# whatever word carried no geresh (run 16: the true book lost to a subset
# record because of exactly this).
_INWORD_MARKS = re.compile(r"[\u05F3\u05F4'\"`\u2018\u2019\u201C\u201D]")
_KEEP = re.compile(r"[^\u05D0-\u05EAa-zA-Z0-9 ]")
_WS = re.compile(r"\s+")


def normalize(s: str) -> str:
    """Normalise Hebrew for matching: strip nikud, punctuation, final-letter
    variants folded, collapse whitespace."""
    s = unicodedata.normalize("NFKD", s)
    s = _NIKUD.sub("", s)
    s = _INWORD_MARKS.sub("", s)
    s = _KEEP.sub(" ", s)
    # fold final letters to base forms so OCR mid/final confusion is harmless
    s = s.translate(str.maketrans("\u05da\u05dd\u05df\u05e3\u05e5",
                                  "\u05db\u05de\u05e0\u05e4\u05e6"))
    return _WS.sub(" ", s).strip()


class CatalogEntry:
    __slots__ = ("id", "title", "author", "norm_title", "norm_author")

    def __init__(self, cid: str, title: str, author: str):
        self.id = cid
        self.title = title
        self.author = author
        self.norm_title = normalize(title)
        self.norm_author = normalize(author)


class Catalog(Protocol):
    def candidates(self, query: str, limit: int = 25) -> list[CatalogEntry]:
        """Return plausible catalog entries for an OCR query string.

        A real backend (Meilisearch) does typo-tolerant retrieval here; the
        matcher then re-scores with token-level evidence gates.
        """
        ...


class LocalCatalog:
    """In-memory catalog backed by a JSON list of {title, author}. For dev the
    query is ignored and all entries are returned; the matcher does the work.
    A production Meilisearch catalog would use the query to prefilter."""

    def __init__(self, entries: Iterable[CatalogEntry]):
        self._entries = list(entries)

    @classmethod
    def from_json(cls, path: str | Path) -> "LocalCatalog":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(CatalogEntry(str(i), d["title"], d.get("author", ""))
                   for i, d in enumerate(data))

    def __len__(self) -> int:
        return len(self._entries)

    def candidates(self, query: str, limit: int = 25) -> list[CatalogEntry]:
        return self._entries
