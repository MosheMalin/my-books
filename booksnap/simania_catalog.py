# -*- coding: utf-8 -*-
"""Simania (simania.co.il) catalog adapter — community Hebrew books site.

Why this exists (measured, Aug 2026, tools/simania_probe.py): on the 35-book
fixture Simania covers 34/35 with edition-true spellings (the printed
כל היצורים גדולים כקטנים, not cataloguing orthography) and returns structured
JSON including series name + number — the exact signal our same-author series
disambiguation lacks. NLI remains the authority (legal deposit); Simania is the
better first stop for popular fiction, which is what shelves mostly hold.

Design mirrors nli_catalog.py:
- transport injected -> unit-testable offline;
- permanent on-disk cache -> deterministic after first contact, and the site
  is only ever asked a given query once (politeness);
- RAW tokens go in the query, never `normalize()`d ones — the index is
  literal, and folding final letters (ן->נ) silently breaks every title
  ending in ך ם ן ף ץ (the NLI lesson);
- a polite floor between live calls (the cache makes re-runs free).

This uses Simania's own search endpoint at person-equivalent volume for a
personal library catalog; a bulk mirror is deliberately NOT implemented.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from .catalog import CatalogEntry, normalize

Transport = Callable[[str], str]

API = "https://simania.co.il/api/search/suggestions?q={q}&limit=15"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# edition annotations that pad titles: "חברברי הסוונה [מהדורה חדשה]",
# "האימפריה השנייה (השניה)". Extra tokens depress title coverage in the
# matcher, and they are not on the spine.
_ANNOT = re.compile(r"\s*[\[(][^\])]*[\])]")
_WS = re.compile(r"\s+")


def _default_transport(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def _clean_title(t: str) -> str:
    return _WS.sub(" ", _ANNOT.sub(" ", t)).strip(" -:،,")


class SimaniaCatalog:
    def __init__(self, transport: Optional[Transport] = None,
                 cache_dir: Optional[str | Path] = None,
                 delay_s: float = 1.5):
        self._transport = transport or _default_transport
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._delay_s = delay_s
        self._last_call = 0.0

    # -- query strategy ------------------------------------------------------
    def _terms(self, query: str) -> list[str]:
        """Search terms for one OCR/LLM string, most-precise first.

        The endpoint is a literal typeahead: the full string is best when the
        read is clean; leading/trailing windows catch "title author" strings
        where the full concatenation returns nothing.
        """
        toks = [t for t in query.split() if t.strip()]
        if not toks:
            return []
        terms = [" ".join(toks)]
        if len(toks) > 3:
            terms.append(" ".join(toks[:3]))       # title-side window
            terms.append(" ".join(toks[-3:]))      # author-side window
        return terms


    # -- transport + cache ---------------------------------------------------
    def _fetch(self, term: str) -> dict:
        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            key = hashlib.sha1(term.encode("utf-8")).hexdigest()[:16]
            cached = self._cache_dir / f"{key}.json"
            if cached.exists():
                return json.loads(cached.read_text(encoding="utf-8"))
        wait = self._delay_s - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            data = json.loads(self._transport(API.format(
                q=urllib.parse.quote(term))))
        except Exception:
            return {}                      # degrade to "no candidates"
        self._last_call = time.time()
        if self._cache_dir:
            cached.write_text(json.dumps({"_query": term, **data},
                                         ensure_ascii=False), encoding="utf-8")
        return data

    def candidates(self, query: str, limit: int = 15) -> list[CatalogEntry]:
        merged: dict[str, CatalogEntry] = {}

        def take(term: str) -> None:
            for s in (self._fetch(term).get("suggestions") or []):
                if s.get("type") != "book":
                    continue
                title = _clean_title(s.get("title") or "")
                if not title:
                    continue
                e = CatalogEntry(f"sim{s.get('id')}", title,
                                 (s.get("author") or "").strip())
                merged.setdefault(normalize(e.title) + "|" + e.norm_author, e)

        for term in self._terms(query):
            take(term)
            if len(merged) >= limit:
                break
        return list(merged.values())


class FallbackCatalog:
    """Primary catalog first; the secondary joins only when the primary's
    harvest is THIN (< min_results candidates).

    Default min_results=1 == fallback only when the primary found NOTHING.
    Three strategies were measured on the stored llmpage reads (Aug 2026),
    and the two "smarter" ones both lost — do not retry without new evidence:
      - single-token Simania rescue query: fixed the known מלכוד 22 miss
        (phrase queries only surface a film record + an editions-index page)
        but REGRESSED both labelled shelves — one-word noise displaced
        correct matches;
      - thin-union (min_results=3, NLI candidates join when Simania returns
        <3): also a net loss — 6082 A+R 0.88->0.86, 7849 AUTO 0.89->0.86,
        importing NLI phantoms (סיפור אהבה) on reads Simania answered fine.
    So מלכוד 22 stays a priced-in miss: its junk candidates fail the gates,
    the read lands unverified, and the review UI surfaces it. A FULL union
    everywhere is worse again (same lesson as the modes union in CLAUDE.md).
    """

    def __init__(self, primary, secondary, min_results: int = 1):
        self.primary = primary
        self.secondary = secondary
        self.min_results = min_results

    def candidates(self, query: str, limit: int = 15) -> list[CatalogEntry]:
        found = self.primary.candidates(query, limit)
        if len(found) >= self.min_results:
            return found
        seen = {normalize(e.title) + "|" + e.norm_author for e in found}
        for e in self.secondary.candidates(query, limit):
            key = normalize(e.title) + "|" + e.norm_author
            if key not in seen:
                seen.add(key)
                found.append(e)
        return found
