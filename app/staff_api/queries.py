# -*- coding: utf-8 -*-
"""Cross-tenant reads over the product database.

⚠ These deliberately do **not** go through :mod:`app.ports.store`. Every method
of every store leads with a ``LibraryRef`` — that is the whole point of those
ports, and the tenant-isolation suite exists to keep it true — so expressing
"every library at once" through them would mean either loosening the ports
(weakening the product's isolation to serve a console) or issuing N queries per
figure. A separate read model, in a separate service, keeps the isolation rule
exactly as strict as it is.

⚠ The price is that this module knows the SCHEMA, so a migration that renames a
column breaks it. That is accepted and made cheap on purpose: everything here
is one ``SELECT`` per question, in one file, and
:func:`app.staff_api.queries.self_check` fails loudly at startup rather than
letting a stale column surface as a wrong number. What is NOT duplicated is
anything with a *rule* in it — the §5.1 status ladder and the Hebrew search are
imported from where they already live.

⚠ **No ``migrate()`` call anywhere in this module.** See the package docstring:
opening the product database the usual way would upgrade the owner's schema as
a side effect of viewing a dashboard.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

from app.domain.search import TextEntry, compile_sql_like, parse, score

#: The §5.1 ladder, as SQL. A book's status is the strongest claim among its
#: copies and is DERIVED, never stored — the product's own book listing derives
#: it the same way, and the two must not disagree, so the expression is written
#: once here and reused by every query below.
STATUS_RANK_SQL = (
    "(SELECT MAX(CASE status WHEN 'manual' THEN 2 WHEN 'approved' THEN 1"
    " ELSE 0 END) FROM copies WHERE copies.book_id = books.id)"
)

#: rank -> name, matching :class:`app.domain.book.Status`.
RANK_NAMES = ("auto", "approved", "manual")

#: How many matching rows a ranked search pulls before ordering them in Python.
#: `app/domain/search.py` documents the same linear-scan trade for ONE library
#: (measured 4ms at 251 books, 53ms at 10k); across every tenant the number is
#: bigger, so it is capped — and the cap is REPORTED to the caller, because a
#: silently truncated result set reads as "that is all there is".
RANKED_SCAN_CAP = 5000

#: Columns this module depends on, per table. Checked at startup so a schema
#: change is a refusal to serve rather than a silently wrong dashboard.
REQUIRED_COLUMNS = {
    "accounts": ("id", "display_name", "email", "created_at"),
    "libraries": ("id", "label", "created_at"),
    "memberships": ("account_id", "library_id", "role", "joined_at"),
    "books": ("id", "library_id", "title", "author", "added_at",
              "search_text", "sort_author", "norm_title", "norm_author"),
    "copies": ("id", "book_id", "library_id", "status", "shelf_id", "lent_out"),
    "shelves": ("id", "library_id", "label", "virtual", "depth_count",
                "created_at"),
    "captures": ("id", "library_id", "shelf_id"),
    "reads": ("id", "library_id", "shelf_id", "depth", "mode", "status",
              "started_at", "finished_at"),
    "duplicate_questions": ("id", "library_id"),
}


class SchemaMismatch(RuntimeError):
    """The product database is not the shape this read model expects."""


@contextmanager
def _open(path: Path) -> Iterator[sqlite3.Connection]:
    """A connection that reads and never migrates.

    ⚠ Opened read-WRITE rather than with SQLite's ``mode=ro``, which looks like
    the safer choice and is not: a WAL database needs to create its ``-shm``
    file, and a genuinely read-only handle fails to do so the moment the
    product server is not already holding one open. Read-only here is a
    property of the STATEMENTS — every one is a SELECT — plus the absence of a
    ``migrate()`` call, both of which are visible in this file.
    """
    conn = sqlite3.connect(str(path), timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        yield conn
    finally:
        conn.close()


@dataclass(frozen=True)
class LibraryRow:
    id: str
    label: str
    created_at: str | None
    members: int
    admins: int
    books: int
    copies: int
    auto: int
    approved: int
    manual: int
    shelves: int
    captures: int
    reads: int
    duplicates: int
    lent_out: int
    last_activity: str | None


@dataclass(frozen=True)
class MembershipRow:
    account_id: str
    library_id: str
    role: str
    joined_at: str | None


@dataclass(frozen=True)
class AccountRow:
    id: str
    display_name: str
    email: str | None
    created_at: str | None
    memberships: tuple[MembershipRow, ...] = field(default=())


@dataclass(frozen=True)
class BookRow:
    id: str
    library_id: str
    title: str
    author: str
    status: str
    copy_count: int
    added_at: str | None
    shelf_count: int


@dataclass(frozen=True)
class ShelfRow:
    id: str
    library_id: str
    label: str
    depth_count: int
    virtual: bool
    captures: int
    books: int
    last_read: str | None


@dataclass(frozen=True)
class ReadRow:
    id: str
    library_id: str
    shelf_id: str
    shelf_label: str
    depth: int
    mode: str
    status: str
    started_at: str | None
    finished_at: str | None
    claims: int


class StaffQueries:
    """Every cross-tenant question the console asks, in one place."""

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        if not self.path.exists():
            raise FileNotFoundError(
                f"no product database at {self.path}; set BOOKSNAP_DB"
            )
        self.self_check()

    # --- guard ------------------------------------------------------------

    def self_check(self) -> None:
        """Refuse to serve a database whose shape has moved under us.

        A missing column would otherwise surface as a 500 on one screen, or —
        far worse — as a plausible wrong number on a dashboard nobody
        double-checks.
        """
        missing: list[str] = []
        with _open(self.path) as conn:
            for table, columns in REQUIRED_COLUMNS.items():
                rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
                if not rows:
                    missing.append(f"{table} (table absent)")
                    continue
                have = {r["name"] for r in rows}
                for column in columns:
                    if column not in have:
                        missing.append(f"{table}.{column}")
        if missing:
            raise SchemaMismatch(
                "the product database is missing columns this read model needs: "
                + ", ".join(missing)
                + ". app/staff_api/queries.py knows the schema on purpose "
                  "(see its docstring) — update REQUIRED_COLUMNS and the "
                  "queries together."
            )

    # --- the whole system -------------------------------------------------

    def overview(self) -> dict[str, int]:
        with _open(self.path) as conn:
            def count(sql: str) -> int:
                return int(conn.execute(sql).fetchone()[0])

            by_rank = dict(conn.execute(
                f"SELECT {STATUS_RANK_SQL} AS rank, COUNT(*) FROM books"
                " GROUP BY rank"
            ).fetchall())
            return {
                "accounts": count("SELECT COUNT(*) FROM accounts"),
                "libraries": count("SELECT COUNT(*) FROM libraries"),
                "memberships": count("SELECT COUNT(*) FROM memberships"),
                "books": count("SELECT COUNT(*) FROM books"),
                "copies": count("SELECT COUNT(*) FROM copies"),
                "shelves": count("SELECT COUNT(*) FROM shelves WHERE virtual = 0"),
                "captures": count("SELECT COUNT(*) FROM captures"),
                "reads": count("SELECT COUNT(*) FROM reads"),
                "duplicates": count("SELECT COUNT(*) FROM duplicate_questions"),
                "lent_out": count(
                    "SELECT COUNT(DISTINCT book_id) FROM copies WHERE lent_out = 1"
                ),
                # A rank with no books is absent from the GROUP BY, so each is
                # defaulted rather than indexed — otherwise a system with no
                # manual books 500s instead of reporting zero.
                "auto": int(by_rank.get(0, 0)),
                "approved": int(by_rank.get(1, 0)),
                "manual": int(by_rank.get(2, 0)),
            }

    # --- libraries --------------------------------------------------------

    def libraries(self) -> tuple[LibraryRow, ...]:
        """Every library in the system, with its numbers.

        One grouped query per figure and a join in Python, rather than one
        query per library: the point of this service is that "how big is
        everything" costs a bounded number of round trips.
        """
        with _open(self.path) as conn:
            base = conn.execute(
                "SELECT id, label, created_at FROM libraries"
                " ORDER BY label, COALESCE(created_at, ''), id"
            ).fetchall()

            def grouped(sql: str) -> dict[str, int]:
                return {str(r[0]): int(r[1]) for r in conn.execute(sql).fetchall()}

            members = grouped(
                "SELECT library_id, COUNT(*) FROM memberships GROUP BY library_id")
            admins = grouped(
                "SELECT library_id, COUNT(*) FROM memberships"
                " WHERE role = 'admin' GROUP BY library_id")
            books = grouped(
                "SELECT library_id, COUNT(*) FROM books GROUP BY library_id")
            copies = grouped(
                "SELECT library_id, COUNT(*) FROM copies GROUP BY library_id")
            shelves = grouped(
                "SELECT library_id, COUNT(*) FROM shelves WHERE virtual = 0"
                " GROUP BY library_id")
            captures = grouped(
                "SELECT library_id, COUNT(*) FROM captures GROUP BY library_id")
            reads = grouped(
                "SELECT library_id, COUNT(*) FROM reads GROUP BY library_id")
            dupes = grouped(
                "SELECT library_id, COUNT(*) FROM duplicate_questions"
                " GROUP BY library_id")
            lent = grouped(
                "SELECT library_id, COUNT(DISTINCT book_id) FROM copies"
                " WHERE lent_out = 1 GROUP BY library_id")

            status_rows = conn.execute(
                f"SELECT library_id, {STATUS_RANK_SQL} AS rank, COUNT(*)"
                " FROM books GROUP BY library_id, rank"
            ).fetchall()
            by_status: dict[str, dict[int, int]] = {}
            for lib_id, rank, n in status_rows:
                by_status.setdefault(str(lib_id), {})[int(rank or 0)] = int(n)

            activity = {
                str(r[0]): r[1] for r in conn.execute(
                    "SELECT library_id, MAX(COALESCE(finished_at, started_at))"
                    " FROM reads GROUP BY library_id"
                ).fetchall()
            }

        out = []
        for row in base:
            lid = str(row["id"])
            status = by_status.get(lid, {})
            out.append(LibraryRow(
                id=lid, label=row["label"] or "", created_at=row["created_at"],
                members=members.get(lid, 0), admins=admins.get(lid, 0),
                books=books.get(lid, 0), copies=copies.get(lid, 0),
                auto=status.get(0, 0), approved=status.get(1, 0),
                manual=status.get(2, 0),
                shelves=shelves.get(lid, 0), captures=captures.get(lid, 0),
                reads=reads.get(lid, 0), duplicates=dupes.get(lid, 0),
                lent_out=lent.get(lid, 0), last_activity=activity.get(lid),
            ))
        return tuple(out)

    # --- people -----------------------------------------------------------

    def accounts(self) -> tuple[AccountRow, ...]:
        """Every account, with every membership it holds.

        ⚠ This is the screen that did not exist before, and could not: the
        product API answers "which libraries may *I* name", never "who is in
        the system". It is also the one to be careful with — see the router's
        note on what a system administrator should and should not be able to
        read about a household.
        """
        with _open(self.path) as conn:
            rows = conn.execute(
                "SELECT id, display_name, email, created_at FROM accounts"
                " ORDER BY COALESCE(created_at, ''), id"
            ).fetchall()
            memberships = conn.execute(
                "SELECT account_id, library_id, role, joined_at FROM memberships"
                " ORDER BY account_id, library_id"
            ).fetchall()

        held: dict[str, list[MembershipRow]] = {}
        for m in memberships:
            held.setdefault(str(m["account_id"]), []).append(MembershipRow(
                account_id=str(m["account_id"]), library_id=str(m["library_id"]),
                role=str(m["role"]), joined_at=m["joined_at"],
            ))
        return tuple(
            AccountRow(
                id=str(r["id"]), display_name=r["display_name"] or "",
                email=r["email"], created_at=r["created_at"],
                memberships=tuple(held.get(str(r["id"]), ())),
            )
            for r in rows
        )

    def orphan_libraries(self) -> tuple[str, ...]:
        """Libraries with no membership at all.

        Not a curiosity: `new_library` mints an admin membership in the same
        call precisely so this set stays empty, and a row here means a library
        nobody can administer or even see — exactly the state that rule
        exists to prevent. A system console is the only place it is visible.
        """
        with _open(self.path) as conn:
            rows = conn.execute(
                "SELECT id FROM libraries WHERE id NOT IN"
                " (SELECT library_id FROM memberships)"
            ).fetchall()
        return tuple(str(r["id"]) for r in rows)

    # --- books ------------------------------------------------------------

    def books(
        self,
        *,
        q: str = "",
        library_id: str | None = None,
        status: str | None = None,
        sort: str = "title",
        ascending: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[tuple[BookRow, ...], int]:
        """Books across every tenant. Returns ``(page, total)``.

        ⚠ Searching reuses :mod:`app.domain.search` — the SAME measured Hebrew
        rules the product uses (P1.5: nikud stripped, final letters folded,
        in-word geresh deleted, leading particles tolerated in the query,
        P@1 1.00 on the fixture). Narrowing is a ``LIKE`` over the stored
        ``search_text`` column and RANKING happens in Python, which is the
        split `app/domain/search.py` documents: ranking in SQL means writing
        it twice and finding the drift in a bug report.
        """
        where: list[str] = []
        params: list[Any] = []
        if library_id:
            where.append("books.library_id = ?")
            params.append(library_id)
        if status is not None:
            where.append(f"{STATUS_RANK_SQL} = ?")
            params.append(RANK_NAMES.index(status))

        query = parse(q) if q.strip() else None
        if query:
            clause, like_params = compile_sql_like(query, "books.search_text")
            if clause:
                where.append(f"({clause})")
                params.extend(like_params)

        clause_sql = (" WHERE " + " AND ".join(where)) if where else ""
        direction = "ASC" if ascending else "DESC"
        order = {
            "title": f"norm_title {direction}, books.id {direction}",
            "author": f"sort_author {direction}, norm_title {direction},"
                      f" books.id {direction}",
            "recently_added": f"COALESCE(added_at, '') {direction},"
                              f" books.id {direction}",
        }.get(sort, f"norm_title {direction}, books.id {direction}")

        select = (
            "SELECT books.id, books.library_id, books.title, books.author,"
            " books.added_at, books.norm_title, books.norm_author,"
            f" {STATUS_RANK_SQL} AS rank,"
            " (SELECT COUNT(*) FROM copies WHERE copies.book_id = books.id)"
            "   AS copy_count,"
            " (SELECT COUNT(DISTINCT shelf_id) FROM copies"
            "   WHERE copies.book_id = books.id AND shelf_id IS NOT NULL)"
            "   AS shelf_count"
            " FROM books"
        )

        with _open(self.path) as conn:
            total = int(conn.execute(
                f"SELECT COUNT(*) FROM books{clause_sql}", params
            ).fetchone()[0])

            if query:
                # Ranked: the matching set is pulled and ordered by the domain's
                # own score. Bounded by RANKED_SCAN_CAP so a one-letter query
                # cannot pull a whole system into memory; the caller is told
                # when the cap bit rather than shown a silently short list.
                rows = conn.execute(
                    f"{select}{clause_sql} LIMIT ?",
                    (*params, RANKED_SCAN_CAP),
                ).fetchall()
                scored = sorted(
                    rows,
                    key=lambda r: (
                        -score(query, TextEntry(title=r["title"],
                                                author=r["author"] or "")),
                        r["norm_title"], r["id"],
                    ),
                )
                page: Sequence[sqlite3.Row] = scored[offset:offset + limit]
            else:
                rows = conn.execute(
                    f"{select}{clause_sql} ORDER BY {order} LIMIT ? OFFSET ?",
                    (*params, limit, offset),
                ).fetchall()
                page = rows

        return tuple(
            BookRow(
                id=str(r["id"]), library_id=str(r["library_id"]),
                title=r["title"], author=r["author"] or "",
                status=RANK_NAMES[int(r["rank"] or 0)],
                copy_count=int(r["copy_count"]), added_at=r["added_at"],
                shelf_count=int(r["shelf_count"]),
            )
            for r in page
        ), total

    # --- shelves ----------------------------------------------------------

    def shelves(self, library_id: str) -> tuple[ShelfRow, ...]:
        """One library's shelves, with what stands on them.

        Cross-tenant, so it cannot come from `/api/v1/shelves` — that resolves
        the caller's membership, and a system administrator is a member of
        nothing.

        ⚠ ``books`` counts DISTINCT books with a copy on the shelf, not copies:
        two copies of one book on one shelf is one book standing there, and
        the shelf screen's question is "what is on it".
        """
        with _open(self.path) as conn:
            rows = conn.execute(
                "SELECT shelves.id, shelves.library_id, shelves.label,"
                " shelves.depth_count, shelves.virtual,"
                " (SELECT COUNT(*) FROM captures"
                "   WHERE captures.shelf_id = shelves.id) AS captures,"
                " (SELECT COUNT(DISTINCT book_id) FROM copies"
                "   WHERE copies.shelf_id = shelves.id) AS books,"
                " (SELECT MAX(COALESCE(finished_at, started_at)) FROM reads"
                "   WHERE reads.shelf_id = shelves.id) AS last_read"
                " FROM shelves WHERE shelves.library_id = ?"
                " ORDER BY shelves.label, COALESCE(shelves.created_at, ''),"
                " shelves.id",
                (library_id,),
            ).fetchall()
        return tuple(
            ShelfRow(
                id=str(r["id"]), library_id=str(r["library_id"]),
                label=r["label"] or "", depth_count=int(r["depth_count"]),
                virtual=bool(r["virtual"]), captures=int(r["captures"]),
                books=int(r["books"]), last_read=r["last_read"],
            )
            for r in rows
        )

    # --- activity ---------------------------------------------------------

    def recent_reads(
        self, limit: int = 30, library_id: str | None = None,
    ) -> tuple[ReadRow, ...]:
        """The newest reads across every tenant.

        ⚠ Reported with a date and an engine mode, never a run number — §5.5
        is explicit that a run is not a user-facing concept and
        `app.domain.read.Read` has no human handle to show even here.
        """
        where = " WHERE reads.library_id = ?" if library_id else ""
        params: tuple[Any, ...] = (library_id, limit) if library_id else (limit,)
        with _open(self.path) as conn:
            rows = conn.execute(
                "SELECT reads.id, reads.library_id, reads.shelf_id, reads.depth,"
                " reads.mode, reads.status, reads.started_at, reads.finished_at,"
                " COALESCE(shelves.label, '') AS shelf_label,"
                " (SELECT COUNT(*) FROM claims WHERE claims.read_id = reads.id)"
                "   AS claims"
                " FROM reads LEFT JOIN shelves ON shelves.id = reads.shelf_id"
                f"{where}"
                " ORDER BY COALESCE(reads.started_at, '') DESC LIMIT ?",
                params,
            ).fetchall()
        return tuple(
            ReadRow(
                id=str(r["id"]), library_id=str(r["library_id"]),
                shelf_id=str(r["shelf_id"]), shelf_label=r["shelf_label"],
                depth=int(r["depth"]), mode=str(r["mode"]),
                status=str(r["status"]), started_at=r["started_at"],
                finished_at=r["finished_at"], claims=int(r["claims"]),
            )
            for r in rows
        )

