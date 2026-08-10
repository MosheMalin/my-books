# -*- coding: utf-8 -*-
"""Report (or collect) orphaned photo blobs — bytes no capture or claim names.

    python tools/blob_gc.py                          # dry run, every library
    python tools/blob_gc.py --library dev-library    # dry run, one library
    python tools/blob_gc.py --collect                # actually delete orphans
    python tools/blob_gc.py --min-age-hours 48       # raise the safety floor

Dry-run BY DEFAULT, and the dry run is the same code path as the real one
minus the deletes (`app.blob_lifecycle.find_orphans` vs `collect_orphans`) —
so the printed plan is exactly what `--collect` would do, not an estimate.

The age floor (24h default) is a safety, not a tuning knob: upload and
capture-binding are two API calls, so a blob is legitimately unreferenced for
the whole afternoon someone spends dropping photos before filing them.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.disk_blobs import DiskBlobStore              # noqa: E402
from app.adapters.sqlite_store import (                        # noqa: E402
    SqliteReadStore,
    SqliteShelfStore,
    SqliteTenancyStore,
)
from app.blob_lifecycle import (                               # noqa: E402
    DEFAULT_MIN_AGE_S,
    collect_orphans,
    find_orphans,
)
from app.domain import LibraryRef                              # noqa: E402


def _work() -> Path:
    return Path(os.environ.get("BOOKSNAP_WORK", REPO_ROOT / "work"))


def _libraries(db: Path, only: str | None) -> list[LibraryRef]:
    """Every library the blob tree could belong to, from the tenancy rows —
    the same source the resolver serves, so a library with photos but no row
    is itself worth noticing (it is printed, never silently skipped)."""
    if only:
        return [LibraryRef(id=only, label="")]
    tenancy = SqliteTenancyStore(db)
    with tenancy._connect() as conn:  # tool-only reach-in; no port lists ALL libraries
        rows = conn.execute("SELECT id, label FROM libraries ORDER BY id").fetchall()
    return [LibraryRef(id=r["id"], label=r["label"] or "") for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=None,
                    help="product database (default <work>/product.db)")
    ap.add_argument("--blobs", type=Path, default=None,
                    help="blob root (default <work>/product_blobs)")
    ap.add_argument("--library", default=None, help="one library id only")
    ap.add_argument("--collect", action="store_true",
                    help="DELETE the orphans (default is a dry run)")
    ap.add_argument("--min-age-hours", type=float,
                    default=DEFAULT_MIN_AGE_S / 3600,
                    help="never touch blobs younger than this (default 24)")
    args = ap.parse_args()

    db = args.db or Path(os.environ.get("BOOKSNAP_DB", _work() / "product.db"))
    blob_root = args.blobs or Path(os.environ.get("BOOKSNAP_BLOBS",
                                                  _work() / "product_blobs"))
    if not db.exists():
        print(f"no database at {db}")
        return 2

    blobs = DiskBlobStore(blob_root)
    shelves = SqliteShelfStore(db)
    reads = SqliteReadStore(db)
    min_age_s = args.min_age_hours * 3600
    run = collect_orphans if args.collect else find_orphans

    total_orphans = 0
    for library in _libraries(db, args.library):
        plan = run(library, blobs, shelves, reads, min_age_s=min_age_s)
        total_orphans += len(plan.orphans)
        verb = "collected" if args.collect else "would collect"
        print(f"{library.id}: {plan.stored} stored, {plan.referenced} referenced, "
              f"{len(plan.too_young)} too young to touch — {verb} "
              f"{len(plan.orphans)}")
        for key in plan.orphans:
            print(f"  - {key}")
    if not args.collect and total_orphans:
        print("\ndry run — re-run with --collect to delete these")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
