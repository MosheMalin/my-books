# -*- coding: utf-8 -*-
"""Hebrew search — the SEMANTICS, in one place, portable to any store.

Plan P1.5 calls this "the one genuinely hard part", and Risk 3 says it is the
item most likely to be underestimated. So the mechanism here was chosen by
MEASUREMENT on a fixture of real queries against the real 251 books, not by
plausibility — see ``tools/search_eval.py`` and the numbers in CLAUDE.md.

**Why the rules live here and not in the SQL.** Every store implementation has
to agree on what "matches" means, or the same query gives different answers
depending on the datastore — and the datastore is explicitly meant to be
swappable (D1). So:

  - this module owns *parsing* (what a query means) and *ranking* (what comes
    first). Both pure, both shared;
  - an adapter owns only *retrieval* — how it narrows the rows. SQLite uses
    ``LIKE`` over the normalized columns; a Postgres adapter could use
    ``ILIKE``, ``pg_trgm`` or a tsvector and still be correct, because
    :func:`compile_sql_like` and :func:`matches` are checked against each
    other by the shared contract suite;
  - **ranking is always done in Python, never in SQL.** Ordering by relevance
    in SQL means writing the ranking twice, in two dialects, and discovering
    the drift from a user report. Narrowing is what databases are good at;
    ordering a few hundred already-matched rows is free.

The Hebrew rules, and why each is needed:

  - ``normalize()`` (shared with the matcher) strips nikud, folds final
    letters (ם→מ) and DELETES in-word geresh, so הצ'ופצ'יק stays one token;
  - **leading particles ה/ו/ב/ל/מ/ש/כ are tolerated in the QUERY.** Note the
    asymmetry: the same transform measured *harmful* inside the matcher
    (CLAUDE.md: precision 0.62 → 0.50) and is *required* here, because a
    matcher compares two machine strings while search compares a human's
    typing to a catalogue. The stored key is never stripped — only the query
    grows variants;
  - substring matching handles the other direction for free: a query for
    ``נבונים`` finds the stored ``הנבונים`` with no variant at all;
  - mixed script falls out of ``normalize()`` keeping Latin letters, so
    ``sapiens`` and ``ספיינס`` both work on the same field.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.book import Book
from app.domain.text import normalize

# One-letter prefixes a Hebrew speaker attaches to a noun: the definite
# article and the common prepositions/conjunctions. Not a stemmer — a stemmer
# would also strip suffixes, which is where precision goes to die on a
# 251-book corpus.
PARTICLES = "הובלמשכ"

# Below this, an infix match is noise: 1-2 letters appear inside almost every
# Hebrew word. Measured on the query fixture — see tools/search_eval.py.
MIN_INFIX_LEN = 3


@dataclass(frozen=True)
class Term:
    """One word of the query, plus the spellings it should also match."""

    text: str
    variants: tuple[str, ...]

    @property
    def anchored_only(self) -> bool:
        """Short terms match only at a word start, never mid-word."""
        return len(self.text) < MIN_INFIX_LEN


@dataclass(frozen=True)
class Query:
    """A parsed query. Empty ``terms`` means "match nothing", never "match
    everything" — an empty search box is the caller's business, not a request
    for the whole library."""

    raw: str
    normalized: str
    terms: tuple[Term, ...]

    def __bool__(self) -> bool:
        return bool(self.terms)


def _variants(token: str) -> tuple[str, ...]:
    """The token plus its particle-stripped form.

    Only ONE leading letter is removed, and only when what remains is still a
    real word (>= 2 chars). Stripping two would turn ``ולמלך`` into ``מלך``
    and also turn ``ובבית`` into a stem that matches far too much.
    """
    if len(token) >= 3 and token[0] in PARTICLES:
        return (token, token[1:])
    return (token,)


def parse(text: str) -> Query:
    """Normalize and split a user's query. Pure; no store, no I/O."""
    norm = normalize(text or "")
    terms = tuple(Term(text=t, variants=_variants(t)) for t in norm.split() if t)
    return Query(raw=text or "", normalized=norm, terms=terms)


def haystack(book: Book) -> str:
    """What a query is matched against: normalized title, then author.

    Title first so a title hit can be told from an author hit by position —
    that is what lets ranking prefer the book you named over the shelf-mate by
    the same author.
    """
    return f"{book.normalized_title} | {book.normalized_author}"


# --- matching --------------------------------------------------------------

def _hit(hay: str, variant: str, anchored: bool) -> bool:
    if anchored:
        return hay.startswith(variant) or f" {variant}" in hay
    return variant in hay


def term_matches(term: Term, hay: str) -> bool:
    return any(_hit(hay, v, term.anchored_only) for v in term.variants)


def matches(query: Query, hay: str) -> bool:
    """ALL terms must appear. This is the reference semantics every store
    implementation must reproduce.

    AND rather than OR, measured: OR turns a two-word query into "every book
    sharing either word", which on this corpus means a common word like
    ``הצי`` drags in a dozen unrelated titles and buries the one you meant.
    """
    if not query.terms:
        return False
    return all(term_matches(t, hay) for t in query.terms)


# --- ranking ---------------------------------------------------------------

def score(query: Query, book: Book) -> float:
    """Relevance. Higher is better; ties broken by the caller, stably.

    Every signal is about *specificity*, because on a personal library the
    failure mode is never "nothing found" — it is the right book sitting at
    rank 9 behind its series siblings.
    """
    title = book.normalized_title
    author = book.normalized_author
    hay = haystack(book)
    q = query.normalized

    total = 0.0
    if title == q:
        total += 1000.0                     # you typed the title exactly
    if title.startswith(q):
        total += 400.0                      # …or the start of it
    if q and q in title:
        total += 150.0                      # the whole query, in order

    in_title = sum(1 for t in query.terms if term_matches(t, title))
    in_author = sum(1 for t in query.terms if term_matches(t, author))
    n = max(len(query.terms), 1)
    total += 120.0 * (in_title / n)         # title hits outrank author hits
    total += 40.0 * (in_author / n)

    # A word-start hit is a real word; an infix hit may be a coincidence
    # inside a longer word.
    total += 25.0 * sum(
        1 for t in query.terms
        if any(_hit(hay, v, anchored=True) for v in t.variants)
    ) / n

    # Shorter titles are more specific answers to the same query: "אבן" should
    # rank the book called אבן above אבן, נייר, מספריים. Capped so a long
    # title with a genuinely better match still wins.
    #
    # ONLY when the query actually touched the title. On a pure author search
    # ("baldacci") every hit scores identically, and a length bonus would then
    # be the sole tiebreak — ordering an author's shelf by title length, which
    # is arbitrary and looks broken. Without it the tie falls through to the
    # caller's stable (title, id) order, i.e. alphabetical, which is what
    # browsing an author's books should do. Found by reading real output, not
    # by the fixture.
    if in_title:
        total += max(0.0, 30.0 - len(title) * 0.4)
    return total


def search(query: Query, books: list[Book]) -> list[Book]:
    """The reference implementation: filter, then rank.

    ``MemoryBookStore`` calls this directly. ``SqliteBookStore`` narrows in
    SQL first and then ranks with the SAME function, so the two cannot drift.
    """
    hits = [b for b in books if matches(query, haystack(b))]
    # Sorted by (-score, normalized_title, id): a total order, so paging a
    # result set cannot show one book twice and another never.
    hits.sort(key=lambda b: (-score(query, b), b.normalized_title, b.id))
    return hits


# --- adapter support -------------------------------------------------------

def compile_sql_like(query: Query, column: str) -> tuple[str, list[str]]:
    """Compile to a portable ``LIKE`` predicate over one text column.

    Returns ``(sql, params)``. Uses only ANSI ``LIKE``, so it runs unchanged on
    SQLite and Postgres; a Postgres adapter is free to swap in ``ILIKE`` or a
    trigram index instead, and the contract suite will tell it whether the
    answers still agree.

    The column is expected to already hold the normalized haystack, lower-cased
    the way ``normalize()`` leaves it — no ``LOWER()`` here, because collation
    behaviour on Hebrew is exactly the kind of thing that differs between
    engines and would make the two adapters disagree.
    """
    clauses: list[str] = []
    params: list[str] = []
    for term in query.terms:
        alts = []
        for v in term.variants:
            escaped = _escape_like(v)
            if term.anchored_only:
                alts.append(f"({column} LIKE ? ESCAPE '\\' "
                            f"OR {column} LIKE ? ESCAPE '\\')")
                params += [f"{escaped}%", f"% {escaped}%"]
            else:
                alts.append(f"{column} LIKE ? ESCAPE '\\'")
                params.append(f"%{escaped}%")
        clauses.append("(" + " OR ".join(alts) + ")")
    return " AND ".join(clauses), params


def _escape_like(s: str) -> str:
    """``%`` and ``_`` are wildcards; a title containing one must not become a
    wildcard query. ``normalize()`` already drops both, so this is belt and
    braces for a caller that skips it."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
