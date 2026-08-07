# -*- coding: utf-8 -*-
"""H4 ring 2 — ONE store spec, run against EVERY implementation.

This is the suite that makes plan D1 (SQLite now, Postgres later) a decision
rather than a bet. A contract with one implementation is just that
implementation's behaviour written down twice; the second implementation is
what turns it into a spec. So every test below runs against both
``MemoryBookStore`` and ``SqliteBookStore``, and adding a third adapter means
adding one line to ``IMPLEMENTATIONS``.

It also carries the **tenant isolation** suite. Written now, against two
library refs, even though the app resolves exactly one library until pillar 3
— because the store already takes a ``LibraryRef`` on every method, so the
isolation is testable today, and P3.3 inherits a suite instead of writing one
under pressure. §4.2's rule (a foreign record reads as ABSENT, so the API can
answer 404 and not leak existence) is a store-level property; it has to hold
here or the route cannot honour it.

No pytest, so parametrisation is explicit: contract functions are collected by
the ``@contract`` decorator and bound to each implementation at import time
into module-level ``test_*`` names, which is what ``tests/run_all.py`` scans.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.memory_store import MemoryBookStore
from app.adapters.migrations import SCHEMA_VERSION, current_version, migrate
from app.adapters.sqlite_store import SqliteBookStore
from app.domain import (
    LibraryRef,
    Provenance,
    Status,
    add_copy,
    approve,
    edit,
    new_book,
    observe,
    remove_from_shelf,
)
from app.ports.store import (
    BookPage,
    BookSort,
    DuplicateBookKey,
    WrongLibrary,
)

LIB = LibraryRef("lib-a", "Library A")
OTHER = LibraryRef("lib-b", "Library B")

CONTRACT: list = []


def contract(fn):
    """Mark a function as part of the spec. It receives a fresh store."""
    CONTRACT.append(fn)
    return fn


def _book(n: int = 1, *, library: LibraryRef = LIB, title: str | None = None,
          author: str = "פול קארני", **kw):
    return new_book(
        id=f"b{n}",
        library_id=library.id,
        title=title or f"ספר מספר {n}",
        author=author,
        copy_id=f"c{n}",
        **kw,
    )


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"expected {exc.__name__}, nothing raised")


# --- round-trip -----------------------------------------------------------

@contract
def saves_and_reads_back_the_whole_aggregate(store):
    """Copies and provenance travel WITH the book. A store that could write a
    Copy on its own would be a second creation path, and §5.1 says there is
    exactly one."""
    b = _book(shelf_id="s1", added_at="2026-08-01")
    b = observe(b, Provenance("r1", "sp1", shelf_id="s1", captured_at="2026-08-01"))
    b = observe(b, Provenance("r2", "sp4", shelf_id="s1"))
    b = approve(b)
    b = add_copy(b, copy_id="c1b", label="כריכה רכה", shelf_id="s2")
    store.save(LIB, b)

    got = store.get(LIB, b.id)
    assert got == b, "the aggregate did not survive the round trip"


@contract
def round_trips_every_optional_field(store):
    """Guards the columns that are easy to forget in a mapper: tags, lending,
    condition, work fields, shared_book_id."""
    from app.domain import CopyFields, Lending, set_work_fields
    from dataclasses import replace

    b = _book(shelf_id="s1")
    b = set_work_fields(b, rating=4, notes="מתנה מאבא", read_status="read")
    b = replace(b, shared_book_id="shared-77")
    b = replace(b, copies=(replace(
        b.copies[0],
        fields=CopyFields(tags=("חתום", "נדיר"), condition="שמור",
                          acquired_at="2019-03-02"),
        lending=Lending(lent_to="דנה", lent_at="2026-07-01", due_at="2026-08-01"),
    ),))
    store.save(LIB, b)

    got = store.get(LIB, b.id)
    assert got == b
    assert got.copies[0].lending.is_out is True
    assert got.copies[0].fields.tags == ("חתום", "נדיר")


@contract
def save_replaces_rather_than_accumulates(store):
    """Saving twice must not duplicate copies or provenance. The aggregate is
    written whole, so 'replace' is the only correct semantic."""
    b = _book(shelf_id="s1")
    store.save(LIB, b)
    b = observe(b, Provenance("r1", "sp1", shelf_id="s1"))
    store.save(LIB, b)
    store.save(LIB, b)

    got = store.get(LIB, b.id)
    assert got.copy_count == 1
    assert len(got.copies[0].provenance) == 1


@contract
def copy_order_is_preserved(store):
    """Copy #1 is the original; the UI lists them as the owner acquired them."""
    b = _book()
    for i in (2, 3, 4):
        b = add_copy(b, copy_id=f"c1-{i}", label=f"L{i}")
    store.save(LIB, b)
    assert [c.id for c in store.get(LIB, b.id).copies] == \
           [c.id for c in b.copies]


@contract
def missing_book_reads_as_none(store):
    assert store.get(LIB, "nope") is None
    assert store.get_by_key(LIB, "nope|nope") is None


# --- identity (§5.1) ------------------------------------------------------

@contract
def finds_a_book_by_its_normalized_key(store):
    """The identity a read uses to ask "do I already own this?" (§5.4/§5.6)."""
    b = _book(title="מלכי הכופרים", author="פול קארני")
    store.save(LIB, b)
    got = store.get_by_key(LIB, b.key)
    assert got is not None and got.id == b.id


@contract
def two_books_cannot_share_one_key_in_a_library(store):
    """§5.1: one Book per {title, author} per library. A second one is a bug,
    and it must surface — a silent overwrite loses a record the user owns."""
    store.save(LIB, _book(1, title="מלכי הכופרים"))
    clash = _book(2, title="מלכי הכופרים")
    _raises(DuplicateBookKey, store.save, LIB, clash)
    assert store.count(LIB) == 1


@contract
def renaming_onto_an_existing_book_is_refused_not_merged(store):
    """Fixing a misread title onto a book you already own is a real case. The
    store refuses; deciding (merge? keep both?) is P1.4's, not the store's."""
    store.save(LIB, _book(1, title="מלכי הכופרים"))
    b2 = _book(2, title="ספינות מן המערב")
    store.save(LIB, b2)
    _raises(DuplicateBookKey, store.save, LIB, edit(b2, title="מלכי הכופרים"))
    # …and the attempt left nothing behind.
    assert store.get(LIB, "b2").title == "ספינות מן המערב"
    assert store.count(LIB) == 2


@contract
def the_same_key_is_free_in_another_library(store):
    """Uniqueness is per tenant. Two people owning one book is the normal
    case, not a conflict."""
    store.save(LIB, _book(1, title="מלכי הכופרים"))
    store.save(OTHER, _book(2, library=OTHER, title="מלכי הכופרים"))
    assert store.count(LIB) == 1 and store.count(OTHER) == 1


# --- delete-from-library (UI_PLAN §5) ------------------------------------

@contract
def delete_removes_the_book_and_every_copy(store):
    b = add_copy(_book(shelf_id="s1"), copy_id="c1b")
    b = observe(b, Provenance("r1", "sp1", shelf_id="s1"))
    store.save(LIB, b)

    assert store.delete(LIB, b.id) is True
    assert store.get(LIB, b.id) is None
    assert store.delete(LIB, b.id) is False, "second delete must report nothing"
    # The key is free again — the row and its children are really gone, not
    # orphaned behind a still-live unique index.
    store.save(LIB, _book(9, title=b.title, author=b.author))
    assert store.count(LIB) == 1


@contract
def remove_from_shelf_is_persisted_without_losing_the_copy(store):
    """The domain rule, asserted end to end through the store — this is the
    pair that a mapper bug (dropping a NULL shelf_id row) would break."""
    b = observe(_book(shelf_id="s1"), Provenance("r1", "sp1", shelf_id="s1"))
    store.save(LIB, b)
    store.save(LIB, remove_from_shelf(b, "c1"))

    got = store.get(LIB, b.id)
    assert got.copy_count == 1
    assert got.copies[0].shelf_id is None
    assert len(got.copies[0].provenance) == 1, "history was discarded"


# --- listing (§6) ---------------------------------------------------------

@contract
def lists_sorted_by_normalized_title(store):
    """Sorting on the NORMALIZED form is what makes Hebrew order sensibly
    whatever nikud or geresh the stored string carries."""
    for i, t in enumerate(["בית", "אבן", "גדר"], start=1):
        store.save(LIB, _book(i, title=t))
    page = store.list(LIB, sort=BookSort.TITLE)
    assert [b.title for b in page.items] == ["אבן", "בית", "גדר"]
    assert page.total == 3


@contract
def sort_is_a_total_order_so_paging_cannot_skip_or_repeat(store):
    """Ties broken by id. Without a total order two same-titled books page
    inconsistently: the user scrolls, sees one twice and the other never.

    Written to fail on a MISSING tiebreaker, which is harder than it looks:
    inserting in id order and checking for duplicates passes even with no
    tiebreaker at all, because Python's sort is stable and dicts keep
    insertion order. So the books are inserted in DESCENDING id order — then
    only a real ``(title, id)`` ordering produces an ascending page.
    """
    for i in reversed(range(1, 7)):
        store.save(LIB, _book(i, title="אותו שם", author=f"מחבר {i}"))

    seen = []
    for offset in (0, 2, 4):
        seen += [b.id for b in store.list(LIB, limit=2, offset=offset).items]
    assert seen == ["b1", "b2", "b3", "b4", "b5", "b6"], seen


@contract
def paging_reports_the_total_not_the_page_size(store):
    for i in range(1, 8):
        store.save(LIB, _book(i))
    page = store.list(LIB, limit=3, offset=3)
    assert isinstance(page, BookPage)
    assert len(page.items) == 3 and page.total == 7
    assert page.offset == 3 and page.limit == 3
    assert len(store.list(LIB, limit=3, offset=6).items) == 1


@contract
def sorts_by_author_then_title(store):
    store.save(LIB, _book(1, title="ב", author="דורל"))
    store.save(LIB, _book(2, title="א", author="דורל"))
    store.save(LIB, _book(3, title="א", author="אסימוב"))
    page = store.list(LIB, sort=BookSort.AUTHOR)
    assert [b.id for b in page.items] == ["b3", "b2", "b1"]


@contract
def sorts_by_recently_added_and_tolerates_missing_dates(store):
    """P1.3 imports 251 books with no added_at. They must sort together at one
    end rather than scattering by NULL-ordering rules."""
    store.save(LIB, _book(1, added_at="2026-01-01"))
    store.save(LIB, _book(2, added_at="2026-06-01"))
    store.save(LIB, _book(3))  # no date
    ids = [b.id for b in store.list(LIB, sort=BookSort.RECENTLY_ADDED,
                                    ascending=False).items]
    assert ids[:2] == ["b2", "b1"], ids
    assert ids[2] == "b3"


@contract
def filters_by_derived_book_status(store):
    """Status is the strongest claim among a book's copies (§5.2) — derived,
    never stored, so the filter cannot disagree with the entity."""
    store.save(LIB, _book(1))                       # auto
    store.save(LIB, approve(_book(2)))              # approved
    store.save(LIB, edit(_book(3), title="ידני"))   # manual
    store.save(LIB, add_copy(_book(4), copy_id="c4b"))  # manual via copy #2

    for status, ids in [(Status.AUTO, ["b1"]),
                        (Status.APPROVED, ["b2"]),
                        (Status.MANUAL, ["b3", "b4"])]:
        got = sorted(b.id for b in store.list(LIB, status=status).items)
        assert got == ids, (status, got)


@contract
def filters_by_normalized_author(store):
    """The author chip is a grouping over normalized strings, not an entity
    (§5.1) — so a query keyed on the normalized form finds both spellings of
    a name that normalize together."""
    store.save(LIB, _book(1, author="דָּארֶל"))
    store.save(LIB, _book(2, author="דארל"))
    store.save(LIB, _book(3, author="אסימוב"))
    key = store.get(LIB, "b2").normalized_author
    got = sorted(b.id for b in store.list(LIB, author_key=key).items)
    assert got == ["b1", "b2"], got


@contract
def an_empty_library_lists_cleanly(store):
    page = store.list(LIB)
    assert page.items == () and page.total == 0
    assert store.count(LIB) == 0


# --- tenant isolation (§4.2, H2) -----------------------------------------

@contract
def a_foreign_book_reads_as_absent_not_as_forbidden(store):
    """§4.2 / P3.3: 404, not 403 — don't leak that a record exists. That has
    to be true HERE, or no route can honour it."""
    store.save(OTHER, _book(1, library=OTHER))
    assert store.get(LIB, "b1") is None
    assert store.get_by_key(LIB, store.get(OTHER, "b1").key) is None


@contract
def a_foreign_book_cannot_be_deleted(store):
    store.save(OTHER, _book(1, library=OTHER))
    assert store.delete(LIB, "b1") is False
    assert store.get(OTHER, "b1") is not None, "cross-tenant delete succeeded"


@contract
def listing_never_crosses_libraries(store):
    for i in (1, 2):
        store.save(LIB, _book(i))
    for i in (3, 4, 5):
        store.save(OTHER, _book(i, library=OTHER))
    assert store.list(LIB).total == 2 and store.count(LIB) == 2
    assert store.list(OTHER).total == 3 and store.count(OTHER) == 3
    assert all(b.library_id == LIB.id for b in store.list(LIB).items)


@contract
def saving_into_the_wrong_library_is_refused_loudly(store):
    """Never a user error — always a wiring bug, and the kind that writes one
    tenant's data into another's. Coercing it would hide the bug."""
    _raises(WrongLibrary, store.save, OTHER, _book(1, library=LIB))
    assert store.count(OTHER) == 0
    assert store.count(LIB) == 0, "the refused write leaked into the source"


@contract
def every_store_method_takes_a_library(store):
    """H2, checked by signature rather than by reading the code — a method
    added later without a library scope fails here, before it has callers."""
    import inspect

    from app.ports.store import BookStore

    for name, member in vars(BookStore).items():
        if name.startswith("_") or not callable(member):
            continue
        params = list(inspect.signature(member).parameters)
        assert params[:2] == ["self", "library"], (name, params)
        assert hasattr(store, name), f"{type(store).__name__} lacks {name}()"


# --- registration ---------------------------------------------------------

@contextmanager
def _memory_store():
    yield MemoryBookStore()


@contextmanager
def _sqlite_store():
    tmp = tempfile.mkdtemp(prefix="booksnap-store-")
    try:
        yield SqliteBookStore(Path(tmp) / "books.db")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


IMPLEMENTATIONS = (("memory", _memory_store), ("sqlite", _sqlite_store))


def _bind(fn, factory, name):
    def run():
        with factory() as store:
            fn(store)

    # run_all.py reports fn.__name__, so without this every bound case prints
    # as "run" and a failure doesn't say WHICH implementation broke.
    run.__name__ = name
    run.__doc__ = fn.__doc__
    return run


for _label, _factory in IMPLEMENTATIONS:
    for _fn in CONTRACT:
        _name = f"test_{_fn.__name__}__{_label}"
        globals()[_name] = _bind(_fn, _factory, _name)


# --- migrations (H6), sqlite-specific ------------------------------------

def test_a_fresh_database_is_at_the_current_schema_version():
    import sqlite3

    with _sqlite_store() as store:
        conn = sqlite3.connect(str(store.path))
        try:
            assert current_version(conn) == SCHEMA_VERSION
        finally:
            conn.close()


def test_migrating_an_already_current_database_is_a_no_op():
    """The store migrates on every construction, so re-running steps must be
    harmless — otherwise the second server start fails on a live database."""
    import sqlite3

    with _sqlite_store() as store:
        store.save(LIB, _book(1))
        conn = sqlite3.connect(str(store.path))
        try:
            assert migrate(conn) == SCHEMA_VERSION
        finally:
            conn.close()
        reopened = SqliteBookStore(store.path)
        assert reopened.count(LIB) == 1, "re-opening lost data"


def test_deleting_a_book_leaves_no_orphan_rows():
    """The cascade is only real with PRAGMA foreign_keys=ON, which SQLite
    defaults OFF — so this asserts the pragma, not just the DDL."""
    import sqlite3

    with _sqlite_store() as store:
        b = observe(_book(shelf_id="s1"), Provenance("r1", "sp1", shelf_id="s1"))
        store.save(LIB, add_copy(b, copy_id="c1b"))
        store.delete(LIB, "b1")

        conn = sqlite3.connect(str(store.path))
        try:
            for table in ("books", "copies", "provenance"):
                n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                assert n == 0, f"{table} kept {n} orphan row(s)"
        finally:
            conn.close()


def test_the_store_refuses_an_in_memory_path():
    """A connection per operation means ':memory:' would hand every call its
    own empty database — working perfectly and storing nothing."""
    _raises(ValueError, SqliteBookStore, ":memory:")


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))
