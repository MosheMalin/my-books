# -*- coding: utf-8 -*-
"""The BookStore port — the seam that makes the datastore decision reversible.

Plan D1 picks SQLite *now*, Postgres later, and says plainly that "the
contract tests are what keep this revisitable". So this file is the contract,
and `tests/test_store_contract.py` runs it against every implementation.

Two rules shape every signature here:

  - **every method is library-scoped** (H2). Not "most"; every one. A method
    without a ``library`` parameter is a method that has to be rewritten at
    pillar 3, and by then it has call sites;
  - **the Book aggregate is saved whole.** Copies and provenance travel with
    their book rather than having stores of their own. That keeps the rules in
    ``app/domain`` — a store that could write a Copy independently would be a
    second path to creating one, and §5.1 says there is exactly one.

Deliberately NOT here: full-text search (P1.5 — it needs a measured mechanism,
not a guessed one) and shelf queries (P2.1 owns Shelf).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from app.domain import Book, LibraryRef, Status


class StoreError(Exception):
    """Base for storage-contract violations, as opposed to domain rules."""


class DuplicateBookKey(StoreError):
    """Two different books would share one ``normalize(t)|normalize(a)`` key.

    §5.1: a Book is identified by ``{title, author}`` *within a library*. This
    fires when an edit renames a book onto another one — a real case (fixing a
    misread title to one you already own), and one whose resolution is a merge,
    not a silent overwrite. The store refuses; P1.4 decides.
    """


class WrongLibrary(StoreError):
    """A record's ``library_id`` disagrees with the scope it is written to.

    Never a user error — always a wiring bug, and the kind that writes one
    tenant's data into another's. It raises loudly rather than being coerced.
    """


class BookSort(str, Enum):
    """Sort orders §6 lists as "Must". ``TITLE``/``AUTHOR`` sort by NORMALIZED
    forms, so Hebrew orders sensibly regardless of nikud, geresh or a leading
    particle in the stored string.

    ``AUTHOR`` orders by SURNAME (``app.domain.text.author_sort_key``), the way
    a shelf is filed — not by the stored string, which would put every author
    under their given name. Every implementation must agree; the contract
    suite asserts it against each one.
    """

    TITLE = "title"
    AUTHOR = "author"
    RECENTLY_ADDED = "recently_added"


@dataclass(frozen=True)
class BookPage:
    """One page of results plus the total, so the client can render "1-20 of
    251" without a second round trip."""

    items: tuple[Book, ...]
    total: int
    offset: int
    limit: int


class BookStore(Protocol):
    """Persistence for the Book aggregate. All methods library-scoped (H2)."""

    def save(self, library: LibraryRef, book: Book) -> None:
        """Insert or replace a book and everything under it.

        Raises :class:`WrongLibrary` if ``book.library_id`` disagrees with
        ``library``, and :class:`DuplicateBookKey` if a *different* book in
        this library already holds the same key.
        """

    def get(self, library: LibraryRef, book_id: str) -> Book | None:
        """By id, or ``None``. A book in another library reads as ``None`` —
        indistinguishable from absent, which is what lets the API answer 404
        rather than 403 and avoid leaking existence (§4.2, P3.3)."""

    def get_by_key(self, library: LibraryRef, key: str) -> Book | None:
        """By ``normalize(title)|normalize(author)`` — the identity a read
        uses to ask "do I already own this?" (§5.4, §5.6)."""

    def delete(self, library: LibraryRef, book_id: str) -> bool:
        """*Delete from the library*: the book and every copy under it.

        The other, non-destructive action lives in the domain
        (``remove_from_shelf``). Returns False if it wasn't there.
        """

    def list(
        self,
        library: LibraryRef,
        *,
        sort: BookSort = BookSort.TITLE,
        ascending: bool = True,
        status: Status | None = None,
        author_key: str | None = None,
        lent_out: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> BookPage:
        """The Books tab's query (§6): sort, page, filter by status or author.

        ``author_key`` is a NORMALIZED author string — the author chip is a
        grouping over normalized strings, not an entity (§5.1).

        ``lent_out`` matches a book with AT LEAST ONE copy currently lent out
        (``Lending.is_out``) — the "who has my books" view (§5.2). It is a
        book-level filter over a copy-level fact, same shape as ``status``.
        """

    def search(
        self,
        library: LibraryRef,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> BookPage:
        """Hebrew search over title + author, ranked by relevance (P1.5).

        A separate method from :meth:`list` because the result ORDER is the
        answer here — relevance, not an axis the caller picks. Passing a
        ``sort`` alongside a query would be a lie.

        **What an implementation may and may not choose.** The semantics are
        fixed by ``app.domain.search``: :func:`~app.domain.search.parse` says
        what a query means and :func:`~app.domain.search.score` says what comes
        first, and both are pure. An adapter chooses only how it NARROWS —
        SQLite uses ``LIKE`` over a stored haystack column, Postgres could use
        ``pg_trgm`` or a tsvector — and then ranks with the shared function.
        The contract suite runs the same cases against every implementation,
        so a clever retrieval strategy that changes the answers gets caught.

        An empty or whitespace-only query returns an EMPTY page, never the
        whole library: an empty search box is the caller's business.
        """

    def count(self, library: LibraryRef) -> int:
        """Books in this library. Cheap enough to call on every page."""
