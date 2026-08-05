# -*- coding: utf-8 -*-
"""National Library of Israel (NLI) Open Library catalog adapter.

Implements the `Catalog` protocol against NLI's public search API:

    https://api.nli.org.il/openlibrary/search?api_key={KEY}&query=...

The query grammar is field-scoped and boolean-chained, e.g.:
    query=title,contains,הכופרים,AND;creator,contains,קארני

Design notes for the server:
- `candidates()` turns OCR text into a search query, calls NLI, parses the
  records into CatalogEntry objects, and hands them to the same matcher used
  for the local catalog. NLI does the retrieval; our matcher does the scoring.
- The HTTP call is injected (`transport`) so this class is unit-testable
  offline and so you can swap requests/httpx/aiohttp without touching logic.
- A tiny on-disk cache avoids re-querying NLI for repeated OCR strings across
  a large photo batch (and keeps you well under any rate limits).
- The api_key is read from the environment (NLI_API_KEY) and never hard-coded.
  Sign up (free) at https://api2.nli.org.il/signup/ .
  VERIFIED LIVE (Aug 2026): the literal string "guest" is NOT accepted — the
  API answers 403 {"error":{"code":"API_KEY_INVALID"}}. Earlier notes in this
  repo claiming a usable guest key were wrong. A real key is required.

This module makes NO network call at import time and none unless
`candidates()` is invoked with a real transport.
"""
from __future__ import annotations
import json
import os
import re
import hashlib
import time
import unicodedata
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlencode

from .catalog import CatalogEntry, normalize

NLI_SEARCH_URL = "https://api.nli.org.il/openlibrary/search"

_NIKUD_RE = re.compile(r"[֑-ׇ]")
# keep Hebrew (incl. final letters), latin and digits; drop everything else
_NONWORD_RE = re.compile(r"[^א-תa-zA-Z0-9 ]")

# Transport is any callable(url: str) -> str  (returns response body text).
Transport = Callable[[str], str]


# api.nli.org.il sits behind Cloudflare, which rejects the stdlib default
# User-Agent ("Python-urllib/3.x") with a 403 HTML challenge page before the
# request ever reaches the API. Verified live: with this header the same URL
# returns a normal JSON response (an API_KEY_INVALID error for a bad key).
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _default_transport(url: str) -> str:
    """Lazy stdlib transport so the package has no hard network dependency."""
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", "replace")


class NLICatalog:
    def __init__(self, api_key: Optional[str] = None,
                 transport: Optional[Transport] = None,
                 cache_dir: Optional[str | Path] = None,
                 record_limit: int = 60):
        # record_limit truncates the parsed list BEFORE our matcher ranks it,
        # so a low value silently discards the right book: at 15, the correct
        # "חברברי הסונה" fell outside NLI's own ordering and the spine went
        # unmatched. Scoring candidates is microseconds; the HTTP call is the
        # expensive part and has already happened. Keep them all.
        self.api_key = api_key or os.environ.get("NLI_API_KEY", "")
        self.transport = transport or _default_transport
        self.record_limit = record_limit
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.retries = 3
        self.retry_backoff = 1.5
        self.failed_fetches = 0        # queries lost after all retries
        self.last_error = ""

    # -- query construction --------------------------------------------------
    @staticmethod
    def _raw_tokens(ocr_text: str) -> list[str]:
        """Tokenise for the *remote* index: strip nikud and punctuation but
        KEEP final letters.

        `catalog.normalize()` folds ך ם ן ף ץ to their medial forms, which is
        right for local fuzzy matching (OCR confuses them) but wrong to send to
        NLI, whose index stores real Hebrew and matches `contains` literally.
        Verified live: `title,contains,לחתנ` misses the book entirely, while
        `title,contains,לחתן` finds it. This bug silently broke every title
        whose words end in a final letter — a large share of Hebrew.
        """
        s = unicodedata.normalize("NFKD", ocr_text)
        s = _NIKUD_RE.sub("", s)
        s = _NONWORD_RE.sub(" ", s)
        return [t for t in s.split() if t]

    @classmethod
    def _pick_phrases(cls, ocr_text: str, max_phrases: int = 3) -> list[str]:
        """Consecutive word-runs, most precise query form available.

        `title,contains,לחתן את אמא` returns 5 records (3 books, the right one
        first); the single token `לחתן` returns 50. Phrases only survive when
        OCR got a clean run of words, so they complement single terms.
        """
        toks = [t for t in cls._raw_tokens(ocr_text) if len(t) >= 2]
        out = []
        for n in (3, 2):
            for i in range(len(toks) - n + 1):
                run = toks[i:i + n]
                if sum(len(t) for t in run) >= 8:
                    p = " ".join(run)
                    if p not in out:
                        out.append(p)
        return out[:max_phrases]

    @staticmethod
    def _pick_terms(ocr_text: str, max_terms: int = 6) -> list[str]:
        """Choose the most useful query tokens from noisy OCR.

        Longest-first is a decent proxy for discriminative, but keeping only
        the top 4 measurably lost real titles: for the spine
        "ג'ראלד דארל ציפור הלעג" the author tokens (גיראלד/גראלד/דארל) crowd
        out the short, highly distinctive title word הלעג, and the search then
        retrieves books that merely contain the author's name in their title.
        Keeping a few more terms restores it — the matcher re-ranks anyway.
        """
        toks = [t for t in NLICatalog._raw_tokens(ocr_text) if len(t) >= 4]
        toks.sort(key=len, reverse=True)
        seen, out = set(), []
        for t in toks:
            if t not in seen:
                seen.add(t)
                out.append(t)
            if len(out) >= max_terms:
                break
        return out

    def _term_url(self, term: str) -> str:
        """One narrow title-scoped query.

        Measured live, two facts drive this shape:
        1. `any,contains,...` drags in archive photos and subject headings —
           49 records / 34 books for 5 real hits. `title,contains` gave 8 / 5.
        2. NLI returns at most **50 records per query**, so OR-ing several OCR
           tokens *loses* books: a common token like דארל floods all 50 slots
           and pushes the target out. `title,contains,חברברי` alone returns 3
           precise records including the right one.
        So we issue one narrow query per distinctive term and merge, instead of
        one broad OR query. Each term also caches independently, which reuses
        far better across a shelf of same-author spines.
        """
        params = {"api_key": self.api_key,
                  "query": f"title,contains,{term}",
                  "output_format": "json"}
        return f"{NLI_SEARCH_URL}?{urlencode(params)}"

    # -- response parsing ----------------------------------------------------
    @staticmethod
    def _parse(body: str) -> list[CatalogEntry]:
        """Parse NLI JSON-LD into CatalogEntry list.

        Verified against a live response (Aug 2026). The payload is a bare
        JSON *list* of records; every field is a Dublin Core URI key whose
        value is a list of wrapper objects:

            {"http://purl.org/dc/elements/1.1/title": [{"@value": "..."}]}

        The previous implementation probed short keys ("title", "dc:title")
        and, when it did hit the URI key, handed the `{"@value": ...}` dict
        straight to str() — so titles came out as "{'@value': '...'}". Both
        bugs are fixed here.
        """
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return []
        records = data if isinstance(data, list) else \
            data.get("docs", data.get("records", []))

        out: list[CatalogEntry] = []
        seen: set[tuple[str, str]] = set()
        for i, rec in enumerate(records or []):
            if not isinstance(rec, dict):
                continue
            # A search hits archive photos, dissertations and maps too; a
            # bookshelf spine is a book. Live sample: 34 books, 12 archive.
            if _dc(rec, "type") and _dc(rec, "type") != "book":
                continue
            title = _clean(_dc(rec, "title"))
            if not title:
                continue
            author = _clean_creator(_dc(rec, "creator"))
            # NLI holds many editions of the same work; collapse them or the
            # matcher's dedup sees a shelf full of identical claimants.
            key = (normalize(title), normalize(author))
            if key in seen:
                continue
            seen.add(key)
            cid = str(_dc(rec, "recordid") or rec.get("@id") or f"nli{i}")
            out.append(CatalogEntry(cid, title, author))
        return out

    # -- Catalog protocol ----------------------------------------------------
    def _fetch(self, url: str) -> str:
        """Fetch with disk cache, retrying transient server errors.

        NLI intermittently answers 500 to a query it serves fine on retry.
        Swallowing that (returning '') silently costs recall — the spine just
        finds no candidates and looks unmatched — and, worse, makes results
        NON-REPRODUCIBLE, which quietly corrupts a tune-and-measure loop:
        rescoring the same run twice gave different numbers. Retry, and count
        what still failed so the caller can tell "no such book" from
        "the catalog was unreachable".
        """
        cache_file = None
        if self.cache_dir:
            h = hashlib.sha1(url.encode()).hexdigest()[:16]
            cache_file = self.cache_dir / f"{h}.json"
            if cache_file.exists():
                return cache_file.read_text(encoding="utf-8")

        body = ""
        for attempt in range(self.retries):
            try:
                body = self.transport(url)
                break
            except Exception as exc:
                self.last_error = str(exc)
                if attempt == self.retries - 1:
                    self.failed_fetches += 1
                    return ""
                time.sleep(self.retry_backoff * (attempt + 1))
        if cache_file and body:
            cache_file.write_text(body, encoding="utf-8")
        return body

    def candidates(self, query: str, limit: int = 15) -> list[CatalogEntry]:
        merged: dict[str, CatalogEntry] = {}
        # Phrases first (highest precision), then single terms for recall.
        for term in self._pick_phrases(query) + self._pick_terms(query):
            for e in self._parse(self._fetch(self._term_url(term))):
                merged.setdefault(normalize(e.title) + "|" + normalize(e.author), e)
            if len(merged) >= self.record_limit:
                break
        return list(merged.values())[: self.record_limit]


DC = "http://purl.org/dc/elements/1.1/"


def _dc(rec: dict, field: str) -> str:
    """Read one Dublin Core field out of an NLI JSON-LD record.

    Values arrive as [{"@value": "..."}] (or {"@id": ...} for links), so the
    wrapper has to be unpacked — this is the mapping that could not be
    verified during prototyping.
    """
    v = rec.get(DC + field) or rec.get(field)
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, dict):
        v = v.get("@value") or v.get("@id")
    return str(v).strip() if v else ""


def _clean(s: str) -> str:
    s = str(s)
    # MARC 245 often packs "title / statement of responsibility" — the part
    # after ' / ' is author/editor credits, not the title. Drop it.
    s = re.split(r"\s+/\s+", s, maxsplit=1)[0]
    s = re.split(r"\s+:\s+", s, maxsplit=1)[0]   # drop subtitle after ' : '
    s = s.split("$$")[0]                          # MARC subfield delimiters
    s = re.sub(r"\s*[.,;:/]\s*$", "", s)
    return s.strip()


def _clean_creator(s: str) -> str:
    """NLI creators look like "דארל, ג'ראלד, 1925-1995$$Qדארל, ג'ראלד" or
    "לו, מרי, 1984- מחבר" — strip the MARC subfield tail, cataloguer role
    words, and the life dates. The roles leaked into the UI (the owner had to
    ask why וורקרוס was "by מרי לו 1984- מחבר") and depress author matching.
    """
    s = str(s).split("$$")[0]
    # trailing role designators, possibly several: מחבר מאייר / עורך / מתרגם
    s = re.sub(r"(?:\s+(?:מחבר|מאייר|עורך|עורכת|מתרגם|מתרגמת|כותב))+\s*$", "", s)
    s = re.sub(r",?\s*\d{3,4}\s*-\s*\d{0,4}\.?\s*$", "", s)
    s = re.sub(r"\s*[.,;:]\s*$", "", s)
    return s.strip()
