# -*- coding: utf-8 -*-
"""Versioned schema migrations. Code, and tested (plan H6).

A runner from the FIRST schema, not from the first schema change — retrofitting
one means the first production database is the one with no upgrade path, and
that database is the one holding the owner's 251 real books.

Mechanism is SQLite's own ``PRAGMA user_version``: an integer in the file
header, so there is no bookkeeping table and no chance of the bookkeeping and
the schema disagreeing. Each step runs once, in order.

**The runner owns the transaction (P4.0a).** The ENTIRE pending upgrade —
every not-yet-applied step and its ``PRAGMA user_version`` bump — runs inside
one explicit ``BEGIN IMMEDIATE`` … ``COMMIT``. Three properties, each closing
a hole recorded in planning/TENANCY_BOUNDARY_PLAN.md ("Found on the way"):

  - **atomic**: a crash anywhere rolls the file back to the version it
    STARTED at — never half-upgraded at the old number. String steps are
    split into statements and executed one at a time; ``executescript`` is
    banned in the runner because it issues an implicit COMMIT before it
    starts and then autocommits as it goes (measured, P3.7a — and a callable
    was no safer: Python's ``sqlite3`` opens an implicit transaction for DML
    only, so bare DDL in a callable also autocommitted);
  - **exclusive across processes**: ``BEGIN IMMEDIATE`` takes SQLite's write
    lock BEFORE ``user_version`` is read, so N workers opening a fresh file
    replay the chain exactly once instead of racing (the recorded
    ``duplicate column name: lent_out`` failure). The version is re-read
    under the lock; losers find the winner's number and skip;
  - **refuses a file NEWER than the code**: :class:`SchemaNewerThanCode`
    names both versions at the door, instead of skipping quietly and dying
    later on a raw ``no such table``.

One transaction for the whole run, not one per step, on purpose — and for
ATOMICITY, not for the race: the cross-process race is closed by the re-read
under the lock (a per-step variant that re-reads per step would be equally
race-free, measured at P4.0a's review). What the single transaction buys is
that a file is only ever at the version it STARTED at or at
``SCHEMA_VERSION``, never between — a crash during a fresh clone's first
open cannot leave a half-built schema for someone to debug. The chain is
short and a household database is small; nothing needs incremental progress.

Rules for adding a step:
  - APPEND, never edit a shipped one. An edited step has already run on the
    owner's file and will never run again;
  - each step is idempotent-by-version, not idempotent-by-SQL — the runner
    guarantees once-only, so ``CREATE TABLE`` needs no ``IF NOT EXISTS``
    (and shouldn't have it: it would hide a real ordering bug);
  - a step is SQL text OR a callable taking the connection. Reach for a
    callable only when the data being written is DERIVED by a rule that lives
    in the domain — restating that rule in SQL is how the two copies drift;
  - a step NEVER manages the transaction: no ``BEGIN``, no ``COMMIT``, no
    ``executescript``. The runner provides the transaction; a callable that
    needs to read before writing simply does so on the open connection
    (see :func:`_v14`).
"""
from __future__ import annotations

import hashlib
import sqlite3
from typing import Callable, Iterator

Step = Callable[[sqlite3.Connection], None]


class SchemaNewerThanCode(RuntimeError):
    """The database file was written by NEWER code than this checkout.

    Raised at the door, naming both numbers and the file, instead of skipping
    quietly and dying later with a raw ``no such table`` — rolling back
    between items is a real action, and the failure should say what happened.

    ⚠ The guard exists from P4.0a on: rolling back to an OLDER checkout still
    dies the old way, because the guard is not there to fire.
    """

    def __init__(self, file_version: int, code_version: int,
                 path: str = "") -> None:
        where = f" ({path})" if path else ""
        super().__init__(
            f"database{where} is at schema v{file_version} but this code "
            f"stops at v{code_version}: the file was written by newer code. "
            f"Update the checkout, or restore the backup that matches it."
        )
        self.file_version = file_version
        self.code_version = code_version


def _db_path(conn: sqlite3.Connection) -> str:
    """The main database's file path, for error messages. Never raises —
    a failure to NAME the file must not outrank the failure being named."""
    try:
        for _, name, path in conn.execute("PRAGMA database_list"):
            if name == "main":
                return path or "<memory>"
    except sqlite3.Error:
        pass
    return "<unknown>"


def _statements(script: str) -> Iterator[str]:
    """Split a SQL script into complete statements, without ``executescript``.

    ``sqlite3.complete_statement`` does the judging, so a semicolon inside a
    string literal or a trigger body does not split. Fragments that are only
    whitespace/``--`` line comments (a script's trailing comment) are dropped
    — SQLite has nothing to execute in them. A trailing ``/* */`` block
    comment would be yielded as a fragment, which SQLite executes as a no-op;
    the shipped steps use only ``--``.
    """
    buf = ""
    for piece in script.split(";"):
        buf += piece + ";"
        if sqlite3.complete_statement(buf):
            stmt = buf.strip()
            buf = ""
            if any(line.strip() and not line.strip().startswith("--")
                   for line in stmt.rstrip(";").splitlines()):
                yield stmt
    tail = buf.strip()
    if tail and any(line.strip() and not line.strip().startswith("--")
                    for line in tail.splitlines()):
        yield tail

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

# --- v11: a read's diff summary snapshot (P2.8, §5.5/§5.6) -----------------
#
# Headline diff counts (added/corrected/unchanged/needs_decision/not_seen/
# rejected/ignored), captured ONCE when a read settles into done or stopped
# — never recomputed later. `app.reconcile_apply`'s own diff endpoints
# deliberately recompute `reconcile()` fresh against CURRENT library state on
# every call (never cached — see `diff_for`'s docstring), which is right for
# the ONE active, not-yet-applied read every review screen shows. A read's
# place in HISTORY is a different question: recomputing an ALREADY-APPLIED
# read's diff today would show it as "0 added, N unchanged" forever — the
# books it added are, by definition, already there the moment you ask again
# — silently erasing the very history this column exists to keep. So it is a
# snapshot, the same shape as a run's own config snapshot (CLAUDE.md, "Run
# history": "THIS IS THE EXPERIMENT VARIABLE"). See `app.domain.read.DiffSummary`.
#
# Pure SQL, no backfill: rows written before this migration simply have no
# summary (NULL) — the shelf history view shows them without one rather than
# inventing a number nobody measured, same shape as v10's `alternatives`.
_V11 = """
ALTER TABLE reads ADD COLUMN diff_summary TEXT;  -- JSON object, or NULL
"""

# --- v12: accounts, libraries, memberships (P3.1, §4.1) --------------------
#
# The tenancy tables, and the first ones in this file that are not scoped BY a
# library — `libraries` is the table every other `library_id` column has been
# referring to since v1 without anything to point at.
#
# ⚠ The backfill is the load-bearing half. Every row the owner already owns
# carries `library_id = 'dev-library'` (or whatever BOOKSNAP_DEV_LIBRARY was
# set to), and from this item on the resolver only serves a library it can
# find. Without a row per existing library_id, the first request after the
# upgrade answers 404 and the 251 books look deleted. So the step derives one
# from the data itself rather than from anything the app knows: every distinct
# library_id in every table that carries one, UNIONed (which dedups).
#
# `label` is left EMPTY there on purpose. A migration cannot know what the
# owner calls their library, and inventing an English "My library" would write
# a string of ours into the Hebrew UI's switcher. Naming it is the composition
# root's job (`app.main:_bootstrap_dev_account`, from the same env var that
# already produced the label on screen) — and `Library` tolerates a blank one
# for exactly these rows while `new_library` refuses to mint another.
#
# No accounts are backfilled: before this item nothing recorded a person, so
# there is no account to derive. The dev one is created at composition time.
_V12 = """
CREATE TABLE accounts (
    id           TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    email        TEXT,
    created_at   TEXT
);

-- Partial, so the many rows with no address yet (there is no login until
-- pillar 4) do not collide with each other on NULL.
CREATE UNIQUE INDEX accounts_by_email ON accounts (email) WHERE email IS NOT NULL;

CREATE TABLE libraries (
    id         TEXT PRIMARY KEY,
    label      TEXT NOT NULL DEFAULT '',
    created_at TEXT
);

CREATE TABLE memberships (
    account_id TEXT NOT NULL REFERENCES accounts (id)  ON DELETE CASCADE,
    library_id TEXT NOT NULL REFERENCES libraries (id) ON DELETE CASCADE,
    role       TEXT NOT NULL,        -- viewer | editor | admin
    joined_at  TEXT,
    PRIMARY KEY (account_id, library_id)
);

-- The PRIMARY KEY already covers "this account's membership of this library"
-- and "every library of this account" (leftmost prefix). This one serves the
-- other direction, "everyone in this library", which `set_role`/`remove_member`
-- need in full to answer "is there still an admin?".
CREATE INDEX memberships_of_library ON memberships (library_id, role);

INSERT INTO libraries (id)
    SELECT library_id FROM books
    UNION SELECT library_id FROM copies
    UNION SELECT library_id FROM shelves
    UNION SELECT library_id FROM captures
    UNION SELECT library_id FROM reads
    UNION SELECT library_id FROM decisions
    UNION SELECT library_id FROM duplicate_questions;
"""

# --- v13: the person is a user, not an account (P3.7a, §4.1) ---------------
#
# A RENAME and nothing else. VISION §4.1's 2026-08-11 revision makes the
# ACCOUNT the tenant — the customer — and the word was already taken by the
# person, which is why the admin console had to document the mismatch instead
# of using its own vocabulary. This step frees the noun; P3.7b's v14 spends it.
#
# ⚠ Nothing about the tenancy boundary moves here. `memberships` still names a
# library, and the resolver still asks about that pair. A reviewer looking for
# the security change is looking at the wrong version.
#
# `ALTER TABLE ... RENAME TO` rewrites the REFERENCES clauses in other tables
# (SQLite ≥ 3.25 with legacy_alter_table off, which is the default), so
# `memberships.user_id` keeps pointing at the renamed table — and the composite
# PRIMARY KEY and the secondary index come along too — without the 12-step
# table rebuild the SQLite docs describe for other alterations. The email index
# is dropped and recreated rather than left behind under its old name: an index
# called `accounts_by_email` on a table called `users` is exactly the kind of
# residue that makes the next reader doubt which one is authoritative.
#
# ⚠⚠ **A CALLABLE, and atomicity was the whole reason.** When this step
# shipped (P3.7a) the runner applied string steps with `executescript`, which
# COMMITS as it goes — and a crash between two statements of this rename
# would have left a file that re-enters at `DROP INDEX accounts_by_email` and
# raises `no such index`: the owner's books, openable only by hand (measured,
# P3.7a's data-integrity review). So it became a callable holding its own
# explicit `BEGIN`, left OPEN for the runner to commit together with the
# `PRAGMA user_version` bump.
#
# Since P4.0a the RUNNER provides that transaction for every step, so the
# `BEGIN` is gone — a step never manages the transaction (module rule). The
# schema statements are byte-identical to what shipped; only the transaction
# scaffolding, which the runner made dead, was removed.
def _v13(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX accounts_by_email")
    conn.execute("ALTER TABLE accounts RENAME TO users")
    conn.execute("ALTER TABLE memberships RENAME COLUMN account_id TO user_id")
    conn.execute(
        "CREATE UNIQUE INDEX users_by_email ON users (email)"
        " WHERE email IS NOT NULL"
    )

# --- v14: the account becomes the tenant (P3.7b, §4.1) ---------------------
#
# The boundary move. `accounts` (the CUSTOMER, not the person — v13 freed the
# word), `libraries.account_id`, and `memberships` re-keyed from
# (user, library) to (user, account). After this, authorization is "is this
# library owned by an account you belong to", answered once in
# `app.api.deps.current_library`.
#
# ⚠ `library_id` does not move and does not gain a sibling. No other table is
# touched by this step. A second enforced scope on the data is precisely what
# §4.1's revision refuses — see `app/domain/tenancy.py`'s ⚠⚠.
#
# **The backfill is the judgment call, and it is a GRANT question.** Nothing
# in a v13 file says which libraries belong to the same customer; the only
# evidence is the membership graph. Grouping by "same admin" would be the
# obvious guess and is wrong in a way that cannot be undone: if `lib-X` has
# members {Alice:admin} and `lib-Y` has {Alice:admin, Bob:editor}, putting
# them under one account hands Bob a library he was never invited to, because
# a role is now account-wide. So the rule is the conservative one:
#
#   libraries whose member set is IDENTICAL — same users, same roles —
#   collapse into one account; everything else gets its own.
#
# That cannot widen anyone's access, because every library in a group already
# had exactly those members. On the owner's real data (one person holding
# admin on both libraries) it produces the intended answer: one account, two
# libraries — confirmed with the owner before the work started.
#
# ⚠ A library with NO memberships is its own account, never grouped with the
# other orphans. They share an empty member set, so the rule above would
# collapse unrelated dead libraries into one customer — the one case where
# "identical members" means "no evidence" rather than "same owner".
#
# Account ids are derived from the group rather than random, so re-running
# this on a copy of a database produces the same ids as the original — which
# is what makes a migration debuggable after the fact.
#
# Callable because the backfill is DERIVED (the identical-member-set rule
# below), which SQL restating would drift from. No transaction scaffolding —
# the runner owns the transaction since P4.0a, same as _v13.
def _v14(conn: sqlite3.Connection) -> None:
    # --- who is in which library, before anything moves ------------------
    members_of: dict[str, set[tuple[str, str]]] = {}
    joined_of: dict[tuple[str, str], list[str]] = {}
    for lib, user, role, joined in conn.execute(
        "SELECT library_id, user_id, role, joined_at FROM memberships"
    ):
        members_of.setdefault(lib, set()).add((user, role))
        if joined is not None:
            joined_of.setdefault((lib, user), []).append(joined)

    names = {
        uid: (name or "")
        for uid, name in conn.execute("SELECT id, display_name FROM users")
    }

    # --- group libraries into accounts -----------------------------------
    groups: dict[frozenset[tuple[str, str]], list[str]] = {}
    orphans: list[str] = []
    libraries = [
        (r[0], r[1], r[2])
        for r in conn.execute(
            "SELECT id, label, created_at FROM libraries ORDER BY id"
        )
    ]
    for lib_id, _label, _created in libraries:
        members = frozenset(members_of.get(lib_id, ()))
        if not members:
            orphans.append(lib_id)          # never grouped — see the ⚠ above
        else:
            groups.setdefault(members, []).append(lib_id)

    plan: list[tuple[str, frozenset[tuple[str, str]], list[str]]] = []
    for members, lib_ids in groups.items():
        plan.append((_account_id(lib_ids), members, sorted(lib_ids)))
    for lib_id in orphans:
        plan.append((_account_id([lib_id]), frozenset(), [lib_id]))

    # --- accounts ---------------------------------------------------------
    conn.execute(
        "CREATE TABLE accounts ("
        " id         TEXT PRIMARY KEY,"
        " label      TEXT NOT NULL DEFAULT '',"
        " created_at TEXT"
        ")"
    )
    created_at = {lib_id: created for lib_id, _l, created in libraries}
    for account_id, members, lib_ids in plan:
        # The account's name is the sole admin's, when there is exactly one
        # and they have one. Anything else — no admin, several admins, an
        # unnamed person — stays blank rather than inventing a string of ours
        # in a Hebrew UI, which is v12's argument for library labels.
        admins = sorted(u for u, role in members if role == "admin")
        label = names.get(admins[0], "") if len(admins) == 1 else ""
        birthdays = sorted(c for c in (created_at[l] for l in lib_ids) if c)
        conn.execute(
            "INSERT INTO accounts (id, label, created_at) VALUES (?,?,?)",
            (account_id, label, birthdays[0] if birthdays else None),
        )

    owner_of = {lib: acc for acc, _m, libs in plan for lib in libs}

    # --- memberships, re-keyed -------------------------------------------
    #
    # Rebuilt rather than altered: the primary key changes, one column is
    # replaced by another, and its foreign key moves from `libraries` to
    # `accounts`. Dropped BEFORE `libraries` below, because this is the only
    # table that references it — every `library_id` elsewhere is a bare TEXT
    # column with no REFERENCES clause, which the rebuild depends on and
    # `tests/test_store_contract.py` asserts rather than assumes.
    conn.execute(
        "CREATE TABLE memberships_v14 ("
        " user_id    TEXT NOT NULL REFERENCES users (id)     ON DELETE CASCADE,"
        " account_id TEXT NOT NULL REFERENCES accounts (id)  ON DELETE CASCADE,"
        " role       TEXT NOT NULL,"
        " joined_at  TEXT,"
        " PRIMARY KEY (user_id, account_id)"
        ")"
    )
    for account_id, members, lib_ids in plan:
        for user, role in sorted(members):
            # Earliest sighting wins: the person has belonged to this customer
            # since the first library they were added to, not the last.
            dates = sorted(
                d for lib in lib_ids for d in joined_of.get((lib, user), [])
            )
            conn.execute(
                "INSERT INTO memberships_v14 (user_id, account_id, role,"
                " joined_at) VALUES (?,?,?,?)",
                (user, account_id, role, dates[0] if dates else None),
            )
    # ⚠ This is the first step that re-INSERTS every membership row, so a
    # pre-existing row naming a user that does not exist stops being dormant
    # and becomes `FOREIGN KEY constraint failed` — the whole step rolls back
    # to v13 and every open afterwards fails the same way, with nothing naming
    # the offending row. If that ever happens, `PRAGMA foreign_key_check` on
    # the v13 file names it in one line. (A row naming a missing LIBRARY is
    # dropped instead of raising: it granted access to something unreachable,
    # so nobody loses anything.)
    conn.execute("DROP TABLE memberships")
    conn.execute("ALTER TABLE memberships_v14 RENAME TO memberships")
    conn.execute(
        "CREATE INDEX memberships_of_account ON memberships (account_id, role)"
    )

    # --- libraries, now owned --------------------------------------------
    conn.execute(
        "CREATE TABLE libraries_v14 ("
        " id         TEXT PRIMARY KEY,"
        " account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,"
        " label      TEXT NOT NULL DEFAULT '',"
        " created_at TEXT"
        ")"
    )
    for lib_id, label, created in libraries:
        conn.execute(
            "INSERT INTO libraries_v14 (id, account_id, label, created_at)"
            " VALUES (?,?,?,?)",
            (lib_id, owner_of[lib_id], label, created),
        )
    conn.execute("DROP TABLE libraries")
    conn.execute("ALTER TABLE libraries_v14 RENAME TO libraries")
    # `list_libraries` is the resolver's neighbour and runs on every switcher
    # render; it narrows by account and orders by label.
    conn.execute(
        "CREATE INDEX libraries_of_account ON libraries (account_id, label, id)"
    )
    # ⚠ The two CASCADEs above cover exactly `accounts -> libraries` and
    # `accounts -> memberships`, and NOTHING below that. Every other
    # `library_id` is a bare TEXT column with no REFERENCES (which is what
    # this rebuild depends on), so deleting an account row would drop its
    # libraries while leaving their books, copies, shelves, captures,
    # reads, decisions and questions behind as rows no query can reach —
    # invisible even to `orphan_libraries`, which reads FROM `libraries`.
    # Nothing in the product deletes an account, and removing a customer
    # is not a supported operation; do not read the CASCADE as one
    # (P3.7b's data-integrity review).


def _account_id(library_ids: list[str]) -> str:
    """A stable id for the account a group of libraries collapses into.

    Derived, not random, so the same v13 file always migrates to the same
    account ids — a migration whose output cannot be reproduced is one that
    cannot be argued with afterwards. 32 hex characters, matching the shape
    ``IdGen`` already mints for every other id in the product.
    """
    # ⚠ Length-prefixed, not "|"-joined. A library id may itself contain a
    # pipe (nothing forbids it), so joining would give the group {"a", "b"}
    # and the group {"a|b"} the same seed — and therefore the same account id.
    # The collision is loud rather than silent (the PRIMARY KEY refuses the
    # second INSERT and the whole step rolls back), but the result is a file
    # the product cannot open at all. One line, free (P3.7b's migration
    # review).
    seed = "".join(f"{len(i)}:{i}" for i in sorted(library_ids))
    return hashlib.blake2s(seed.encode("utf-8"), digest_size=16).hexdigest()


# --- v15: sessions and login tokens (P4.1a, VISION §3) ---------------------
#
# Authentication arrives. Two tables, both holding HASHES only
# (`app.domain.auth.hash_token`): a leaked database must contain nothing
# that logs anyone in. The cookie and the emailed link carry the raw token
# exactly once, to its owner.
#
# `sessions.revoked_at` is a tombstone, never a DELETE — "when did this
# device stop being trusted" outlives the trust. `login_tokens.consumed_at`
# is the single-use rule's record; the consume itself is one guarded UPDATE
# in the store, so two racing redeems of one link mint one session.
#
# `source_hash` is the requesting client's HASHED address, kept solely for
# §3's per-source rate window. The address itself has no business
# persisting, and no column here holds one.
#
# ⚠ User-scoped, deliberately: neither table names a library or a role.
# A session says WHO — the account walk stays where it lives today
# (`deps.owner_membership`), and adding a shortcut column here would be a
# second copy of that rule.
_V15 = """
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);

-- "Every session of this user" is the lost-phone question (revoke them
-- all) and P4.3's account screen. Nothing queries by expiry alone.
CREATE INDEX sessions_by_user ON sessions (user_id, created_at);

CREATE TABLE login_tokens (
    token_hash  TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    source_hash TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    consumed_at TEXT
);

-- The two rate windows (§3): how many links for this address, how many
-- from this source, inside the hour. Both lead with their filter.
CREATE INDEX login_tokens_by_email  ON login_tokens (email, created_at);
CREATE INDEX login_tokens_by_source ON login_tokens (source_hash, created_at);
"""


# --- v16: invites (P4.3, §4.1 "invite once") -------------------------------
#
# ⚠ `consumed_by` carries NO foreign key while its two neighbours do,
# deliberately: it is the link's own audit line, written to outlive the
# membership it minted (see app/domain/invites.py) — an FK would make
# a future user deletion either cascade the audit away or refuse the
# deletion over a spent link. Recorded here, OUTSIDE the shipped
# string, because v16 has run on the real file and rule 11 owns it.
#
# One table, same credential discipline as v15: the HASH of the token, never
# the token — nothing stored can reproduce the link the admin was shown.
# Joining is to the ACCOUNT (the FK is the boundary object itself), at the
# role the invite carries. Revocation DELETEs (an invite that minted nothing
# leaves nothing worth explaining); acceptance records who and when, so the
# row outlives its use as the link's own audit line.
_V16 = """
CREATE TABLE invites (
    token_hash  TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL REFERENCES accounts (id),
    role        TEXT NOT NULL,
    created_by  TEXT NOT NULL REFERENCES users (id),
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    consumed_at TEXT,
    consumed_by TEXT
);

-- The admin's screen: open invites of ONE account, oldest first.
CREATE INDEX invites_by_account ON invites (account_id, created_at);
"""


# --- v17: an invite goes inert once it has granted (P4.3's DI review) ------
#
# `consumed_at` says the link was SPENT; it does not say the membership
# landed. Consume and grant are two transactions over one file, so a crash
# between them left a spent link with nothing granted and no way back — and
# the fix for THAT (letting its own consumer re-enter) turned every consumed
# invite into a permanent re-entry ticket: a removed member could replay
# their link a year later and be re-granted, at the role it carried, with no
# revoke possible (a consumed invite is invisible to `list_open_invites` and
# refused by `revoke_invite`). Measured end to end at review.
#
# `granted_at` closes both: the re-entry is allowed only while it is NULL,
# and it is stamped the moment the membership exists. After that the link is
# inert for EVERYONE, including the person who used it — which is what makes
# `delete_member` final again.
#
# Backfilled to `consumed_at` for rows that already exist. That is the
# fail-CLOSED reading, not a universal truth: a pre-v17 row could also have
# been consumed by the very crash this column exists for, and such a row is
# marked granted here, locking its consumer out of an acceptance they
# legitimately half-finished. The two costs are not comparable — wrongly
# granted costs "ask the admin for a new link", wrongly NULL leaves the
# permanent re-entry ticket alive on the owner's own file (the CRITICAL both
# P4.3 reviews measured). Open rows stay NULL, which reopens nothing:
# `may_finish` also requires `consumed_by` to match, and NULL never does.
_V17 = """
ALTER TABLE invites ADD COLUMN granted_at TEXT;

UPDATE invites SET granted_at = consumed_at WHERE consumed_at IS NOT NULL;
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
    (11, _V11),
    (12, _V12),
    (13, _v13),
    (14, _v14),
    (15, _V15),
    (16, _V16),
    (17, _V17),
)

SCHEMA_VERSION = MIGRATIONS[-1][0]


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Bring ``conn`` up to :data:`SCHEMA_VERSION`. Returns the new version.

    Safe to call on every connect: already-applied steps are skipped, so this
    is how the store guarantees a usable file without a separate setup command
    someone can forget to run. An up-to-date file takes no lock at all — this
    runs on every store construction, several times per process.

    The pending chain runs in ONE ``BEGIN IMMEDIATE`` transaction — atomic,
    and exclusive across processes; see the module note for the argument.
    """
    # v13 uses ALTER TABLE ... RENAME COLUMN, which is 3.25+. Stated once,
    # here, rather than discovered as a half-applied step on an old build:
    # the versions where this matters are exactly the ones where a failure
    # cannot be rolled back.
    if sqlite3.sqlite_version_info < (3, 25):
        raise RuntimeError(
            f"booksnap needs SQLite 3.25+ (this build has "
            f"{sqlite3.sqlite_version}); schema v13 renames a column"
        )
    version = current_version(conn)
    if version == SCHEMA_VERSION:
        return version
    if version > SCHEMA_VERSION:
        raise SchemaNewerThanCode(version, SCHEMA_VERSION, _db_path(conn))

    # The write lock comes BEFORE the re-read: two processes opening a fresh
    # file both pass the check above, but only one holds the lock, and the
    # loser re-reads the winner's number and walks straight through the loop.
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        # A bare `database is locked` out of a store constructor answers
        # nothing; say which file and what was being attempted.
        raise sqlite3.OperationalError(
            f"could not lock {_db_path(conn)} to migrate it "
            f"(v{version} -> v{SCHEMA_VERSION}): {exc}; another process may "
            f"be migrating the same file — retry when it finishes"
        ) from exc
    try:
        version = current_version(conn)
        if version > SCHEMA_VERSION:
            raise SchemaNewerThanCode(version, SCHEMA_VERSION, _db_path(conn))
        for target, step in MIGRATIONS:
            if target <= version:
                continue
            if isinstance(step, str):
                for stmt in _statements(step):
                    conn.execute(stmt)
            else:
                step(conn)
            # PRAGMA does not take bound parameters; `target` is an int from
            # this module's own tuple, never from input. The bump joins the
            # step in the same transaction — they land or vanish together.
            conn.execute(f"PRAGMA user_version = {int(target)}")
            version = target
        # COMMIT can itself fail (disk full, a WAL checkpoint losing a
        # race); it belongs inside the try so the rollback still runs.
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return version
