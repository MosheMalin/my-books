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

import threading
from dataclasses import replace

from app.domain.auth import LoginToken, Session
from app.domain.invites import Invite
from app.domain.oauth import OAuthState
from app.domain import (
    Account,
    Book,
    Bookcase,
    Capture,
    Decision,
    DuplicateQuestion,
    Floor,
    GroupingContents,
    Library,
    LibraryRef,
    Membership,
    Place,
    Read,
    Role,
    Section,
    Shelf,
    ShelfAddress,
    Site,
    Status,
    User,
    check_removable,
)
from app.domain.place import NotEmpty, NotOnThisFloor
from app.domain.tenancy import remove_member, set_role
from app.domain.search import parse
from app.domain.search import search as domain_search
from app.ports.map import MapSnapshot, UnknownParent
from app.ports.store import (
    BookPage,
    BookSort,
    DuplicateBookKey,
    DuplicateCaptureSlot,
    DuplicateSectionOrdinal,
    DuplicateShelfSlot,
    ShelfNotEmpty,
    UnknownShelf,
    WrongLibrary,
)
from app.ports.tenancy import EmailTaken, UnknownAccount, UnknownUser


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

    def copies_per_shelf(self, library: LibraryRef) -> dict[str, int]:
        counts: dict[str, int] = {}
        for book in self._shelf(library).values():
            for copy in book.copies:
                if copy.shelf_id:
                    counts[copy.shelf_id] = counts.get(copy.shelf_id, 0) + 1
        return counts

    def deepest_copy_depth(self, library: LibraryRef) -> dict[str, int]:
        deepest: dict[str, int] = {}
        for book in self._shelf(library).values():
            for copy in book.copies:
                if not copy.shelf_id:
                    continue
                depth = copy.depth or 1
                if depth > deepest.get(copy.shelf_id, 0):
                    deepest[copy.shelf_id] = depth
        return deepest

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
        #: The sections this store may address a shelf to. SQLite gets the
        #: same check free — one file, one foreign key — so without it the
        #: memory store would ACCEPT an address the real database refuses,
        #: and the API ring (which runs on memory stores) would never see it.
        self._sections: "MemoryMapStore | None" = None
        #: The books this store must ask about before deleting a shelf.
        #: SQLite does NOT get this one free — `copies.shelf_id` has no
        #: foreign key, it predates the `shelves` table by four schema
        #: versions — so the real database is as blind to it as this dict is,
        #: and both implementations have to be told the same rule by hand.
        self._books: "MemoryBookStore | None" = None

    def bind_map(self, maps: "MemoryMapStore") -> None:
        """Tell this store where the sections are, so an address can be
        checked against one."""
        self._sections = maps

    def bind_books(self, books: "MemoryBookStore") -> None:
        """Tell this store where the books are, so a shelf holding one cannot
        be deleted out from under it."""
        self._books = books

    def _s(self, library: LibraryRef) -> dict[str, Shelf]:
        return self._shelves.setdefault(library.id, {})

    def _c(self, library: LibraryRef) -> dict[str, Capture]:
        return self._captures.setdefault(library.id, {})

    # --- shelves ---------------------------------------------------------

    def save_shelf(self, library: LibraryRef, shelf: Shelf) -> None:
        self._check_shelf(library, shelf, self._s(library))
        self._s(library)[shelf.id] = shelf

    def _check_shelf(self, library: LibraryRef, shelf: Shelf,
                     against: dict) -> None:
        """Every refusal the SQL store's constraints produce, in Python.

        Shared by the single and the batch write so the two cannot drift —
        without these this store would accept what the real database refuses,
        and the contract suite would be asserting SQLite's behaviour rather
        than the spec's.
        """
        if shelf.library_id != library.id:
            raise WrongLibrary(
                f"shelf {shelf.id} belongs to {shelf.library_id!r}, "
                f"not {library.id!r}"
            )
        if shelf.address is None:
            return
        # ⚠ FAIL CLOSED when unbound. This guard used to be conditional on the
        # binding, so a bare `MemoryShelfStore()` silently skipped it and
        # accepted an address the real database refuses. A guard whose default
        # is "skip me" is the same shape as the `occupied_ids` default a
        # review already measured.
        if self._sections is None:
            raise RuntimeError(
                "MemoryShelfStore was given an addressed shelf before "
                "bind_map(); it cannot check the section exists"
            )
        if self._sections.get_section(
                library, shelf.address.section_id) is None:
            raise UnknownParent(
                f"no section {shelf.address.section_id!r} in library "
                f"{library.id!r}"
            )
        for other in against.values():
            if other.address == shelf.address and other.id != shelf.id:
                raise DuplicateShelfSlot(
                    f"shelf {other.id} already stands at {shelf.address} "
                    f"(MAP_PLAN §3.1)"
                )

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

    def list_shelves_in_section(
        self, library: LibraryRef, section_id: str
    ) -> tuple[Shelf, ...]:
        rows = [s for s in self._s(library).values()
                if s.address is not None and s.address.section_id == section_id]
        rows.sort(key=lambda s: (s.address.col, s.address.level, s.id))
        return tuple(rows)

    def save_shelves(self, library: LibraryRef,
                     shelves: tuple[Shelf, ...]) -> None:
        # All-or-nothing, like the SQL one's transaction: validate every
        # shelf before writing any, so a rejected member leaves none written.
        staged = dict(self._s(library))
        for shelf in shelves:
            self._check_shelf(library, shelf, staged)
            staged[shelf.id] = shelf
        self._shelves[library.id] = staged

    def deepest_capture_depth(self, library: LibraryRef) -> dict[str, int]:
        deepest: dict[str, int] = {}
        for capture in self._c(library).values():
            if capture.depth > deepest.get(capture.shelf_id, 0):
                deepest[capture.shelf_id] = capture.depth
        return deepest

    def get_shelf_at(
        self, library: LibraryRef, address: ShelfAddress
    ) -> Shelf | None:
        for shelf in self._s(library).values():
            if shelf.address == address:
                return shelf
        return None

    def delete_shelf(self, library: LibraryRef, shelf_id: str) -> bool:
        if shelf_id not in self._s(library):
            return False
        if self.list_captures(library, shelf_id):
            raise ShelfNotEmpty(
                f"shelf {shelf_id} still has captures; deleting it would "
                "destroy the record a re-read diffs against (§5.6)"
            )
        # ⚠ FAIL CLOSED when unbound, exactly as the address check does and
        # for the same reason its comment gives: a guard whose default is
        # "skip me" is the shape of the `occupied_ids` default a review
        # already measured. An unbound store cannot answer "does a book stand
        # here", so it must not answer "yes, deleted".
        if self._books is None:
            raise RuntimeError(
                "MemoryShelfStore was asked to delete a shelf before "
                "bind_books(); it cannot check whether a book stands on it"
            )
        # `deepest_copy_depth` is the port method the map's own occupancy
        # check already asks this question with (`map_edit`), so the two
        # doors cannot answer it differently — and it needs no reach into
        # another store's internals.
        if shelf_id in self._books.deepest_copy_depth(library):
            raise ShelfNotEmpty(
                f"shelf {shelf_id} still holds books; deleting it would "
                "leave them with a location nothing can open (§5.6)"
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
        self._users: dict[str, User] = {}
        self._accounts: dict[str, Account] = {}
        self._libraries: dict[str, Library] = {}
        self._members: dict[tuple[str, str], Membership] = {}
        self._mint = threading.Lock()

    # --- users -----------------------------------------------------------

    def save_user(self, user: User) -> None:
        # The email-uniqueness rule the sqlite index enforces, enforced
        # here too -- or the contract suite tests the one adapter that
        # cannot fail (P4.1a's data-integrity review).
        if user.email is not None and any(
            u.email == user.email and u.id != user.id
            for u in self._users.values()
        ):
            raise EmailTaken(f"{user.email!r} already belongs to another user")
        self._users[user.id] = user

    def get_user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def user_by_email(self, email: str) -> User | None:
        # Exact match, like the sqlite index: the caller normalizes.
        for user in self._users.values():
            if user.email == email:
                return user
        return None

    # --- accounts --------------------------------------------------------

    def save_account(self, account: Account) -> None:
        self._accounts[account.id] = account

    def get_account(self, account_id: str) -> Account | None:
        return self._accounts.get(account_id)

    # --- libraries -------------------------------------------------------

    def save_library(self, library: Library) -> None:
        if library.account_id not in self._accounts:
            raise UnknownAccount(f"no account {library.account_id!r}")
        self._libraries[library.id] = library

    def get_library(self, library_id: str) -> Library | None:
        return self._libraries.get(library_id)

    def list_libraries(self, account_id: str) -> tuple[Library, ...]:
        rows = [lib for lib in self._libraries.values()
                if lib.account_id == account_id]
        rows.sort(key=lambda lib: lib.sort_key)
        return tuple(rows)

    # --- memberships -----------------------------------------------------

    def save_membership(self, membership: Membership) -> None:
        if membership.user_id not in self._users:
            raise UnknownUser(f"no user {membership.user_id!r}")
        if membership.account_id not in self._accounts:
            raise UnknownAccount(f"no account {membership.account_id!r}")
        self._members[(membership.user_id, membership.account_id)] = membership

    def membership(self, user_id: str, account_id: str) -> Membership | None:
        return self._members.get((user_id, account_id))

    def delete_membership(self, user_id: str, account_id: str) -> bool:
        return self._members.pop((user_id, account_id), None) is not None

    def mint_first_account(
        self, account: Account, membership: Membership, library: Library,
    ) -> tuple[Account, Membership]:
        with self._mint:
            for (user, account_id), held in sorted(self._members.items()):
                if user == membership.user_id:
                    return self._accounts[account_id], held
            self._accounts[account.id] = account
            self._members[(membership.user_id, membership.account_id)] = \
                membership
            self._libraries[library.id] = library
            return account, membership

    def list_accounts(
        self, user_id: str,
    ) -> tuple[tuple[Account, Membership], ...]:
        rows = [(self._accounts[m.account_id], m)
                for (usr, _acc), m in self._members.items() if usr == user_id]
        rows.sort(key=lambda pair: pair[0].id)
        return tuple(rows)

    def change_member_role(
        self, account_id: str, user_id: str, role: Role,
    ) -> tuple[Membership, ...]:
        with self._mint:
            return self._rewrite(account_id,
                                 lambda rows: set_role(rows, user_id, role))

    def remove_member_row(
        self, account_id: str, user_id: str,
    ) -> tuple[Membership, ...]:
        with self._mint:
            return self._rewrite(account_id,
                                 lambda rows: remove_member(rows, user_id))

    def _rewrite(self, account_id: str, rule):
        rows = self.list_members(account_id)
        updated = rule(rows)
        keep = {m.user_id for m in updated}
        for old in rows:
            if old.user_id not in keep:
                self._members.pop((old.user_id, account_id), None)
        for m in updated:
            self._members[(m.user_id, account_id)] = m
        return self.list_members(account_id)

    def list_members(self, account_id: str) -> tuple[Membership, ...]:
        rows = [m for m in self._members.values() if m.account_id == account_id]
        rows.sort(key=lambda m: (m.role is not Role.ADMIN, m.user_id))
        return tuple(rows)


class MemoryAuthStore:
    """Implements ``app.ports.auth.AuthStore`` (P4.1a).

    Single-use consume holds a real `threading.Lock` around the
    check-and-mark. An earlier draft claimed the GIL made it atomic; the
    migration review measured 2299/4000 double-redeems at 4 threads with a
    tiny switch interval — read-check-replace is several bytecodes, and
    CPython preempts between them. One lock, matching what the port
    promises.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._tokens: dict[str, LoginToken] = {}
        self._consume = threading.Lock()

    # --- sessions --------------------------------------------------------

    def save_session(self, session: Session) -> None:
        # Parity with the sqlite upsert, field for field: an existing row
        # keeps its identity (user_id, created_at) and its tombstone; a
        # save updates expiry and may only ADD a revocation (measured
        # divergence, P4.1a's data-integrity review).
        old = self._sessions.get(session.token_hash)
        if old is not None:
            session = replace(
                session,
                user_id=old.user_id,
                created_at=old.created_at,
                revoked_at=old.revoked_at if old.revoked_at is not None
                else session.revoked_at,
            )
        self._sessions[session.token_hash] = session

    def revoke_sessions_of_user(self, user_id: str, *, at: str) -> int:
        revoked = 0
        for token_hash, s in list(self._sessions.items()):
            if s.user_id == user_id and s.revoked_at is None:
                self._sessions[token_hash] = replace(s, revoked_at=at)
                revoked += 1
        return revoked

    def get_session(self, token_hash: str) -> Session | None:
        return self._sessions.get(token_hash)

    def revoke_session(self, token_hash: str, *, at: str) -> bool:
        session = self._sessions.get(token_hash)
        if session is None or session.revoked_at is not None:
            return False
        self._sessions[token_hash] = replace(session, revoked_at=at)
        return True

    # --- login tokens ----------------------------------------------------

    def save_login_token(self, token: LoginToken) -> None:
        # "Insert", like the port says: silently replacing an existing
        # hash would reset consumed_at and re-arm a spent link (measured
        # divergence, P4.1a's data-integrity review). Unreachable with
        # 256-bit tokens; refused identically to the sqlite PK.
        if token.token_hash in self._tokens:
            raise ValueError(f"login token {token.token_hash!r} already stored")
        self._tokens[token.token_hash] = token

    def purge_login_tokens(self, *, before: str) -> int:
        dead = [h for h, t in self._tokens.items() if t.expires_at < before]
        for h in dead:
            del self._tokens[h]
        return len(dead)

    def consume_login_token(self, token_hash: str, *, now: str) -> LoginToken | None:
        with self._consume:
            token = self._tokens.get(token_hash)
            if token is None or token.consumed_at is not None \
                    or token.expires_at <= now:
                return None
            consumed = replace(token, consumed_at=now)
            self._tokens[token_hash] = consumed
            return consumed

    def count_recent_login_tokens(self, *, email: str | None = None,
                                  source_hash: str | None = None,
                                  since: str) -> int:
        if email is None and source_hash is None:
            raise ValueError("at least one filter per call")
        return sum(
            1 for t in self._tokens.values()
            if t.created_at >= since
            and (email is None or t.email == email)
            and (source_hash is None or t.source_hash == source_hash)
        )


class MemoryOAuthStateStore:
    """Implements ``app.ports.oauth.OAuthStateStore`` (P4.2)."""

    def __init__(self) -> None:
        self._states: dict[str, OAuthState] = {}
        self._lock = threading.Lock()

    def save_state(self, state: OAuthState) -> None:
        with self._lock:
            if state.state_hash in self._states:
                raise ValueError(
                    f"oauth state {state.state_hash!r} already stored")
            self._states[state.state_hash] = state

    def consume_state(self, state_hash: str, *, now: str) -> OAuthState | None:
        # Deleted, not tombstoned — see the sqlite adapter for why.
        with self._lock:
            state = self._states.get(state_hash)
            if state is None or not state.live(now):
                return None
            del self._states[state_hash]
            return replace(state, consumed_at=now)

    def purge_states(self, *, before: str) -> int:
        with self._lock:
            dead = [h for h, s in self._states.items()
                    if s.expires_at < before]
            for h in dead:
                del self._states[h]
            return len(dead)


class MemoryMapStore:
    """Implements ``app.ports.map.MapStore`` (P6.1).

    Five dictionaries rather than one nested tree, because that is what the
    SQL adapter has and the contract suite has to be able to hold both to the
    same answers — a tree here would make "which floors belong to this site"
    free in one implementation and a scan in the other, and the spec would
    quietly become the tree's.

    The refusals (``NotEmpty``, ``UnknownParent``) are enforced HERE as well
    as by the schema's foreign keys, for the same reason: a rule that only
    SQLite holds is a rule the API ring never exercises.
    """

    def __init__(self) -> None:
        self._sites: dict[str, dict[str, Site]] = {}
        self._floors: dict[str, dict[str, Floor]] = {}
        self._places: dict[str, dict[str, Place]] = {}
        self._cases: dict[str, dict[str, Bookcase]] = {}
        self._sections: dict[str, dict[str, Section]] = {}
        #: Shelves live in ``MemoryShelfStore``, so this store cannot see
        #: whether a slot is filled; ``bind_shelves`` hands it that view.
        #:
        #: ⚠ Unbound, it REFUSES to answer rather than answering weakly. The
        #: first version said the refusal "falls to the layer that does
        #: (app/map_edit.py)" — which was simply false: `map_edit` empties
        #: slots, it never re-checks before a delete, so an unbound store
        #: deleted sections out from under addressed shelves and returned
        #: True. A wrong stated reason is what makes the next reader delete
        #: the guard.
        self._occupied: "MemoryShelfStore | None" = None

    def bind_shelves(self, shelves: "MemoryShelfStore") -> None:
        """Tell this store where the shelves are, so it can refuse to delete a
        bookcase out from under one. The SQL adapter gets this free — one
        file, one query."""
        self._occupied = shelves

    def _t(self, table: dict, library: LibraryRef) -> dict:
        return table.setdefault(library.id, {})

    # --- the whole drawing ------------------------------------------------

    def load_map(self, library: LibraryRef) -> MapSnapshot:
        sites = sorted(self._t(self._sites, library).values(),
                       key=lambda s: (s.order, s.name, s.id))
        floors = sorted(self._t(self._floors, library).values(),
                        key=lambda f: (f.site_id, f.order, f.name, f.id))
        places = sorted(self._t(self._places, library).values(),
                        key=lambda p: (p.floor_id, p.order, p.id))
        cases = sorted(self._t(self._cases, library).values(),
                       key=lambda c: (c.floor_id, c.order, c.id))
        sections = sorted(self._t(self._sections, library).values(),
                          key=lambda s: (s.bookcase_id, s.ordinal, s.id))
        return MapSnapshot(tuple(sites), tuple(floors), tuple(places),
                           tuple(cases), tuple(sections))

    # --- sites ------------------------------------------------------------

    def save_site(self, library: LibraryRef, site: Site) -> None:
        _same_library(site, library, "site")
        self._t(self._sites, library)[site.id] = site

    def get_site(self, library: LibraryRef, site_id: str) -> Site | None:
        return self._t(self._sites, library).get(site_id)

    def delete_site(self, library: LibraryRef, site_id: str) -> bool:
        sites = self._t(self._sites, library)
        if site_id not in sites:
            return False
        floors = [f for f in self._t(self._floors, library).values()
                  if f.site_id == site_id]
        mine = {f.id for f in floors}
        # ⚠ Measured at review: refusing a site that holds ANY floor made a
        # site with one empty storey undeletable, because `delete_floor`
        # refuses the last storey of a site. "The parents' place", drawn by
        # mistake, was permanent. So the refusal is about what the floors
        # HOLD, and empty storeys leave with their site — a floor with no
        # rooms and no bookcases is not something "nothing auto-removes" is
        # protecting.
        check_removable(f"site {site_id}", GroupingContents(
            places=sum(1 for p in self._t(self._places, library).values()
                       if p.floor_id in mine),
            bookcases=sum(1 for c in self._t(self._cases, library).values()
                          if c.floor_id in mine),
        ))
        if len(sites) <= 1:
            raise NotEmpty(
                f"site {site_id} is the only one; a drawing has somewhere to be"
            )
        for floor_id in mine:
            del self._t(self._floors, library)[floor_id]
        del sites[site_id]
        return True

    # --- floors -----------------------------------------------------------

    def save_floor(self, library: LibraryRef, floor: Floor) -> None:
        _same_library(floor, library, "floor")
        if floor.site_id not in self._t(self._sites, library):
            raise UnknownParent(
                f"no site {floor.site_id!r} in library {library.id!r}"
            )
        self._t(self._floors, library)[floor.id] = floor

    def get_floor(self, library: LibraryRef, floor_id: str) -> Floor | None:
        return self._t(self._floors, library).get(floor_id)

    def delete_floor(self, library: LibraryRef, floor_id: str) -> bool:
        floors = self._t(self._floors, library)
        floor = floors.get(floor_id)
        if floor is None:
            return False
        check_removable(f"floor {floor_id}", GroupingContents(
            places=sum(1 for p in self._t(self._places, library).values()
                       if p.floor_id == floor_id),
            bookcases=sum(1 for c in self._t(self._cases, library).values()
                          if c.floor_id == floor_id),
        ))
        siblings = [f for f in floors.values() if f.site_id == floor.site_id]
        if len(siblings) <= 1:
            raise NotEmpty(
                f"floor {floor_id} is the only storey of its site; a site has "
                f"at least one"
            )
        del floors[floor_id]
        return True

    # --- places -----------------------------------------------------------

    def save_place(self, library: LibraryRef, place: Place) -> None:
        _same_library(place, library, "place")
        if place.floor_id not in self._t(self._floors, library):
            raise UnknownParent(
                f"no floor {place.floor_id!r} in library {library.id!r}"
            )
        self._t(self._places, library)[place.id] = place

    def get_place(self, library: LibraryRef, place_id: str) -> Place | None:
        return self._t(self._places, library).get(place_id)

    def delete_place(self, library: LibraryRef, place_id: str) -> bool:
        places = self._t(self._places, library)
        if place_id not in places:
            return False
        # The room goes; its furniture stays, attached to no room. Deleting a
        # container never destroys what it held — the rule the lab drew and
        # the product already holds for shelves and copies.
        cases = self._t(self._cases, library)
        for case_id, case in list(cases.items()):
            if case.place_id == place_id:
                cases[case_id] = replace(case, place_id=None)
        del places[place_id]
        return True

    # --- bookcases --------------------------------------------------------

    def save_bookcase(self, library: LibraryRef, bookcase: Bookcase) -> None:
        _same_library(bookcase, library, "bookcase")
        if bookcase.floor_id not in self._t(self._floors, library):
            raise UnknownParent(
                f"no floor {bookcase.floor_id!r} in library {library.id!r}"
            )
        if bookcase.place_id is not None:
            place = self._t(self._places, library).get(bookcase.place_id)
            if place is None:
                raise UnknownParent(
                    f"no place {bookcase.place_id!r} in library {library.id!r}"
                )
            if place.floor_id != bookcase.floor_id:
                raise NotOnThisFloor(
                    f"bookcase {bookcase.id} is on floor {bookcase.floor_id!r} "
                    f"but room {place.id} is on {place.floor_id!r} "
                    f"(MAP_PLAN §3.7)"
                )
        self._t(self._cases, library)[bookcase.id] = bookcase

    def get_bookcase(
        self, library: LibraryRef, bookcase_id: str
    ) -> Bookcase | None:
        return self._t(self._cases, library).get(bookcase_id)

    def delete_bookcase(self, library: LibraryRef, bookcase_id: str) -> bool:
        cases = self._t(self._cases, library)
        if bookcase_id not in cases:
            return False
        sections = self._t(self._sections, library)
        mine = [s for s in sections.values() if s.bookcase_id == bookcase_id]
        for section in mine:
            self._refuse_if_filled(library, section)
        for section in mine:
            del sections[section.id]
        del cases[bookcase_id]
        return True

    # --- sections ---------------------------------------------------------

    def save_section(self, library: LibraryRef, section: Section) -> None:
        _same_library(section, library, "section")
        if section.bookcase_id not in self._t(self._cases, library):
            raise UnknownParent(
                f"no bookcase {section.bookcase_id!r} in library {library.id!r}"
            )
        # v20's unique index, in Python — `ordinal` is what the address PRINTS,
        # so two sections of one bookcase both at 1 send the owner to the
        # wrong half of the furniture. Without it here the SQL store would
        # refuse what this one accepts.
        for other in self._t(self._sections, library).values():
            if (other.bookcase_id == section.bookcase_id
                    and other.ordinal == section.ordinal
                    and other.id != section.id):
                raise DuplicateSectionOrdinal(
                    f"section {other.id} is already number {section.ordinal} "
                    f"of bookcase {section.bookcase_id}"
                )
        self._t(self._sections, library)[section.id] = section

    def save_sections(self, library: LibraryRef,
                      sections: tuple[Section, ...]) -> None:
        # All-or-nothing, and the ordinal check runs against the FINAL set
        # rather than the live one: "push everything up by one" transiently
        # collides at every step, and refusing that would make the operation
        # the review found broken impossible rather than atomic.
        staged = dict(self._t(self._sections, library))
        for section in sections:
            _same_library(section, library, "section")
            if section.bookcase_id not in self._t(self._cases, library):
                raise UnknownParent(
                    f"no bookcase {section.bookcase_id!r} in library "
                    f"{library.id!r}")
            staged[section.id] = section
        seen: set = set()
        for section in staged.values():
            key = (section.bookcase_id, section.ordinal)
            if key in seen:
                raise DuplicateSectionOrdinal(
                    f"two sections would both be number {section.ordinal} of "
                    f"bookcase {section.bookcase_id}")
            seen.add(key)
        self._sections[library.id] = staged

    def move_place(self, library: LibraryRef, place: Place,
                   floor_id: str) -> Place:
        if floor_id not in self._t(self._floors, library):
            raise UnknownParent(
                f"no floor {floor_id!r} in library {library.id!r}")
        moved = replace(place, floor_id=floor_id)
        self._t(self._places, library)[place.id] = moved
        # …and the furniture goes with the room, in the same call. A review
        # left a room upstairs and its bookcase on the ground floor, and the
        # case was then un-renamable forever: every write re-checked
        # `NotOnThisFloor` and answered 409.
        cases = self._t(self._cases, library)
        for case_id, case in list(cases.items()):
            if case.place_id == place.id:
                cases[case_id] = replace(case, floor_id=floor_id)
        return moved

    def get_section(
        self, library: LibraryRef, section_id: str
    ) -> Section | None:
        return self._t(self._sections, library).get(section_id)

    def delete_section(self, library: LibraryRef, section_id: str) -> bool:
        sections = self._t(self._sections, library)
        section = sections.get(section_id)
        if section is None:
            return False
        siblings = [s for s in sections.values()
                    if s.bookcase_id == section.bookcase_id]
        if len(siblings) <= 1:
            raise NotEmpty(
                f"section {section_id} is the only one of its bookcase; a "
                f"bookcase with no sections is not simpler, it is unaddressable"
            )
        self._refuse_if_filled(library, section)
        del sections[section_id]
        return True

    def _refuse_if_filled(self, library: LibraryRef, section: Section) -> None:
        # ⚠ FAIL CLOSED when unbound — see `MemoryShelfStore.save_shelf`. This
        # returned silently before, so a bare `MemoryMapStore()` deleted a
        # bookcase out from under the shelves standing in it.
        if self._occupied is None:
            raise RuntimeError(
                "MemoryMapStore was asked to remove furniture before "
                "bind_shelves(); it cannot check whether a shelf stands in it"
            )
        standing = self._occupied.list_shelves_in_section(library, section.id)
        if standing:
            raise NotEmpty(
                f"{len(standing)} shelf/shelves still stand in section "
                f"{section.id}; empty the slots first (MAP_PLAN §3.1)"
            )


def _same_library(record, library: LibraryRef, what: str) -> None:
    if record.library_id != library.id:
        raise WrongLibrary(
            f"{what} {record.id} belongs to {record.library_id!r}, "
            f"not {library.id!r}"
        )


class MemoryInviteStore:
    """Implements ``app.ports.invites.InviteStore`` (P4.3)."""

    def __init__(self) -> None:
        self._invites: dict[str, Invite] = {}
        self._consume = threading.Lock()

    def save_invite(self, invite: Invite) -> None:
        # Under the same lock as consume/revoke: check-and-write is several
        # bytecodes, and the GIL preempts between them (the login token's
        # measured lesson, applied to every writer here).
        with self._consume:
            if invite.token_hash in self._invites:
                raise ValueError(f"invite {invite.token_hash!r} already stored")
            self._invites[invite.token_hash] = invite

    def get_invite(self, token_hash: str) -> Invite | None:
        return self._invites.get(token_hash)

    def list_open_invites(self, account_id: str, *, now: str) -> tuple[Invite, ...]:
        rows = [i for i in self._invites.values()
                if i.account_id == account_id and i.live(now)]
        rows.sort(key=lambda i: (i.created_at, i.token_hash))
        return tuple(rows)

    def consume_invite(self, token_hash: str, *, by: str, now: str) -> Invite | None:
        # A real lock, like the login token's — read-check-replace is
        # several bytecodes and the GIL preempts between them.
        with self._consume:
            invite = self._invites.get(token_hash)
            if invite is None or not invite.live(now):
                return None
            consumed = replace(invite, consumed_at=now, consumed_by=by)
            self._invites[token_hash] = consumed
            return consumed

    def purge_invites(self, *, before: str) -> int:
        with self._consume:
            dead = [h for h, i in self._invites.items()
                    if i.expires_at < before]
            for h in dead:
                del self._invites[h]
            return len(dead)

    def mark_granted(self, token_hash: str, *, at: str) -> bool:
        with self._consume:
            invite = self._invites.get(token_hash)
            if invite is None or invite.granted_at is not None:
                return False
            self._invites[token_hash] = replace(invite, granted_at=at)
            return True

    def revoke_invite(self, account_id: str, token_hash: str) -> bool:
        # The same lock consume takes: without it, a revoke landing inside
        # consume's check-and-write window reported success AND left the
        # row granted (measured under a forced interleave at review).
        with self._consume:
            invite = self._invites.get(token_hash)
            if invite is None or invite.account_id != account_id \
                    or invite.consumed_at is not None:
                return False
            del self._invites[token_hash]
            return True


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
