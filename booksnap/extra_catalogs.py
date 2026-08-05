# -*- coding: utf-8 -*-
"""Last-resort catalog sources — used-book and small-shop sites.

Purpose: the הקרע class of misses. Simania (community) and NLI (legal
deposit) cover most shelves, but some editions — old SF, small prints —
surface only on second-hand shops. These adapters are LAST in the retrieval
chain: they are only asked when everything before them returned nothing, so
their messier data (titles glued to author/category/stock text) is fed to
the same evidence gates as everything else and mostly lands in REVIEW.

Both follow the house adapter rules: injected transport (offline-testable),
permanent on-disk cache keyed by query (a site is asked a given question
once, ever), raw un-normalized tokens in URLs, and a polite delay between
live calls. Person-equivalent volume only — no crawling.

Owner-suggested sources probed 2026-08-06:
  - rebooks.org.il    WooCommerce, server-rendered `?s=` search. Titles in
    wd-entities-title blocks (compound: title+series), no author field.
  - booksefer.co.il   ~52k used titles, server-rendered
    index.php?dir=site&page=search&q=. box-product__title holds
    "<title> <author> ספרי <category> [חסר]" glued together.
  - bookpod.co.il / realbooks.co.il — client-rendered, no cheap adapter
    (probed and skipped; revisit if their APIs surface).
"""
from __future__ import annotations

import hashlib
import html
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from .catalog import CatalogEntry, normalize

Transport = Callable[[str], str]

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_WS = re.compile(r"\s+")


def _default_transport(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


class _HtmlSearchCatalog:
    """Shared plumbing: cache -> polite fetch -> regex parse."""

    #: subclasses set these
    id_prefix = "x"
    url_template = ""            # {q} placeholder, urlencoded query
    item_re: re.Pattern = re.compile("$^")

    def __init__(self, transport: Optional[Transport] = None,
                 cache_dir: Optional[str | Path] = None,
                 delay_s: float = 1.5):
        self._transport = transport or _default_transport
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._delay_s = delay_s
        self._last_call = 0.0

    def _fetch(self, query: str) -> str:
        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            key = hashlib.sha1(query.encode("utf-8")).hexdigest()[:16]
            cached = self._cache_dir / f"{key}.html"
            if cached.exists():
                return cached.read_text(encoding="utf-8")
        wait = self._delay_s - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            page = self._transport(
                self.url_template.format(q=urllib.parse.quote(query)))
        except Exception:
            return ""                    # degrade to "no candidates"
        self._last_call = time.time()
        if self._cache_dir:
            cached.write_text(page, encoding="utf-8")
        return page

    def _clean(self, raw: str) -> str:
        return _WS.sub(" ", html.unescape(raw)).strip(" -–—:,")

    def candidates(self, query: str, limit: int = 15) -> list[CatalogEntry]:
        toks = query.split()
        merged: dict[str, CatalogEntry] = {}
        # full query first; a leading window rescues title+author strings
        terms = [" ".join(toks)]
        if len(toks) > 2:
            terms.append(" ".join(toks[:2]))
        for term in terms:
            for i, m in enumerate(self.item_re.finditer(self._fetch(term))):
                title = self._clean(m.group(1))
                if len(title) < 3:
                    continue
                e = CatalogEntry(f"{self.id_prefix}{hash(title) & 0xffffff}",
                                 title, "")
                merged.setdefault(normalize(e.title), e)
            if len(merged) >= limit:
                break
        return list(merged.values())[:limit]


class RebooksCatalog(_HtmlSearchCatalog):
    """rebooks.org.il — used books, strong on out-of-print SF."""

    id_prefix = "rb"
    url_template = "https://rebooks.org.il/?s={q}"
    item_re = re.compile(
        r'wd-entities-title[^>]*>\s*<a[^>]*>([^<]{3,120})</a>')


class BooksferCatalog(_HtmlSearchCatalog):
    """booksefer.co.il — ~52k used titles, good for older books."""

    id_prefix = "bs"
    url_template = ("https://www.booksefer.co.il/index.php"
                    "?dir=site&page=search&q={q}")
    item_re = re.compile(
        r'box-product__title[^>]*>\s*([^<]{3,160})\s*</div>')

    # titles arrive as "<title> <author> ספרי <category> [חסר]"; the category
    # marker and stock words are site furniture, not spine text
    _TAIL = re.compile(r"\s+ספרי\s+.*$|\s+(?:חסר|אזל(?:\s+במלאי)?)\s*$")

    def _clean(self, raw: str) -> str:
        return super()._clean(self._TAIL.sub("", html.unescape(raw)))


class UnionCatalog:
    """Merge candidates from ALL sources, deduped — no gating at all.

    Adopted for Simania+NLI (2026-08-06 measurement, tools/rematch_blocks E
    vs D): thin-union's threshold kept mis-firing — 3-4 junk Simania rows
    "satisfied" it and blocked NLI's EXACT hit (על דם ואור). Full union of
    the two primary sources beats thin-union on both fixture means (AUTO
    0.805 vs 0.79, A+R 0.87 vs 0.865) now that the gates carry the
    precision. The shop tail stays thin-gated (noisy + slow).
    """

    def __init__(self, catalogs: list):
        self.catalogs = list(catalogs)

    def candidates(self, query: str, limit: int = 15) -> list[CatalogEntry]:
        merged: dict[str, CatalogEntry] = {}
        for c in self.catalogs:
            for e in c.candidates(query, limit):
                merged.setdefault(normalize(e.title) + "|" + e.norm_author, e)
        return list(merged.values())


class ChainCatalog:
    """Ordered cascade: precise sources first, broader ones only when the
    harvest so far is thin (fewer than `min_results` candidates, unioned).

    min_results=1 is the pure on-empty cascade. It was the measured best
    early on, but kept failing the same way as gates improved: a precise
    source returning WRONG-but-nonempty candidates blocks the source that
    has the right book (מלכוד 22, The elephant, and on IMG_8131 the exact
    NLI title שלושה ימים בספטמבר blocked by Simania's שלושה-ימים lookalikes)
    — re-measured with the current gates, min_results=3 no longer regresses
    the fixture, so the union is the default now.
    """

    def __init__(self, catalogs: list, min_results: int = 3):
        self.catalogs = list(catalogs)
        self.min_results = min_results

    def candidates(self, query: str, limit: int = 15) -> list[CatalogEntry]:
        merged: dict[str, CatalogEntry] = {}
        for c in self.catalogs:
            if len(merged) >= self.min_results:
                break
            for e in c.candidates(query, limit):
                merged.setdefault(normalize(e.title) + "|" + e.norm_author, e)
        return list(merged.values())
