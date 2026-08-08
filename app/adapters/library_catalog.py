# -*- coding: utf-8 -*-
"""The product's confirmed books, as a retrieval source.

The tuning server unions its own confirmed library into the retrieval chain
(``booksnap/library.py:ConfirmedCatalog``, wired by ``LibraryFirstCatalog``)
because a book the owner has confirmed once should match instantly on every
later shelf. The product needs the same thing and **cannot use that class**:
``ConfirmedCatalog`` reads ``work/library.json``, which is the TUNING server's
store. The product reads its own or nothing — that boundary is what keeps the
run archive from becoming a shared filesystem (D1, and CLAUDE.md's rule that
the product never reads ``work/runs/``).

So this is the product's own implementation over ``BookStore``, duck-typed to
``booksnap.catalog.Catalog`` — an ADAPTER, which is the layer allowed to know
both worlds.

Two properties carried over deliberately from the original, because both are
load-bearing and neither is obvious:

  - **candidates are prefiltered by token overlap**, so an unrelated query
    returns ``[]``. This source AUGMENTS the chain rather than gating it, and
    a source that answers everything would flood the matcher's pool with the
    whole library on every spine;
  - **it is a union, never a cascade** (see ``LibraryFirstCatalog``). A shared
    token with a confirmed book must not stop retrieval for a different,
    unconfirmed book — a new series sibling is exactly that case.

⚠ Note the asymmetry with the sweep: CLAUDE.md records the owner's decision
that the confirmed library is **never** a source in `tools/sweep.py`, because
there it is an *outcome* of the runs being measured and would leak the answer
into the fixture. In a real read it is legitimate evidence. Same object, two
roles; do not "fix" the inconsistency by making them agree.
"""
from __future__ import annotations

from booksnap.catalog import CatalogEntry, normalize

from app.domain import LibraryRef
from app.ports.store import BookStore

# The whole library is scanned per query. Measured in P1.5's search work: a
# linear pass over the owner's real 251 books is ~4ms, and 10k is ~53ms. The
# target is a few thousand, so this is not the place to add an index; when it
# stops being enough the fix is a narrowing clause in the store, exactly as
# `BookStore.search` documents.
_SCAN_LIMIT = 10_000

# Tokens shorter than this are dropped from the query. 1-2 letter Hebrew
# tokens appear inside almost every word, so keeping them would make every
# query overlap every book — which is precisely the flooding this prefilter
# exists to prevent. Same threshold as `ConfirmedCatalog`.
_MIN_TOKEN = 3


class ProductLibraryCatalog:
    """The library's confirmed books as ``booksnap`` catalog entries."""

    def __init__(self, store: BookStore, library: LibraryRef) -> None:
        self._store = store
        self._library = library

    def candidates(self, query: str, limit: int = 15) -> list[CatalogEntry]:
        q = {t for t in normalize(query).split() if len(t) >= _MIN_TOKEN}
        if not q:
            return []
        out: list[CatalogEntry] = []
        for book in self._store.list(self._library, limit=_SCAN_LIMIT).items:
            tokens = (set(book.normalized_title.split())
                      | set(book.normalized_author.split()))
            if q & tokens:
                # `lib:` prefix matches the tuning server's convention, so a
                # claim's catalog_id says which source produced it.
                out.append(CatalogEntry(f"lib:{book.key}", book.title,
                                        book.author))
            if len(out) >= limit:
                break
        return out
