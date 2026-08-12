# -*- coding: utf-8 -*-
"""The migration RUNNER's three guards (P4.0a).

Each closes a hole recorded in planning/TENANCY_BOUNDARY_PLAN.md ("Found on
the way, deliberately NOT fixed here") — pre-existing, and live the moment
pillar 4 adds auth schema. The steps themselves are exercised by
test_store_contract.py; this module is about how the runner APPLIES them.
"""
from __future__ import annotations

import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

import app.adapters.migrations as migrations
from app.adapters.migrations import (
    SCHEMA_VERSION,
    SchemaNewerThanCode,
    _statements,
    current_version,
    migrate,
)


@contextmanager
def _fresh_file():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp) / "fresh.db"


@contextmanager
def _appended_step(step):
    """Temporarily append a fake next step to the chain.

    Module attributes are patched and restored because migrate() reads the
    globals; run_all runs a worker's tests sequentially, so nothing observes
    the patch mid-flight.
    """
    old_chain, old_version = migrations.MIGRATIONS, migrations.SCHEMA_VERSION
    target = old_version + 1
    migrations.MIGRATIONS = old_chain + ((target, step),)
    migrations.SCHEMA_VERSION = target
    try:
        yield target
    finally:
        migrations.MIGRATIONS, migrations.SCHEMA_VERSION = old_chain, old_version


def test_a_failing_step_rolls_the_file_back_to_the_version_it_started_at():
    """The atomicity guard. Under the pre-P4.0a runner `executescript`
    committed as it went, so the canary table would SURVIVE the crash and the
    file would sit half-upgraded at the old version — openable only by hand.
    Now the whole pending run is one transaction: nothing of the failed step
    remains, and re-running after a fix starts from a consistent file."""
    bad = (
        "CREATE TABLE p4_canary (id TEXT PRIMARY KEY);\n"
        "INSERT INTO no_such_table VALUES (1);\n"
    )
    # Both journal modes: the product always sets WAL (sqlite_store), and a
    # rollback proven only under the default journal is proven for a file
    # the owner does not have.
    for journal in ("delete", "wal"):
        with _fresh_file() as path:
            conn = sqlite3.connect(str(path))
            try:
                conn.execute(f"PRAGMA journal_mode = {journal}")
                assert migrate(conn) == SCHEMA_VERSION
                with _appended_step(bad):
                    try:
                        migrate(conn)
                    except sqlite3.OperationalError:
                        pass
                    else:
                        raise AssertionError("the broken step did not raise")
                assert current_version(conn) == SCHEMA_VERSION, (
                    f"user_version moved despite the failed step ({journal})"
                )
                canary = conn.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'p4_canary'"
                ).fetchone()
                assert canary is None, (
                    f"the failed step's first statement survived ({journal}) "
                    "— the step did not roll back as a unit"
                )
            finally:
                conn.close()


def test_a_failure_late_in_a_fresh_chain_rolls_back_every_earlier_step():
    """The whole-run transaction, pinned. The runner deliberately wraps the
    ENTIRE pending chain rather than each step (the plan's recorded per-step
    suggestion): a file is at the version it started at or at SCHEMA_VERSION,
    never between. A per-step runner would pass the single-step rollback test
    above and leave a fresh file at v14 here — half-upgraded is exactly the
    state this refuses to mint."""
    bad = "INSERT INTO no_such_table VALUES (1);\n"
    for journal in ("delete", "wal"):
        with _fresh_file() as path:
            conn = sqlite3.connect(str(path))
            try:
                conn.execute(f"PRAGMA journal_mode = {journal}")
                with _appended_step(bad):
                    try:
                        migrate(conn)
                    except sqlite3.OperationalError:
                        pass
                    else:
                        raise AssertionError("the broken step did not raise")
                assert current_version(conn) == 0, (
                    f"the chain committed partway ({journal})"
                )
                assert conn.execute(
                    "SELECT count(*) FROM sqlite_master WHERE name = 'books'"
                ).fetchone()[0] == 0, (
                    f"v1's table survived a chain that failed later ({journal})"
                )
            finally:
                conn.close()


def test_a_database_newer_than_the_code_is_refused_naming_both_numbers():
    """The rollback guard: checking out an older build against an upgraded
    file must fail AT THE DOOR with both numbers, not later with a raw
    `no such table`."""
    with _fresh_file() as path:
        conn = sqlite3.connect(str(path))
        try:
            migrate(conn)
            conn.execute("PRAGMA user_version = 99")
            try:
                migrate(conn)
            except SchemaNewerThanCode as e:
                assert e.file_version == 99
                assert e.code_version == SCHEMA_VERSION
                assert "99" in str(e) and str(SCHEMA_VERSION) in str(e)
                assert isinstance(e, RuntimeError)  # older callers still catch
            else:
                raise AssertionError("a newer file was migrated silently")

            # "At the door" is an ordering claim: the refusal comes BEFORE the
            # write lock. With a writer holding the lock, a guard that locked
            # first would raise `database is locked` off this 50ms timeout
            # instead of naming the versions.
            holder = sqlite3.connect(str(path))
            impatient = sqlite3.connect(str(path), timeout=0.05)
            try:
                holder.execute("BEGIN IMMEDIATE")
                try:
                    migrate(impatient)
                except SchemaNewerThanCode:
                    pass
                else:
                    raise AssertionError("a newer file was migrated silently")
            finally:
                holder.rollback()
                holder.close()
                impatient.close()
        finally:
            conn.close()


def test_concurrent_first_opens_replay_the_chain_exactly_once():
    """The cross-process guard. tests/run_all.py shards across processes, so
    a fresh worktree's first gate run has N workers racing the whole chain
    from zero — seen as `duplicate column name: lent_out`. Threads with a
    connection each contend on the same SQLite file lock as processes do,
    without the spawn cost. Pre-P4.0a this failed timing-dependently; the
    barrier maximises the collision."""
    n = 8
    # The timeout is a hang guard, not a race window: if one thread dies
    # before reaching the barrier (an AV lock on connect — this is the
    # Windows box), the others must fail loudly rather than block the gate
    # forever with no output at all.
    barrier = threading.Barrier(n, timeout=30)
    failures: list[BaseException] = []

    def worker(path: Path) -> None:
        try:
            conn = sqlite3.connect(str(path), timeout=30.0)
            try:
                barrier.wait()
                assert migrate(conn) == SCHEMA_VERSION
            finally:
                conn.close()
        except BaseException as e:  # noqa: BLE001 — collected, re-raised below
            barrier.abort()
            failures.append(e)

    with _fresh_file() as path:
        threads = [threading.Thread(target=worker, args=(path,)) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not failures, f"concurrent fresh-file migration failed: {failures[0]!r}"
        conn = sqlite3.connect(str(path))
        try:
            assert current_version(conn) == SCHEMA_VERSION
        finally:
            conn.close()


def test_the_statement_splitter_respects_literals_triggers_and_comments():
    """`executescript` is banned in the runner (it autocommits), so string
    steps go through _statements(). The splitter must not split on a
    semicolon inside a string literal or a trigger body, and must drop a
    trailing comment rather than hand SQLite an empty statement."""
    script = (
        "-- leading comment; the semicolon in it must not split (V5 has one)\n"
        "CREATE TABLE t (x TEXT);\n"
        "INSERT INTO t VALUES ('a;b');\n"
        "CREATE TRIGGER trg AFTER INSERT ON t BEGIN\n"
        "  INSERT INTO t VALUES ('c;d');\n"
        "  DELETE FROM t WHERE x = 'never';\n"
        "END;\n"
        "-- trailing comment, no statement\n"
    )
    stmts = list(_statements(script))
    assert len(stmts) == 3, f"expected 3 statements, got {len(stmts)}: {stmts}"

    conn = sqlite3.connect(":memory:")
    try:
        for s in stmts:
            conn.execute(s)
        # One row from the INSERT; the trigger was created after it ran. A
        # second insert proves the trigger's body survived splitting intact.
        conn.execute("INSERT INTO t VALUES ('e')")
        rows = {r[0] for r in conn.execute("SELECT x FROM t")}
        assert rows == {"a;b", "e", "c;d"}
    finally:
        conn.close()


def test_an_up_to_date_file_is_migrated_without_taking_the_write_lock():
    """migrate() runs on EVERY store construction, several times per process;
    the fast path must not queue behind a writer. A second connection holds
    the write lock; migrate() on an up-to-date file must return immediately
    rather than block or raise `database is locked`."""
    with _fresh_file() as path:
        conn = sqlite3.connect(str(path))
        try:
            migrate(conn)
        finally:
            conn.close()

        holder = sqlite3.connect(str(path))
        reader = sqlite3.connect(str(path), timeout=0.05)
        try:
            holder.execute("BEGIN IMMEDIATE")
            assert migrate(reader) == SCHEMA_VERSION
        finally:
            holder.rollback()
            holder.close()
            reader.close()
