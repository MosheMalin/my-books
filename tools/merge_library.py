# -*- coding: utf-8 -*-
"""Merge a mis-modelled library back into the collection it belongs to.

    python tools/merge_library.py --src <id> --dst <id>              # dry run
    python tools/merge_library.py --src <id> --dst <id> --execute \
        --label-unnamed-shelves "אצל ההורים"

The §4.1 cleanup tool (owner, 2026-08-10): a location that was modelled as a
TENANT before Place existed moves back — books, copies, shelves, captures,
reads and photos, identities intact, colliding works becoming additional
copies of the books already owned. See `app/adapters/merge_library.py` for
the rules; this CLI adds the operational safety:

  - **dry run by default** — reports what would move and which works collide,
    writes nothing;
  - **`--execute` snapshots first**, automatically: the database file (plus
    WAL/SHM sidecars) and BOTH libraries' blob trees are copied to
    `work/backups/merge-<stamp>/` before a byte changes. Restoring is copying
    them back.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.disk_blobs import DiskBlobStore          # noqa: E402
from app.adapters.merge_library import (                   # noqa: E402
    MergeRefused,
    merge_library,
)
from app.domain import LibraryRef                          # noqa: E402


def _work() -> Path:
    return Path(os.environ.get("BOOKSNAP_WORK", REPO_ROOT / "work"))


def _dry_run(db: Path, src: str, dst: str) -> int:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        for lib, name in ((src, "source"), (dst, "target")):
            row = conn.execute("SELECT label FROM libraries WHERE id = ?",
                               (lib,)).fetchone()
            if row is None:
                print(f"no such {name} library: {lib}")
                return 2
            print(f"{name}: {lib}  ({row['label'] or 'unnamed'})")
        for table in ("books", "shelves", "captures", "reads",
                      "decisions", "duplicate_questions"):
            n = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE library_id = ?",
                (src,)).fetchone()[0]
            print(f"  would move {table}: {n}")
        rows = conn.execute(
            """SELECT s.title, s.author FROM books s JOIN books d
               ON d.library_id = ? AND d.book_key = s.book_key
               WHERE s.library_id = ?""", (dst, src)).fetchall()
        for r in rows:
            print(f"  collision -> becomes another copy of: "
                  f"{r['title']} / {r['author']}")
        print("\ndry run — nothing written. Re-run with --execute to merge "
              "(a backup is taken automatically).")
        return 0
    finally:
        conn.close()


def _backup(db: Path, blob_root: Path, src: str, dst: str) -> Path:
    """A CONSISTENT snapshot, then proof it is one.

    ⚠ Not `shutil.copy2` of db + wal (review F3): copying a live WAL
    database as separate files is not a snapshot — a checkpoint landing
    between the two copies silently loses committed rows, and a backup
    nobody verified is a belief, not a safety net. SQLite's backup API
    produces one consistent file whatever a concurrent writer does, and the
    integrity check is run ON THE BACKUP before anything destructive starts.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = _work() / "backups" / f"merge-{stamp}"
    target.mkdir(parents=True, exist_ok=False)
    backup_db = target / db.name
    with sqlite3.connect(str(db)) as source_conn, \
            sqlite3.connect(str(backup_db)) as backup_conn:
        source_conn.backup(backup_conn)
    with sqlite3.connect(str(backup_db)) as check:
        verdict = check.execute("PRAGMA integrity_check").fetchone()[0]
    if verdict != "ok":
        raise SystemExit(
            f"the BACKUP failed its integrity check ({verdict}) — refusing "
            "to merge without a safety net"
        )
    for lib in (src, dst):
        tree = blob_root / "libraries" / lib
        if tree.is_dir():
            shutil.copytree(tree, target / "blobs" / lib)
    return target


def main() -> int:
    # The report prints Hebrew titles; the Windows console codepage either
    # renders them as mojibake (cp1255 — defeating the dry run's one job,
    # letting a human read WHICH works collide) or raises UnicodeEncodeError
    # AFTER the commit, which looks like a failed merge that actually
    # succeeded (review F4).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, help="library id to retire")
    ap.add_argument("--dst", required=True, help="library id that absorbs it")
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--blobs", type=Path, default=None)
    ap.add_argument("--execute", action="store_true",
                    help="actually merge (default is a dry run)")
    ap.add_argument("--confirm-retire", default=None, metavar="SRC_ID",
                    help="required with --execute: repeat the SOURCE id. "
                         "Naming the library being RETIRED is what catches "
                         "swapped --src/--dst before it retires the main "
                         "collection (review F7).")
    ap.add_argument("--label-unnamed-shelves", default="",
                    help="label to give the source's UNNAMED shelves, so the "
                         "location survives until P6.1's Place (e.g. "
                         "'אצל ההורים'). Named shelves keep their own.")
    args = ap.parse_args()

    db = args.db or Path(os.environ.get("BOOKSNAP_DB", _work() / "product.db"))
    blob_root = args.blobs or Path(os.environ.get("BOOKSNAP_BLOBS",
                                                  _work() / "product_blobs"))
    if not db.exists():
        print(f"no database at {db}")
        return 2

    # The dev principal's own library is re-bootstrapped by app/main.py on
    # the next server start — retiring it would resurrect an EMPTY ghost
    # while its books live under another id (review F9).
    default_lib = os.environ.get("BOOKSNAP_DEV_LIBRARY", "dev-library")
    if args.src == default_lib:
        print(f"REFUSED: {args.src} is the principal's own default library — "
              "retiring it would just re-bootstrap an empty ghost. You "
              "almost certainly meant it as --dst.")
        return 1

    if not args.execute:
        return _dry_run(db, args.src, args.dst)
    if args.confirm_retire != args.src:
        print("REFUSED: --execute needs --confirm-retire with the SOURCE id "
              f"({args.src}) repeated verbatim — the check that catches "
              "swapped --src/--dst. Run the dry run first and read the "
              "collision list.")
        return 1

    backup = _backup(db, blob_root, args.src, args.dst)
    print(f"backup: {backup}")
    try:
        report = merge_library(
            db, args.src, args.dst, DiskBlobStore(blob_root),
            label_unnamed_shelves=args.label_unnamed_shelves,
        )
    except MergeRefused as exc:
        print(f"REFUSED: {exc}")
        print(f"nothing merged; the backup at {backup} is redundant but kept")
        return 1
    print(report.summary())
    print(f"\nmerged. The backup at {backup} restores the pre-merge state if "
          "anything looks wrong.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
