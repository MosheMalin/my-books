# -*- coding: utf-8 -*-
"""SQLite BookStore (plan D1).

Chosen against the vision's own criteria (§12.1): memberships/roles/lending
need relational integrity — that is where a bug means someone sees a library
they shouldn't; zero ops, one file, portable, and real SQL so the Postgres
step is small. What keeps it revisitable is that it passes the same contract
suite as the in-memory store, not that it is easy to rip out.

**A connection per operation**, deliberately. FastAPI runs sync endpoints in a
threadpool, and a shared ``sqlite3`` connection is not thread-safe; per-call
connections make the whole class of "same connection, two threads" bugs
unreachable, at a cost (~0.1ms) that is noise next to a page render. WAL plus
a busy timeout handles the concurrent-writer case. Revisit if a profile ever
says so — not before.

Images are NOT stored here (D1): shelf photos are multi-MB JPEGs, they would
bloat the file and route every image read through this process. Blobs go on
disk with a storage key in a row, in P3.5.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Iterator

from app.adapters.migrations import migrate
from app.domain import (
    Alternative,
    Book,
    Capture,
    Claim,
    ClaimTier,
    Copy,
    CopyFields,
    Decision,
    DecisionKind,
    DiffSummary,
    DuplicateQuestion,
    Lending,
    LibraryRef,
    Provenance,
    Read,
    ReadStatus,
    Shelf,
    Status,
    WorkFields,
)
from app.domain.search import compile_sql_like, haystack, parse
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

_ORDER_BY = {
    BookSort.TITLE: "norm_title {dir}, id {dir}",
    # sort_author, not norm_author: §6's "sort by author" means the shelf
    # order — by SURNAME. norm_author is identity (the author filter's key),
    # and it files everyone under their given name.
    BookSort.AUTHOR: "sort_author {dir}, norm_title {dir}, id {dir}",
    # COALESCE so books with no added_at (P1.3 imports 251 of them) sort
    # together at one end rather than scattering by NULL-ordering rules.
    BookSort.RECENTLY_ADDED: "COALESCE(added_at, '') {dir}, id {dir}",
}


@contextmanager
def _open(path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(path), timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        # ON by connection, not by database: SQLite defaults it OFF, and
        # without it the copies/provenance cascades silently do nothing
        # and `delete` leaves orphans behind.
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        yield conn
    finally:
        conn.close()


class _SqliteStore:
    """The file, the pragmas and the migration — shared by both aggregates.

    Not an abstraction over the stores; just the three lines that would
    otherwise be copied and drift. Each store still implements its own port.
    """

    def __init__(self, path: str | Path, *, kind: str) -> None:
        if str(path) == ":memory:":
            # Would silently "work" and lose everything: a connection per
            # operation means each call would get its own empty database.
            # The Memory* stores are the in-memory implementations.
            raise ValueError(
                f"{kind} needs a file; use the in-memory store for RAM"
            )
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            migrate(conn)

    def _connect(self) -> Iterator[sqlite3.Connection]:
        return _open(self.path)


class SqliteBookStore(_SqliteStore):
    """Implements ``app.ports.store.BookStore``."""

    def __init__(self, path: str | Path) -> None:
        super().__init__(path, kind="SqliteBookStore")

    # --- BookStore -------------------------------------------------------

    def save(self, library: LibraryRef, book: Book) -> None:
        if book.library_id != library.id:
            raise WrongLibrary(
                f"book {book.id} belongs to {book.library_id!r}, "
                f"not {library.id!r}"
            )
        with self._connect() as conn:
            try:
                with conn:
                    # Replace the aggregate wholesale. NOT `INSERT OR REPLACE`:
                    # that resolves a conflict on the (library_id, book_key)
                    # unique index by DELETING the other book — silently losing
                    # a record the user owns. An explicit delete-by-id lets the
                    # index raise instead, which is the honest outcome.
                    conn.execute(
                        "DELETE FROM books WHERE id = ? AND library_id = ?",
                        (book.id, library.id),
                    )
                    _insert_book(conn, library, book)
            except sqlite3.IntegrityError as exc:
                # SQLite names the COLUMNS, not the index:
                #   "UNIQUE constraint failed: books.library_id, books.book_key"
                if "books.book_key" in str(exc):
                    raise DuplicateBookKey(
                        f"{book.key!r} is already another book in this library"
                    ) from exc
                raise

    def get(self, library: LibraryRef, book_id: str) -> Book | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM books WHERE id = ? AND library_id = ?",
                (book_id, library.id),
            ).fetchone()
            return _load_book(conn, row) if row else None

    def get_by_key(self, library: LibraryRef, key: str) -> Book | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM books WHERE library_id = ? AND book_key = ?",
                (library.id, key),
            ).fetchone()
            return _load_book(conn, row) if row else None

    def delete(self, library: LibraryRef, book_id: str) -> bool:
        with self._connect() as conn:
            with conn:
                cur = conn.execute(
                    "DELETE FROM books WHERE id = ? AND library_id = ?",
                    (book_id, library.id),
                )
            return cur.rowcount > 0

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
            # See the port docstring: an explicit EMPTY set means "match
            # nothing", not "no id filter" — an "IN ()" clause is invalid
            # SQL, so this has to be handled before a query is even built.
            return BookPage(items=(), total=0, offset=offset, limit=limit)
        where = ["library_id = ?"]
        params: list[object] = [library.id]
        if author_key is not None:
            where.append("norm_author = ?")
            params.append(author_key)
        if book_ids is not None:
            where.append(f"id IN ({','.join('?' for _ in book_ids)})")
            params.extend(book_ids)
        clause = " AND ".join(where)

        # A book's status is the strongest claim among its copies (§5.2), so
        # it is derived here exactly as the entity derives it — never stored,
        # so the two cannot disagree.
        if status is not None:
            clause += (
                " AND (SELECT MAX(CASE status WHEN 'manual' THEN 2"
                " WHEN 'approved' THEN 1 ELSE 0 END) FROM copies"
                " WHERE copies.book_id = books.id) = ?"
            )
            params.append(status.rank)

        # "at least one copy lent out" — unlike status this is a plain stored
        # column (the v4 comment explains why), so EXISTS is enough; no
        # per-row derivation to keep in sync with the entity.
        if lent_out is not None:
            clause += (
                f" AND {'' if lent_out else 'NOT '}EXISTS (SELECT 1 FROM copies"
                " WHERE copies.book_id = books.id AND copies.lent_out = 1)"
            )

        order = _ORDER_BY[sort].format(dir="ASC" if ascending else "DESC")
        with self._connect() as conn:
            total = int(conn.execute(
                f"SELECT COUNT(*) FROM books WHERE {clause}", params
            ).fetchone()[0])
            rows = conn.execute(
                f"SELECT * FROM books WHERE {clause} ORDER BY {order}"
                f" LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            items = tuple(_load_book(conn, r) for r in rows)
        return BookPage(items=items, total=total, offset=offset, limit=limit)

    def search(
        self,
        library: LibraryRef,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> BookPage:
        """SQL narrows, Python ranks.

        The split is the whole reason a Postgres adapter is cheap later:
        ordering by relevance in SQL means writing the ranking twice, in two
        dialects, and finding the drift in a user report. Here the WHERE
        clause is engine-specific (and portable ANSI ``LIKE`` at that) while
        ``domain_search`` orders the survivors — the same function the memory
        store uses, so the two cannot disagree.

        Loading all matches before paging is deliberate and bounded: on the
        real 251 books a query matches ~3, and the fixture's worst case is 12.
        If a library ever makes that expensive, the fix is a better narrowing
        clause (trigram, FTS5), not a different ranking.
        """
        parsed = parse(query)
        if not parsed:
            return BookPage(items=(), total=0, offset=offset, limit=limit)

        where, params = compile_sql_like(parsed, "search_text")
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM books WHERE library_id = ? AND ({where})",
                (library.id, *params),
            ).fetchall()
            books = [_load_book(conn, r) for r in rows]

        hits = domain_search(parsed, books)
        return BookPage(items=tuple(hits[offset: offset + limit]),
                        total=len(hits), offset=offset, limit=limit)

    def count(self, library: LibraryRef) -> int:
        with self._connect() as conn:
            return int(conn.execute(
                "SELECT COUNT(*) FROM books WHERE library_id = ?",
                (library.id,),
            ).fetchone()[0])


class SqliteShelfStore(_SqliteStore):
    """Implements ``app.ports.store.ShelfStore``.

    Shares the file with :class:`SqliteBookStore` — one database, two
    aggregates — and the same connection-per-operation rule, for the same
    reason (FastAPI's threadpool). It migrates on construction too, so
    whichever store is built first brings the file up to date and the other
    finds it current.
    """

    def __init__(self, path: str | Path) -> None:
        super().__init__(path, kind="SqliteShelfStore")

    # --- shelves ---------------------------------------------------------

    def save_shelf(self, library: LibraryRef, shelf: Shelf) -> None:
        if shelf.library_id != library.id:
            raise WrongLibrary(
                f"shelf {shelf.id} belongs to {shelf.library_id!r}, "
                f"not {library.id!r}"
            )
        with self._connect() as conn:
            with conn:
                # INSERT OR REPLACE is safe HERE, unlike on books: the only
                # unique key is the primary key, so a conflict can only be this
                # same shelf. (On books it would resolve a book_key collision by
                # deleting somebody else's record.) But it would fire the
                # captures cascade on the delete half, so an explicit UPSERT it
                # is — a rename must not destroy the shelf's photos.
                conn.execute(
                    "INSERT INTO shelves (id, library_id, label, depth_count,"
                    " virtual, created_at) VALUES (?,?,?,?,?,?)"
                    " ON CONFLICT(id) DO UPDATE SET label=excluded.label,"
                    " depth_count=excluded.depth_count,"
                    " virtual=excluded.virtual,"
                    " created_at=excluded.created_at"
                    " WHERE shelves.library_id = excluded.library_id",
                    (shelf.id, library.id, shelf.label, shelf.depth_count,
                     int(shelf.virtual), shelf.created_at),
                )

    def get_shelf(self, library: LibraryRef, shelf_id: str) -> Shelf | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM shelves WHERE id = ? AND library_id = ?",
                (shelf_id, library.id),
            ).fetchone()
        return _load_shelf(row) if row else None

    def list_shelves(
        self,
        library: LibraryRef,
        *,
        include_virtual: bool = False,
    ) -> tuple[Shelf, ...]:
        clause, params = self._scope(library, include_virtual)
        with self._connect() as conn:
            # Mirrors `Shelf.sort_key`: named shelves alphabetically, then
            # unnamed ones oldest-first. COALESCE so a NULL created_at sorts
            # with the empty ones rather than by SQLite's NULL rules.
            rows = conn.execute(
                f"SELECT * FROM shelves WHERE {clause}"
                " ORDER BY label, COALESCE(created_at, ''), id",
                params,
            ).fetchall()
        return tuple(_load_shelf(r) for r in rows)

    def count_shelves(
        self, library: LibraryRef, *, include_virtual: bool = False
    ) -> int:
        clause, params = self._scope(library, include_virtual)
        with self._connect() as conn:
            return int(conn.execute(
                f"SELECT COUNT(*) FROM shelves WHERE {clause}", params
            ).fetchone()[0])

    @staticmethod
    def _scope(library: LibraryRef, include_virtual: bool) -> tuple[str, tuple]:
        if include_virtual:
            return "library_id = ?", (library.id,)
        return "library_id = ? AND virtual = 0", (library.id,)

    def delete_shelf(self, library: LibraryRef, shelf_id: str) -> bool:
        with self._connect() as conn:
            if not conn.execute(
                "SELECT 1 FROM shelves WHERE id = ? AND library_id = ?",
                (shelf_id, library.id),
            ).fetchone():
                return False
            if conn.execute(
                "SELECT 1 FROM captures WHERE shelf_id = ? AND library_id = ?",
                (shelf_id, library.id),
            ).fetchone():
                raise ShelfNotEmpty(
                    f"shelf {shelf_id} still has captures; deleting it would "
                    "destroy the record a re-read diffs against (§5.6)"
                )
            with conn:
                cur = conn.execute(
                    "DELETE FROM shelves WHERE id = ? AND library_id = ?",
                    (shelf_id, library.id),
                )
            return cur.rowcount > 0

    # --- captures --------------------------------------------------------

    def save_capture(self, library: LibraryRef, capture: Capture) -> None:
        if capture.library_id != library.id:
            raise WrongLibrary(
                f"capture {capture.id} belongs to {capture.library_id!r}, "
                f"not {library.id!r}"
            )
        with self._connect() as conn:
            # Checked in Python rather than left to the foreign key, because
            # the FK cannot express "in THIS library" — a capture pointing at
            # another tenant's shelf satisfies it perfectly.
            if not conn.execute(
                "SELECT 1 FROM shelves WHERE id = ? AND library_id = ?",
                (capture.shelf_id, library.id),
            ).fetchone():
                raise UnknownShelf(
                    f"no shelf {capture.shelf_id!r} in library {library.id!r}"
                )
            try:
                with conn:
                    conn.execute(
                        'INSERT INTO captures (id, shelf_id, library_id, depth,'
                        ' "order", image_id, captured_at) VALUES (?,?,?,?,?,?,?)'
                        ' ON CONFLICT(id) DO UPDATE SET'
                        ' shelf_id=excluded.shelf_id, depth=excluded.depth,'
                        ' "order"=excluded."order", image_id=excluded.image_id,'
                        ' captured_at=excluded.captured_at'
                        ' WHERE captures.library_id = excluded.library_id',
                        (capture.id, capture.shelf_id, library.id,
                         capture.depth, capture.order, capture.image_id,
                         capture.captured_at),
                    )
            except sqlite3.IntegrityError as exc:
                # Named by columns, not by index, same as books.book_key:
                #   "UNIQUE constraint failed: captures.shelf_id, ..."
                if "captures.shelf_id" in str(exc):
                    raise DuplicateCaptureSlot(
                        f"another capture already holds {capture.slot} (§5.3)"
                    ) from exc
                raise

    def get_capture(self, library: LibraryRef, capture_id: str) -> Capture | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM captures WHERE id = ? AND library_id = ?",
                (capture_id, library.id),
            ).fetchone()
        return _load_capture(row) if row else None

    def list_captures(
        self,
        library: LibraryRef,
        shelf_id: str,
        *,
        depth: int | None = None,
    ) -> tuple[Capture, ...]:
        clause = "library_id = ? AND shelf_id = ?"
        params: list[object] = [library.id, shelf_id]
        if depth is not None:
            clause += " AND depth = ?"
            params.append(depth)
        with self._connect() as conn:
            rows = conn.execute(
                f'SELECT * FROM captures WHERE {clause}'
                ' ORDER BY depth, "order", id',
                params,
            ).fetchall()
        return tuple(_load_capture(r) for r in rows)

    def delete_capture(self, library: LibraryRef, capture_id: str) -> bool:
        with self._connect() as conn:
            with conn:
                cur = conn.execute(
                    "DELETE FROM captures WHERE id = ? AND library_id = ?",
                    (capture_id, library.id),
                )
            return cur.rowcount > 0


class SqliteReadStore(_SqliteStore):
    """Implements ``app.ports.store.ReadStore``.

    Shares the file with the other two stores — one database, three
    aggregates now — for the same reason ``SqliteShelfStore`` does: a capture
    and the reads it feeds must never end up in different places.
    """

    def __init__(self, path: str | Path) -> None:
        super().__init__(path, kind="SqliteReadStore")

    def save_read(self, library: LibraryRef, read: Read) -> None:
        if read.library_id != library.id:
            raise WrongLibrary(
                f"read {read.id} belongs to {read.library_id!r}, "
                f"not {library.id!r}"
            )
        with self._connect() as conn:
            with conn:
                # DELETE + INSERT, like books — not the shelf's upsert. A
                # shelf's upsert exists to protect its captures from a
                # cascade on rename; nothing points AT a read's row except its
                # own claims, and ON DELETE CASCADE clears those correctly
                # before they are re-inserted below, so replace-whole is both
                # safe and simpler here.
                conn.execute(
                    "DELETE FROM reads WHERE id = ? AND library_id = ?",
                    (read.id, library.id),
                )
                _insert_read(conn, library, read)

    def get_read(self, library: LibraryRef, read_id: str) -> Read | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reads WHERE id = ? AND library_id = ?",
                (read_id, library.id),
            ).fetchone()
            return _load_read(conn, row) if row else None

    def list_reads(
        self,
        library: LibraryRef,
        shelf_id: str,
        *,
        depth: int | None = None,
    ) -> tuple[Read, ...]:
        clause = "library_id = ? AND shelf_id = ?"
        params: list[object] = [library.id, shelf_id]
        if depth is not None:
            clause += " AND depth = ?"
            params.append(depth)
        with self._connect() as conn:
            # Most-recent-first (started_at DESC), id DESC as the tiebreaker
            # for a total order — same reasoning as every other listing here:
            # two reads started in the same clock second must still page
            # consistently.
            rows = conn.execute(
                f"SELECT * FROM reads WHERE {clause}"
                " ORDER BY started_at DESC, id DESC",
                params,
            ).fetchall()
            return tuple(_load_read(conn, r) for r in rows)

    def list_reads_for_capture(
        self, library: LibraryRef, capture_id: str,
    ) -> tuple[Read, ...]:
        # `capture_ids` is a JSON array column (v7 — json1 is not guaranteed
        # present, see the migration's own note), so SQL NARROWS and Python
        # DECIDES: the LIKE clause finds rows whose JSON text contains the
        # quoted id, and the membership check below confirms it against the
        # parsed list. Same split `app.domain.search` documents for its own
        # `LIKE` scan — a clever retrieval clause may never change the answer.
        # The escape matters because an id is opaque: a `%` or `_` in one
        # would otherwise widen the pattern rather than narrow it.
        #
        # The quoted needle is already exact, so the membership re-check below
        # changes no result today and SURVIVES mutation testing — recorded in
        # the contract test that covers this rather than left looking like a
        # missing case. It stays because it is what keeps the SQL a pure
        # NARROWING clause: an index- or FTS-shaped rewrite of this query can
        # then be judged on speed alone, never on whether it moved an answer.
        needle = ('%"' + capture_id.replace("\\", "\\\\")
                  .replace("%", "\\%").replace("_", "\\_") + '"%')
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reads WHERE library_id = ?"
                " AND capture_ids LIKE ? ESCAPE '\\'"
                " ORDER BY started_at DESC, id DESC",
                (library.id, needle),
            ).fetchall()
            reads = (_load_read(conn, r) for r in rows)
            return tuple(r for r in reads if capture_id in r.capture_ids)


class SqliteDecisionStore(_SqliteStore):
    """Implements ``app.ports.decisions.DecisionStore`` (P2.5).

    Shares the file with the other stores, same reasoning as
    :class:`SqliteReadStore` — a decision made about a claim from a specific
    read must never end up in a different database from the read itself.
    """

    def __init__(self, path: str | Path) -> None:
        super().__init__(path, kind="SqliteDecisionStore")

    def save_decision(self, library: LibraryRef, decision: Decision) -> None:
        if decision.library_id != library.id:
            raise WrongLibrary(
                f"decision for {decision.book_key!r} belongs to "
                f"{decision.library_id!r}, not {library.id!r}"
            )
        with self._connect() as conn:
            with conn:
                # A human changing their mind (§5.4's queue makes this
                # possible) overwrites the row for this (shelf, depth,
                # book_key) rather than accumulating a history nobody reads —
                # the composite PRIMARY KEY is what makes this a plain upsert.
                conn.execute(
                    "INSERT INTO decisions (library_id, shelf_id, depth,"
                    " book_key, kind, copy_id, decided_at) VALUES (?,?,?,?,?,?,?)"
                    " ON CONFLICT(library_id, shelf_id, depth, book_key)"
                    " DO UPDATE SET kind=excluded.kind,"
                    " copy_id=excluded.copy_id, decided_at=excluded.decided_at",
                    (library.id, decision.shelf_id, decision.depth,
                     decision.book_key, decision.kind.value, decision.copy_id,
                     decision.decided_at),
                )

    def get_decision(
        self, library: LibraryRef, shelf_id: str, depth: int, book_key: str,
    ) -> Decision | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM decisions WHERE library_id = ? AND shelf_id = ?"
                " AND depth = ? AND book_key = ?",
                (library.id, shelf_id, depth, book_key),
            ).fetchone()
        return _load_decision(row) if row else None

    def list_decisions(
        self, library: LibraryRef, shelf_id: str, depth: int,
    ) -> tuple[Decision, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE library_id = ? AND shelf_id = ?"
                " AND depth = ? ORDER BY book_key",
                (library.id, shelf_id, depth),
            ).fetchall()
        return tuple(_load_decision(r) for r in rows)

    def delete_decision(
        self, library: LibraryRef, shelf_id: str, depth: int, book_key: str,
    ) -> bool:
        with self._connect() as conn:
            with conn:
                cur = conn.execute(
                    "DELETE FROM decisions WHERE library_id = ? AND shelf_id = ?"
                    " AND depth = ? AND book_key = ?",
                    (library.id, shelf_id, depth, book_key),
                )
            return cur.rowcount > 0


def _load_decision(row: sqlite3.Row) -> Decision:
    return Decision(
        library_id=row["library_id"], shelf_id=row["shelf_id"],
        depth=row["depth"], book_key=row["book_key"],
        kind=DecisionKind(row["kind"]), copy_id=row["copy_id"],
        decided_at=row["decided_at"],
    )


class SqliteDuplicateQueue(_SqliteStore):
    """Implements ``app.ports.duplicates.DuplicateQueue`` (P2.6).

    Shares the file with the other stores, same reasoning as
    :class:`SqliteDecisionStore` — a queued question and the `Decision` that
    eventually closes it must never end up in different databases.
    """

    def __init__(self, path: str | Path) -> None:
        super().__init__(path, kind="SqliteDuplicateQueue")

    def save_question(self, library: LibraryRef, question: DuplicateQuestion) -> None:
        if question.library_id != library.id:
            raise WrongLibrary(
                f"question for {question.book_key!r} belongs to "
                f"{question.library_id!r}, not {library.id!r}"
            )
        with self._connect() as conn:
            with conn:
                # Same upsert shape as decisions: the composite key IS the
                # identity, so a refresh (a re-skip on a later read) replaces
                # the row rather than accumulating one per read.
                conn.execute(
                    "INSERT INTO duplicate_questions (id, library_id, shelf_id,"
                    " depth, book_key, read_id, spine_id, claim_title,"
                    " claim_author, existing_book_id, opened_at, captured_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(library_id, shelf_id, depth, book_key)"
                    " DO UPDATE SET id=excluded.id, read_id=excluded.read_id,"
                    " spine_id=excluded.spine_id,"
                    " claim_title=excluded.claim_title,"
                    " claim_author=excluded.claim_author,"
                    " existing_book_id=excluded.existing_book_id,"
                    " opened_at=excluded.opened_at,"
                    " captured_at=excluded.captured_at",
                    (question.id, library.id, question.shelf_id, question.depth,
                     question.book_key, question.read_id, question.spine_id,
                     question.claim_title, question.claim_author,
                     question.existing_book_id, question.opened_at,
                     question.captured_at),
                )

    def get_question(
        self, library: LibraryRef, shelf_id: str, depth: int, book_key: str,
    ) -> DuplicateQuestion | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM duplicate_questions WHERE library_id = ?"
                " AND shelf_id = ? AND depth = ? AND book_key = ?",
                (library.id, shelf_id, depth, book_key),
            ).fetchone()
        return _load_question(row) if row else None

    def list_open_questions(
        self, library: LibraryRef, *, shelf_id: str | None = None,
    ) -> tuple[DuplicateQuestion, ...]:
        clause = "library_id = ?"
        params: list[object] = [library.id]
        if shelf_id is not None:
            clause += " AND shelf_id = ?"
            params.append(shelf_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM duplicate_questions WHERE {clause}"
                " ORDER BY opened_at, id",
                params,
            ).fetchall()
        return tuple(_load_question(r) for r in rows)

    def delete_question(
        self, library: LibraryRef, shelf_id: str, depth: int, book_key: str,
    ) -> bool:
        with self._connect() as conn:
            with conn:
                cur = conn.execute(
                    "DELETE FROM duplicate_questions WHERE library_id = ?"
                    " AND shelf_id = ? AND depth = ? AND book_key = ?",
                    (library.id, shelf_id, depth, book_key),
                )
            return cur.rowcount > 0


def _load_question(row: sqlite3.Row) -> DuplicateQuestion:
    return DuplicateQuestion(
        id=row["id"], library_id=row["library_id"], shelf_id=row["shelf_id"],
        depth=row["depth"], book_key=row["book_key"], read_id=row["read_id"],
        spine_id=row["spine_id"], claim_title=row["claim_title"],
        claim_author=row["claim_author"], existing_book_id=row["existing_book_id"],
        opened_at=row["opened_at"], captured_at=row["captured_at"],
    )


# --- row <-> entity -------------------------------------------------------
#
# `list` loads copies and provenance per book, so a 50-row page is ~101
# queries. Measured irrelevant at a few thousand books on a local file; if a
# profile ever says otherwise the fix is two batched queries keyed by book_id,
# not a schema change.

def _insert_book(conn: sqlite3.Connection, library: LibraryRef, book: Book) -> None:
    conn.execute(
        "INSERT INTO books (id, library_id, title, author, norm_title,"
        " norm_author, sort_author, book_key, shared_book_id, rating, notes,"
        " read_status, added_at, search_text)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (book.id, library.id, book.title, book.author, book.normalized_title,
         book.normalized_author,
         # Surname-first, by the SAME domain rule the v3 backfill used — a
         # book saved after the migration must sort with the ones migrated
         # before it.
         book.author_sort,
         book.key, book.shared_book_id,
         book.work.rating, book.work.notes, book.work.read_status,
         book.added_at,
         # Written by the SAME function the matcher uses at query time, so the
         # stored haystack and the in-memory one cannot drift apart.
         haystack(book)),
    )
    for position, copy in enumerate(book.copies):
        conn.execute(
            "INSERT INTO copies (id, book_id, library_id, position, status,"
            " label, shelf_id, depth, tags, condition, acquired_at, lending,"
            " lent_out) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (copy.id, book.id, library.id, position, copy.status.value,
             copy.label, copy.shelf_id, copy.depth,
             json.dumps(list(copy.fields.tags)),
             copy.fields.condition, copy.fields.acquired_at,
             json.dumps(asdict(copy.lending)) if copy.lending else None,
             # The SAME predicate `Lending.is_out` uses, kept in a comment
             # rather than a shared function because it is one boolean
             # expression — a helper here would be more indirection than the
             # rule it guards.
             int(copy.lending is not None and copy.lending.returned_at is None)),
        )
        for seq, p in enumerate(copy.provenance):
            conn.execute(
                "INSERT INTO provenance (copy_id, seq, run_id, spine_id,"
                " shelf_id, captured_at, depth) VALUES (?,?,?,?,?,?,?)",
                (copy.id, seq, p.run_id, p.spine_id, p.shelf_id, p.captured_at,
                 p.depth),
            )


def _load_book(conn: sqlite3.Connection, row: sqlite3.Row) -> Book:
    copies = tuple(
        _load_copy(conn, c)
        for c in conn.execute(
            "SELECT * FROM copies WHERE book_id = ? ORDER BY position",
            (row["id"],),
        ).fetchall()
    )
    return Book(
        id=row["id"],
        library_id=row["library_id"],
        title=row["title"],
        author=row["author"],
        copies=copies,
        shared_book_id=row["shared_book_id"],
        work=WorkFields(
            rating=row["rating"],
            notes=row["notes"],
            read_status=row["read_status"],
        ),
        added_at=row["added_at"],
    )


def _load_shelf(row: sqlite3.Row) -> Shelf:
    return Shelf(
        id=row["id"],
        library_id=row["library_id"],
        label=row["label"],
        depth_count=row["depth_count"],
        virtual=bool(row["virtual"]),
        created_at=row["created_at"],
    )


def _load_capture(row: sqlite3.Row) -> Capture:
    return Capture(
        id=row["id"],
        shelf_id=row["shelf_id"],
        library_id=row["library_id"],
        depth=row["depth"],
        order=row["order"],
        image_id=row["image_id"],
        captured_at=row["captured_at"],
    )


def _load_copy(conn: sqlite3.Connection, row: sqlite3.Row) -> Copy:
    provenance = tuple(
        Provenance(
            run_id=p["run_id"], spine_id=p["spine_id"],
            shelf_id=p["shelf_id"], captured_at=p["captured_at"],
            depth=p["depth"],
        )
        for p in conn.execute(
            "SELECT * FROM provenance WHERE copy_id = ? ORDER BY seq",
            (row["id"],),
        ).fetchall()
    )
    return Copy(
        id=row["id"],
        book_id=row["book_id"],
        status=Status(row["status"]),
        label=row["label"],
        shelf_id=row["shelf_id"],
        depth=row["depth"],
        provenance=provenance,
        fields=CopyFields(
            tags=tuple(json.loads(row["tags"])),
            condition=row["condition"],
            acquired_at=row["acquired_at"],
        ),
        lending=Lending(**json.loads(row["lending"])) if row["lending"] else None,
    )


def _insert_read(conn: sqlite3.Connection, library: LibraryRef, read: Read) -> None:
    conn.execute(
        "INSERT INTO reads (id, library_id, shelf_id, depth, capture_ids,"
        " mode, status, code_version, config, started_at, finished_at, error,"
        " diff_summary) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (read.id, library.id, read.shelf_id, read.depth,
         json.dumps(list(read.capture_ids)), read.mode, read.status.value,
         json.dumps(read.code_version) if read.code_version is not None else None,
         json.dumps(read.config) if read.config is not None else None,
         read.started_at, read.finished_at, read.error,
         json.dumps(asdict(read.diff_summary))
         if read.diff_summary is not None else None),
    )
    for position, claim in enumerate(read.claims):
        conn.execute(
            "INSERT INTO claims (id, read_id, position, spine_id, capture_id,"
            " text, title, author, tier, score, catalog_id, crop_key, box,"
            " alternatives) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (claim.id, read.id, position, claim.spine_id, claim.capture_id,
             claim.text, claim.title, claim.author, claim.tier.value,
             claim.score, claim.catalog_id, claim.crop_key,
             json.dumps(list(claim.box)) if claim.box is not None else None,
             json.dumps([
                 {"title": a.title, "author": a.author, "score": a.score,
                  "reason": a.reason}
                 for a in claim.alternatives
             ]) if claim.alternatives else None),
        )


def _load_read(conn: sqlite3.Connection, row: sqlite3.Row) -> Read:
    claims = tuple(
        Claim(
            id=c["id"], spine_id=c["spine_id"], capture_id=c["capture_id"],
            text=c["text"], title=c["title"], author=c["author"],
            tier=ClaimTier(c["tier"]), score=c["score"],
            catalog_id=c["catalog_id"], crop_key=c["crop_key"],
            box=tuple(json.loads(c["box"])) if c["box"] else None,
            alternatives=tuple(
                Alternative(**a) for a in json.loads(c["alternatives"])
            ) if c["alternatives"] else (),
        )
        for c in conn.execute(
            "SELECT * FROM claims WHERE read_id = ? ORDER BY position",
            (row["id"],),
        ).fetchall()
    )
    return Read(
        id=row["id"],
        library_id=row["library_id"],
        shelf_id=row["shelf_id"],
        depth=row["depth"],
        capture_ids=tuple(json.loads(row["capture_ids"])),
        mode=row["mode"],
        status=ReadStatus(row["status"]),
        claims=claims,
        code_version=json.loads(row["code_version"]) if row["code_version"] else None,
        config=json.loads(row["config"]) if row["config"] else None,
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error=row["error"],
        diff_summary=DiffSummary(**json.loads(row["diff_summary"]))
        if row["diff_summary"] else None,
    )
