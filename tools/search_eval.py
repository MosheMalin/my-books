# -*- coding: utf-8 -*-
"""Measure Hebrew search against real queries on the real library.

    python tools/search_eval.py              # score the shipped mechanism
    python tools/search_eval.py --compare    # score every variant, side by side
    python tools/search_eval.py --explain "הצי האבוד תעוזה"

Plan P1.5 asks for "a query fixture (query -> expected-hit pairs drawn from the
real 251 books) asserted in tests, and a measured note on the mechanism chosen.
Not 'it should work'." This is the measurement half; `tests/test_search.py` is
the asserted half.

Metrics, and why these three:

  P@1     the expected book is the FIRST result. On a personal library the
          failure mode is never "nothing found" — it is the right book sitting
          at rank 9 behind its series siblings. This is the metric that
          matters most and the one a naive implementation quietly fails.
  recall  the expected book is somewhere in the results. Cheap to max out by
          matching everything, which is exactly why it is not reported alone.
  noise   mean results per query. A mechanism that returns 40 books for every
          query has perfect recall and is useless.

Inputs are committed (fixtures/search/), so this reproduces on a fresh clone
with no work/ directory.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.domain import Book, new_book  # noqa: E402
from app.domain import search as S  # noqa: E402

FIXTURES = REPO_ROOT / "fixtures" / "search"


def load_corpus() -> list[Book]:
    rows = json.loads((FIXTURES / "corpus.json").read_text(encoding="utf-8"))
    return [
        new_book(id=f"b{i}", library_id="eval", title=r["title"],
                 author=r.get("author", ""), copy_id=f"c{i}")
        for i, r in enumerate(rows)
    ]


def load_queries() -> list[dict]:
    return json.loads((FIXTURES / "queries.json").read_text(encoding="utf-8"))


# --- mechanism variants, so the choice is a comparison and not an assertion --
#
# Each returns the ranked hit list. The shipped one is "and+particles+rank";
# the others exist to justify it. Keep them: a future change ("let's use OR",
# "let's drop the particle variants") should have to beat the table again.

def _run(books, q, *, require_all=True, particles=True, ranked=True,
         anchor_all=False):
    query = S.parse(q)
    if not particles:
        query = S.Query(
            raw=query.raw, normalized=query.normalized,
            terms=tuple(S.Term(t.text, (t.text,)) for t in query.terms),
        )
    if anchor_all:
        query = S.Query(
            raw=query.raw, normalized=query.normalized,
            # force every term to word-start matching by making it "short"
            terms=tuple(S.Term(t.text, t.variants) for t in query.terms),
        )

    def hit(b):
        hay = S.haystack(b)
        if anchor_all:
            ok = [any(S._hit(hay, v, True) for v in t.variants)
                  for t in query.terms]
        else:
            ok = [S.term_matches(t, hay) for t in query.terms]
        if not ok:
            return False
        return all(ok) if require_all else any(ok)

    hits = [b for b in books if hit(b)] if query.terms else []
    if ranked:
        hits.sort(key=lambda b: (-S.score(query, b), b.normalized_title, b.id))
    else:
        hits.sort(key=lambda b: (b.normalized_title, b.id))
    return hits


VARIANTS = {
    "and+particles+rank": {},
    "and+particles+alpha": {"ranked": False},
    "and, no particles":   {"particles": False},
    "OR terms":            {"require_all": False},
    "word-start only":     {"anchor_all": True},
}


def evaluate(books, queries, **kw) -> dict:
    at1 = found = total_expected = 0
    noise = 0
    misses: list[str] = []
    for case in queries:
        hits = _run(books, case["q"], **kw)
        titles = [b.title for b in hits]
        noise += len(titles)

        top = case.get("expect_top")
        if top:
            total_expected += 1
            if titles and titles[0] == top:
                at1 += 1
            elif top in titles:
                found += 1
                misses.append(f"rank {titles.index(top) + 1}: {case['q']!r} "
                              f"-> want {top!r}, got {titles[0]!r}")
            else:
                misses.append(f"MISSING: {case['q']!r} -> want {top!r}")

        for want in case.get("expect_contains", []):
            total_expected += 1
            if want in titles:
                found += 1
                at1 += 0
            else:
                misses.append(f"MISSING: {case['q']!r} -> want {want!r}")
    tops = sum(1 for c in queries if c.get("expect_top"))
    return {
        "p_at_1": at1 / tops if tops else 0.0,
        "recall": (at1 + found) / total_expected if total_expected else 0.0,
        "noise": noise / len(queries) if queries else 0.0,
        "misses": misses,
    }


def cmd_compare(books, queries) -> int:
    print(f"{len(queries)} queries against {len(books)} books\n")
    print(f"{'mechanism':<22} {'P@1':>6} {'recall':>7} {'noise':>7}")
    print("-" * 46)
    for name, kw in VARIANTS.items():
        r = evaluate(books, queries, **kw)
        print(f"{name:<22} {r['p_at_1']:>6.2f} {r['recall']:>7.2f} "
              f"{r['noise']:>7.1f}")
    return 0


def cmd_score(books, queries) -> int:
    r = evaluate(books, queries)
    print(f"{len(queries)} queries against {len(books)} books")
    print(f"  P@1    {r['p_at_1']:.2f}")
    print(f"  recall {r['recall']:.2f}")
    print(f"  noise  {r['noise']:.1f} results/query")
    for m in r["misses"]:
        print(f"  ! {m}")
    return 0 if not r["misses"] else 1


def cmd_explain(books, q: str) -> int:
    query = S.parse(q)
    print(f"query {q!r} -> normalized {query.normalized!r}")
    for t in query.terms:
        print(f"  term {t.text!r} variants={list(t.variants)} "
              f"anchored={t.anchored_only}")
    hits = S.search(query, books)
    print(f"{len(hits)} hits:")
    for b in hits[:15]:
        print(f"  {S.score(query, b):7.1f}  {b.title}  /  {b.author}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--explain", metavar="QUERY")
    args = ap.parse_args(argv)

    books = load_corpus()
    if args.explain:
        return cmd_explain(books, args.explain)
    queries = load_queries()
    return cmd_compare(books, queries) if args.compare \
        else cmd_score(books, queries)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
