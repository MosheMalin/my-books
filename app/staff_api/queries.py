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
from app.staff_api.storage import BlobTree, Usage

#: A library whose blob directory does not exist. Zero is the true answer for a
#: tenant that has never uploaded a photograph, and it is also the answer when
#: the tree lives on another machine — see :class:`BlobTree`.
_NO_DISK = Usage()

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

#: The aggregation key for a WORK — the STORED one the product writes.
#:
#: ⚠ This was ``(norm_title || '|' || norm_author)`` for one commit, with a
#: comment claiming it avoided needing a new column. It did not: ``book_key``
#: has been a column since schema v1, written from ``Book.key`` (i.e.
#: ``app.domain.text.book_key``) on every save, carrying
#: ``UNIQUE INDEX books_library_key``, and read by the product's own
#: ``get_by_key``. Recomputing it made a FOURTH expression of one identity —
#: caught by a review, which measured that a separator change was pinned but a
#: divergence between the column and the recomputation was not. A console
#: built to be authoritative about book identity must read the same value the
#: product keys on, not a lookalike.
WORK_KEY_SQL = "books.book_key"

#: Sort keys :meth:`StaffQueries.works` understands.
#:
#: ⚠ Validated rather than silently defaulted, unlike ``books()``. The two
#: routes' keys genuinely differ — a work's date is ``first_added`` (the
#: earliest anywhere), a book's is ``recently_added`` — so a caller carrying
#: the other route's spelling would otherwise get title order and no hint,
#: which is exactly the "answers plausibly" failure this codebase keeps
#: recording about stale servers.
WORK_SORTS = ("title", "author", "first_added", "libraries")

#: How many matching rows a ranked search pulls before ordering them in Python.
#: `app/domain/search.py` documents the same linear-scan trade for ONE library
#: (measured 4ms at 251 books, 53ms at 10k); across every tenant the number is
#: bigger, so it is capped — and the cap is REPORTED to the caller, because a
#: silently truncated result set reads as "that is all there is".
RANKED_SCAN_CAP = 5000

#: Columns this module depends on, per table. Checked at startup so a schema
#: change is a refusal to serve rather than a silently wrong dashboard.
REQUIRED_COLUMNS = {
    "users": ("id", "display_name", "email", "created_at"),
    "accounts": ("id", "label", "created_at"),
    "libraries": ("id", "account_id", "label", "created_at"),
    "memberships": ("user_id", "account_id", "role", "joined_at"),
    "books": ("id", "library_id", "title", "author", "added_at", "book_key",
              "search_text", "sort_author", "norm_title", "norm_author"),
    "copies": ("id", "book_id", "library_id", "status", "shelf_id", "lent_out"),
    "shelves": ("id", "library_id", "label", "virtual", "depth_count",
                "created_at"),
    "captures": ("id", "library_id", "shelf_id", "depth", "order", "image_id",
                 "captured_at"),
    "reads": ("id", "library_id", "shelf_id", "depth", "mode", "status",
              "started_at", "finished_at", "capture_ids"),
    # ⚠ `claims` was used by `recent_reads` before it was declared here, which
    # is exactly the gap `self_check` exists to close: a renamed `claims.
    # read_id` would have surfaced as a 500 on the reads screen rather than as
    # the named refusal this dict produces.
    "claims": ("id", "read_id", "capture_id", "tier"),
    "duplicate_questions": ("id", "library_id"),
}


#: Every book in the system as an INSTANCE of a work, with the display-order
#: number that decides which spelling represents the group.
#:
#: ⚠ ``ROW_NUMBER() OVER (…)`` is the display rule, in one place. See
#: :meth:`StaffQueries.works` for the argument; changing the ``ORDER BY``
#: inside it changes which title the console shows for a work held twice.
_WORK_CTE = f"""
WITH inst AS (
    SELECT books.id AS id,
           books.library_id AS library_id,
           books.title AS title,
           books.author AS author,
           books.added_at AS added_at,
           books.norm_title AS norm_title,
           books.sort_author AS sort_author,
           books.search_text AS search_text,
           {WORK_KEY_SQL} AS work_key,
           {STATUS_RANK_SQL} AS rank,
           (SELECT COUNT(*) FROM copies WHERE copies.book_id = books.id)
             AS copy_count
    FROM books
),
picked AS (
    SELECT inst.*, ROW_NUMBER() OVER (
        PARTITION BY work_key
        ORDER BY rank DESC, COALESCE(added_at, '~') ASC, id ASC
    ) AS pick
    FROM inst
)
"""

#: The aggregate itself. ``MAX(CASE WHEN pick = 1 …)`` reads oddly and is
#: exactly right: one row per group has ``pick = 1``, so the aggregate returns
#: that row's value — SQLite's bare-column shortcut would work here too and is
#: undefined behaviour the day someone ports this.
_WORK_GROUPED = """
SELECT work_key AS key,
       MAX(CASE WHEN pick = 1 THEN title END) AS title,
       MAX(CASE WHEN pick = 1 THEN author END) AS author,
       MAX(CASE WHEN pick = 1 THEN norm_title END) AS norm_title,
       MAX(CASE WHEN pick = 1 THEN sort_author END) AS sort_author,
       MAX(rank) AS rank,
       MIN(rank) AS weakest,
       -- ⚠ `COUNT(*)` is EQUAL to this today and must not replace it: the
       -- equality holds only because `UNIQUE INDEX books_library_key` forbids
       -- one library holding a key twice. A mutation to `COUNT(*)` survives
       -- the suite for that reason (measured), so this comment is the guard —
       -- DISTINCT states the question, which is "how many libraries", not
       -- "how many rows".
       COUNT(DISTINCT library_id) AS libraries,
       SUM(copy_count) AS copies,
       MIN(added_at) AS first_added,
       MAX(added_at) AS last_added
FROM picked
GROUP BY work_key
"""


def images_sql(where: str = "") -> str:
    """One page of photographs, with what the engine made of each.

    ⚠⚠ **A module-level function, and the test EXPLAINs this exact string.**
    The two engine figures were correlated subqueries once, asked per returned
    row, each scanning every ``reads`` row in the system and expanding its
    ``capture_ids`` array. Two reviewers measured the same thing
    independently — **13.6 seconds of SQLite CPU for one ``?limit=200``** at
    4000 reads, on a service whose credential may be unset, with the route
    holding a threadpool worker for the duration. Grouped: 14ms on the same
    data. The cost is invisible in a three-row fixture, so the shape is what
    gets pinned, and it is pinned against the string that actually runs.

    ⚠ ``json_valid`` guard: ``json_each`` RAISES on a malformed array, and the
    pre-pass is not narrowed by library — so ONE tenant's bad row would blank
    the cross-tenant page for everybody. Not reachable through the product's
    write path (the column is ``NOT NULL`` and always written by
    ``json.dumps``), which is why it is a cheap guard rather than a migration.
    """
    return f"""
WITH consumed AS (
    SELECT je.value AS capture_id, COUNT(*) AS runs,
           MAX(COALESCE(reads.finished_at, reads.started_at)) AS last_read
    FROM reads, json_each(reads.capture_ids) je
    WHERE json_valid(reads.capture_ids)
    GROUP BY je.value
),
found AS (
    SELECT capture_id, COUNT(*) AS findings,
           SUM(tier = 'auto') AS auto,
           SUM(tier = 'review') AS review,
           SUM(tier = 'unmatched') AS unmatched
    FROM claims GROUP BY capture_id
)
SELECT captures.id, captures.library_id, captures.shelf_id,
       captures.depth, captures."order" AS ord, captures.image_id,
       captures.captured_at,
       COALESCE(shelves.label, '') AS shelf_label,
       COALESCE(found.findings, 0) AS findings,
       COALESCE(found.auto, 0) AS auto,
       COALESCE(found.review, 0) AS review,
       COALESCE(found.unmatched, 0) AS unmatched,
       COALESCE(consumed.runs, 0) AS reads,
       consumed.last_read AS last_read
FROM captures
LEFT JOIN shelves ON shelves.id = captures.shelf_id
LEFT JOIN consumed ON consumed.capture_id = captures.id
LEFT JOIN found ON found.capture_id = captures.id
{where}
-- Newest photograph first; `id` breaks the tie so paging is stable when a
-- phone uploads a burst carrying one timestamp.
ORDER BY COALESCE(captures.captured_at, '') DESC, captures.id DESC
LIMIT ? OFFSET ?
"""


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
    account_id: str
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
    #: Files and bytes under this library's blob directory — everything the
    #: disk holds, renditions included. See :mod:`app.staff_api.storage`.
    image_files: int = 0
    image_bytes: int = 0


@dataclass(frozen=True)
class AccountRow:
    """One CUSTOMER, with every figure summed across the libraries it owns.

    ⚠ This is the row the console has been drawing since revision 4 while
    calling a `LibraryRow` an "account". The gloss was right when a library
    WAS the tenant; since P3.7b it is not, and a customer owning two
    collections was being drawn as two customers. Every number here is the
    sum over its libraries — which is the same number as before for the
    common one-library account, and the correct one for the rest.
    """

    id: str
    label: str
    created_at: str | None
    libraries: int
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
    image_files: int = 0
    image_bytes: int = 0


@dataclass(frozen=True)
class MembershipRow:
    user_id: str
    account_id: str
    role: str
    joined_at: str | None


@dataclass(frozen=True)
class UserRow:
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
class WorkRow:
    """One book ACROSS every tenant — the console's unit since revision 4.

    ``key`` is :data:`WORK_KEY_SQL`'s value, i.e. ``app.domain.text.book_key``.
    ``title``/``author`` are the DISPLAY spelling, chosen by the rule in
    :meth:`StaffQueries.works` — two households may hold one work under two
    spellings that normalize alike, which is the whole point of the key.
    """

    key: str
    title: str
    author: str
    status: str
    mixed: bool
    libraries: int
    copies: int
    first_added: str | None
    last_added: str | None


@dataclass(frozen=True)
class ImageRow:
    """One photograph, and what has been made of it.

    ⚠ **The image is the entity; the shelf is a BINDING it currently has.**
    VISION §4.1a records that "one image = one shelf" is a placeholder with an
    exit (P2.1) — intake mints a shelf identity per photograph until pillar 6's
    map can say two photographs are the same piece of wood. A console listing
    shelves is therefore mostly listing photographs under a noun they have not
    earned, which is why this row leads with the image and reports
    ``shelf_id``/``depth`` as the slot it is filed at.

    The engine figures come from the CLAIM side, because that is where the data
    actually binds: ``claims.capture_id`` names the photograph a finding came
    from, and ``reads.capture_ids`` names the photographs a run consumed.
    """

    id: str
    library_id: str
    image_key: str | None
    captured_at: str | None
    # the binding (pillar 6 replaces this pair with a real address)
    shelf_id: str
    shelf_label: str
    depth: int
    order: int
    # the bytes
    present: bool
    bytes: int
    width: int
    height: int
    content_type: str
    filename: str
    # what the engine made of it
    reads: int
    findings: int
    auto: int
    review: int
    unmatched: int
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


def _work_row(r: sqlite3.Row) -> WorkRow:
    """One grouped row as a :class:`WorkRow`.

    ``mixed`` is the honest half of a single status badge: a work held as
    `manual` in one house and `auto` in another has no one status, and a
    console that showed only the strongest would tell an operator hunting for
    unapproved books that there are none.
    """
    strongest, weakest = int(r["rank"] or 0), int(r["weakest"] or 0)
    return WorkRow(
        key=str(r["key"]), title=r["title"] or "", author=r["author"] or "",
        status=RANK_NAMES[strongest], mixed=strongest != weakest,
        libraries=int(r["libraries"]), copies=int(r["copies"] or 0),
        first_added=r["first_added"], last_added=r["last_added"],
    )


class StaffQueries:
    """Every cross-tenant question the console asks, in one place."""

    def __init__(self, db_path: str | Path, blobs: BlobTree | None = None,
                 scan_cap: int = RANKED_SCAN_CAP) -> None:
        self.path = Path(db_path)
        # ⚠ Injectable ONLY so a test can reach it. `RANKED_SCAN_CAP` is 5000
        # and a fixture will never seed that many rows, so the determinism the
        # capped scan was fixed for had no gate — a review measured both
        # `ORDER BY`s removable with the suite green.
        self.scan_cap = scan_cap
        if not self.path.exists():
            raise FileNotFoundError(
                f"no product database at {self.path}; set BOOKSNAP_DB"
            )
        # ⚠ Defaulting to an UNCONFIGURED tree rather than to the product's
        # default location. Guessing would make a console pointed at one
        # machine's database report another machine's disk; an absent tree
        # reports zero and the composition root is the one place that decides
        # where the bytes are.
        self.blobs = blobs if blobs is not None else BlobTree(None)
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
        # One walk of the blob tree, outside the connection: the database and
        # the disk answer different halves of "how big is this system", and
        # neither knows the other's number.
        disk = self.blobs.usage()
        with _open(self.path) as conn:
            def count(sql: str) -> int:
                return int(conn.execute(sql).fetchone()[0])

            by_rank = dict(conn.execute(
                f"SELECT {STATUS_RANK_SQL} AS rank, COUNT(*) FROM books"
                " GROUP BY rank"
            ).fetchall())
            return {
                # ⚠ Three different counts that used to be two. `accounts`
                # is CUSTOMERS, `users` is PEOPLE, `libraries` is
                # collections — and until P3.7b the console rendered the
                # third under the first's label because they were the same
                # thing. They are not, and an operator reading "12
                # accounts" when it means 12 collections of 4 customers is
                # reading the wrong business.
                "accounts": count("SELECT COUNT(*) FROM accounts"),
                "users": count("SELECT COUNT(*) FROM users"),
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
                # ⚠ Summed over the WHOLE tree, including directories no
                # library row matches. Bytes belonging to a deleted tenant
                # still occupy the disk, and a total that omitted them would
                # be wrong in the one direction an operator cares about.
                "image_files": sum(u.files for u in disk.values()),
                "image_bytes": sum(u.bytes for u in disk.values()),
                # Three states, not two — see `BlobTree.visible`. Zero storage
                # and "the disk is on another machine" look identical, and
                # only one of them is a reason to go looking.
                "blobs_visible": int(self.blobs.visible),
                # An account with members but NO admin: nobody can invite,
                # re-role, rename or delete. `new_account` mints the admin
                # in the same call precisely so this stays zero, and
                # `NoAdminLeft` refuses the last demotion — so a number
                # here is a bug that already happened, and only a system
                # console can see it.
                "accounts_without_admin": count(
                    "SELECT COUNT(*) FROM accounts WHERE id IN"
                    " (SELECT account_id FROM memberships)"
                    " AND id NOT IN (SELECT account_id FROM memberships"
                    " WHERE role = 'admin')"
                ),
            }

    # --- libraries --------------------------------------------------------

    def libraries(self) -> tuple[LibraryRow, ...]:
        """Every library in the system, with its numbers.

        One grouped query per figure and a join in Python, rather than one
        query per library: the point of this service is that "how big is
        everything" costs a bounded number of round trips.
        """
        disk = self.blobs.usage()
        with _open(self.path) as conn:
            base = conn.execute(
                "SELECT id, account_id, label, created_at FROM libraries"
                " ORDER BY label, COALESCE(created_at, ''), id"
            ).fetchall()

            def grouped(sql: str) -> dict[str, int]:
                return {str(r[0]): int(r[1]) for r in conn.execute(sql).fetchall()}

            # ⚠ People reach a library THROUGH its owning account since
            # P3.7b, so both counts join `libraries` — a member count read
            # straight off `memberships` would be a count per customer
            # silently labelled per library, and the two differ exactly when
            # an account owns more than one.
            members = grouped(
                "SELECT l.id, COUNT(*) FROM libraries l JOIN memberships m"
                " ON m.account_id = l.account_id GROUP BY l.id")
            admins = grouped(
                "SELECT l.id, COUNT(*) FROM libraries l JOIN memberships m"
                " ON m.account_id = l.account_id WHERE m.role = 'admin'"
                " GROUP BY l.id")
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
                id=lid, account_id=str(row["account_id"]),
                label=row["label"] or "", created_at=row["created_at"],
                members=members.get(lid, 0), admins=admins.get(lid, 0),
                books=books.get(lid, 0), copies=copies.get(lid, 0),
                auto=status.get(0, 0), approved=status.get(1, 0),
                manual=status.get(2, 0),
                shelves=shelves.get(lid, 0), captures=captures.get(lid, 0),
                reads=reads.get(lid, 0), duplicates=dupes.get(lid, 0),
                lent_out=lent.get(lid, 0), last_activity=activity.get(lid),
                image_files=disk.get(lid, _NO_DISK).files,
                image_bytes=disk.get(lid, _NO_DISK).bytes,
            ))
        return tuple(out)

    # --- accounts ---------------------------------------------------------

    def accounts(self) -> tuple[AccountRow, ...]:
        """Every customer in the system, with its libraries' figures summed.

        Built by FOLDING :meth:`libraries` rather than by a second set of
        grouped queries. Two reasons, and the second is the load-bearing one:
        the per-library numbers are already one grouped pass each (the shape
        that replaced a correlated subquery per row after `/images` measured
        13.6s), so folding them costs a dictionary; and a customer's totals
        that were computed independently of its libraries' totals is exactly
        the pair that drifts, leaving an operator with two screens that
        disagree about the same books.

        An account owning no library still appears, with zeroes — the state
        P4.3's invite flow can produce, and one nothing else would show.
        """
        by_account: dict[str, list[LibraryRow]] = {}
        for row in self.libraries():
            by_account.setdefault(row.account_id, []).append(row)

        with _open(self.path) as conn:
            base = conn.execute(
                "SELECT id, label, created_at FROM accounts"
                " ORDER BY label, COALESCE(created_at, ''), id"
            ).fetchall()
            members = {str(r[0]): int(r[1]) for r in conn.execute(
                "SELECT account_id, COUNT(*) FROM memberships"
                " GROUP BY account_id")}
            admins = {str(r[0]): int(r[1]) for r in conn.execute(
                "SELECT account_id, COUNT(*) FROM memberships"
                " WHERE role = 'admin' GROUP BY account_id")}

        out = []
        for row in base:
            aid = str(row["id"])
            libs = by_account.get(aid, [])
            seen = [lib.last_activity for lib in libs if lib.last_activity]
            out.append(AccountRow(
                id=aid, label=row["label"] or "", created_at=row["created_at"],
                libraries=len(libs),
                members=members.get(aid, 0), admins=admins.get(aid, 0),
                books=sum(lib.books for lib in libs),
                copies=sum(lib.copies for lib in libs),
                auto=sum(lib.auto for lib in libs),
                approved=sum(lib.approved for lib in libs),
                manual=sum(lib.manual for lib in libs),
                shelves=sum(lib.shelves for lib in libs),
                captures=sum(lib.captures for lib in libs),
                reads=sum(lib.reads for lib in libs),
                duplicates=sum(lib.duplicates for lib in libs),
                lent_out=sum(lib.lent_out for lib in libs),
                last_activity=max(seen) if seen else None,
                image_files=sum(lib.image_files for lib in libs),
                image_bytes=sum(lib.image_bytes for lib in libs),
            ))
        return tuple(out)

    # --- people -----------------------------------------------------------

    def users(self) -> tuple[UserRow, ...]:
        """Every user, with every membership they hold.

        ⚠ This is the screen that did not exist before, and could not: the
        product API answers "which libraries may *I* name", never "who is in
        the system". It is also the one to be careful with — see the router's
        note on what a system administrator should and should not be able to
        read about a household.
        """
        with _open(self.path) as conn:
            rows = conn.execute(
                "SELECT id, display_name, email, created_at FROM users"
                " ORDER BY COALESCE(created_at, ''), id"
            ).fetchall()
            memberships = conn.execute(
                "SELECT user_id, account_id, role, joined_at FROM memberships"
                " ORDER BY user_id, account_id"
            ).fetchall()

        held: dict[str, list[MembershipRow]] = {}
        for m in memberships:
            held.setdefault(str(m["user_id"]), []).append(MembershipRow(
                user_id=str(m["user_id"]), account_id=str(m["account_id"]),
                role=str(m["role"]), joined_at=m["joined_at"],
            ))
        return tuple(
            UserRow(
                id=str(r["id"]), display_name=r["display_name"] or "",
                email=r["email"], created_at=r["created_at"],
                memberships=tuple(held.get(str(r["id"]), ())),
            )
            for r in rows
        )

    def orphan_libraries(self) -> tuple[str, ...]:
        """Libraries whose OWNING ACCOUNT has no member at all.

        Not a curiosity: a library nobody can administer or even see is
        exactly the state `new_account` exists to prevent, by minting the
        admin membership in the same call that makes the account. A system
        console is the only place it is visible.

        ⚠ The question changed shape at P3.7b and kept its meaning. It used to
        be "no membership names this library"; a membership now names an
        account, so it is "no membership names this library's owner". Reading
        it the old way is not possible any more (there is no `library_id` on
        `memberships`), which is the good kind of breakage — the alternative
        was a query that still ran and quietly answered a different question.
        """
        with _open(self.path) as conn:
            rows = conn.execute(
                "SELECT id FROM libraries WHERE account_id NOT IN"
                " (SELECT account_id FROM memberships)"
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
        if q.strip() and not query:
            # See `works()`: empty terms means "match nothing", never "match
            # everything". The product's own store already answers that way.
            return (), 0
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
                    # Deterministic slice — see `works()` for the argument.
                    f"{select}{clause_sql} ORDER BY books.id LIMIT ?",
                    (*params, self.scan_cap),
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

    # --- works (books, aggregated across every tenant) ---------------------

    def works(
        self,
        *,
        q: str = "",
        library_id: str | None = None,
        status: str | None = None,
        sort: str = "title",
        ascending: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[tuple[WorkRow, ...], int]:
        """One row per BOOK, across every tenant. Returns ``(page, total)``.

        ⚠⚠ **Every narrowing here is a ``HAVING``, never a ``WHERE``, and that
        is the whole design.** A filter selects which WORKS appear; it must not
        change what each of them REPORTS. Filtering instances in the ``WHERE``
        would make "in 3 libraries" read "in 1 library" the moment the operator
        narrowed to one library or one status — a number that changes meaning
        when you filter is a number nobody can trust, and the console's central
        column is exactly that number.

        ⚠ **While `q` ranks, `sort` and `ascending` are ignored** — relevance
        IS the order. The console's control goes inert and reads "relevance"
        for that reason; a caller that is not the console should know it too.

        ⚠ **Cost**: two passes over `books` per call (one for `total`, one for
        the page), each a group-sort over every row. Measured by a review:
        8ms at 175 books, 158ms at 3.5k, 2.8s at 70k. The owner's real data is
        251 books. The lever, when one is needed, is caching `total` or
        materialising the aggregate — NOT rewriting the correlated subqueries,
        which were measured at 11% of it.

        ⚠ **The display title is a choice, not a fact.** Two households may
        hold one work under two spellings that normalize alike — that is what
        the key is FOR — so one has to be shown. The rule: the strongest §5.1
        status first (a human typed `manual`; the engine guessed `auto`), then
        the earliest ``added_at``, then the id. Written into the window
        function in :data:`_WORK_CTE` and pinned by a test, so it cannot decay
        into "whatever SQLite happened to return first".
        """
        if status is not None and status not in RANK_NAMES:
            raise ValueError(f"unknown status {status!r}")
        if sort not in WORK_SORTS:
            raise ValueError(f"unknown sort {sort!r}")

        having: list[str] = []
        params: list[Any] = []
        # `SUM(CASE …) > 0` is "at least one instance satisfies this". Spelled
        # out rather than EXISTS so all three filters read the same way.
        if library_id:
            having.append("SUM(CASE WHEN library_id = ? THEN 1 ELSE 0 END) > 0")
            params.append(library_id)
        if status is not None:
            having.append("SUM(CASE WHEN rank = ? THEN 1 ELSE 0 END) > 0")
            params.append(RANK_NAMES.index(status))

        query = parse(q) if q.strip() else None
        if q.strip() and not query:
            # ⚠ A query that parses to no terms means "match nothing", never
            # "match everything" — `app/domain/search.py` says so and the
            # product's own store honours it. Without this line a search box
            # fed one punctuation character answers with the entire system,
            # and (because the ranked path never runs) reports it as
            # truncated. Found by a review, which measured `q="!!!"` returning
            # every book here while the product returned none.
            return (), 0
        if query:
            # ⚠ `search_text` is derived from the same normalized pair as the
            # key (`app/domain/search.py:haystack`), so every instance of one
            # work carries a byte-identical haystack: matching per instance and
            # matching the group are equivalent here, and neither can find a
            # "different spelling" — there is no such thing at this column.
            # Written as a HAVING anyway so all three narrowings read the same
            # way, and so it stays correct if `search_text` ever grows a
            # per-instance term (a subtitle, a publisher).
            clause, like_params = compile_sql_like(query, "search_text")
            if clause:
                having.append(
                    f"SUM(CASE WHEN ({clause}) THEN 1 ELSE 0 END) > 0")
                params.extend(like_params)

        having_sql = (" HAVING " + " AND ".join(having)) if having else ""
        direction = "ASC" if ascending else "DESC"
        order = {
            "title": f"norm_title {direction}, key {direction}",
            "author": f"sort_author {direction}, norm_title {direction},"
                      f" key {direction}",
            "first_added": f"COALESCE(first_added, '') {direction},"
                           f" norm_title ASC, key ASC",
            # "in how many libraries" — the question this screen exists to
            # answer, so it is a sort key and not only a column.
            "libraries": f"libraries {direction}, norm_title ASC, key ASC",
        }[sort]

        grouped = f"{_WORK_CTE}{_WORK_GROUPED}{having_sql}"

        with _open(self.path) as conn:
            total = int(conn.execute(
                f"{_WORK_CTE}SELECT COUNT(*) FROM ({_WORK_GROUPED}"
                f"{having_sql})", params,
            ).fetchone()[0])

            if query:
                # Ranked, like `books()`: the domain's own score decides the
                # order, bounded by the same cap so a one-letter query cannot
                # pull a whole system into memory.
                # ⚠ `ORDER BY key` inside the CAP, though Python re-sorts by
                # score straight after. Without it the LIMIT takes an
                # unspecified slice of the grouped set: which works get ranked
                # at all is then whatever the planner chose, and a review
                # measured the exact-title hit vanishing from page 1.
                #
                # ⚠ Removing it is an EQUIVALENT MUTANT today (measured):
                # SQLite's GROUP BY happens to emit rows in grouping-key order,
                # so the slice is the same either way and no test can tell.
                # It stays because "happens to" is not a contract — the day the
                # aggregate grows an index-driven plan, or moves to another
                # engine, the slice changes and nothing would have said so.
                # Deterministic is not the same as correct: the best match can
                # still be outside the cap, which is what `truncated` says.
                rows = conn.execute(f"{grouped} ORDER BY key LIMIT ?",
                                    (*params, self.scan_cap)).fetchall()
                page: Sequence[sqlite3.Row] = sorted(
                    rows,
                    key=lambda r: (
                        -score(query, TextEntry(title=r["title"],
                                                author=r["author"] or "")),
                        r["norm_title"], r["key"],
                    ),
                )[offset:offset + limit]
            else:
                page = conn.execute(
                    f"{grouped} ORDER BY {order} LIMIT ? OFFSET ?",
                    (*params, limit, offset),
                ).fetchall()

        return tuple(_work_row(r) for r in page), total

    def work_instances(self, key: str) -> tuple[BookRow, ...]:
        """Every household's copy of ONE work, strongest claim first.

        The other half of the aggregate: the row says "in 3 libraries", this
        says which three and what each of them holds. Ordered by the same rule
        that picks the display title, so the first row here is the one the
        aggregate is named after.

        ⚠ Matched on the composed key rather than by splitting it: a title
        containing the separator would make ``key.split('|')`` wrong, and there
        is nothing stopping one.
        """
        with _open(self.path) as conn:
            rows = conn.execute(
                "SELECT books.id, books.library_id, books.title, books.author,"
                " books.added_at,"
                f" {STATUS_RANK_SQL} AS rank,"
                " (SELECT COUNT(*) FROM copies WHERE copies.book_id = books.id)"
                "   AS copy_count,"
                " (SELECT COUNT(DISTINCT shelf_id) FROM copies"
                "   WHERE copies.book_id = books.id AND shelf_id IS NOT NULL)"
                "   AS shelf_count"
                f" FROM books WHERE {WORK_KEY_SQL} = ?"
                " ORDER BY rank DESC, COALESCE(books.added_at, '~') ASC,"
                " books.id ASC",
                (key,),
            ).fetchall()
        return tuple(
            BookRow(
                id=str(r["id"]), library_id=str(r["library_id"]),
                title=r["title"], author=r["author"] or "",
                status=RANK_NAMES[int(r["rank"] or 0)],
                copy_count=int(r["copy_count"]), added_at=r["added_at"],
                shelf_count=int(r["shelf_count"]),
            )
            for r in rows
        )

    # --- images -------------------------------------------------------------

    def images(
        self, *, library_id: str | None = None, limit: int = 50,
        offset: int = 0,
    ) -> tuple[tuple[ImageRow, ...], int]:
        """Photographs across every tenant, newest first. ``(page, total)``.

        ⚠ **Two sources, joined per row.** The database knows a capture's
        identity, its binding and what the engine made of it; the disk knows
        how many bytes it is. Neither knows the other's half, so the sidecars
        are read for the PAGE only — 25 small reads, not one per capture in the
        system.

        ⚠ **`reads` counts runs that CONSUMED this photograph**, from
        ``reads.capture_ids``, while the tier figures count findings from
        ``claims.capture_id``. Those are genuinely different questions and a
        run that produced nothing from an image is exactly the case an operator
        is looking for, so the run count may not be derived from the claims.

        ⚠⚠ **Both engine figures are GROUPED pre-passes, never correlated
        subqueries.** The first version asked each of them per returned row,
        and each inner query scanned every ``reads`` row in the system and
        expanded its ``capture_ids`` array: two reviewers measured the same
        thing independently — **13.6 seconds of SQLite CPU for one
        ``?limit=200``** at 4000 reads, on a service whose credential may be
        unset. One unauthenticated request per threadpool worker took the
        console down. The grouped form measured 2.6s → 14ms on the same data.
        """
        where = " WHERE captures.library_id = ?" if library_id else ""
        narrow: tuple[Any, ...] = (library_id,) if library_id else ()

        with _open(self.path) as conn:
            total = int(conn.execute(
                f"SELECT COUNT(*) FROM captures{where}", narrow).fetchone()[0])
            rows = conn.execute(images_sql(where),
                                (*narrow, limit, offset)).fetchall()

        out = []
        for r in rows:
            facts = self.blobs.facts(str(r["library_id"]), r["image_id"])
            out.append(ImageRow(
                id=str(r["id"]), library_id=str(r["library_id"]),
                image_key=r["image_id"], captured_at=r["captured_at"],
                shelf_id=str(r["shelf_id"]), shelf_label=r["shelf_label"],
                depth=int(r["depth"]), order=int(r["ord"]),
                present=facts.present, bytes=facts.bytes,
                width=facts.width, height=facts.height,
                content_type=facts.content_type, filename=facts.filename,
                reads=int(r["reads"]), findings=int(r["findings"]),
                auto=int(r["auto"]), review=int(r["review"]),
                unmatched=int(r["unmatched"]), last_read=r["last_read"],
            ))
        return tuple(out), total

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

