# -*- coding: utf-8 -*-
"""Run (or rehearse) the legacy import; export the committed test fixture.

    python tools/import_legacy.py --dry-run           # report, write nothing
    python tools/import_legacy.py --db work/product.db
    python tools/import_legacy.py --export-fixture    # refresh fixtures/legacy/

``--dry-run`` imports into an in-memory store and prints the same report, so
the mapping can be checked against the real 251 books without creating a
database. Worth doing first: the import is safe to re-run, but reading the
report before writing is cheaper than reading it after.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.legacy_import import (  # noqa: E402
    import_legacy,
    read_snapshot,
    to_books,
)
from app.adapters.memory_store import MemoryBookStore  # noqa: E402
from app.adapters.sqlite_store import SqliteBookStore  # noqa: E402
from app.domain import LibraryRef, book_key  # noqa: E402

FIXTURE_DIR = REPO_ROOT / "fixtures" / "legacy"


def _default_work() -> Path:
    import os

    return Path(os.environ.get("BOOKSNAP_WORK", REPO_ROOT / "work"))


def cmd_import(work: Path, library: LibraryRef, db: Path | None) -> int:
    store = MemoryBookStore() if db is None else SqliteBookStore(db)
    report = import_legacy(work, library, store)
    print(f"source: {work}")
    print(f"target: {'(dry run, in memory)' if db is None else db}")
    print(report.summary())
    if report.rejections_not_migrated:
        print("\nrejected claims with nowhere to live yet:")
        for r in report.rejections_not_migrated:
            print(f"  - {r}")
    return 0


def cmd_export_fixture(work: Path) -> int:
    """Sample the real ``work/`` into a small committed fixture (H6).

    Selection is by SHAPE, not at random: every distinct source shape the real
    data contains must appear, or the fixture stops proving anything. Includes
    a stale-key entry on purpose — that is the case most likely to be broken
    by a future normalize() change.
    """
    snapshot = read_snapshot(work)
    if not snapshot.books:
        print(f"no library.json under {work} — nothing to export")
        return 1

    picked: dict[str, dict] = {}

    def take(label, predicate, n=2):
        got = 0
        for key, entry in snapshot.books.items():
            if key in picked or not predicate(key, entry):
                continue
            picked[key] = entry
            got += 1
            if got >= n:
                break
        if not got:
            print(f"  WARNING: no sample found for shape {label!r}")
        else:
            print(f"  {label}: {got}")

    def src(entry):
        return entry.get("source") or {}

    def stale(key, entry):
        return key != book_key(entry.get("title", ""), entry.get("author", ""))

    print("sampling by shape:")
    # Stale keys first, so they are guaranteed present rather than incidental.
    take("stale key (pre-geresh normalize)", stale, n=2)
    take("manual add, owner-fb spine id",
         lambda k, e: src(e).get("manual")
         and str(src(e).get("spine_id", "")).startswith("owner-fb-"), n=1)
    take("manual add, manual-<ts> spine id",
         lambda k, e: src(e).get("manual")
         and str(src(e).get("spine_id", "")).startswith("manual-"), n=1)
    take("replaced from alternatives",
         lambda k, e: bool(src(e).get("replaced")), n=1)
    take("auto", lambda k, e: e.get("status") == "auto", n=2)
    take("approved from a real spine",
         lambda k, e: e.get("status") == "approved" and not src(e).get("manual")
         and "_b" in str(src(e).get("spine_id", "")), n=2)

    # Keep only the runs/images these books actually reference, and prune the
    # per-run `config` and `images` blobs: the importer never reads them, and
    # they carry absolute paths off the owner's machine.
    run_ids = {src(e).get("run_id") for e in picked.values()}
    image_ids = {str(src(e).get("spine_id", "")).split("_", 1)[0]
                 for e in picked.values()}
    # Keep store.json's real shape: `runs` is a DICT keyed by run_id.
    runs = {rid: {k: v for k, v in r.items() if k not in ("config", "images")}
            for rid, r in snapshot.runs.items() if rid in run_ids}
    images = {i: img for i, img in snapshot.images.items() if i in image_ids}

    decisions = {}
    for run_id, per_run in snapshot.decisions.items():
        keep = {sid: d for sid, d in per_run.items()
                if d.get("action") in ("reject_ignore", "manual_add", "replace")}
        if keep:
            decisions[run_id] = dict(list(keep.items())[:3])

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    _write(FIXTURE_DIR / "library.json", {"books": picked})
    _write(FIXTURE_DIR / "store.json",
           {"runs": runs, "images": images, "next_run_no": 1})
    _write(FIXTURE_DIR / "decisions.json", decisions)
    (FIXTURE_DIR / "README.md").write_text(_manifest(picked, runs, images,
                                                     decisions),
                                           encoding="utf-8")
    print(f"\nwrote {len(picked)} books to {FIXTURE_DIR.relative_to(REPO_ROOT)}")
    return 0


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")


def _manifest(books, runs, images, decisions) -> str:
    return f"""# fixtures/legacy — a sample of today's `work/` shapes

Committed so `tests/test_legacy_import.py` runs on a fresh clone with no
`work/` directory at all (plan H6: "a committed fixtures/legacy/ sample of
today's work/ shapes, and a test asserting the import produces the expected
entities").

Regenerate with:

    python tools/import_legacy.py --export-fixture

**Sampled by SHAPE, not at random** — every distinct `source` shape the real
data contains appears here, because a fixture that misses one stops proving
anything about it. Currently {len(books)} books, {len(runs)} run(s),
{len(images)} image(s), {sum(len(v) for v in decisions.values())} decision(s).

Shapes covered:

| Shape | Why it is here |
|---|---|
| stale key | 30 of the owner's 251 keys predate the geresh fix in `normalize()`; the importer must RE-KEY rather than trust the file |
| `source.manual` + `owner-fb-<title>` spine id | a book typed in from the review screen |
| `source.manual` + `manual-<timestamp>` spine id | the same action, a different id format — `owner-fb-` alone would miss 9 of the 24 |
| `source.replaced` | a human picked from ranked alternatives; imported as `approved`, not `manual` |
| `status: auto` | absorbed from an AUTO claim, never looked at |
| `status: approved`, real spine id | the common case; its `<image_id>_b<n>_s<nn>` prefix is what dates the sighting |

Pruned from `store.json`: each run's `config` snapshot and per-image detail.
The importer never reads them, and they carry absolute paths from the owner's
machine. Everything the importer DOES read is verbatim.

The owner's own book titles. Not synthetic — a hand-written fixture would have
agreed with whatever the importer happened to do.
"""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", type=Path, default=None,
                    help="source work/ dir (default: $BOOKSNAP_WORK or ./work)")
    ap.add_argument("--db", type=Path, default=None,
                    help="target sqlite file; omit for a dry run")
    ap.add_argument("--library", default="dev-library")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit form of omitting --db")
    ap.add_argument("--export-fixture", action="store_true",
                    help="refresh fixtures/legacy/ from --work")
    args = ap.parse_args(argv)

    work = args.work or _default_work()
    if args.export_fixture:
        return cmd_export_fixture(work)
    db = None if args.dry_run else args.db
    return cmd_import(work, LibraryRef(args.library), db)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
