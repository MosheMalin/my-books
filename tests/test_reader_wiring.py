# -*- coding: utf-8 -*-
"""What catalog the product hands the engine — offline.

This module exists because of a bug that cost a real afternoon and looked
exactly like an engine regression: a real shelf read 69 spines correctly and
matched **zero** books. Nothing was wrong with the engine. The product's
reader had no ``simania`` branch, so a correctly-set
``BOOKSNAP_CATALOG_BACKEND=simania`` fell through an ``else`` and loaded
``sample_catalog.json`` — the **57-entry hand-typed stand-in** from early
prototyping. The measured baseline in CLAUDE.md is the other one.

So the rules here are about WIRING, not accuracy: which catalog gets built,
and that a misconfiguration is loud instead of silently degrading. No network
— the chain's constructors only take cache directories; nothing is queried
until a spine asks for candidates.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.booksnap_reader import BooksnapReader
from app.adapters.library_catalog import ProductLibraryCatalog
from app.adapters.memory_store import MemoryBookStore
from app.domain import LibraryRef, new_book

LIB = LibraryRef("lib-test", "Test library")


def _reader(books=None) -> BooksnapReader:
    """No blob store needed: nothing here reads an image, and `_build` never
    touches one — which is itself worth knowing, since it means catalog wiring
    is testable without a filesystem."""
    return BooksnapReader(blob_store=None, book_store=books)  # type: ignore[arg-type]


class _Env:
    """Set env vars for one test and restore them, whatever happens."""

    def __init__(self, **vars_: str | None):
        self._want = vars_
        self._saved: dict[str, str | None] = {}

    def __enter__(self):
        for k, v in self._want.items():
            self._saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"expected {exc.__name__}, nothing raised")


# --- the bug ---------------------------------------------------------------

def test_the_default_catalog_is_the_measured_chain_not_the_sample_file():
    """The regression. `sample_catalog.json` is 57 hand-typed entries; every
    measured number in CLAUDE.md comes from the simania chain. A product whose
    out-of-the-box catalog is the stand-in reads a real shelf as zero books,
    which is indistinguishable from a broken engine to whoever is looking."""
    from booksnap.extra_catalogs import ChainCatalog

    with _Env(BOOKSNAP_CATALOG_BACKEND=None):
        catalog, _fallback, _pr = _reader()._build("llmpage")
    assert isinstance(catalog, ChainCatalog), type(catalog).__name__


def test_the_simania_backend_is_actually_wired():
    """It was not: `_build` had `nli` and an `else` that swallowed everything
    else. The owner's .env said `simania` and was silently ignored."""
    from booksnap.extra_catalogs import ChainCatalog

    with _Env(BOOKSNAP_CATALOG_BACKEND="simania"):
        catalog, _f, _p = _reader()._build("llmpage")
    assert isinstance(catalog, ChainCatalog)


def test_an_unrecognised_backend_raises_instead_of_degrading_quietly():
    """The defect CLASS, not just the instance. Falling back to the sample
    catalog turned a one-line config gap into an afternoon of "why does the
    engine find nothing" — a refusal would have named it immediately."""
    with _Env(BOOKSNAP_CATALOG_BACKEND="siamnia"):     # a typo, deliberately
        err = _raises(RuntimeError, _reader()._build, "llmpage")
    assert "siamnia" in str(err)
    assert "sample" in str(err).lower(), "the message does not explain the risk"


def test_local_is_still_reachable_for_offline_work():
    """Opt-in now rather than the default. It is the right catalog for a
    machine with no network, and the wrong one for a real shelf."""
    from booksnap.catalog import LocalCatalog

    with _Env(BOOKSNAP_CATALOG_BACKEND="local"):
        catalog, _f, _p = _reader()._build("llmpage")
    assert isinstance(catalog, LocalCatalog)


def test_the_confirmed_library_joins_the_chain_when_a_book_store_is_bound():
    """A book the owner confirmed once should match instantly on every later
    shelf — what the tuning server gets from `ConfirmedCatalog`. The product
    must get it from its OWN store: `booksnap.library.ConfirmedCatalog` reads
    `work/library.json`, which belongs to the tuning server."""
    from booksnap.library import LibraryFirstCatalog

    with _Env(BOOKSNAP_CATALOG_BACKEND="simania"):
        bound, _f, _p = _reader(MemoryBookStore())._build("llmpage", LIB)
        unbound, _f2, _p2 = _reader()._build("llmpage", LIB)
    assert isinstance(bound, LibraryFirstCatalog)
    assert not isinstance(unbound, LibraryFirstCatalog), \
        "an unbound reader invented a library from nowhere"


# --- the product's confirmed books as a source -----------------------------

def _store_with(*titles_authors) -> MemoryBookStore:
    store = MemoryBookStore()
    for i, (title, author) in enumerate(titles_authors, start=1):
        store.save(LIB, new_book(id=f"b{i}", library_id=LIB.id, title=title,
                                 author=author, copy_id=f"c{i}"))
    return store


def test_a_confirmed_book_is_offered_for_a_query_that_shares_a_word():
    store = _store_with(("הנשר נחת", "ג'ק היגינס"), ("רוחות מלחמה", "הרמן ווק"))
    cat = ProductLibraryCatalog(store, LIB)

    got = cat.candidates("הנשר נחת")
    assert [e.title for e in got] == ["הנשר נחת"]


def test_an_unrelated_query_gets_nothing_so_the_chain_is_not_flooded():
    """This source AUGMENTS the chain rather than gating it, so a source that
    answered everything would put the whole library into the matcher's pool on
    every single spine — and the gates would then have to argue with 250
    irrelevant candidates per read."""
    cat = ProductLibraryCatalog(_store_with(("הנשר נחת", "ג'ק היגינס")), LIB)
    assert cat.candidates("מלכי הכופרים פול קארני") == []


def test_one_and_two_letter_words_never_match_on_their_own():
    """1-2 letter Hebrew tokens sit inside almost every title, so keeping them
    in the query would make nearly every book overlap nearly every query —
    exactly the flooding the prefilter exists to prevent (the same threshold
    P1.5 measured for search).

    ⚠ The stored book must itself CONTAIN the short word, or this passes with
    the rule removed: a fixture with no short token has nothing for the
    mutation to match against. Found by mutation testing — the first version of
    this test survived dropping the length check entirely.
    """
    cat = ProductLibraryCatalog(_store_with(("בית של קלפים", "מייקל דובס")), LIB)

    assert cat.candidates("של") == [], "a two-letter word pulled a book in"
    assert cat.candidates("") == []
    # The same book is still reachable by a real word, so the filter narrows
    # the QUERY rather than hiding the book.
    assert [e.title for e in cat.candidates("קלפים")] == ["בית של קלפים"]


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))
