# -*- coding: utf-8 -*-
"""Restore a backup — and REHEARSE the restore, which is the point.

VISION §11.3, P4.4: *"Not backup — restore."* This item gates handing a URL
to a relative, because their review decisions cannot be re-derived. A
backup nobody has ever restored is a hope; the ``--drill`` mode below is
what turns it into a fact, and it is a fact this repo can re-establish in
seconds, on demand, without touching the live system.

Three modes:

    python tools/restore.py --drill               # prove the newest backup
    python tools/restore.py --drill --from <dir>  # prove a specific one
    python tools/restore.py --from <dir> --to-db work/product.db \
                            --to-blobs work/product_blobs --i-mean-it

The drill restores into a TEMPORARY directory, opens the restored database
through the product's own store adapters, and checks the numbers against
the manifest. It never writes to the live paths — so it is safe to run
from cron, and safe to run while the server is up.

The real restore REFUSES to overwrite without ``--i-mean-it``, and moves
anything already at the destination aside rather than deleting it: the one
moment you are most likely to restore the wrong backup is the moment you
are least able to afford losing the current one.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.backup import (  # noqa: E402  (path set above)
    BACKUP_FORMAT,
    _sha256,
    _work,
    complete_backups,
    default_blobs,
    default_db,
)


def newest(root: Path) -> Path:
    """The most recent backup under ``root``, by its manifest's own time.

    One definition, shared with `backup.prune` — three copies of "which
    is newest" is how the sweep and the restore come to disagree about
    which file they are talking about.
    """
    candidates = complete_backups(root)
    if not candidates:
        raise SystemExit(f"no backups under {root}")
    return candidates[-1]


def read_manifest(backup: Path) -> dict:
    path = backup / "manifest.json"
    if not path.exists():
        # An interrupted backup has no manifest — refusing it is the whole
        # reason the manifest is written last.
        raise SystemExit(
            f"{backup} has no manifest.json — it is an incomplete backup, "
            f"not a restorable one"
        )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("format") != BACKUP_FORMAT:
        raise SystemExit(
            f"{backup} is format {manifest.get('format')}, this tool reads "
            f"{BACKUP_FORMAT}"
        )
    return manifest


def verify(backup: Path) -> dict:
    """Check a backup against its own manifest, without restoring it."""
    manifest = read_manifest(backup)
    db = backup / "product.db"
    if not db.exists():
        raise SystemExit(f"{backup} has a manifest but no product.db")
    actual = _sha256(db)
    if actual != manifest["database"]["sha256"]:
        raise SystemExit(
            f"{backup}'s database does not match its manifest "
            f"({actual[:12]}… vs {manifest['database']['sha256'][:12]}…) — "
            f"the copy is corrupt; do NOT restore it"
        )
    return manifest


def drill(backup: Path) -> dict:
    """Restore into a temp directory and READ IT BACK through the product.

    The check that matters is not "the file copied" — it is that the
    restored database answers the questions the household actually asks:
    how many books, and how many review decisions (§11.3's expensive
    artifact). Opening it through the real store adapters also proves the
    schema is one this code can migrate and serve.
    """
    manifest = verify(backup)
    from app.adapters.sqlite_store import (
        SqliteBookStore,
        SqliteDecisionStore,
        SqliteTenancyStore,
    )
    from app.domain import LibraryRef

    findings: dict = {"backup": str(backup), "checks": []}
    with tempfile.TemporaryDirectory(prefix="booksnap-drill-") as tmp:
        room = Path(tmp)
        db = room / "product.db"
        shutil.copy2(backup / "product.db", db)
        if (backup / "blobs").is_dir():
            shutil.copytree(backup / "blobs", room / "blobs")

        conn = sqlite3.connect(str(db))
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            fk = conn.execute("PRAGMA foreign_key_check").fetchall()
            before = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        if integrity != "ok":
            raise SystemExit(f"restored database fails integrity: {integrity}")
        if fk:
            raise SystemExit(f"restored database has broken references: {fk}")
        findings["checks"].append(f"integrity ok, {len(fk)} broken references")

        # Opening a store MIGRATES — which is itself part of the drill: a
        # backup taken on an older schema must come up on today's code.
        tenancy = SqliteTenancyStore(db)
        books = SqliteBookStore(db)
        decisions = SqliteDecisionStore(db)
        conn = sqlite3.connect(str(db))
        try:
            after = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        findings["checks"].append(
            f"schema v{before} opened as v{after}"
            + (" (migrated)" if after != before else "")
        )

        # Every library the backup holds, counted the way the app counts.
        total_books = 0
        libraries = []
        for account_row in conn_accounts(db):
            for library in tenancy.list_libraries(account_row):
                ref = LibraryRef(id=library.id, label=library.label)
                count = books.count(ref)
                total_books += count
                libraries.append((library.label or library.id, count))
        findings["libraries"] = libraries
        findings["books"] = total_books

        # ⚠ Only tables no migration ever POPULATES may be compared:
        # v12 inserts into `libraries`, so a future backfill into `books`
        # or `decisions` would turn every drill of every older backup
        # into a permanent false alarm. Add the check there, not here.
        expected = manifest["database"]["rows"]["books"]
        if expected is not None and total_books != expected:
            raise SystemExit(
                f"the restored library holds {total_books} books, the "
                f"manifest says {expected} — a restore that loses books is "
                f"the failure this drill exists to catch"
            )
        findings["checks"].append(f"{total_books} books, matching the manifest")

        # §11.3's expensive artifact: the decisions. Counted on the
        # RESTORED file after the stores have opened it, so a schema this
        # code cannot read fails here rather than at 3am.
        # `[...]`, not `.get`: a manifest that stopped recording the
        # decisions count would silently stop CHECKING it, and §11.3's
        # expensive artifact is the one thing this drill exists for.
        stored = manifest["database"]["rows"]["decisions"]
        conn = sqlite3.connect(str(db))
        try:
            seen = conn.execute("SELECT count(*) FROM decisions").fetchone()[0]
        finally:
            conn.close()
        if stored is not None and seen != stored:
            raise SystemExit(
                f"{seen} review decisions restored, manifest says {stored}"
            )
        findings["decisions"] = seen
        findings["checks"].append(f"{seen} review decisions, matching")

        # Open invites: a standing 7-day grant somebody is waiting on, and
        # the other row a restore must not silently drop (P4.2's review).
        stored_invites = manifest["database"]["rows"].get("invites")
        if stored_invites is not None:
            conn = sqlite3.connect(str(db))
            try:
                live = conn.execute(
                    "SELECT count(*) FROM invites").fetchone()[0]
            finally:
                conn.close()
            if live != stored_invites:
                raise SystemExit(
                    f"{live} invites restored, manifest says {stored_invites}")
            findings["invites"] = live
            findings["checks"].append(f"{live} invites, matching")

        blob_files = sum(1 for p in (room / "blobs").rglob("*") if p.is_file()) \
            if (room / "blobs").is_dir() else 0
        if blob_files != manifest["blobs"]["files"]:
            raise SystemExit(
                f"{blob_files} blob files restored, manifest says "
                f"{manifest['blobs']['files']}"
            )
        findings["blob_files"] = blob_files
        findings["checks"].append(f"{blob_files} blob files, matching")

        _ = decisions  # opened to prove the adapter accepts the schema
    return findings


def conn_accounts(db: Path) -> list[str]:
    conn = sqlite3.connect(str(db))
    try:
        return [row[0] for row in conn.execute("SELECT id FROM accounts")]
    finally:
        conn.close()


def restore(backup: Path, to_db: Path, to_blobs: Path) -> None:
    """The real thing. Anything already there is MOVED ASIDE, never
    deleted — the moment you restore the wrong backup is the moment you
    can least afford to lose what was there."""
    verify(backup)
    _refuse_impossible_destinations(backup, to_db, to_blobs)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if to_db.exists():
        _refuse_if_in_use(to_db)
    for live in (to_db, to_blobs):
        if live.exists():
            aside = live.with_name(f"{live.name}.replaced-{stamp}")
            shutil.move(str(live), str(aside))
            print(f"moved existing {live} aside to {aside}")
            # ⚠ The SIDECARS MOVE WITH IT. A `.db` whose `-wal` was left
            # behind (or unlinked, as this did) is a database missing
            # every write since the last checkpoint — measured at
            # review: the aside copy read as `no such table`, i.e. the
            # safety net destroyed exactly what it promised to keep.
            if live is to_db:
                for suffix in ("-wal", "-shm"):
                    sidecar = live.with_name(live.name + suffix)
                    if sidecar.exists():
                        shutil.move(str(sidecar),
                                    str(aside.with_name(aside.name + suffix)))
    to_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup / "product.db", to_db)
    if (backup / "blobs").is_dir():
        shutil.copytree(backup / "blobs", to_blobs)
    else:
        to_blobs.mkdir(parents=True, exist_ok=True)
    # ASCII: this console is cp1255, and an arrow here raised AFTER the
    # files had landed — reading as "the restore failed" at the exact
    # moment ambiguity is most expensive (measured at review).
    print(f"restored {backup} -> {to_db} / {to_blobs}")


def _refuse_impossible_destinations(backup: Path, to_db: Path,
                                    to_blobs: Path) -> None:
    """Check WHERE before moving anything. ``--i-mean-it`` gates whether,
    never where.

    Every step of a restore is a move, so nothing here is unrecoverable —
    but the failures are exactly the moment the tool promises to protect:
    P4.4's security review measured `--to-blobs /data/work` (one word off
    the line above it in the runbook) replacing the database, failing on
    the blobs, reporting failure, and leaving the previous database two
    directories deep; and naming the volume root moved the BACKUP being
    restored from out from under the copy.
    """
    backup, to_db, to_blobs = (p.resolve() for p in (backup, to_db, to_blobs))

    def inside(child: Path, parent: Path) -> bool:
        return child == parent or parent in child.parents

    for name, target in (("--to-db", to_db), ("--to-blobs", to_blobs)):
        if inside(target, backup) or inside(backup, target):
            raise SystemExit(
                f"{name} {target} overlaps the backup at {backup} — the "
                f"restore would move its own source aside"
            )
    if inside(to_db, to_blobs) or to_blobs == to_db.parent:
        raise SystemExit(
            f"--to-blobs {to_blobs} contains --to-db {to_db}: restoring "
            f"the blobs would move the database away with it"
        )
    if to_db == to_blobs:
        raise SystemExit("--to-db and --to-blobs are the same path")


def _refuse_if_in_use(db: Path) -> None:
    """Stop BEFORE moving anything if a server still holds the file.

    On Windows `shutil.move` falls back to copy-then-unlink, so it made
    the aside copy and THEN died on WinError 32 — a half-done restore at
    the worst possible moment (measured at review).

    ⚠ Asked through SQLITE, not by opening the file: a plain ``open()``
    succeeds against a database another process has open (measured on
    this machine), so the obvious probe answers "free" for exactly the
    case it exists to catch. ``BEGIN EXCLUSIVE`` is the question SQLite
    itself answers.
    """
    probe = sqlite3.connect(str(db), timeout=0.2)
    try:
        probe.execute("BEGIN EXCLUSIVE")
        probe.rollback()
        # …and, having established that nobody else holds it, FOLD THE
        # WAL IN. This is what actually makes the move-aside keep the
        # recent writes: a `.db` separated from its `-wal` is a database
        # missing every commit since the last checkpoint. Moving the
        # sidecars along (below) is the belt to this braces — it covers
        # the case where a checkpoint cannot complete.
        probe.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError as exc:
        raise SystemExit(
            f"{db} is in use ({exc}) — stop the servers before restoring"
        )
    finally:
        probe.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="source", type=Path, default=None,
                    help="a backup directory (default: the newest)")
    ap.add_argument("--drill", action="store_true",
                    help="restore into a temp dir and verify; never writes "
                         "to the live paths")
    ap.add_argument("--to-db", type=Path, default=None)
    ap.add_argument("--to-blobs", type=Path, default=None)
    ap.add_argument("--i-mean-it", action="store_true",
                    help="required for a real restore over live data")
    args = ap.parse_args(argv)

    backup = args.source or newest(_work() / "backups")

    if args.drill or not args.i_mean_it:
        if not args.drill:
            print("refusing to restore without --i-mean-it; "
                  "running the drill instead\n")
        findings = drill(backup)
        print(f"DRILL PASSED for {findings['backup']}")
        for check in findings["checks"]:
            print(f"  ok  {check}")
        for label, count in findings["libraries"]:
            print(f"    {label}: {count} books")
        return 0

    restore(backup, args.to_db or default_db(), args.to_blobs or default_blobs())
    print("NOTE: restart the servers -- they hold no connection to the "
          "file you just replaced, but they do hold the old one's state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
