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
    User,
)
from app.domain.tenancy import remove_member, set_role
from app.domain.search import parse
from app.domain.search import search as domain_search
from app.ports.store import (
    BookPage,
    BookSort,
    DuplicateBookKey,
    DuplicateCaptureSlot,
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
