# -*- coding: utf-8 -*-
"""In-memory BookStore. Not a toy — it is the API ring's store (H4 ring 3).

It exists so API tests never touch a file, and so the contract suite has a
second implementation to run against. A contract with one implementation is
just that implementation's behaviour written twice; the second one is what
turns it into a spec, and it is why swapping SQLite for Postgres later is a
measured change rather than a leap (D1).

Books are stored per library and returned as-is: the domain entities are
frozen, so there is nothing to defensively copy.
"""
from __future__ import annotations

from app.domain import Book, LibraryRef, Status
from app.domain.search import parse
from app.domain.search import search as domain_search
from app.ports.store import (
    BookPage,
    BookSort,
    DuplicateBookKey,
    WrongLibrary,
)


class MemoryBookStore:
    """Implements ``app.ports.store.BookStore``."""

    def __init__(self) -> None:
        # Instance state, never module state (H2/§1.3).
        self._by_library: dict[str, dict[str, Book]] = {}

    # --- helpers ---------------------------------------------------------

    def _shelf(self, library: LibraryRef) -> dict[str, Book]:
        return self._by_library.setdefault(library.id, {})

    # --- BookStore -------------------------------------------------------

    def save(self, library: LibraryRef, book: Book) -> None:
        if book.library_id != library.id:
            raise WrongLibrary(
                f"book {book.id} belongs to {book.library_id!r}, "
                f"not {library.id!r}"
            )
        books = self._shelf(library)
        for other in books.values():
            if other.id != book.id and other.key == book.key:
                raise DuplicateBookKey(
                    f"{book.key!r} is already book {other.id} in this library"
                )
        books[book.id] = book

    def get(self, library: LibraryRef, book_id: str) -> Book | None:
        return self._shelf(library).get(book_id)

    def get_by_key(self, library: LibraryRef, key: str) -> Book | None:
        for b in self._shelf(library).values():
            if b.key == key:
                return b
        return None

    def delete(self, library: LibraryRef, book_id: str) -> bool:
        return self._shelf(library).pop(book_id, None) is not None

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
        rows = list(self._shelf(library).values())
        if status is not None:
            rows = [b for b in rows if b.status is status]
        if author_key is not None:
            rows = [b for b in rows if b.normalized_author == author_key]
        if lent_out is not None:
            rows = [b for b in rows if _any_copy_out(b) == lent_out]

        rows.sort(key=lambda b: _sort_key(b, sort), reverse=not ascending)
        total = len(rows)
        return BookPage(
            items=tuple(rows[offset: offset + limit]),
            total=total,
            offset=offset,
            limit=limit,
        )

    def search(
        self,
        library: LibraryRef,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> BookPage:
        """Straight to the reference implementation — no retrieval trick to
        get wrong. This is the answer the sqlite adapter has to reproduce."""
        parsed = parse(query)
        hits = domain_search(parsed, list(self._shelf(library).values()))
        return BookPage(items=tuple(hits[offset: offset + limit]),
                        total=len(hits), offset=offset, limit=limit)

    def count(self, library: LibraryRef) -> int:
        return len(self._shelf(library))


def _any_copy_out(book: Book) -> bool:
    return any(c.lending is not None and c.lending.is_out for c in book.copies)


def _sort_key(book: Book, sort: BookSort) -> tuple:
    """Mirror of the SQL ORDER BY in the sqlite adapter.

    The trailing ``book.id`` is not decoration: without a total order, two
    books with the same title page inconsistently and a user scrolling sees
    one twice and another never. The contract suite asserts it.
    """
    if sort is BookSort.AUTHOR:
        return (book.author_sort, book.normalized_title, book.id)
    if sort is BookSort.RECENTLY_ADDED:
        return (book.added_at or "", book.id)
    return (book.normalized_title, book.id)
