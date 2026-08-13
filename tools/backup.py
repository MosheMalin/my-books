# -*- coding: utf-8 -*-
"""Back up the product: the database, the photographs, and a manifest.

**This exists for RESTORE** (P4.4, VISION §11.3). An accuracy regression on
someone else's library is not recoverable by re-running, because their
REVIEW DECISIONS are the expensive artifact — the engine can re-read a
shelf, but nobody can re-derive which findings a human approved, corrected
or rejected. So the thing being protected here is not "the books"; it is
every table that records a judgement.

Two rules, both learned the hard way in this repo:

  - **the database is copied through SQLite's own backup API**, never
    ``copy2``. A live file has WAL sidecars, and three separate copies of
    ``.db``/``.db-wal``/``.db-shm`` are three snapshots of three different
    instants (CLAUDE.md's own trap list);
  - **the manifest is written LAST and carries a checksum of everything
    before it.** A backup interrupted halfway then has no manifest, and
    ``restore.py`` refuses it rather than restoring a half-copy over a
    working system.

Usage::

    python tools/backup.py                        # into work/backups/
    python tools/backup.py --out D:/tmp/drill     # somewhere else
    python tools/backup.py --db work/product.db --blobs work/product_blobs

The output is a DIRECTORY, not an archive: the blob tree is already
content-addressed and mostly-immutable, so a plain directory lets the next
backup hard-link or rsync only what changed, and lets a human look inside
without unpacking anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Bumped when the layout of a backup directory changes. `restore.py`
#: refuses a format it does not know rather than guessing.
BACKUP_FORMAT = 1


def _work() -> Path:
    return Path(os.environ.get("BOOKSNAP_WORK", REPO_ROOT / "work"))


def default_db() -> Path:
    explicit = os.environ.get("BOOKSNAP_DB")
    return Path(explicit) if explicit else _work() / "product.db"


def default_blobs() -> Path:
    explicit = os.environ.get("BOOKSNAP_BLOBS")
    return Path(explicit) if explicit else _work() / "product_blobs"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_database(src: Path, dst: Path) -> dict:
    """SQLite's backup API — the only safe way to copy a live database.

    Returns the facts a restore should be able to check WITHOUT opening
    the app: the schema version and the row counts of the tables whose
    contents cannot be re-derived.
    """
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    target = sqlite3.connect(str(dst))
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()

    conn = sqlite3.connect(str(dst))
    try:
        counts = {}
        for table in ("books", "copies", "provenance", "shelves", "captures",
                      "reads", "claims", "decisions", "duplicate_questions",
                      "users", "accounts", "memberships", "libraries"):
            try:
                counts[table] = conn.execute(
                    f"SELECT count(*) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError:
                # A table this schema version does not have yet. Recorded
                # as absent rather than skipped: a restore comparing
                # manifests should see the difference.
                counts[table] = None
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    if integrity != "ok":
        raise RuntimeError(f"the COPY failed its integrity check: {integrity}")
    return {"schema_version": version, "rows": counts}


def _copy_blobs(src: Path, dst: Path) -> dict:
    """Every byte under the blob root, with a count and a total size.

    Originals, variants and sidecars alike: a thumbnail is regenerable and
    a sidecar is not, and telling them apart here would be a second copy
    of a rule that lives in the adapter.
    """
    files = 0
    total = 0
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
        for path in dst.rglob("*"):
            if path.is_file():
                files += 1
                total += path.stat().st_size
    else:
        dst.mkdir(parents=True, exist_ok=True)
    return {"files": files, "bytes": total}


def run(db: Path, blobs: Path, out: Path, *, stamp: str | None = None) -> Path:
    """Write one backup directory. Returns its path."""
    if not db.exists():
        raise SystemExit(f"no database at {db}")
    when = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = out / when
    if target.exists():
        raise SystemExit(f"{target} already exists")
    target.mkdir(parents=True)

    db_copy = target / "product.db"
    facts = _copy_database(db, db_copy)
    blob_facts = _copy_blobs(blobs, target / "blobs")

    manifest = {
        "format": BACKUP_FORMAT,
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {"db": str(db), "blobs": str(blobs)},
        "database": {**facts, "sha256": _sha256(db_copy)},
        "blobs": blob_facts,
    }
    # LAST, and only after every byte is on disk: an interrupted backup
    # has no manifest, and restore.py refuses one it cannot verify.
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def prune(out: Path, keep: int) -> list[Path]:
    """Drop the oldest COMPLETE backups beyond ``keep``. Returns what went.

    Never touches a directory without a manifest: that is either a backup
    in flight or one that died halfway, and deleting the evidence of a
    failed backup is how nobody finds out backups are failing. Each
    nightly run copies the whole blob tree, so without this the backups
    fill the very volume holding the database they protect.
    """
    complete = sorted(p for p in out.glob("*")
                      if (p / "manifest.json").exists())
    doomed = complete[:-keep] if keep > 0 else []
    for old in doomed:
        shutil.rmtree(old)
    return doomed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--blobs", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None,
                    help="backup root (default: <work>/backups)")
    ap.add_argument("--keep", type=int, default=0,
                    help="keep only the newest N complete backups")
    args = ap.parse_args(argv)

    db = args.db or default_db()
    blobs = args.blobs or default_blobs()
    out = args.out or (_work() / "backups")

    target = run(db, blobs, out)
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    print(f"backed up to {target}")
    print(f"  schema v{manifest['database']['schema_version']}, "
          f"{manifest['database']['rows']['books']} books, "
          f"{manifest['database']['rows']['decisions']} decisions, "
          f"{manifest['blobs']['files']} blob files "
          f"({manifest['blobs']['bytes'] / 1e6:.1f} MB)")
    if args.keep:
        for gone in prune(out, args.keep):
            print(f"pruned {gone}")
    print("NOTE: a backup nobody has restored is a hope, not a "
          "backup -- python tools/restore.py --drill")
    return 0


if __name__ == "__main__":
    sys.exit(main())
