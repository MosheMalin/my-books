# -*- coding: utf-8 -*-
"""P1.5 — Hebrew search, asserted against real queries on the real library.

The plan calls this "the one genuinely hard part" and Risk 3 says it is the
item most likely to be underestimated, so it ships with numbers rather than
adjectives. Two halves:

  - ``fixtures/search/`` — the owner's 251 real {title, author} pairs and a
    hand-written query fixture. Every query records WHY it is there, because a
    query whose purpose nobody remembers gets deleted the first time it fails;
  - the mechanism comparison below, which pins the *measured* justification.
    Ranking, particle tolerance and AND-not-OR each earn their place on this
    fixture, and a future change that drops one has to beat the table again.

``tools/search_eval.py`` runs the same measurement interactively.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.domain import Book, new_book, normalize
from app.domain import search as S

FIXTURES = REPO_ROOT / "fixtures" / "search"


def _corpus() -> list[Book]:
    rows = json.loads((FIXTURES / "corpus.json").read_text(encoding="utf-8"))
    return [
        new_book(id=f"b{i}", library_id="lib", title=r["title"],
                 author=r.get("author", ""), copy_id=f"c{i}")
        for i, r in enumerate(rows)
    ]


def _queries() -> list[dict]:
    return json.loads((FIXTURES / "queries.json").read_text(encoding="utf-8"))


def _titles(books: list[Book], q: str) -> list[str]:
    return [b.title for b in S.search(S.parse(q), books)]


# --- the fixture ----------------------------------------------------------

def test_every_fixture_query_puts_the_right_book_first():
    """P@1 — the metric that matters. On a personal library the failure mode
    is never "nothing found"; it is the right book at rank 9 behind its series
    siblings."""
    books = _corpus()
    misses = []
    for case in _queries():
        want = case.get("expect_top")
        if not want:
            continue
        got = _titles(books, case["q"])
        if not got or got[0] != want:
            misses.append(f"{case['q']!r}: want {want!r}, got {got[:3]}")
    assert not misses, "\n".join(misses)


def test_every_fixture_query_returns_all_the_books_it_should():
    books = _corpus()
    misses = []
    for case in _queries():
        got = _titles(books, case["q"])
        for want in case.get("expect_contains", []):
            if want not in got:
                misses.append(f"{case['q']!r}: {want!r} missing from {got[:4]}")
    assert not misses, "\n".join(misses)


def test_the_fixture_still_covers_the_cases_it_claims_to():
    """Guards the fixture itself. Every entry carries a `why`, and the whole
    set has to keep covering the Hebrew rules the plan names — otherwise the
    suite can go green while quietly testing nothing."""
    cases = _queries()
    assert len(cases) >= 20
    for c in cases:
        assert c.get("why"), c
        assert "expect_top" in c or "expect_contains" in c, c

    joined = " ".join(c["why"].lower() for c in cases)
    for topic in ("particle", "geresh", "final letter", "mixed script",
                  "ranking", "series"):
        assert topic in joined, f"no fixture case explains {topic!r}"


def test_a_corpus_query_is_not_accidentally_matching_everything():
    """Noise ceiling. A mechanism with perfect recall that returns 40 books
    per query is useless, and recall alone would not show it."""
    books = _corpus()
    counts = [len(_titles(books, c["q"])) for c in _queries()]
    assert max(counts) <= 15, f"a query returned {max(counts)} books"
    assert sum(counts) / len(counts) < 4.0


# --- the mechanism, measured ---------------------------------------------

def _p_at_1(books, *, ranked=True, particles=True, require_all=True) -> float:
    hits = 0
    total = 0
    for case in _queries():
        want = case.get("expect_top")
        if not want:
            continue
        total += 1
        q = S.parse(case["q"])
        if not particles:
            q = S.Query(raw=q.raw, normalized=q.normalized,
                        terms=tuple(S.Term(t.text, (t.text,)) for t in q.terms))
        pred = all if require_all else any
        got = [b for b in books
               if q.terms and pred(S.term_matches(t, S.haystack(b))
                                   for t in q.terms)]
        got.sort(key=lambda b: ((-S.score(q, b)) if ranked else 0,
                                b.normalized_title, b.id))
        if got and got[0].title == want:
            hits += 1
    return hits / total


def test_relevance_ranking_beats_alphabetical_order():
    """Measured +0.12 P@1 on this fixture. Two queries decide it: 'עיר', where
    the exact title loses alphabetically to 'מהעיר הדוממת', and 'ירושלים',
    where an AUTHOR match sorts above the book that has it in the TITLE."""
    books = _corpus()
    assert _p_at_1(books, ranked=True) == 1.0
    assert _p_at_1(books, ranked=False) < 0.95


def test_particle_tolerance_earns_its_place():
    """The ה/ו/ב/ל/מ/ש/כ variants. Note the asymmetry with the matcher, where
    the SAME transform measured harmful (CLAUDE.md: precision 0.62 -> 0.50):
    a matcher compares two machine strings, search compares a human's typing
    to a catalogue."""
    books = _corpus()
    assert _p_at_1(books, particles=True) > _p_at_1(books, particles=False)


def test_requiring_all_terms_is_much_quieter_than_any():
    """AND vs OR. Both reach P@1 1.00 here — ranking is strong enough to
    surface the right book either way — so the case for AND is the RESULT SET:
    OR returns ~2.4x the books, which on a list UI is the difference between
    an answer and a haystack."""
    books = _corpus()
    def noise(require_all):
        total = 0
        for case in _queries():
            q = S.parse(case["q"])
            pred = all if require_all else any
            total += sum(1 for b in books if q.terms
                         and pred(S.term_matches(t, S.haystack(b))
                                  for t in q.terms))
        return total / len(_queries())

    assert noise(True) < noise(False) / 2


# --- rules ---------------------------------------------------------------

def test_an_empty_query_matches_nothing_not_everything():
    """An empty search box is the caller's business. Returning the whole
    library here is how a UI shows 251 results for a stray keystroke."""
    for blank in ("", "   ", "\t", "!!!"):
        assert not S.parse(blank)
        assert _titles(_corpus(), blank) == []


def test_only_one_leading_particle_is_stripped():
    """Two would turn ובבית into a stem that matches far too much, and a
    stemmer that also strips SUFFIXES is where precision dies on 251 books."""
    assert S.parse("הבית").terms[0].variants == ("הבית", "בית")
    assert S.parse("ובבית").terms[0].variants == ("ובבית", "בבית")


def test_a_two_letter_term_never_matches_mid_word():
    """1-2 letters appear inside almost every Hebrew word, so short terms are
    anchored to a word start. Otherwise 'אב' returns the library."""
    short = S.parse("אב").terms[0]
    assert short.anchored_only
    assert S.term_matches(short, "אבנ הזמנ")          # word start
    assert not S.term_matches(short, "כתאב הזמנ")     # mid-word
    assert len(_titles(_corpus(), "אב")) < 15


def test_search_keys_come_from_the_same_normalize_the_matcher_uses():
    """Nikud, final letters and in-word geresh must behave for search exactly
    as they do for matching — that is the whole reason normalize() is imported
    rather than re-implemented."""
    assert S.parse("שָׁלוֹם").normalized == "שלומ"
    assert S.parse("הצ'ופצ'יק").terms[0].text == "הצופציק"
    assert S.parse("ABC def").normalized == "ABC def"  # Latin survives


# --- the adapter seam -----------------------------------------------------

def test_sql_compilation_escapes_like_wildcards():
    """normalize() already drops % and _, so this is belt and braces — but a
    title that reached the column unescaped would turn a search into a
    wildcard query returning the library."""
    sql, params = S.compile_sql_like(S.parse("100% pure"), "search_text")
    assert all("%" not in p.strip("%") or "\\%" in p for p in params)
    assert "ESCAPE" in sql


def test_sql_compilation_emits_one_and_clause_per_term():
    """The shape the adapters rely on: terms AND-ed, variants OR-ed inside."""
    sql, params = S.compile_sql_like(S.parse("הבית הגדול"), "search_text")
    assert sql.count(" AND ") == 1
    assert sql.count(" OR ") == 2      # one particle variant per term
    assert len(params) == 4


def test_an_author_search_browses_alphabetically_not_by_title_length():
    """When every hit matches only the AUTHOR they all score identically, so
    whatever breaks the tie IS the order. The title-length bonus is skipped in
    that case, letting the stable (title, id) tiebreak show through — an
    author's shelf in alphabetical order, which is what browsing wants.

    Found by reading real output: 'באלדאצי' used to lead with 'מרסי' purely
    because it is the shortest title of the eleven.
    """
    books = _corpus()
    titles = _titles(books, "באלדאצי")
    assert len(titles) > 5
    assert titles == sorted(titles, key=normalize), titles


def test_the_reference_ordering_is_a_total_order():
    """Ties broken by (title, id), so paging a result set cannot show one book
    twice and another never — the same rule the store contract enforces for
    list()."""
    books = _corpus()
    q = S.parse("הצי האבוד")
    first = [b.id for b in S.search(q, books)]
    second = [b.id for b in S.search(q, list(reversed(books)))]
    assert first == second and len(first) == 5


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))
