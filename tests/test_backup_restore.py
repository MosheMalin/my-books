# -*- coding: utf-8 -*-
"""The restore rehearsal (P4.4, VISION §11.3).

**Not backup — restore.** This item gates handing a URL to a relative,
because their review decisions cannot be re-derived: the engine can re-read
a shelf, but nobody can reconstruct which findings a human approved,
corrected or rejected. A backup nobody has restored is a hope, so the drill
is a TEST, run by the gate, on every commit — not a runbook step someone
performs once and never again.

Every case here drives the real ``tools/backup.py`` / ``tools/restore.py``
against real sqlite files and the product's own store adapters.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.sqlite_store import (  # noqa: E402
    SqliteBookStore,
    SqliteDecisionStore,
    SqliteTenancyStore,
)
from app.domain import (  # noqa: E402
    Account,
    Decision,
    DecisionKind,
    Library,
    LibraryRef,
    Membership,
    Role,
    User,
    new_book,
)
from tools import backup as backup_tool  # noqa: E402
from tools import restore as restore_tool  # noqa: E402

LIB = LibraryRef(id="lib-a", label="הבית")


def _a_world(root: Path) -> tuple[Path, Path]:
    """A database with the things that cannot be re-derived in it."""
    db = root / "product.db"
    blobs = root / "blobs"
    tenancy = SqliteTenancyStore(db)
    tenancy.save_user(User(id="u1", email="owner@example.com"))
    tenancy.save_account(Account(id="acc"))
    tenancy.save_membership(Membership("u1", "acc", Role.ADMIN))
    tenancy.save_library(Library(id=LIB.id, account_id="acc", label=LIB.label))

    books = SqliteBookStore(db)
    for i in range(3):
        books.save(LIB, new_book(id=f"b{i}", copy_id=f"c{i}",
                                 library_id=LIB.id,
                                 title=f"ספר {i}", author="מחבר"))
    decisions = SqliteDecisionStore(db)
    decisions.save_decision(LIB, Decision(
        library_id=LIB.id, shelf_id="sh1", depth=1, book_key="לא זה|",
        kind=DecisionKind.REJECTED,
        decided_at="2026-08-13T12:00:00+00:00",
    ))

    (blobs / "libraries" / LIB.id / "blobs" / "ab").mkdir(parents=True)
    (blobs / "libraries" / LIB.id / "blobs" / "ab" / "photo.jpg").write_bytes(
        b"not really a jpeg, but it is bytes on disk")
    return db, blobs


def test_a_backup_of_a_live_database_restores_with_everything_that_matters():
    """The round trip, end to end: back up, restore into a fresh place,
    and read it back THROUGH THE PRODUCT'S OWN STORES. The books prove the
    copy; the decision proves §11.3's expensive artifact came with it."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db, blobs = _a_world(root / "live")
        target = backup_tool.run(db, blobs, root / "backups")

        manifest = json.loads(
            (target / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["database"]["rows"]["books"] == 3
        assert manifest["database"]["rows"]["decisions"] == 1
        assert manifest["blobs"]["files"] == 1

        restored_db = root / "restored" / "product.db"
        restored_blobs = root / "restored" / "blobs"
        restore_tool.restore(target, restored_db, restored_blobs)

        books = SqliteBookStore(restored_db)
        assert books.count(LIB) == 3
        decisions = SqliteDecisionStore(restored_db)
        assert len(decisions.list_decisions(LIB, "sh1", 1)) == 1, (
            "the review decisions did not survive the restore — they are "
            "the one thing that cannot be re-derived (§11.3)"
        )
        assert (restored_blobs / "libraries" / LIB.id / "blobs" / "ab"
                / "photo.jpg").exists()


def test_the_drill_reads_the_backup_back_through_the_stores():
    """The rehearsal itself, which is what P4.4 actually delivers: it must
    PASS on a good backup without touching the live paths."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db, blobs = _a_world(root / "live")
        target = backup_tool.run(db, blobs, root / "backups")

        findings = restore_tool.drill(target)
        assert findings["books"] == 3
        assert findings["decisions"] == 1
        assert findings["blob_files"] == 1
        assert findings["libraries"] == [("הבית", 3)]
        # The live files are untouched — a drill is safe to run on a
        # server that is up, which is the only way it gets run often.
        assert db.exists() and SqliteBookStore(db).count(LIB) == 3


def test_a_backup_taken_on_an_older_schema_still_comes_up():
    """The case that matters at 3am: last night's backup was written by
    yesterday's code. The drill opens it through today's stores, which
    MIGRATES it — and a backup that cannot be migrated forward is not a
    backup of anything."""
    from app.adapters.migrations import MIGRATIONS, SCHEMA_VERSION

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old = root / "live"
        old.mkdir(parents=True)
        db = old / "product.db"
        conn = sqlite3.connect(str(db))
        try:
            for version, step in MIGRATIONS:
                if version > 14:          # a v14 file: two schema versions back
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 14")
            conn.execute("INSERT INTO users (id, display_name) VALUES"
                         " ('u1', 'משה')")
            conn.execute("INSERT INTO accounts (id, label) VALUES ('acc', '')")
            conn.execute("INSERT INTO libraries (id, account_id, label)"
                         " VALUES ('lib-a', 'acc', 'הבית')")
            conn.execute("INSERT INTO memberships (user_id, account_id, role)"
                         " VALUES ('u1', 'acc', 'admin')")
            conn.execute(
                "INSERT INTO books (id, library_id, title, author, norm_title,"
                " norm_author, book_key, notes, search_text, sort_author)"
                " VALUES ('b1','lib-a','ספר','','ספר','','k','','ספר','')")
            conn.commit()
        finally:
            conn.close()

        target = backup_tool.run(db, old / "blobs", root / "backups")
        assert json.loads((target / "manifest.json").read_text(
            encoding="utf-8"))["database"]["schema_version"] == 14

        findings = restore_tool.drill(target)
        assert findings["books"] == 1
        assert any(f"v14 opened as v{SCHEMA_VERSION}" in c
                   for c in findings["checks"]), findings["checks"]


def test_an_interrupted_backup_is_refused_rather_than_restored():
    """The manifest is written LAST, so a backup killed halfway has none —
    and restoring a half-copy over a working system is the failure a
    restore tool must never commit."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db, blobs = _a_world(root / "live")
        target = backup_tool.run(db, blobs, root / "backups")
        (target / "manifest.json").unlink()

        for call in (lambda: restore_tool.verify(target),
                     lambda: restore_tool.drill(target),
                     lambda: restore_tool.restore(
                         target, root / "x" / "product.db", root / "x" / "b")):
            try:
                call()
            except SystemExit as exc:
                assert "incomplete" in str(exc), str(exc)
            else:
                raise AssertionError("an incomplete backup was accepted")


def test_a_corrupted_backup_is_refused_by_its_own_checksum():
    """A restore that writes a corrupt database over a live one turns a
    bad night into an unrecoverable one."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db, blobs = _a_world(root / "live")
        target = backup_tool.run(db, blobs, root / "backups")

        with (target / "product.db").open("r+b") as handle:
            handle.seek(4096)
            handle.write(b"\x00" * 512)

        try:
            restore_tool.verify(target)
        except SystemExit as exc:
            assert "do NOT restore" in str(exc), str(exc)
        else:
            raise AssertionError("a corrupted backup passed verification")


def test_a_real_restore_moves_the_existing_data_aside_rather_than_deleting():
    """The moment you restore the wrong backup is the moment you can least
    afford to lose what was there."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db, blobs = _a_world(root / "live")
        target = backup_tool.run(db, blobs, root / "backups")

        # Something ELSE is already at the destination.
        other = root / "other"
        other_db, other_blobs = _a_world(other)
        SqliteBookStore(other_db).save(
            LIB, new_book(id="keep-me", copy_id="keep-c", library_id=LIB.id,
                          title="ספר יקר", author=""))
        assert SqliteBookStore(other_db).count(LIB) == 4

        restore_tool.restore(target, other_db, other_blobs)

        assert SqliteBookStore(other_db).count(LIB) == 3, "the restore landed"
        aside = [p for p in other.iterdir() if ".replaced-" in p.name]
        assert any(p.name.startswith("product.db.replaced-") for p in aside), (
            f"the replaced database was deleted, not moved aside: {aside}"
        )
        kept = next(p for p in aside if p.name.startswith("product.db."))
        assert SqliteBookStore(kept).count(LIB) == 4, (
            "what was there is still readable after being moved aside"
        )


def test_a_backup_of_a_RUNNING_database_captures_its_uncheckpointed_writes():
    """The backup API, pinned where it differs from a file copy: with a
    connection still open, recent commits live in the `-wal` sidecar, and
    `copy2` of the `.db` alone captures a database missing them — while
    every check still passes, because the manifest is computed from that
    same truncated copy. A self-consistent backup of nothing (measured,
    P4.4's migration review: the copy2 mutation survived the whole
    suite)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db, blobs = _a_world(root / "live")

        # A connection that STAYS OPEN, so its writes sit in the WAL.
        holder = sqlite3.connect(str(db))
        try:
            holder.execute("PRAGMA journal_mode = WAL")
            holder.execute(
                "INSERT INTO books (id, library_id, title, author,"
                " norm_title, norm_author, book_key, notes, search_text,"
                " sort_author) VALUES ('late', ?, 'ספר מאוחר', '',"
                " 'ספר מאוחר', '', 'late|', '', 'ספר מאוחר', '')",
                (LIB.id,),
            )
            holder.commit()
            assert (db.with_name(db.name + "-wal")).exists(), (
                "no WAL to lose — this test would prove nothing"
            )

            target = backup_tool.run(db, blobs, root / "backups")
        finally:
            holder.close()

        manifest = json.loads(
            (target / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["database"]["rows"]["books"] == 4
        assert SqliteBookStore(target / "product.db").count(LIB) == 4, (
            "the backup lost writes that were only in the WAL"
        )


def test_the_manifest_is_written_after_everything_it_vouches_for():
    """The ordering IS the integrity rule: a backup killed halfway must
    have no manifest, because `restore.py` trusts a manifest's presence.
    Written first, an interrupted backup looks complete (measured: the
    reorder survived the whole suite)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db, blobs = _a_world(root / "live")

        real_copy_blobs = backup_tool._copy_blobs

        def die(*args, **kwargs):
            raise OSError("disk full, halfway through the photographs")

        backup_tool._copy_blobs = die
        try:
            backup_tool.run(db, blobs, root / "backups")
        except OSError:
            pass
        else:
            raise AssertionError("the injected failure did not surface")
        finally:
            backup_tool._copy_blobs = real_copy_blobs

        made = list((root / "backups").glob("*"))
        assert made, "nothing was created at all — check the fixture"
        for attempt in made:
            assert not (attempt / "manifest.json").exists(), (
                "an interrupted backup carries a manifest, so restore.py "
                "would trust it"
            )


def test_a_restore_keeps_the_replaced_databases_recent_writes():
    """The move-aside promises the current data survives. With the `.db`
    moved and its `-wal` left behind (or unlinked, as this first did),
    the aside copy reads as `no such table` — the safety net destroying
    exactly what it exists to keep (measured, P4.4's migration review).

    ⚠ This asserts the PROPERTY, and three things now enforce it, so no
    single mutation kills this test — measured, and recorded rather than
    called a gap (the redundant-enforcement pattern): `restore()` opens
    the file to check nobody holds it and SQLite checkpoints on that
    close; it then checkpoints explicitly; and it moves the sidecars with
    the database. Remove all three and this fails. The property is what
    matters — do not "simplify" it away one layer at a time.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db, blobs = _a_world(root / "live")
        target = backup_tool.run(db, blobs, root / "backups")

        # A KILLED server's file set: the .db plus an un-checkpointed
        # -wal, with no process holding it. Captured by copying the live
        # files mid-write, which is precisely what a `docker kill` leaves
        # behind — and the state the owner restores over.
        live = root / "live2"
        live.mkdir()
        source_db, _source_blobs = _a_world(root / "src2")
        holder = sqlite3.connect(str(source_db))
        try:
            holder.execute("PRAGMA journal_mode = WAL")
            holder.execute("PRAGMA wal_autocheckpoint = 0")
            holder.execute(
                "INSERT INTO books (id, library_id, title, author,"
                " norm_title, norm_author, book_key, notes, search_text,"
                " sort_author) VALUES ('today', ?, 'אישור של היום', '',"
                " 'אישור של היום', '', 'today|', '', 'אישור', '')",
                (LIB.id,),
            )
            holder.commit()
            assert (source_db.with_name(source_db.name + "-wal")).exists(), (
                "no WAL to lose — this test would prove nothing"
            )
            other_db = live / "product.db"
            for suffix in ("", "-wal", "-shm"):
                sidecar = source_db.with_name(source_db.name + suffix)
                if sidecar.exists():
                    shutil.copy2(sidecar,
                                 other_db.with_name(other_db.name + suffix))
        finally:
            holder.close()

        other_blobs = live / "blobs"
        other_blobs.mkdir()
        assert SqliteBookStore(other_db).count(LIB) == 4, (
            "the crashed copy should read 4 through its own WAL"
        )
        # Re-crash it: opening it above checkpointed, so redo the capture.
        shutil.rmtree(live)
        live.mkdir()
        other_blobs = live / "blobs"
        other_blobs.mkdir()
        holder = sqlite3.connect(str(source_db))
        try:
            holder.execute("PRAGMA journal_mode = WAL")
            holder.execute("PRAGMA wal_autocheckpoint = 0")
            holder.execute(
                "INSERT INTO books (id, library_id, title, author,"
                " norm_title, norm_author, book_key, notes, search_text,"
                " sort_author) VALUES ('later', ?, 'ואישור נוסף', '',"
                " 'ואישור נוסף', '', 'later|', '', 'ואישור', '')",
                (LIB.id,),
            )
            holder.commit()
            for suffix in ("", "-wal", "-shm"):
                sidecar = source_db.with_name(source_db.name + suffix)
                if sidecar.exists():
                    shutil.copy2(sidecar,
                                 other_db.with_name(other_db.name + suffix))
        finally:
            holder.close()

        restore_tool.restore(target, other_db, other_blobs)

        aside = next(p for p in live.iterdir()
                     if p.name.startswith("product.db.replaced-")
                     and not p.name.endswith(("-wal", "-shm")))
        assert SqliteBookStore(aside).count(LIB) == 5, (
            "the moved-aside database lost the writes that were in its "
            "WAL — the safety net destroyed what it promised to keep"
        )
        assert SqliteBookStore(other_db).count(LIB) == 3, "the restore landed"
