# -*- coding: utf-8 -*-
"""P1.3 / H6 — the legacy import, against a committed fixture.

The owner's 251 confirmed books and 155 review decisions **cannot be
re-derived**: re-running the pipeline reproduces the claims but not the human
judgements on them (§11.3). So this import is a required deliverable, and the
tests below are what stand between it and a silent mis-mapping.

Two rings in one file, deliberately:

  - the **pure** mapping (``to_books``) tested case by case from dicts, which
    is where the tricky rules live — re-keying, status, dating a sighting;
  - the **fixture** end to end, from ``fixtures/legacy/``, which is committed
    so a fresh clone with no ``work/`` at all still runs this;
  - plus a **real-data** check that self-skips when ``work/`` isn't on the
    machine, the same way ``tools/spotcheck.py`` does. A fixture proves the
    shapes it contains; only the real file proves there are no others.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.legacy_import import (
    LegacySnapshot,
    import_legacy,
    read_snapshot,
    stable_id,
    to_books,
    unmigrated_rejections,
)
from app.adapters.memory_store import MemoryBookStore
from app.domain import LibraryRef, Status, book_key, edit
from app.ports.store import BookSort

FIXTURE = REPO_ROOT / "fixtures" / "legacy"
WORK = Path(os.environ.get("BOOKSNAP_WORK", REPO_ROOT / "work"))
LIB = LibraryRef("lib-import", "Import target")


def _snapshot(books: dict, runs: dict | None = None,
              images: dict | None = None, decisions: dict | None = None):
    return LegacySnapshot(books=books, runs=runs or {}, images=images or {},
                          decisions=decisions or {})


def _entry(title, author="", status="auto", **source):
    return {book_key(title, author): {
        "title": title, "author": author, "status": status,
        "source": {"run_id": "r1", "spine_id": "img1_b0_s00", **source}}}


def _fixture_import():
    store = MemoryBookStore()
    return store, import_legacy(FIXTURE, LIB, store)


# --- the fixture, end to end ---------------------------------------------

def test_the_fixture_imports_every_book_with_no_problems():
    store, report = _fixture_import()
    assert report.books_read == 9
    assert report.books_written == 9
    assert report.problems == (), report.problems
    assert store.count(LIB) == 9


def test_the_fixture_covers_every_status_the_real_data_produces():
    """If a shape stops being represented the fixture stops proving anything
    about it — so the distribution is pinned, not just the total."""
    _, report = _fixture_import()
    assert report.by_status == {"manual": 4, "approved": 3, "auto": 2}


def test_every_imported_book_has_exactly_one_copy():
    """§5.1: copies are created by the user, never inferred. An import that
    invented a second copy would be the matcher auto-creating one by proxy."""
    store, _ = _fixture_import()
    for b in store.list(LIB, limit=100).items:
        assert b.copy_count == 1, b.title


def test_locations_are_null_by_design_not_by_accident():
    """§1.1: a book's physical location is derived from the map, which does
    not exist until pillar 6. Guessing a shelf here would be inventing data
    that later has to be un-invented."""
    store, _ = _fixture_import()
    for b in store.list(LIB, limit=100).items:
        assert b.copies[0].shelf_id is None, b.title
        assert all(p.shelf_id is None for p in b.copies[0].provenance)


def test_each_book_carries_exactly_one_provenance_entry():
    """The honest scope: one sighting each, naming the run and spine it came
    from. That is what `library.py`'s `source` field has always held."""
    store, _ = _fixture_import()
    for b in store.list(LIB, limit=100).items:
        prov = b.copies[0].provenance
        assert len(prov) == 1, b.title
        assert prov[0].run_id and prov[0].spine_id


def test_the_fixture_surfaces_rejections_that_have_nowhere_to_live():
    """§5.6 says a rejected book must not be re-added by a later run. The
    product has no home for that yet (a rejection is scoped to a SHELF, P2.1).
    Reported loudly rather than dropped, so the gap cannot be discovered by a
    re-read instead."""
    _, report = _fixture_import()
    assert len(report.rejections_not_migrated) == 11
    assert "!!" in report.summary()


# --- re-keying: the case most likely to break later -----------------------

def test_stored_keys_are_recomputed_never_trusted():
    """30 of the owner's 251 keys predate the geresh fix in normalize(): they
    read "צ רלס סטרוס" where today's key is "צרלס סטרוס". Imported verbatim,
    those books would carry a key no future lookup could ever produce."""
    _, report = _fixture_import()
    assert len(report.rekeyed) == 4, report.rekeyed

    raw = json.loads((FIXTURE / "library.json").read_text(encoding="utf-8"))
    for stale in report.rekeyed:
        entry = raw["books"][stale]
        assert book_key(entry["title"], entry["author"]) != stale, (
            f"{stale!r} was reported as re-keyed but recomputes to itself")


def test_a_rekeyed_book_is_findable_by_its_current_key():
    """The point of re-keying, asserted through the store rather than the
    report — this is what a later `get_by_key` will actually do."""
    store, report = _fixture_import()
    raw = json.loads((FIXTURE / "library.json").read_text(encoding="utf-8"))
    for stale in report.rekeyed:
        entry = raw["books"][stale]
        found = store.get_by_key(LIB, book_key(entry["title"], entry["author"]))
        assert found is not None, stale
        assert store.get_by_key(LIB, stale) is None, "stale key still resolves"


def test_two_entries_collapsing_to_one_key_are_reported_not_dropped():
    """Re-keying CAN merge two old rows. Measured: it does not on the real 251
    (zero collisions). If it ever does, the import must say so — silently
    keeping one is how a book disappears."""
    books = {}
    books.update(_entry("הצ'ופצ'יק", "מאיר שלו", status="approved"))
    books["הצ ופצ יק|מאיר שלו"] = {           # a pre-geresh spelling
        "title": "הצ'ופצ'יק", "author": "מאיר שלו", "status": "auto",
        "source": {"run_id": "r9", "spine_id": "s9"}}

    out, rekeyed, problems = to_books(_snapshot(books), LIB)
    assert len(out) == 1
    assert len(problems) == 1 and "collapse" in problems[0]


# --- status mapping -------------------------------------------------------

def test_status_mapping_covers_every_source_shape():
    cases = [
        (_entry("א", status="auto"), Status.AUTO),
        (_entry("ב", status="approved"), Status.APPROVED),
        (_entry("ג", status="approved", manual=True), Status.MANUAL),
        (_entry("ד", status="approved", replaced="שם ישן"), Status.APPROVED),
    ]
    for books, expected in cases:
        out, _, _ = to_books(_snapshot(books), LIB)
        assert out[0].status is expected, (out[0].title, out[0].status)


def test_a_manual_add_is_manual_whichever_spine_id_format_it_used():
    """The plan expected manual adds to be identifiable by an `owner-fb-…`
    spine id. They are not: 9 of the owner's 24 use `manual-<timestamp>`, and
    `owner-fb-` also covers 5 books that were REPLACED rather than typed. The
    reliable marker is `source.manual`."""
    for spine in ("owner-fb-הענן השחור", "manual-1786050722680", "whatever"):
        books = _entry("הענן השחור", "פרד הויל", status="approved",
                       manual=True, spine_id=spine)
        out, _, _ = to_books(_snapshot(books), LIB)
        assert out[0].status is Status.MANUAL, spine


def test_an_imported_book_can_never_be_demoted_by_a_later_read():
    """The whole point of importing the status rather than re-deriving it: a
    re-read must not undo the owner's 141 confirmations (§5.6)."""
    from app.domain import Provenance, observe

    store, _ = _fixture_import()
    approved = [b for b in store.list(LIB, limit=100).items
                if b.status is not Status.AUTO]
    assert approved
    for b in approved[:3]:
        after = observe(b, Provenance("later-run", "sp1"), status=Status.AUTO)
        assert after.status is b.status


# --- dating a sighting ----------------------------------------------------

def test_a_sighting_is_dated_from_its_image_when_the_spine_names_one():
    """A spine id is `<image_id>_b<n>_s<nn>`, so the photo is identifiable
    without opening runs/*."""
    snap = _snapshot(
        _entry("ספר", spine_id="img7_b0_s03"),
        runs={"r1": {"run_id": "r1", "finished_at": "2026-01-02T00:00:00+00:00"}},
        images={"img7": {"uploaded_at": "2025-12-25T10:00:00+00:00"}},
    )
    out, _, _ = to_books(snap, LIB)
    assert out[0].added_at == "2025-12-25T10:00:00+00:00"


def test_a_hand_typed_book_falls_back_to_its_run_and_then_to_nothing():
    """`owner-fb-…` and `manual-…` ids name no image. The run's end time is
    the honest answer; None is the honest answer when even that is unknown."""
    books = _entry("ספר", manual=True, spine_id="owner-fb-ספר")
    runs = {"r1": {"run_id": "r1", "finished_at": "2026-01-02T00:00:00+00:00"}}
    out, _, _ = to_books(_snapshot(books, runs=runs), LIB)
    assert out[0].added_at == "2026-01-02T00:00:00+00:00"

    out, _, _ = to_books(_snapshot(books), LIB)
    assert out[0].added_at is None, "a date was invented"


def test_runs_are_read_from_store_jsons_real_dict_shape():
    """`store.json`'s `runs` is a DICT keyed by run_id. Reading it as a list
    fails SILENTLY — iterating a dict yields strings, an isinstance guard drops
    them all, and every book quietly loses its date. Caught by the fixture, so
    it is pinned here."""
    raw = json.loads((FIXTURE / "store.json").read_text(encoding="utf-8"))
    assert isinstance(raw["runs"], dict), "fixture drifted from the real shape"
    assert read_snapshot(FIXTURE).runs, "runs read as empty"

    # …and the list form is still accepted, so an older store.json imports too.
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "store.json").write_text(json.dumps(
            {"runs": [{"run_id": "r1", "finished_at": "2026-01-01T00:00:00+00:00"}],
             "images": {}}), encoding="utf-8")
        assert list(read_snapshot(d).runs) == ["r1"]


# --- re-runnable, non-destructive ----------------------------------------

def test_importing_twice_does_not_duplicate_anything():
    """Ids are minted deterministically from (library, key) for exactly this
    reason — a resumed or repeated import must converge, not accumulate."""
    store = MemoryBookStore()
    first = import_legacy(FIXTURE, LIB, store)
    ids = sorted(b.id for b in store.list(LIB, limit=100).items)

    second = import_legacy(FIXTURE, LIB, store)
    assert second.books_written == 0
    assert len(second.already_present) == first.books_written
    assert store.count(LIB) == 9
    assert sorted(b.id for b in store.list(LIB, limit=100).items) == ids


def test_a_second_import_never_reverts_an_edit():
    """After the first import the owner starts fixing titles. A re-run that
    silently restored the imported text would destroy exactly the work this
    import exists to preserve."""
    store = MemoryBookStore()
    import_legacy(FIXTURE, LIB, store)
    victim = store.list(LIB, sort=BookSort.TITLE, limit=1).items[0]
    store.save(LIB, edit(victim, title="כותרת מתוקנת"))

    report = import_legacy(FIXTURE, LIB, store)
    kept = store.get(LIB, victim.id)
    assert kept.title == "כותרת מתוקנת", "a re-import reverted an edit"
    assert kept.status is Status.MANUAL
    # …and it did not sneak the original back in beside it. This is the half
    # a key-only "already present" check gets wrong: the edited book's key no
    # longer matches, so only the deterministic ID still identifies it.
    assert store.count(LIB) == 9
    assert report.books_written == 0


def test_ids_are_stable_across_processes_and_scoped_to_the_library():
    a = stable_id("lib-1", "כותרת|מחבר")
    assert a == stable_id("lib-1", "כותרת|מחבר")
    assert a != stable_id("lib-2", "כותרת|מחבר")
    assert a != stable_id("lib-1", "כותרת|מחבר", suffix="|copy-1")


def test_an_empty_or_missing_work_dir_imports_nothing_and_does_not_crash():
    """A fresh clone has no work/. That is a normal state, not an error."""
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryBookStore()
        report = import_legacy(Path(tmp), LIB, store)
        assert report.books_read == 0 and report.books_written == 0
        assert store.count(LIB) == 0


def test_an_entry_with_no_title_is_reported_not_silently_dropped():
    books = {"|מחבר": {"title": "", "author": "מחבר", "status": "auto"}}
    out, _, problems = to_books(_snapshot(books), LIB)
    assert out == [] and len(problems) == 1


# --- the real thing, when it is on this machine ---------------------------

def test_the_owners_real_library_imports_cleanly():
    """Self-skips without work/, like tools/spotcheck.py does without run data.

    A fixture proves the shapes it contains; only the real file proves there
    are no others. Deliberately NOT pinned to 251 — the owner keeps
    cataloguing — so it asserts the invariants instead: everything read is
    written, nothing collides, and the totals reconcile with the source file.
    """
    lib_path = WORK / "library.json"
    if not lib_path.exists():
        print("    (skipped: no work/library.json on this machine)")
        return

    raw = json.loads(lib_path.read_text(encoding="utf-8"))["books"]
    store = MemoryBookStore()
    report = import_legacy(WORK, LIB, store)

    assert report.problems == (), report.problems
    assert report.books_read == len(raw)
    assert report.books_written == len(raw), "books were lost in the mapping"
    assert store.count(LIB) == len(raw)
    assert sum(report.by_status.values()) == len(raw)
    # Every book keeps a sighting and gains no location.
    for b in store.list(LIB, limit=10_000).items:
        assert b.copy_count == 1
        assert b.copies[0].shelf_id is None
        assert len(b.copies[0].provenance) == 1


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))
