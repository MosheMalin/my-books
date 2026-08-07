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
    Book,
    Copy,
    CopyFields,
    Lending,
    LibraryRef,
    Provenance,
    Status,
    WorkFields,
)
from app.ports.store import (
    BookPage,
    BookSort,
    DuplicateBookKey,
    WrongLibrary,
)

_ORDER_BY = {
    BookSort.TITLE: "norm_title {dir}, id {dir}",
    BookSort.AUTHOR: "norm_author {dir}, norm_title {dir}, id {dir}",
    # COALESCE so books with no added_at (P1.3 imports 251 of them) sort
    # together at one end rather than scattering by NULL-ordering rules.
    BookSort.RECENTLY_ADDED: "COALESCE(added_at, '') {dir}, id {dir}",
}


class SqliteBookStore:
    """Implements ``app.ports.store.BookStore``."""

    def __init__(self, path: str | Path) -> None:
        if str(path) == ":memory:":
            # Would silently "work" and lose everything: a connection per
            # operation means each call would get its own empty database.
            # MemoryBookStore is the in-memory implementation.
            raise ValueError(
                "SqliteBookStore needs a file; use MemoryBookStore for RAM"
            )
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            migrate(conn)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=10.0)
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
        limit: int = 50,
        offset: int = 0,
    ) -> BookPage:
        where = ["library_id = ?"]
        params: list[object] = [library.id]
        if author_key is not None:
            where.append("norm_author = ?")
            params.append(author_key)
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

    def count(self, library: LibraryRef) -> int:
        with self._connect() as conn:
            return int(conn.execute(
                "SELECT COUNT(*) FROM books WHERE library_id = ?",
                (library.id,),
            ).fetchone()[0])


# --- row <-> entity -------------------------------------------------------
#
# `list` loads copies and provenance per book, so a 50-row page is ~101
# queries. Measured irrelevant at a few thousand books on a local file; if a
# profile ever says otherwise the fix is two batched queries keyed by book_id,
# not a schema change.

def _insert_book(conn: sqlite3.Connection, library: LibraryRef, book: Book) -> None:
    conn.execute(
        "INSERT INTO books (id, library_id, title, author, norm_title,"
        " norm_author, book_key, shared_book_id, rating, notes, read_status,"
        " added_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (book.id, library.id, book.title, book.author, book.normalized_title,
         book.normalized_author, book.key, book.shared_book_id,
         book.work.rating, book.work.notes, book.work.read_status,
         book.added_at),
    )
    for position, copy in enumerate(book.copies):
        conn.execute(
            "INSERT INTO copies (id, book_id, library_id, position, status,"
            " label, shelf_id, tags, condition, acquired_at, lending)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (copy.id, book.id, library.id, position, copy.status.value,
             copy.label, copy.shelf_id, json.dumps(list(copy.fields.tags)),
             copy.fields.condition, copy.fields.acquired_at,
             json.dumps(asdict(copy.lending)) if copy.lending else None),
        )
        for seq, p in enumerate(copy.provenance):
            conn.execute(
                "INSERT INTO provenance (copy_id, seq, run_id, spine_id,"
                " shelf_id, captured_at) VALUES (?,?,?,?,?,?)",
                (copy.id, seq, p.run_id, p.spine_id, p.shelf_id, p.captured_at),
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


def _load_copy(conn: sqlite3.Connection, row: sqlite3.Row) -> Copy:
    provenance = tuple(
        Provenance(
            run_id=p["run_id"], spine_id=p["spine_id"],
            shelf_id=p["shelf_id"], captured_at=p["captured_at"],
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
        provenance=provenance,
        fields=CopyFields(
            tags=tuple(json.loads(row["tags"])),
            condition=row["condition"],
            acquired_at=row["acquired_at"],
        ),
        lending=Lending(**json.loads(row["lending"])) if row["lending"] else None,
    )
