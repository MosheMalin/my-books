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

from app.domain import (
    Account,
    Book,
    Capture,
    Decision,
    DuplicateQuestion,
    Library,
    LibraryRef,
    Membership,
    Read,
    Role,
    Shelf,
    Status,
)
from app.domain.search import parse
from app.domain.search import search as domain_search
from app.ports.tenancy import UnknownAccount, UnknownLibrary
from app.ports.store import (
    BookPage,
    BookSort,
    DuplicateBookKey,
    DuplicateCaptureSlot,
    ShelfNotEmpty,
    UnknownShelf,
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
        book_ids: tuple[str, ...] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> BookPage:
        if book_ids is not None and not book_ids:
            # An explicit empty set means "nothing" — an empty duplicates
            # queue must page as zero books, not as "no id filter at all".
            return BookPage(items=(), total=0, offset=offset, limit=limit)
        rows = list(self._shelf(library).values())
        if status is not None:
            rows = [b for b in rows if b.status is status]
        if author_key is not None:
            rows = [b for b in rows if b.normalized_author == author_key]
        if lent_out is not None:
            rows = [b for b in rows if _any_copy_out(b) == lent_out]
        if book_ids is not None:
            wanted = set(book_ids)
            rows = [b for b in rows if b.id in wanted]

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


class MemoryShelfStore:
    """Implements ``app.ports.store.ShelfStore``.

    Same role as :class:`MemoryBookStore`: the API ring's store, and the second
    implementation that turns the shelf contract into a spec rather than a
    transcript of what SQLite happens to do.
    """

    def __init__(self) -> None:
        self._shelves: dict[str, dict[str, Shelf]] = {}
        self._captures: dict[str, dict[str, Capture]] = {}

    def _s(self, library: LibraryRef) -> dict[str, Shelf]:
        return self._shelves.setdefault(library.id, {})

    def _c(self, library: LibraryRef) -> dict[str, Capture]:
        return self._captures.setdefault(library.id, {})

    # --- shelves ---------------------------------------------------------

    def save_shelf(self, library: LibraryRef, shelf: Shelf) -> None:
        if shelf.library_id != library.id:
            raise WrongLibrary(
                f"shelf {shelf.id} belongs to {shelf.library_id!r}, "
                f"not {library.id!r}"
            )
        self._s(library)[shelf.id] = shelf

    def get_shelf(self, library: LibraryRef, shelf_id: str) -> Shelf | None:
        return self._s(library).get(shelf_id)

    def list_shelves(
        self,
        library: LibraryRef,
        *,
        include_virtual: bool = False,
    ) -> tuple[Shelf, ...]:
        rows = [s for s in self._s(library).values()
                if include_virtual or not s.virtual]
        # The domain owns the order (`Shelf.sort_key`), so this adapter and the
        # SQL one cannot disagree about where unnamed shelves go — the same
        # split as search's parse/score.
        rows.sort(key=lambda s: s.sort_key)
        return tuple(rows)

    def count_shelves(
        self, library: LibraryRef, *, include_virtual: bool = False
    ) -> int:
        return len(self.list_shelves(library, include_virtual=include_virtual))

    def delete_shelf(self, library: LibraryRef, shelf_id: str) -> bool:
        if shelf_id not in self._s(library):
            return False
        if self.list_captures(library, shelf_id):
            raise ShelfNotEmpty(
                f"shelf {shelf_id} still has captures; deleting it would "
                "destroy the record a re-read diffs against (§5.6)"
            )
        del self._s(library)[shelf_id]
        return True

    # --- captures --------------------------------------------------------

    def save_capture(self, library: LibraryRef, capture: Capture) -> None:
        if capture.library_id != library.id:
            raise WrongLibrary(
                f"capture {capture.id} belongs to {capture.library_id!r}, "
                f"not {library.id!r}"
            )
        if capture.shelf_id not in self._s(library):
            raise UnknownShelf(
                f"no shelf {capture.shelf_id!r} in library {library.id!r}"
            )
        for other in self._c(library).values():
            if other.id != capture.id and other.slot == capture.slot:
                raise DuplicateCaptureSlot(
                    f"capture {other.id} already holds {capture.slot} (§5.3)"
                )
        self._c(library)[capture.id] = capture

    def get_capture(self, library: LibraryRef, capture_id: str) -> Capture | None:
        return self._c(library).get(capture_id)

    def list_captures(
        self,
        library: LibraryRef,
        shelf_id: str,
        *,
        depth: int | None = None,
    ) -> tuple[Capture, ...]:
        rows = [c for c in self._c(library).values() if c.shelf_id == shelf_id]
        if depth is not None:
            rows = [c for c in rows if c.depth == depth]
        rows.sort(key=lambda c: (c.depth, c.order, c.id))
        return tuple(rows)

    def delete_capture(self, library: LibraryRef, capture_id: str) -> bool:
        return self._c(library).pop(capture_id, None) is not None


class MemoryReadStore:
    """Implements ``app.ports.store.ReadStore``.

    Same role as the other two memory stores: the API ring's store, and the
    second implementation that turns the read contract into a spec rather
    than a transcript of what SQLite happens to do.
    """

    def __init__(self) -> None:
        self._reads: dict[str, dict[str, Read]] = {}

    def _r(self, library: LibraryRef) -> dict[str, Read]:
        return self._reads.setdefault(library.id, {})

    def save_read(self, library: LibraryRef, read: Read) -> None:
        if read.library_id != library.id:
            raise WrongLibrary(
                f"read {read.id} belongs to {read.library_id!r}, "
                f"not {library.id!r}"
            )
        self._r(library)[read.id] = read

    def get_read(self, library: LibraryRef, read_id: str) -> Read | None:
        return self._r(library).get(read_id)

    def list_reads(
        self,
        library: LibraryRef,
        shelf_id: str,
        *,
        depth: int | None = None,
    ) -> tuple[Read, ...]:
        rows = [r for r in self._r(library).values() if r.shelf_id == shelf_id]
        if depth is not None:
            rows = [r for r in rows if r.depth == depth]
        # Most-recent-first, id as the tiebreaker for a total order — mirrors
        # the SQL adapter's ORDER BY exactly, so the two cannot disagree.
        rows.sort(key=lambda r: (r.started_at or "", r.id), reverse=True)
        return tuple(rows)

    def list_all_reads(self, library: LibraryRef) -> tuple[Read, ...]:
        rows = list(self._r(library).values())
        rows.sort(key=lambda r: (r.started_at or "", r.id), reverse=True)
        return tuple(rows)

    def list_reads_for_capture(
        self, library: LibraryRef, capture_id: str,
    ) -> tuple[Read, ...]:
        rows = [r for r in self._r(library).values()
                if capture_id in r.capture_ids]
        rows.sort(key=lambda r: (r.started_at or "", r.id), reverse=True)
        return tuple(rows)


class MemoryDecisionStore:
    """Implements ``app.ports.decisions.DecisionStore`` (P2.5).

    Same role as the other memory stores: the API ring's store, and the
    second implementation that turns the decision contract into a spec.
    """

    def __init__(self) -> None:
        self._by_library: dict[str, dict[tuple[str, int, str], Decision]] = {}

    def _d(self, library: LibraryRef) -> dict[tuple[str, int, str], Decision]:
        return self._by_library.setdefault(library.id, {})

    def save_decision(self, library: LibraryRef, decision: Decision) -> None:
        if decision.library_id != library.id:
            raise WrongLibrary(
                f"decision for {decision.book_key!r} belongs to "
                f"{decision.library_id!r}, not {library.id!r}"
            )
        key = (decision.shelf_id, decision.depth, decision.book_key)
        self._d(library)[key] = decision

    def get_decision(
        self, library: LibraryRef, shelf_id: str, depth: int, book_key: str,
    ) -> Decision | None:
        return self._d(library).get((shelf_id, depth, book_key))

    def list_decisions(
        self, library: LibraryRef, shelf_id: str, depth: int,
    ) -> tuple[Decision, ...]:
        rows = [d for d in self._d(library).values()
                if d.shelf_id == shelf_id and d.depth == depth]
        rows.sort(key=lambda d: d.book_key)
        return tuple(rows)

    def delete_decision(
        self, library: LibraryRef, shelf_id: str, depth: int, book_key: str,
    ) -> bool:
        key = (shelf_id, depth, book_key)
        return self._d(library).pop(key, None) is not None


class MemoryDuplicateQueue:
    """Implements ``app.ports.duplicates.DuplicateQueue`` (P2.6).

    Same role and same shape as :class:`MemoryDecisionStore` — the natural
    key is identical, which is the whole point (a question and its answer
    are two states of one fact).
    """

    def __init__(self) -> None:
        self._by_library: dict[str, dict[tuple[str, int, str], DuplicateQuestion]] = {}

    def _q(self, library: LibraryRef) -> dict[tuple[str, int, str], DuplicateQuestion]:
        return self._by_library.setdefault(library.id, {})

    def save_question(self, library: LibraryRef, question: DuplicateQuestion) -> None:
        if question.library_id != library.id:
            raise WrongLibrary(
                f"question for {question.book_key!r} belongs to "
                f"{question.library_id!r}, not {library.id!r}"
            )
        key = (question.shelf_id, question.depth, question.book_key)
        self._q(library)[key] = question

    def get_question(
        self, library: LibraryRef, shelf_id: str, depth: int, book_key: str,
    ) -> DuplicateQuestion | None:
        return self._q(library).get((shelf_id, depth, book_key))

    def list_open_questions(
        self, library: LibraryRef, *, shelf_id: str | None = None,
    ) -> tuple[DuplicateQuestion, ...]:
        rows = list(self._q(library).values())
        if shelf_id is not None:
            rows = [q for q in rows if q.shelf_id == shelf_id]
        rows.sort(key=lambda q: (q.opened_at, q.id))
        return tuple(rows)

    def delete_question(
        self, library: LibraryRef, shelf_id: str, depth: int, book_key: str,
    ) -> bool:
        key = (shelf_id, depth, book_key)
        return self._q(library).pop(key, None) is not None


class MemoryTenancyStore:
    """Implements ``app.ports.tenancy.TenancyStore`` (P3.1).

    ⚠ The one memory store with no ``_by_library`` dict — see the port's own
    ⚠⚠: this is the store that ANSWERS which libraries exist, so scoping it by
    a library would be circular. Its narrowing key is the account.
    """

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._libraries: dict[str, Library] = {}
        self._members: dict[tuple[str, str], Membership] = {}

    # --- accounts --------------------------------------------------------

    def save_account(self, account: Account) -> None:
        self._accounts[account.id] = account

    def get_account(self, account_id: str) -> Account | None:
        return self._accounts.get(account_id)

    # --- libraries -------------------------------------------------------

    def save_library(self, library: Library) -> None:
        self._libraries[library.id] = library

    def get_library(self, library_id: str) -> Library | None:
        return self._libraries.get(library_id)

    # --- memberships -----------------------------------------------------

    def save_membership(self, membership: Membership) -> None:
        if membership.account_id not in self._accounts:
            raise UnknownAccount(f"no account {membership.account_id!r}")
        if membership.library_id not in self._libraries:
            raise UnknownLibrary(f"no library {membership.library_id!r}")
        self._members[(membership.account_id, membership.library_id)] = membership

    def membership(self, account_id: str, library_id: str) -> Membership | None:
        return self._members.get((account_id, library_id))

    def delete_membership(self, account_id: str, library_id: str) -> bool:
        return self._members.pop((account_id, library_id), None) is not None

    def list_libraries(
        self, account_id: str,
    ) -> tuple[tuple[Library, Membership], ...]:
        rows = [(self._libraries[m.library_id], m)
                for (acc, _lib), m in self._members.items() if acc == account_id]
        rows.sort(key=lambda pair: pair[0].sort_key)
        return tuple(rows)

    def list_members(self, library_id: str) -> tuple[Membership, ...]:
        rows = [m for m in self._members.values() if m.library_id == library_id]
        rows.sort(key=lambda m: (m.role is not Role.ADMIN, m.account_id))
        return tuple(rows)


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
