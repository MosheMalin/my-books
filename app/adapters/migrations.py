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

# --- v7: reads and claims (P2.4, §5.7 #1) ---------------------------------
#
# One engine pass over one (shelf, depth), with the claims it produced.
# `capture_ids`, `code_version` and `config` are JSON columns rather than
# normalised tables — D1 explicitly calls this shape out ("JSON columns for
# run/config snapshots"): they are document-shaped, written once per read and
# never queried by field, unlike copies/provenance which get real WHERE
# clauses (who has my books, books on a shelf). Claims DO get their own table,
# for the same reason copies/provenance do: P2.5's reconciliation and P2.6's
# copy resolution need to query them.
#
# Pure SQL, no backfill: this is a brand-new feature, so no row anywhere
# predates it.
#
# `reads.shelf_id` is indexed but NOT a foreign key, unlike `captures.shelf_id`
# — see the ⚠ in `app.ports.store.ReadStore`: a capture's shelf_id is
# client-supplied and must be policed, a read's is not (it can only be built
# from an already-loaded Shelf by `app.domain.read.new_read`), so there is no
# invalid-shelf case for a constraint to catch.
_V7 = """
CREATE TABLE reads (
    id            TEXT PRIMARY KEY,
    library_id    TEXT NOT NULL,
    shelf_id      TEXT NOT NULL,
    depth         INTEGER NOT NULL,
    capture_ids   TEXT NOT NULL,        -- JSON array, in read order
    mode          TEXT NOT NULL,
    status        TEXT NOT NULL,        -- running | done | stopped | failed
    code_version  TEXT,                 -- JSON: {sha, branch, dirty}, or NULL
    config        TEXT,                 -- JSON: full tunable snapshot, or NULL
    started_at    TEXT,
    finished_at   TEXT,
    error         TEXT
);

-- Leads with library_id like every other read index (H2); shelf_id and depth
-- follow because "this shelf's reads, optionally at one depth, newest first"
-- is the only query this table serves.
CREATE INDEX reads_by_shelf ON reads (library_id, shelf_id, depth, started_at);

CREATE TABLE claims (
    id          TEXT PRIMARY KEY,
    read_id     TEXT NOT NULL REFERENCES reads (id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,       -- the order the engine produced them
    spine_id    TEXT NOT NULL,
    capture_id  TEXT NOT NULL,
    text        TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    author      TEXT NOT NULL DEFAULT '',
    tier        TEXT NOT NULL,          -- auto | review | unmatched
    score       REAL NOT NULL DEFAULT 0,
    catalog_id  TEXT,
    crop_key    TEXT,                   -- BlobStore key, or NULL
    box         TEXT                    -- JSON [x0,y0,x1,y1], or NULL
);

CREATE INDEX claims_of_read ON claims (read_id, position);
"""

# --- v8: reconciliation decisions (P2.5, §5.4/§5.6) -----------------------
#
# One human answer, keyed by exactly where it was asked: (library, shelf,
# depth, book_key) IS the identity — not a surrogate id, because that quadruple
# is also every lookup this table ever serves (`reconcile()` asks "what was
# decided HERE", never "what was decision #N"). The composite PRIMARY KEY
# is what makes `save_decision` a plain upsert (INSERT ... ON CONFLICT) rather
# than a select-then-branch: a human changing their mind overwrites the row
# instead of accumulating a history nobody reads.
#
# Pure SQL, no backfill: this is a brand-new feature (P2.5), so no row
# anywhere predates it — same shape as v4's `lent_out` and v7's reads/claims.
#
# `book_key`, not a book id: §5.6's "previously rejected HERE" must survive
# a claim that never became a `Book` at all (the whole point of REJECTED), and
# `Book.key` is exactly the identity `reconcile()` already computes per claim
# — reusing it means this table needs no join back to `books` to be useful.
_V8 = """
CREATE TABLE decisions (
    library_id  TEXT NOT NULL,
    shelf_id    TEXT NOT NULL,
    depth       INTEGER NOT NULL,
    book_key    TEXT NOT NULL,
    kind        TEXT NOT NULL,        -- rejected | wrong_book | already_listed | another_copy
    copy_id     TEXT,
    decided_at  TEXT,
    PRIMARY KEY (library_id, shelf_id, depth, book_key)
);

-- Leads with library_id like every other table (H2); shelf_id and depth
-- follow because "every decision at this (shelf, depth)" is the only query
-- `reconcile()`'s caller ever runs against this table.
CREATE INDEX decisions_by_shelf ON decisions (library_id, shelf_id, depth);
"""

# --- v9: the durable duplicates queue (P2.6, §5.4) ------------------------
#
# One open §5.4 ask, surviving past the read that raised it. Identity is the
# SAME quadruple as `decisions` (library, shelf, depth, book_key) — a
# question and its eventual answer are two states of one fact, so answering
# it (an app.reconcile_apply write to `decisions`) deletes the matching row
# here rather than marking it resolved; there is deliberately no "closed"
# state to query, only "open or gone".
#
# Denormalised claim/book fields (`claim_title`, `claim_author`,
# `existing_book_id`, `spine_id`, `read_id`) rather than a join back to
# `claims`/`books`: the read that raised the question may be long settled by
# the time a human opens the Books tab's queue, and re-deriving "what was
# this claim about" would mean re-loading that whole read just to render one
# row. Same trade `ClaimOutcome` makes for `reconcile()`'s own callers.
#
# Pure SQL, no backfill: this is a brand-new feature (P2.6), so no row
# anywhere predates it — same shape as v4/v7/v8.
_V9 = """
CREATE TABLE duplicate_questions (
    id               TEXT NOT NULL,
    library_id       TEXT NOT NULL,
    shelf_id         TEXT NOT NULL,
    depth            INTEGER NOT NULL,
    book_key         TEXT NOT NULL,
    read_id          TEXT NOT NULL,
    spine_id         TEXT NOT NULL,
    claim_title      TEXT NOT NULL DEFAULT '',
    claim_author     TEXT NOT NULL DEFAULT '',
    existing_book_id TEXT NOT NULL,
    opened_at        TEXT NOT NULL,
    captured_at      TEXT,
    PRIMARY KEY (library_id, shelf_id, depth, book_key)
);

-- The route addresses one question by its minted `id` (P2.6's API, same
-- idiom as every other minted-id resource) — declared UNIQUE so a wiring bug
-- that reused an id would raise loudly rather than silently answering the
-- wrong question.
CREATE UNIQUE INDEX duplicate_questions_by_id ON duplicate_questions (id);

-- Leads with library_id like every other table (H2). No shelf_id in this
-- one: the Books tab's "duplicates to resolve" filter (P2.6) asks across the
-- WHOLE library — a queue entry is about a BOOK, not about which shelf
-- happens to be open — so `opened_at` ordering is what every listing uses,
-- narrowed to one shelf in Python/SQL WHERE only when a caller asks for it.
CREATE INDEX duplicate_questions_by_library
    ON duplicate_questions (library_id, opened_at, id);
"""

# --- v10: ranked alternatives on a claim (P2.7, "why?") --------------------
#
# `booksnap.match.explain()`'s ranked runners-up, computed once at read time
# (`BooksnapReader._alternatives`) and stored alongside the claim they
# explain — never recomputed on demand, because a live "why?" click against
# an NLI-backed catalog would be a second network-shaped call for every
# question a human asks (CLAUDE.md's "deterministic first" cost philosophy).
# Read time already has the catalog open for the SAME query text, so this is
# free (a disk cache hit at worst); a later on-demand endpoint would not be.
#
# Pure SQL, no backfill: rows written before this migration simply have no
# alternatives (NULL -> `()`), same as `crop_key`/`box`/`catalog_id` already
# being nullable on claims that predate P2.3's crops.
_V10 = """
ALTER TABLE claims ADD COLUMN alternatives TEXT;  -- JSON array, or NULL
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
    (7, _V7),
    (8, _V8),
    (9, _V9),
    (10, _V10),
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
