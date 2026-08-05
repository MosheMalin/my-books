# -*- coding: utf-8 -*-
"""Coverage probe: does Simania's search cover the 35 ground-truth books?

For each hand-labelled book, query Simania's suggestions endpoint with the
title as printed on the spine and check whether any returned candidate is the
same book (particle-tolerant title similarity, same bar as scoring.py).
Fallback query: the two longest title tokens (mimics a partial/garbled read).

Polite: ~2s between requests, browser UA, every response cached permanently in
work/simania_cache/ so re-runs cost the site nothing.

Usage: python tools/simania_probe.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from rapidfuzz import fuzz

from booksnap.catalog import normalize
from booksnap.scoring import TITLE_HIT, Book, _title_sim, load_ground_truth

API = "https://simania.co.il/api/search/suggestions?q={q}&limit=15"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CACHE = REPO / "work" / "simania_cache"
DELAY_S = 2.0

_last_call = [0.0]


def query(q: str) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(q.encode("utf-8")).hexdigest()[:16]
    cached = CACHE / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    wait = DELAY_S - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(API.format(q=urllib.parse.quote(q)),
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    _last_call[0] = time.time()
    cached.write_text(json.dumps({"_query": q, **data}, ensure_ascii=False),
                      encoding="utf-8")
    return data


def best_hit(book: Book, cands: list[dict]) -> tuple[float, dict | None]:
    best, hit = 0.0, None
    for c in cands:
        s = _title_sim(c.get("title") or "", book)
        if s > best:
            best, hit = s, c
    return best, hit


def fallback_query(title: str) -> str:
    toks = sorted(title.split(), key=len, reverse=True)[:2]
    return " ".join(toks)


def main() -> None:
    gt = load_ground_truth()
    found = missed = 0
    exact_spelling = 0
    author_ok = author_absent = 0
    with_series = 0

    for image, books in gt.items():
        print(f"\n=== {image} ===")
        for b in books:
            data = query(b.title)
            cands = data.get("suggestions") or []
            sim, hit = best_hit(b, cands)
            via = "title"
            if sim < TITLE_HIT:
                data2 = query(fallback_query(b.title))
                sim2, hit2 = best_hit(b, data2.get("suggestions") or [])
                if sim2 > sim:
                    sim, hit, via = sim2, hit2, "fallback"

            if sim >= TITLE_HIT and hit:
                found += 1
                spelling = "=" if normalize(hit["title"]) == normalize(b.title) else "~"
                if spelling == "=":
                    exact_spelling += 1
                a = ""
                if b.author:
                    ar = fuzz.token_set_ratio(normalize(hit.get("author") or ""),
                                              normalize(b.author))
                    a = f" author {'OK' if ar >= 72 else 'DIFF'}"
                    author_ok += ar >= 72
                else:
                    author_absent += 1
                srs = f" [series: {hit['series']} #{hit.get('seriesNumber')}]" if hit.get("series") else ""
                if hit.get("series"):
                    with_series += 1
                print(f"  HIT {spelling} ({sim:.0f}, {via}) {b.title} -> "
                      f"{hit['title']} | {hit.get('author','')}{a}{srs}")
            else:
                missed += 1
                got = f"best {sim:.0f}: {hit['title']}" if hit else "no results"
                print(f"  MISS       {b.title}  ({got})")

    total = found + missed
    print(f"\ncoverage: {found}/{total} ({found/total:.0%})")
    print(f"  exact normalized spelling: {exact_spelling}/{found}")
    print(f"  author agrees: {author_ok}/{found - author_absent} "
          f"(+{author_absent} books with no GT author)")
    print(f"  series metadata present: {with_series}/{found}")


if __name__ == "__main__":
    main()
