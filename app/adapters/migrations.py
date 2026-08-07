# -*- coding: utf-8 -*-
"""Versioned schema migrations. Code, and tested (plan H6).

A runner from the FIRST schema, not from the first schema change — retrofitting
one means the first production database is the one with no upgrade path, and
that database is the one holding the owner's 251 real books.

Mechanism is SQLite's own ``PRAGMA user_version``: an integer in the file
header, so there is no bookkeeping table and no chance of the bookkeeping and
the schema disagreeing. Each step runs once, in order, inside a transaction.

Rules for adding a step:
  - APPEND, never edit a shipped one. An edited step has already run on the
    owner's file and will never run again;
  - each step is idempotent-by-version, not idempotent-by-SQL — the runner
    guarantees once-only, so ``CREATE TABLE`` needs no ``IF NOT EXISTS``
    (and shouldn't have it: it would hide a real ordering bug);
  - a step is SQL text OR a callable taking the connection. Reach for a
    callable only when the data being written is DERIVED by a rule that lives
    in the domain — restating that rule in SQL is how the two copies drift.
"""
from __future__ import annotations

import sqlite3
from typing import Callable

Step = Callable[[sqlite3.Connection], None]

# --- v1: books, copies, provenance ---------------------------------------
#
# Shape from VISION §5.2. Copies and provenance are real tables rather than
# JSON on the book row because they get QUERIED — "who has my books" (P1.7),
# books on a shelf (P2.5), "not seen in the last 3 reads" (§5.6). D1's "JSON
# columns" note is about run/config snapshots, which are document-shaped; this
# is not.
_V1 = """
CREATE TABLE books (
    id             TEXT PRIMARY KEY,
    library_id     TEXT NOT NULL,
    title          TEXT NOT NULL,
    author         TEXT NOT NULL DEFAULT '',
    norm_title     TEXT NOT NULL,
    norm_author    TEXT NOT NULL,
    book_key       TEXT NOT NULL,
    shared_book_id TEXT,
    rating         INTEGER,
    notes          TEXT NOT NULL DEFAULT '',
    read_status    TEXT,
    added_at       TEXT
);

-- §5.1: one Book per {title, author} PER LIBRARY. Declaring it in the schema
-- means a bug in the app cannot produce two, and the store can turn the
-- constraint violation into a decision (merge?) instead of a silent overwrite.
CREATE UNIQUE INDEX books_library_key ON books (library_id, book_key);

-- Every read index leads with library_id: a tenant-scoped query must never
-- have to scan another tenant's rows to skip them.
CREATE INDEX books_by_title  ON books (library_id, norm_title, id);
CREATE INDEX books_by_author ON books (library_id, norm_author, norm_title, id);
CREATE INDEX books_by_added  ON books (library_id, added_at, id);

CREATE TABLE copies (
    id          TEXT PRIMARY KEY,
    book_id     TEXT NOT NULL REFERENCES books (id) ON DELETE CASCADE,
    library_id  TEXT NOT NULL,
    position    INTEGER NOT NULL,       -- copy #1 is the original (§5.1 order)
    status      TEXT NOT NULL,          -- auto | approved | manual
    label       TEXT NOT NULL DEFAULT '',
    shelf_id    TEXT,                   -- NULL = removed from shelf, not deleted
    tags        TEXT NOT NULL DEFAULT '[]',
    condition   TEXT NOT NULL DEFAULT '',
    acquired_at TEXT,
    lending     TEXT                    -- JSON, or NULL when never lent
);

CREATE INDEX copies_of_book   ON copies (book_id, position);
CREATE INDEX copies_by_shelf  ON copies (library_id, shelf_id);

CREATE TABLE provenance (
    copy_id     TEXT NOT NULL REFERENCES copies (id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    run_id      TEXT NOT NULL,
    spine_id    TEXT NOT NULL,
    shelf_id    TEXT,
    captured_at TEXT,
    PRIMARY KEY (copy_id, seq)
);

-- Idempotent appends (§5.2): the same (run, spine) may be replayed and must
-- not inflate a copy's history. The domain enforces it too; this makes it
-- impossible rather than merely correct.
CREATE UNIQUE INDEX provenance_sighting ON provenance (copy_id, run_id, spine_id);
"""

# --- v2: the search haystack (P1.5) --------------------------------------
#
# A stored column rather than `norm_title || ' | ' || norm_author` computed in
# the query, for two reasons: the concatenation format then lives in exactly
# one place (`app.domain.search.haystack`, written at insert time, so Python
# and SQL cannot disagree), and a Postgres adapter can put a GIN trigram index
# on a real column.
#
# NO index here on purpose. The predicate is `LIKE '%term%'`, and a leading
# wildcard cannot use a B-tree — an index would cost write time and buy
# nothing. Measured: a full scan of the owner's 251 books is well under a
# millisecond (see tools/search_eval.py --bench). The engine-specific answer
# (trigram/GIN on PG, FTS5 on SQLite) belongs in the adapter that needs it,
# not in the shared schema.
_V2 = """
ALTER TABLE books ADD COLUMN search_text TEXT NOT NULL DEFAULT '';
UPDATE books SET search_text = norm_title || ' | ' || norm_author;
"""

# --- v3: the surname sort key (§6 "sort by author") ----------------------
#
# Stored, like search_text, and for the same reason: the rule lives in exactly
# one place (`app.domain.text.author_sort_key`), written at insert time, so
# Python and SQL cannot disagree. Unlike search_text it CANNOT be backfilled
# in SQL — "the last word, unless there is a comma" is not expressible in
# SQLite without a user function, and defining one here would put a second
# copy of the rule in this file. So this step is a CALLABLE.
#
# The index mirrors books_by_author: every read index leads with library_id.
def _v3(conn: sqlite3.Connection) -> None:
    from app.domain.text import author_sort_key

    conn.execute("ALTER TABLE books ADD COLUMN sort_author TEXT NOT NULL"
                 " DEFAULT ''")
    rows = conn.execute("SELECT id, author FROM books").fetchall()
    conn.executemany(
        "UPDATE books SET sort_author = ? WHERE id = ?",
        [(author_sort_key(author), book_id) for book_id, author in rows],
    )
    conn.execute("CREATE INDEX books_by_sort_author ON books"
                 " (library_id, sort_author, norm_title, id)")


# --- v4: "who has my books" (P1.7, §5.2) ----------------------------------
#
# A materialized `lent_out` flag rather than filtering on the `lending` JSON
# blob at query time. SQLite's json1 extension is not guaranteed present in
# every Python build, and even where it is, computing `is_out` (`lending IS
# NOT NULL AND json_extract(lending,'$.returned_at') IS NULL`) on every row of
# every query is the same class of cost search_text/sort_author were added to
# avoid — pay it once, at write time.
#
# Pure SQL, unlike v3: no backfill needed. Every row at v3 predates lending
# (P1.7 is the feature that introduces it), so `DEFAULT 0` is already the
# correct value for all of them — there is nothing to compute from existing
# data.
_V4 = """
ALTER TABLE copies ADD COLUMN lent_out INTEGER NOT NULL DEFAULT 0;
CREATE INDEX copies_lent_out ON copies (library_id, lent_out);
"""

# --- v5: shelf identity and captures (P2.1, §5.3/§5.7) --------------------
#
# No place, no bookcase, no col, no level — those are the shelf ADDRESS and
# they arrive with the map in pillar 6 (plan §1.1). What is here is identity:
# an id, a label the owner types, and the declared depth_count.
#
# `depth` lands on copies and provenance in the same step because a location is
# `(shelf, depth)` together (§5.7). Pure SQL and no backfill: every row at v4
# predates shelves entirely — the 251 imported books have `shelf_id IS NULL`,
# and the domain's rule is that an unlocated copy has no depth, so NULL is
# already correct for all of them. (Contrast v3, which had to be a callable
# because its column was DERIVED from data that already existed.)
#
# `virtual` is the wishlist. It is a column on shelves rather than a separate
# table because it is the same thing with one fact different — a table would
# duplicate every query below it.
_V5 = """
CREATE TABLE shelves (
    id          TEXT PRIMARY KEY,
    library_id  TEXT NOT NULL,
    label       TEXT NOT NULL,
    depth_count INTEGER NOT NULL DEFAULT 1,
    virtual     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT
);

-- Leads with library_id like every other read index, and carries `virtual`
-- because excluding the wishlist is the DEFAULT of every shelf listing, not
-- an occasional filter.
CREATE INDEX shelves_by_label ON shelves (library_id, virtual, label, id);

CREATE TABLE captures (
    id          TEXT NOT NULL PRIMARY KEY,
    shelf_id    TEXT NOT NULL REFERENCES shelves (id) ON DELETE CASCADE,
    library_id  TEXT NOT NULL,
    depth       INTEGER NOT NULL DEFAULT 1,
    "order"     INTEGER NOT NULL DEFAULT 0,
    image_id    TEXT,
    captured_at TEXT
);

-- §5.3 gives a capture its identity as (shelf, depth, order); declaring it
-- means two photos cannot claim the same slot of the same row, which is what
-- would make a shelf's book order ambiguous.
CREATE UNIQUE INDEX captures_slot ON captures (shelf_id, depth, "order");
CREATE INDEX captures_of_shelf ON captures (library_id, shelf_id, depth, "order");

ALTER TABLE copies ADD COLUMN depth INTEGER;
ALTER TABLE provenance ADD COLUMN depth INTEGER;

-- The location index is (shelf_id, depth), not shelf_id alone: §5.7 #1 scopes
-- the not-seen rule to the depth that was read, so "the books at this row" is
-- the query P2.3 runs, and answering it from a shelf-only index would scan
-- every row of a stacked shelf to throw most of them away.
CREATE INDEX copies_by_location ON copies (library_id, shelf_id, depth);
"""

# --- v6: shelf labels are optional, so created_at orders them -------------
#
# The owner's call (2026-08-07): a shelf's identity is FREE — it must exist and
# be re-findable, not be described. Naming one is optional and an unnamed shelf
# is shown by the image it came from.
#
# No column change is needed for that. `label TEXT NOT NULL` already accepts
# '', which is what an unnamed shelf stores, and every insert supplies the
# column — so the missing DEFAULT is unreachable. What DOES change is the
# order: with most early shelves sharing the empty label, `(… label, id)` sorts
# them by an id that means nothing to the reader. `created_at` at least matches
# the order they were photographed in.
#
# ⚠ This is a SEPARATE step rather than an edit to v5, even though v5 shipped
# only on its own branch — because "shipped" turned out to include the owner's
# real work/product.db. Anything that imports `app.main` (the composition root)
# opens it and migrates it, and `tools/api_contract.py` imports `app.main`. So
# running the contract check is enough to advance the real database, and an
# edited v5 would never re-run on it.
_V6 = """
DROP INDEX shelves_by_label;
CREATE INDEX shelves_by_label
    ON shelves (library_id, virtual, label, created_at, id);
"""

# A step is either SQL to execute or a callable to run — both inside the same
# once-only transaction. Callables exist because a derived column whose rule
# lives in the domain must be backfilled BY that rule, not by a re-statement
# of it in SQL.
MIGRATIONS: tuple[tuple[int, str | Step], ...] = (
    (1, _V1),
    (2, _V2),
    (3, _v3),
    (4, _V4),
    (5, _V5),
    (6, _V6),
)

SCHEMA_VERSION = MIGRATIONS[-1][0]


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Bring ``conn`` up to :data:`SCHEMA_VERSION`. Returns the new version.

    Safe to call on every connect: already-applied steps are skipped, so this
    is how the store guarantees a usable file without a separate setup command
    someone can forget to run.
    """
    version = current_version(conn)
    for target, step in MIGRATIONS:
        if target <= version:
            continue
        with conn:  # one transaction per step
            if isinstance(step, str):
                conn.executescript(step)
            else:
                step(conn)
            # PRAGMA does not take bound parameters; `target` is an int from
            # this module's own tuple, never from input.
            conn.execute(f"PRAGMA user_version = {int(target)}")
        version = target
    return version
