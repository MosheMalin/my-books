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

from app.adapters.memory_store import (
    MemoryBookStore,
    MemoryDecisionStore,
    MemoryDuplicateQueue,
    MemoryReadStore,
    MemoryShelfStore,
    MemoryTenancyStore,
)
from app.adapters.migrations import SCHEMA_VERSION, current_version, migrate
from app.adapters.sqlite_store import (
    SqliteBookStore,
    SqliteDecisionStore,
    SqliteDuplicateQueue,
    SqliteReadStore,
    SqliteShelfStore,
    SqliteTenancyStore,
)
from app.domain import (
    Alternative,
    Capture,
    Claim,
    ClaimTier,
    Decision,
    DecisionKind,
    DiffSummary,
    DuplicateQuestion,
    Library,
    LibraryRef,
    Membership,
    Provenance,
    Role,
    Status,
    User,
    add_copy,
    append_claim,
    approve,
    edit,
    finish_read,
    lend,
    new_book,
    new_capture,
    new_library,
    new_read,
    new_shelf,
    observe,
    remove_from_shelf,
    rename_shelf,
    return_copy,
    stop_read,
    with_diff_summary,
)
from app.ports.store import (
    BookPage,
    BookSort,
    DuplicateBookKey,
    DuplicateCaptureSlot,
    ShelfNotEmpty,
    UnknownShelf,
    WrongLibrary,
)
from app.ports.tenancy import UnknownLibrary, UnknownUser

LIB = LibraryRef("lib-a", "Library A")
OTHER = LibraryRef("lib-b", "Library B")

CONTRACT: list = []
SHELF_CONTRACT: list = []
READ_CONTRACT: list = []
DECISION_CONTRACT: list = []
DUPLICATE_CONTRACT: list = []
TENANCY_CONTRACT: list = []

# The tenancy suite's own axis: users, not libraries (P3.1).
USR = User(id="usr-a", display_name="משה")
USR2 = User(id="usr-b", display_name="Dana")


def contract(fn):
    """Mark a function as part of the BookStore spec. Gets a fresh store."""
    CONTRACT.append(fn)
    return fn


def shelf_contract(fn):
    """Mark a function as part of the ShelfStore spec (P2.1).

    A second list rather than a flag on the first: the two ports have separate
    implementations, and a shelf case handed a BookStore would fail for the
    wrong reason.
    """
    SHELF_CONTRACT.append(fn)
    return fn


def read_contract(fn):
    """Mark a function as part of the ReadStore spec (P2.4). A third list,
    same reasoning as `shelf_contract`."""
    READ_CONTRACT.append(fn)
    return fn


def decision_contract(fn):
    """Mark a function as part of the DecisionStore spec (P2.5). A fourth
    list, same reasoning as `shelf_contract`/`read_contract`."""
    DECISION_CONTRACT.append(fn)
    return fn


def duplicate_contract(fn):
    """Mark a function as part of the DuplicateQueue spec (P2.6). A fifth
    list, same reasoning as the others."""
    DUPLICATE_CONTRACT.append(fn)
    return fn


def tenancy_contract(fn):
    """Mark a function as part of the TenancyStore spec (P3.1).

    ⚠ A sixth list, and the only one whose cases take no ``LibraryRef`` — this
    is the store that ANSWERS which libraries exist, so it is scoped by the
    ACCOUNT instead (see the port's own ⚠⚠). Everything above narrows by
    ``LIB``/``OTHER``; everything here narrows by ``USR``/``USR2``.
    """
    TENANCY_CONTRACT.append(fn)
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
def sorts_authors_by_surname_not_by_the_stored_string(store):
    """§6's "by author" is the shelf order. Sorted as stored, גרג הורביץ files
    under ג and דיוויד באלדאצ'י under ד — every author under their given name.
    Both shapes in the real data are here, mixed, because a store that only
    handled one would pass a single-shape test and still order wrongly."""
    store.save(LIB, _book(1, title="א", author="גרג הורביץ"))      # -> הורביצ
    store.save(LIB, _book(2, title="א", author="דיוויד באלדאצ'י"))  # -> באלדאצי
    store.save(LIB, _book(3, title="א", author="אסימוב, אייזיק"))   # -> אסימוב
    ids = [b.id for b in store.list(LIB, sort=BookSort.AUTHOR).items]
    assert ids == ["b3", "b2", "b1"], ids
    assert [b.id for b in store.list(LIB, sort=BookSort.AUTHOR,
                                     ascending=False).items] == ["b1", "b2", "b3"]


@contract
def a_renamed_author_re_sorts(store):
    """The surname key is DERIVED, so a store that computes it once at insert
    and never again would keep the old position after an edit — invisible
    until someone fixes a misread name and it stays filed under the typo."""
    store.save(LIB, _book(1, title="א", author="ורד טוכטרמן"))    # -> טוכטרמנ
    store.save(LIB, _book(2, title="א", author="גרג הורביץ"))     # -> הורביצ
    assert [b.id for b in store.list(LIB, sort=BookSort.AUTHOR).items] == \
        ["b2", "b1"]
    store.save(LIB, _book(1, title="א", author="ורד אבן"))        # -> אבנ
    assert [b.id for b in store.list(LIB, sort=BookSort.AUTHOR).items] == \
        ["b1", "b2"]


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
def filters_by_lent_out(store):
    """"Who has my books" (§5.2): a book qualifies if AT LEAST ONE of its
    copies is currently out — a book-level filter over a copy-level fact,
    exercised with a multi-copy book so a store cannot pass by checking only
    a book's first copy."""
    lent = lend(_book(1), "c1", lent_to="דנה", lent_at="2026-08-01")
    store.save(LIB, lent)
    returned = return_copy(lend(_book(2), "c2", lent_to="יוסי",
                                lent_at="2026-07-01"), "c2",
                           returned_at="2026-07-20")
    store.save(LIB, returned)
    store.save(LIB, _book(3))  # never lent
    multi = add_copy(_book(4), copy_id="c4b")
    multi = lend(multi, "c4b", lent_to="עידו", lent_at="2026-08-01")
    store.save(LIB, multi)     # c4 untouched, c4b out — the book must qualify

    out = sorted(b.id for b in store.list(LIB, lent_out=True).items)
    assert out == ["b1", "b4"], out
    home = sorted(b.id for b in store.list(LIB, lent_out=False).items)
    assert home == ["b2", "b3"], home
    # Omitted entirely: no filter, same as every other `list` param.
    assert store.list(LIB).total == 4


@contract
def filters_by_an_explicit_id_set(store):
    """P2.6: the generic ``book_ids`` narrowing the Books tab's "duplicates
    to resolve" filter is composed on top of, at the API layer — this store
    knows nothing about a DuplicateQuestion, only how to restrict to an id
    set. Sort/paging still apply on top of it."""
    store.save(LIB, _book(1))
    store.save(LIB, _book(2))
    store.save(LIB, _book(3))

    got = sorted(b.id for b in store.list(LIB, book_ids=("b1", "b3")).items)
    assert got == ["b1", "b3"], got
    # An explicit EMPTY set means "nothing", not "no filter" — the whole
    # point of the distinction from `book_ids=None` (an empty queue must
    # page as zero books).
    empty = store.list(LIB, book_ids=())
    assert empty.items == () and empty.total == 0
    # Omitted entirely: no filter, same as every other `list` param.
    assert store.list(LIB, book_ids=None).total == 3


# --- search (P1.5) --------------------------------------------------------
#
# The semantics live in app.domain.search and are tested exhaustively against
# the real 251 books in tests/test_search.py. What these cases pin is that
# EVERY implementation reproduces them — SQLite narrows with LIKE over a
# stored haystack column, a Postgres adapter might use pg_trgm, and this is
# where a clever retrieval strategy that changes the ANSWERS gets caught.

@contract
def search_finds_a_book_by_a_word_from_its_title(store):
    store.save(LIB, _book(1, title="מלכי הכופרים"))
    store.save(LIB, _book(2, title="ספינות מן המערב"))
    page = store.search(LIB, "כופרים")
    assert [b.id for b in page.items] == ["b1"] and page.total == 1


@contract
def search_tolerates_a_definite_article_the_catalogue_lacks(store):
    """The user types "the neutron star"; the catalogue says "neutron star"."""
    store.save(LIB, _book(1, title="כוכב ניוטרון"))
    assert [b.id for b in store.search(LIB, "הכוכב ניוטרון").items] == ["b1"]


def _search_titles(store, q):
    return [b.title for b in store.search(LIB, q).items]


@contract
def search_ranks_the_exact_title_first(store):
    """Not just filtering: three books match and alphabetical order gets it
    wrong. Every implementation must agree on the ORDER, not only the set."""
    store.save(LIB, _book(1, title="מהעיר הדוממת"))
    store.save(LIB, _book(2, title="עיר"))
    store.save(LIB, _book(3, title="עיר הזמן"))
    assert _search_titles(store, "עיר")[0] == "עיר"


@contract
def search_prefers_a_title_hit_over_an_author_hit(store):
    store.save(LIB, _book(1, title="ארץ לא נודעת", author="שלום ירושלים"))
    store.save(LIB, _book(2, title="מלך ירושלים", author="פול קארני"))
    assert _search_titles(store, "ירושלים")[0] == "מלך ירושלים"


@contract
def search_requires_every_term(store):
    store.save(LIB, _book(1, title="עולם טבעת"))
    store.save(LIB, _book(2, title="מהנדסי הטבעת"))
    assert [b.id for b in store.search(LIB, "עולם טבעת").items] == ["b1"]


@contract
def search_ignores_geresh_and_nikud_on_both_sides(store):
    store.save(LIB, _book(1, title="הצ'ופצ'יק", author="מאיר שלו"))
    for typed in ("הצ'ופצ'יק", "הצופציק", "צ'ופצ'יק"):
        assert [b.id for b in store.search(LIB, typed).items] == ["b1"], typed


@contract
def search_folds_final_letters(store):
    store.save(LIB, _book(1, title="גנב הקוונטום"))
    assert [b.id for b in store.search(LIB, "קוונטומ").items] == ["b1"]


@contract
def search_pages_and_reports_the_total(store):
    for i in range(1, 6):
        store.save(LIB, _book(i, title=f"הצי האבוד {i}"))
    page = store.search(LIB, "הצי האבוד", limit=2, offset=2)
    assert page.total == 5 and len(page.items) == 2 and page.offset == 2


@contract
def an_empty_search_returns_nothing_not_the_library(store):
    """An empty search box must not page the whole collection back."""
    store.save(LIB, _book(1))
    for blank in ("", "   ", "!!"):
        page = store.search(LIB, blank)
        assert page.items == () and page.total == 0, blank


@contract
def search_never_crosses_libraries(store):
    store.save(LIB, _book(1, title="מלכי הכופרים"))
    store.save(OTHER, _book(2, library=OTHER, title="מלכי הכופרים"))
    assert [b.id for b in store.search(LIB, "כופרים").items] == ["b1"]
    assert [b.id for b in store.search(OTHER, "כופרים").items] == ["b2"]


@contract
def search_cannot_be_turned_into_a_wildcard(store):
    """``%`` is a LIKE wildcard. normalize() drops it, and compile_sql_like
    escapes it anyway — a query of "%" must find nothing, not everything."""
    store.save(LIB, _book(1))
    store.save(LIB, _book(2))
    for evil in ("%", "%%", "_", "%_%"):
        assert store.search(LIB, evil).total == 0, evil


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


# --- the shelf spec (P2.1) ------------------------------------------------
#
# A second contract list, because these run against the ShelfStore
# implementations rather than the BookStore ones. Same discipline: one spec,
# every implementation, so P2.1's shelf model is as portable as P1.2's books.

def _sh(n: int = 1, *, library: LibraryRef = LIB, **kw):
    args = dict(id=f"sh{n}", library_id=library.id, label=f"מדף {n}")
    args.update(kw)
    return new_shelf(**args)


@shelf_contract
def saves_and_reads_back_a_shelf(store):
    store.save_shelf(LIB, _sh(1, depth_count=2, created_at="2026-08-07"))
    got = store.get_shelf(LIB, "sh1")
    assert got is not None
    assert (got.label, got.depth_count, got.created_at) == ("מדף 1", 2, "2026-08-07")
    assert store.get_shelf(LIB, "nope") is None


@shelf_contract
def the_wishlist_is_excluded_from_shelf_listings_by_default(store):
    """P2.1's named rule. The default has to be exclusion, not a filter the
    caller remembers: the wishlist holds books the owner does not own, so a
    forgotten filter inflates both the shelf list and the apparent size of the
    library — and it inflates them silently."""
    store.save_shelf(LIB, _sh(1))
    store.save_shelf(LIB, _sh(2, id="wish", label="משאלות", virtual=True))

    assert [s.id for s in store.list_shelves(LIB)] == ["sh1"]
    assert store.count_shelves(LIB) == 1
    assert {s.id for s in store.list_shelves(LIB, include_virtual=True)} == {
        "sh1", "wish"}
    assert store.count_shelves(LIB, include_virtual=True) == 2


@shelf_contract
def shelves_are_listed_in_a_total_order(store):
    """Same reasoning as the book sorts: two shelves labelled the same must
    still order identically on every call, or the shelves screen reshuffles
    between renders. Inserted in DESCENDING id order so a missing tiebreaker
    cannot pass on insertion order alone."""
    for n in (3, 2, 1):
        store.save_shelf(LIB, _sh(n, label="מדף"))
    assert [s.id for s in store.list_shelves(LIB)] == ["sh1", "sh2", "sh3"]


@shelf_contract
def unnamed_shelves_are_ordered_by_creation_not_by_id(store):
    """Labels are optional (owner's call), so early on most shelves share the
    empty one — and every implementation has to put them in the same place, or
    the shelves screen reorders itself when the datastore changes. The rule
    lives in `Shelf.sort_key`; adapters mirror it, they do not invent it.

    Inserted so that id order, insertion order and the correct order all
    differ, which is the only arrangement that can catch a wrong tiebreaker.
    """
    store.save_shelf(LIB, _sh(1, label="", created_at="2026-08-05"))
    store.save_shelf(LIB, _sh(2, label="אכסדרה", created_at="2026-08-01"))
    store.save_shelf(LIB, _sh(3, label="", created_at="2026-08-02"))
    assert [s.id for s in store.list_shelves(LIB)] == ["sh3", "sh1", "sh2"]


@shelf_contract
def renaming_a_shelf_keeps_its_captures(store):
    """The label is the whole of a book's location until pillar 6, so it gets
    edited often. A save that replaced the row by delete-then-insert would
    cascade the captures away — and take the record a re-read diffs against
    (§5.6) with it."""
    shelf = _sh(1)
    store.save_shelf(LIB, shelf)
    store.save_capture(LIB, new_capture(shelf, id="cap1"))

    store.save_shelf(LIB, rename_shelf(shelf, "מדף אחר"))
    assert store.get_shelf(LIB, "sh1").label == "מדף אחר"
    assert [c.id for c in store.list_captures(LIB, "sh1")] == ["cap1"]


@shelf_contract
def captures_come_back_in_depth_then_order(store):
    """§5.3: captures are ordered so a shelf's book list has a sensible
    sequence, and keyed by depth so two photos of physically different scenes
    are never one sequence."""
    shelf = _sh(1, depth_count=2)
    store.save_shelf(LIB, shelf)
    for cap_id, depth, order in (("b1", 2, 1), ("a2", 1, 1), ("b0", 2, 0),
                                 ("a1", 1, 0)):
        store.save_capture(LIB, new_capture(shelf, id=cap_id, depth=depth,
                                            order=order))
    assert [c.id for c in store.list_captures(LIB, "sh1")] == [
        "a1", "a2", "b0", "b1"]


@shelf_contract
def captures_can_be_fetched_for_one_depth_alone(store):
    """The parameter §5.6 and §5.7 #1 need. Re-reading only the front row of a
    three-row shelf must compare against that row — comparing against the
    whole shelf would flag two thirds of its books as possibly missing on
    every single re-read, and §5.7 #2 forbids merging overlaps across
    depths."""
    shelf = _sh(1, depth_count=3)
    store.save_shelf(LIB, shelf)
    store.save_capture(LIB, new_capture(shelf, id="front", depth=1))
    store.save_capture(LIB, new_capture(shelf, id="middle", depth=2))
    store.save_capture(LIB, new_capture(shelf, id="back", depth=3))

    assert [c.id for c in store.list_captures(LIB, "sh1", depth=2)] == ["middle"]
    assert len(store.list_captures(LIB, "sh1")) == 3


@shelf_contract
def two_captures_cannot_hold_one_slot(store):
    """(shelf, depth, order) IS a capture's identity (§5.3). Two in one slot
    make a shelf's book order ambiguous, and the ambiguity would surface much
    later as a reconciliation diff that reorders itself between reads.

    Re-saving the SAME capture into its own slot is an update, not a clash."""
    shelf = _sh(1)
    store.save_shelf(LIB, shelf)
    store.save_capture(LIB, new_capture(shelf, id="cap1", order=0))
    store.save_capture(LIB, new_capture(shelf, id="cap1", order=0,
                                        image_id="img-2"))
    assert store.get_capture(LIB, "cap1").image_id == "img-2"

    _raises(DuplicateCaptureSlot, store.save_capture, LIB,
            new_capture(shelf, id="cap2", order=0))


@shelf_contract
def a_capture_cannot_name_a_shelf_that_is_not_here(store):
    """Including — especially — a shelf id from another library. §4.2 says a
    foreign record reads as ABSENT, so this is the same answer either way and
    the route above it cannot leak existence."""
    store.save_shelf(OTHER, _sh(1, library=OTHER))
    ghost = Capture(id="cap1", shelf_id="sh1", library_id=LIB.id)
    _raises(UnknownShelf, store.save_capture, LIB, ghost)
    assert store.get_capture(LIB, "cap1") is None


@shelf_contract
def deleting_a_shelf_with_captures_is_refused_not_cascaded(store):
    """§5.6's direction, at the store: nothing is destroyed automatically. A
    cascade here would delete the photographic record a re-read diffs against,
    on a misclick. Deletion is for the shelf typed by mistake."""
    shelf = _sh(1)
    store.save_shelf(LIB, shelf)
    assert store.delete_shelf(LIB, "sh2") is False, "deleted something absent"

    store.save_capture(LIB, new_capture(shelf, id="cap1"))
    _raises(ShelfNotEmpty, store.delete_shelf, LIB, "sh1")
    assert store.get_shelf(LIB, "sh1") is not None

    assert store.delete_capture(LIB, "cap1") is True
    assert store.delete_shelf(LIB, "sh1") is True
    assert store.get_shelf(LIB, "sh1") is None


@shelf_contract
def a_shelf_in_another_library_reads_as_absent(store):
    """The isolation rule the API's 404-not-403 answer rests on (§4.2, P3.3).
    Written now against two library refs even though the app resolves one."""
    shelf = _sh(1)
    store.save_shelf(LIB, shelf)
    store.save_capture(LIB, new_capture(shelf, id="cap1"))

    assert store.get_shelf(OTHER, "sh1") is None
    assert store.get_capture(OTHER, "cap1") is None
    assert store.list_shelves(OTHER) == ()
    assert store.list_captures(OTHER, "sh1") == ()
    assert store.count_shelves(OTHER) == 0
    assert store.delete_shelf(OTHER, "sh1") is False
    assert store.delete_capture(OTHER, "cap1") is False
    assert store.get_shelf(LIB, "sh1") is not None, "a foreign call reached in"


@shelf_contract
def saving_a_shelf_into_the_wrong_library_is_refused_loudly(store):
    _raises(WrongLibrary, store.save_shelf, OTHER, _sh(1, library=LIB))
    assert store.count_shelves(OTHER) == 0


@shelf_contract
def every_shelf_store_method_takes_a_library(store):
    """H2 by signature, same as the book store's — a method added later
    without a library scope fails here, before it has callers."""
    import inspect

    from app.ports.store import ShelfStore

    for name, member in vars(ShelfStore).items():
        if name.startswith("_") or not callable(member):
            continue
        params = list(inspect.signature(member).parameters)
        assert params[:2] == ["self", "library"], (name, params)
        assert hasattr(store, name), f"{type(store).__name__} lacks {name}()"


# --- the read spec (P2.4) --------------------------------------------------
#
# A third contract list: reads run against the ReadStore implementations, not
# the book or shelf ones. Same discipline as the other two — one spec, every
# implementation, so P2.4's read model is as portable as P1.2's books and
# P2.1's shelves.

def _read(n: int = 1, *, library: LibraryRef = LIB, shelf_id: str = "sh1",
          depth: int = 1, capture_ids=("cap1",), **kw) -> "Read":
    from app.domain import Read

    args = dict(id=f"rd{n}", library_id=library.id, shelf_id=shelf_id,
                depth=depth, capture_ids=tuple(capture_ids), mode="spines",
                started_at="2026-08-07T12:00:00+00:00")
    args.update(kw)
    return Read(**args)


@read_contract
def saves_and_reads_back_a_read_with_its_claims(store):
    r = _read(1)
    r = append_claim(r, Claim(id="cl1", spine_id="sp1", capture_id="cap1",
                              title="מלכי הכופרים", tier=ClaimTier.AUTO, score=91.0,
                              box=(1, 2, 3, 4)))
    r = append_claim(r, Claim(id="cl2", spine_id="sp2", capture_id="cap1"))
    r = finish_read(r, finished_at="2026-08-07T12:05:00+00:00")
    store.save_read(LIB, r)

    got = store.get_read(LIB, "rd1")
    assert got == r, "the read (with its claims) did not survive the round trip"
    assert got.claims[0].box == (1, 2, 3, 4)


@read_contract
def a_claims_alternatives_survive_the_round_trip(store):
    """P2.7's "why?" data — ranked runners-up from explain() — is not just an
    in-memory convenience: it has to come back from SQLite too (v10), or the
    review UI's why? panel is empty for every read served from a real file."""
    r = _read(1)
    r = append_claim(r, Claim(
        id="cl1", spine_id="sp1", capture_id="cap1", title="מלכי הכופרים",
        tier=ClaimTier.AUTO, score=91.0,
        alternatives=(
            Alternative(title="ספינות מן המערב", author="פול קארני", score=61.2),
            Alternative(title="הכופרים", author="", score=40.0,
                       reason="title similarity 40 < 47"),
        ),
    ))
    # A claim with NO alternatives (explain() found nothing, or the engine had
    # no OCR text) must round-trip as an empty tuple, not None/error — the
    # common case, so it is worth its own claim in the same read.
    r = append_claim(r, Claim(id="cl2", spine_id="sp2", capture_id="cap1"))
    store.save_read(LIB, r)

    got = store.get_read(LIB, "rd1")
    assert got.claims[0].alternatives == (
        Alternative(title="ספינות מן המערב", author="פול קארני", score=61.2),
        Alternative(title="הכופרים", author="", score=40.0,
                   reason="title similarity 40 < 47"),
    )
    assert got.claims[1].alternatives == ()


@read_contract
def a_reads_diff_summary_survives_the_round_trip(store):
    """P2.8's snapshot (§5.5/§5.6) is not just an in-memory convenience: a
    shelf's read history has to come back from SQLite too (v11), or the
    history view's headline counts are blank for every read served from a
    real file. A read with none set (the common case — running/failed
    reads, and every read that predates v11) must round-trip as ``None``,
    not a default-zeroed summary that would misreport as "0 added"."""
    r = _read(1)
    r = finish_read(r, finished_at="2026-08-07T12:05:00+00:00")
    r = with_diff_summary(r, DiffSummary(added=3, corrected=1, unchanged=12,
                                         not_seen=1))
    store.save_read(LIB, r)

    got = store.get_read(LIB, "rd1")
    assert got.diff_summary == DiffSummary(added=3, corrected=1, unchanged=12,
                                           not_seen=1)

    store.save_read(LIB, _read(2))  # never summarised
    assert store.get_read(LIB, "rd2").diff_summary is None


@read_contract
def missing_read_reads_as_none(store):
    assert store.get_read(LIB, "nope") is None


@read_contract
def re_saving_a_read_replaces_its_claims_rather_than_accumulating(store):
    """Same "aggregate saved whole" rule as books' provenance — a Read saved
    twice (once running, once finished) must not leave the running version's
    claims lying around alongside the finished ones."""
    r = _read(1)
    store.save_read(LIB, r)
    r = append_claim(r, Claim(id="cl1", spine_id="sp1", capture_id="cap1"))
    r = finish_read(r, finished_at="2026-08-07T12:05:00+00:00")
    store.save_read(LIB, r)

    got = store.get_read(LIB, "rd1")
    assert len(got.claims) == 1
    assert got.status.value == "done"


@read_contract
def a_stopped_read_is_stored_as_a_real_result_not_a_failure(store):
    r = _read(1)
    r = append_claim(r, Claim(id="cl1", spine_id="sp1", capture_id="cap1"))
    r = stop_read(r, finished_at="2026-08-07T12:05:00+00:00")
    store.save_read(LIB, r)

    got = store.get_read(LIB, "rd1")
    assert got.status.value == "stopped"
    assert got.error is None
    assert len(got.claims) == 1, "the stop must not have discarded the claim"


@read_contract
def lists_a_shelfs_reads_most_recent_first(store):
    store.save_read(LIB, _read(1, started_at="2026-08-01T00:00:00+00:00"))
    store.save_read(LIB, _read(2, started_at="2026-08-03T00:00:00+00:00"))
    store.save_read(LIB, _read(3, started_at="2026-08-02T00:00:00+00:00"))
    assert [r.id for r in store.list_reads(LIB, "sh1")] == ["rd2", "rd3", "rd1"]


@read_contract
def lists_can_narrow_to_one_depth(store):
    """The parameter §5.7 #1 needs: a shelf's read HISTORY is scoped to the
    row it actually covered, same shape as ShelfStore.list_captures."""
    store.save_read(LIB, _read(1, depth=1))
    store.save_read(LIB, _read(2, depth=2))
    assert [r.id for r in store.list_reads(LIB, "sh1", depth=2)] == ["rd2"]
    assert len(store.list_reads(LIB, "sh1")) == 2


@read_contract
def listing_reads_never_crosses_shelves_or_libraries(store):
    store.save_read(LIB, _read(1, shelf_id="sh1"))
    store.save_read(LIB, _read(2, shelf_id="sh2"))
    store.save_read(OTHER, _read(3, library=OTHER, shelf_id="sh1"))
    assert [r.id for r in store.list_reads(LIB, "sh1")] == ["rd1"]
    assert [r.id for r in store.list_reads(OTHER, "sh1")] == ["rd3"]


@read_contract
def lists_the_runs_that_touched_one_photo(store):
    """P2.10's *"clicking a photo opens its runs"* (§12.2 #10). A read of a
    whole row lists under every photo of that row — it really did read them
    all (§5.7 #1) — and the newest-first order matches `list_reads`'."""
    store.save_read(LIB, _read(1, capture_ids=("capA", "capB"),
                               started_at="2026-08-01T00:00:00+00:00"))
    store.save_read(LIB, _read(2, capture_ids=("capB",),
                               started_at="2026-08-03T00:00:00+00:00"))
    store.save_read(LIB, _read(3, capture_ids=("capC",),
                               started_at="2026-08-02T00:00:00+00:00"))

    assert [r.id for r in store.list_reads_for_capture(LIB, "capB")] == ["rd2", "rd1"]
    assert [r.id for r in store.list_reads_for_capture(LIB, "capA")] == ["rd1"]
    assert store.list_reads_for_capture(LIB, "capZ") == ()


@read_contract
def a_photos_runs_survive_it_being_re_bound_to_another_shelf(store):
    """The reason this is a store method and not a filter over
    `list_reads(shelf_id)`: intake re-binding a photo (P2.2) must not erase
    the runs that already read it under the shelf it used to be on. Reversing
    this loses history only for the photos someone had to correct — the ones
    whose history is most worth having."""
    store.save_read(LIB, _read(1, shelf_id="sh-old", capture_ids=("capA",)))
    # the capture now lives on sh-new; its old read is still filed on sh-old
    assert [r.id for r in store.list_reads_for_capture(LIB, "capA")] == ["rd1"]
    assert store.list_reads(LIB, "sh-new") == ()


@read_contract
def a_photos_runs_never_cross_libraries(store):
    """Two libraries can mint the same capture id — §4.2 again, at the one
    method whose lookup key is not a shelf."""
    store.save_read(LIB, _read(1, capture_ids=("capA",)))
    store.save_read(OTHER, _read(2, library=OTHER, capture_ids=("capA",)))
    assert [r.id for r in store.list_reads_for_capture(LIB, "capA")] == ["rd1"]
    assert [r.id for r in store.list_reads_for_capture(OTHER, "capA")] == ["rd2"]


@read_contract
def a_photos_runs_match_the_whole_id_not_a_fragment_of_one(store):
    """A prefix-shaped id must not match its own longer sibling.

    This is the case a naive `LIKE '%' || id || '%'` over the JSON column
    gets wrong. The shipped adapter quotes the needle (`%"cap1"%`), which is
    already exact — so this test passes against it and would fail against the
    naive version. Note what it does NOT prove: the Python membership
    re-check after the query survives being deleted, because the quoted LIKE
    alone is sufficient today. That re-check is there to keep the SQL a pure
    NARROWING clause (`app.domain.search`'s own split), so a future index or
    FTS-shaped rewrite of the query cannot change the answer.
    """
    store.save_read(LIB, _read(1, capture_ids=("cap10",)))
    assert store.list_reads_for_capture(LIB, "cap1") == ()
    assert [r.id for r in store.list_reads_for_capture(LIB, "cap10")] == ["rd1"]


@read_contract
def a_read_in_another_library_reads_as_absent(store):
    """§4.2 / P3.3: 404-not-403, same as every other aggregate — asserted
    here because the route above it can only honour it if this holds."""
    store.save_read(LIB, _read(1))
    assert store.get_read(OTHER, "rd1") is None
    assert store.list_reads(OTHER, "sh1") == ()


@read_contract
def list_all_reads_spans_shelves_and_survives_a_retired_shelf_id(store):
    """P3.5's method: the blob reconciler must see every read's crops, and
    the reads that need it most are filed under a shelf id that no longer
    resolves (captures deleted one by one, then the shelf — legal, P2.1).
    A store has no shelf table to join through here, so nothing should
    filter; asserted with a shelf id nothing else references."""
    store.save_read(LIB, _read(1))
    store.save_read(LIB, _read(2, shelf_id="sh-retired"))
    assert {r.id for r in store.list_all_reads(LIB)} == {"rd1", "rd2"}
    assert store.list_all_reads(OTHER) == (), "another library's reads leaked"


@read_contract
def saving_a_read_into_the_wrong_library_is_refused_loudly(store):
    _raises(WrongLibrary, store.save_read, OTHER, _read(1, library=LIB))
    assert store.get_read(OTHER, "rd1") is None
    assert store.get_read(LIB, "rd1") is None, "the refused write leaked"


@read_contract
def every_read_store_method_takes_a_library(store):
    """H2 by signature, same as the other two stores'."""
    import inspect

    from app.ports.store import ReadStore

    for name, member in vars(ReadStore).items():
        if name.startswith("_") or not callable(member):
            continue
        params = list(inspect.signature(member).parameters)
        assert params[:2] == ["self", "library"], (name, params)
        assert hasattr(store, name), f"{type(store).__name__} lacks {name}()"


# --- the decision spec (P2.5) ----------------------------------------------
#
# A fourth contract list: decisions run against the DecisionStore
# implementations, not the book/shelf/read ones. Same discipline as the other
# three — one spec, every implementation, so P2.5's standing answers are as
# portable as everything before them.

def _decision(*, shelf_id: str = "sh1", depth: int = 1, book_key: str = "k|a",
             kind: DecisionKind = DecisionKind.ALREADY_LISTED,
             library: LibraryRef = LIB, **kw) -> Decision:
    args = dict(library_id=library.id, shelf_id=shelf_id, depth=depth,
                book_key=book_key, kind=kind)
    args.update(kw)
    return Decision(**args)


@decision_contract
def saves_and_reads_back_a_decision(store):
    d = _decision(kind=DecisionKind.ALREADY_LISTED, copy_id="c1",
                 decided_at="2026-08-07T12:00:00+00:00")
    store.save_decision(LIB, d)
    got = store.get_decision(LIB, "sh1", 1, "k|a")
    assert got == d


@decision_contract
def missing_decision_reads_as_none(store):
    assert store.get_decision(LIB, "sh1", 1, "nope|nope") is None


@decision_contract
def a_changed_mind_replaces_the_decision_not_accumulates(store):
    """§5.4's queue makes a second answer to the same question possible —
    this asserts it OVERWRITES, so `reconcile()` never has to pick among a
    history of contradictory decisions for one (shelf, depth, book_key)."""
    store.save_decision(LIB, _decision(kind=DecisionKind.WRONG_BOOK))
    store.save_decision(LIB, _decision(kind=DecisionKind.ANOTHER_COPY))
    got = store.get_decision(LIB, "sh1", 1, "k|a")
    assert got.kind is DecisionKind.ANOTHER_COPY
    assert len(store.list_decisions(LIB, "sh1", 1)) == 1


@decision_contract
def lists_every_decision_at_one_shelf_and_depth(store):
    """The exact shape `reconcile()`'s caller needs: every decision for ONE
    (shelf, depth), not the whole library's — §5.6's "previously rejected
    HERE" is scoped that tightly on purpose."""
    store.save_decision(LIB, _decision(book_key="a|a", depth=1))
    store.save_decision(LIB, _decision(book_key="b|b", depth=1))
    store.save_decision(LIB, _decision(book_key="c|c", depth=2))
    store.save_decision(LIB, _decision(book_key="d|d", shelf_id="sh2", depth=1))

    got = {d.book_key for d in store.list_decisions(LIB, "sh1", 1)}
    assert got == {"a|a", "b|b"}
    assert store.list_decisions(LIB, "sh1", 2) == (
        _decision(book_key="c|c", depth=2),
    )
    assert store.list_decisions(LIB, "sh2", 1) == (
        _decision(book_key="d|d", shelf_id="sh2", depth=1),
    )


@decision_contract
def deleting_a_decision_is_the_undo_of_a_mis_click(store):
    """Mirrors ``booksnap.library.clear_decision``: removing the answer does
    not touch any book — it only means the next read asks again."""
    store.save_decision(LIB, _decision())
    assert store.delete_decision(LIB, "sh1", 1, "k|a") is True
    assert store.get_decision(LIB, "sh1", 1, "k|a") is None
    assert store.delete_decision(LIB, "sh1", 1, "k|a") is False


@decision_contract
def a_foreign_decision_reads_as_absent(store):
    """§4.2, same as every other aggregate: absent and forbidden are the
    same answer, checked here so the route above it can honour it."""
    store.save_decision(OTHER, _decision(library=OTHER))
    assert store.get_decision(LIB, "sh1", 1, "k|a") is None
    assert store.list_decisions(LIB, "sh1", 1) == ()
    assert store.delete_decision(LIB, "sh1", 1, "k|a") is False
    assert store.get_decision(OTHER, "sh1", 1, "k|a") is not None, \
        "a foreign call reached in"


@decision_contract
def saving_a_decision_into_the_wrong_library_is_refused_loudly(store):
    _raises(WrongLibrary, store.save_decision, OTHER, _decision(library=LIB))
    assert store.get_decision(OTHER, "sh1", 1, "k|a") is None
    assert store.get_decision(LIB, "sh1", 1, "k|a") is None, \
        "the refused write leaked"


@decision_contract
def every_decision_store_method_takes_a_library(store):
    """H2 by signature, same as the other three stores'."""
    import inspect

    from app.ports.decisions import DecisionStore

    for name, member in vars(DecisionStore).items():
        if name.startswith("_") or not callable(member):
            continue
        params = list(inspect.signature(member).parameters)
        assert params[:2] == ["self", "library"], (name, params)
        assert hasattr(store, name), f"{type(store).__name__} lacks {name}()"


# --- the duplicate queue spec (P2.6) ----------------------------------------
#
# A fifth contract list: the durable "duplicates to resolve" queue (§5.4).
# Same identity shape as decisions on purpose — a question and its eventual
# answer are two states of one fact — so most of this spec mirrors the
# decision spec above line for line; the differences (whole-library listing,
# no "changed mind", closing instead of replacing) are what earn it its own
# tests rather than being folded into the decision spec.

def _dq(*, id: str = "q1", shelf_id: str = "sh1", depth: int = 1,
       book_key: str = "k|a", library: LibraryRef = LIB, **kw) -> DuplicateQuestion:
    args = dict(
        id=id, library_id=library.id, shelf_id=shelf_id, depth=depth,
        book_key=book_key, read_id="r1", spine_id="sp1", claim_title="כותרת",
        claim_author="מחבר", existing_book_id="b1",
        opened_at="2026-08-07T12:00:00+00:00",
    )
    args.update(kw)
    return DuplicateQuestion(**args)


@duplicate_contract
def saves_and_reads_back_a_question(store):
    q = _dq()
    store.save_question(LIB, q)
    assert store.get_question(LIB, "sh1", 1, "k|a") == q


@duplicate_contract
def missing_question_reads_as_none(store):
    assert store.get_question(LIB, "sh1", 1, "nope|nope") is None


@duplicate_contract
def re_saving_a_question_replaces_rather_than_accumulates(store):
    """A refresh (the same question re-raised by a later read) must
    overwrite the row at this key, not add a second one — the domain's
    `open_or_refresh` is what decides WHAT survives a refresh
    (`opened_at`/`id`); the store only needs to not duplicate the row."""
    store.save_question(LIB, _dq(read_id="r1"))
    store.save_question(LIB, _dq(read_id="r2"))
    assert store.get_question(LIB, "sh1", 1, "k|a").read_id == "r2"
    assert len(store.list_open_questions(LIB)) == 1


@duplicate_contract
def lists_every_open_question_across_the_whole_library_by_default(store):
    """The shape the Books tab's "duplicates to resolve" filter needs
    (P2.6): a queue entry is about a BOOK, not about which shelf happens to
    be open, so listing with no ``shelf_id`` spans every shelf."""
    store.save_question(LIB, _dq(id="q1", shelf_id="sh1", book_key="a|a"))
    store.save_question(LIB, _dq(id="q2", shelf_id="sh2", book_key="b|b"))
    got = {q.book_key for q in store.list_open_questions(LIB)}
    assert got == {"a|a", "b|b"}


@duplicate_contract
def lists_can_narrow_to_one_shelf(store):
    store.save_question(LIB, _dq(id="q1", shelf_id="sh1", book_key="a|a"))
    store.save_question(LIB, _dq(id="q2", shelf_id="sh2", book_key="b|b"))
    got = {q.book_key for q in store.list_open_questions(LIB, shelf_id="sh1")}
    assert got == {"a|a"}


@duplicate_contract
def deleting_closes_a_question(store):
    """Mirrors `delete_decision`'s "undo of a mis-click" shape, but for the
    OPPOSITE trigger: this fires the moment an answer exists, not when one
    is cleared. There is deliberately no "resolved" state to query — closed
    means gone."""
    store.save_question(LIB, _dq())
    assert store.delete_question(LIB, "sh1", 1, "k|a") is True
    assert store.get_question(LIB, "sh1", 1, "k|a") is None
    assert store.list_open_questions(LIB) == ()
    # Answering a question nobody skipped is the NORMAL case, not an error.
    assert store.delete_question(LIB, "sh1", 1, "k|a") is False


@duplicate_contract
def a_foreign_question_reads_as_absent(store):
    store.save_question(OTHER, _dq(library=OTHER))
    assert store.get_question(LIB, "sh1", 1, "k|a") is None
    assert store.list_open_questions(LIB) == ()
    assert store.delete_question(LIB, "sh1", 1, "k|a") is False
    assert store.get_question(OTHER, "sh1", 1, "k|a") is not None, \
        "a foreign call reached in"


@duplicate_contract
def saving_a_question_into_the_wrong_library_is_refused_loudly(store):
    _raises(WrongLibrary, store.save_question, OTHER, _dq(library=LIB))
    assert store.get_question(OTHER, "sh1", 1, "k|a") is None
    assert store.get_question(LIB, "sh1", 1, "k|a") is None, \
        "the refused write leaked"


@duplicate_contract
def every_duplicate_queue_method_takes_a_library(store):
    """H2 by signature, same as every other store's."""
    import inspect

    from app.ports.duplicates import DuplicateQueue

    for name, member in vars(DuplicateQueue).items():
        if name.startswith("_") or not callable(member):
            continue
        params = list(inspect.signature(member).parameters)
        assert params[:2] == ["self", "library"], (name, params)
        assert hasattr(store, name), f"{type(store).__name__} lacks {name}()"


# --- the tenancy spec (P3.1, §4.1) ------------------------------------------
#
# Scoped by ACCOUNT, not by library — the one suite in this file that is. See
# `tenancy_contract`'s own note.

def _seed_two_libraries(store):
    """One user in two libraries, another user in one of them."""
    store.save_user(USR)
    store.save_user(USR2)
    a, mine_a = new_library(id="lib-1", label="משפחת מלין", owner=USR,
                            created_at="2026-01-01T00:00:00+00:00")
    b, mine_b = new_library(id="lib-2", label="Office", owner=USR,
                            created_at="2026-02-01T00:00:00+00:00")
    for lib, m in ((a, mine_a), (b, mine_b)):
        store.save_library(lib)
        store.save_membership(m)
    store.save_membership(Membership(USR2.id, "lib-2", Role.EDITOR))
    return a, b


@tenancy_contract
def a_user_round_trips(store):
    store.save_user(USR)
    got = store.get_user(USR.id)
    assert got is not None and got.display_name == "משה"
    assert store.get_user("nobody") is None


@tenancy_contract
def a_library_round_trips_and_yields_the_tenant_key(store):
    """`Library.ref` is the one-way door to `LibraryRef`, so nothing
    downstream has to know which of the two it was handed."""
    store.save_user(USR)
    lib, membership = new_library(id="lib-1", label="משפחת מלין", owner=USR)
    store.save_library(lib)
    store.save_membership(membership)
    got = store.get_library("lib-1")
    assert got is not None and got.ref == LibraryRef("lib-1", "משפחת מלין")


@tenancy_contract
def a_user_only_ever_sees_the_libraries_it_belongs_to(store):
    """The isolation property of THIS store. Every other aggregate leaks one
    record when its scope is dropped; this one leaks a whole library."""
    _seed_two_libraries(store)
    # A set: the ORDER is a separate rule with its own case below, and a
    # Latin label sorts before a Hebrew one, which says nothing about scope.
    assert {lib.id for lib, _ in store.list_libraries(USR.id)} == {"lib-1", "lib-2"}
    assert [lib.id for lib, _ in store.list_libraries(USR2.id)] == ["lib-2"]
    assert store.list_libraries("usr-nobody") == ()


@tenancy_contract
def a_listed_library_carries_the_role_that_was_granted(store):
    """The switcher renders this list directly, and P3.2's policy reads the
    role off it — a listing that dropped it would send every caller back for
    a second lookup per row."""
    _seed_two_libraries(store)
    roles = {lib.id: m.role for lib, m in store.list_libraries(USR2.id)}
    assert roles == {"lib-2": Role.EDITOR}
    mine = {lib.id: m.role for lib, m in store.list_libraries(USR.id)}
    assert mine == {"lib-1": Role.ADMIN, "lib-2": Role.ADMIN}


@tenancy_contract
def libraries_are_listed_in_the_domains_order_not_the_adapters(store):
    """`Library.sort_key`: named alphabetically, then the nameless v12
    backfill oldest-first, id last. An order that varies between adapters is
    an order the user experiences as the switcher reshuffling itself."""
    store.save_user(USR)
    rows = [
        Library(id="l-z", label="Zebra", created_at="2026-01-01"),
        Library(id="l-a", label="Aleph", created_at="2026-03-01"),
        # The backfilled shape: no label, no created_at.
        Library(id="l-old"),
        Library(id="l-mid", created_at="2020-01-01"),
    ]
    for lib in rows:
        store.save_library(lib)
        store.save_membership(Membership(USR.id, lib.id, Role.ADMIN))
    assert [lib.id for lib, _ in store.list_libraries(USR.id)] == \
        ["l-old", "l-mid", "l-a", "l-z"]


@tenancy_contract
def a_role_change_replaces_the_membership_rather_than_adding_one(store):
    """One membership per (user, library) — the store declares it as a
    composite key, so `save_membership` is a plain upsert."""
    _seed_two_libraries(store)
    store.save_membership(Membership(USR2.id, "lib-2", Role.ADMIN))
    rows = store.list_libraries(USR2.id)
    assert len(rows) == 1
    assert rows[0][1].role is Role.ADMIN


@tenancy_contract
def a_membership_naming_a_missing_user_or_library_is_refused(store):
    """The row it would create is a permission granted to nobody, or to
    nothing. SQLite declares it as a foreign key; the memory store has none,
    so both check explicitly or the two adapters disagree."""
    store.save_user(USR)
    store.save_library(Library(id="lib-1", label="משפחת מלין"))
    _raises(UnknownUser, store.save_membership,
            Membership("usr-ghost", "lib-1", Role.EDITOR))
    _raises(UnknownLibrary, store.save_membership,
            Membership(USR.id, "lib-ghost", Role.EDITOR))


@tenancy_contract
def membership_answers_the_resolvers_question_and_nothing_else(store):
    """The hot path: `deps.current_library` calls it on every request that
    names a library."""
    _seed_two_libraries(store)
    assert store.membership(USR.id, "lib-1").role is Role.ADMIN
    assert store.membership(USR2.id, "lib-1") is None
    assert store.membership("usr-nobody", "lib-1") is None


@tenancy_contract
def removing_a_member_removes_nobody_elses_membership_and_no_library(store):
    """UI_PLAN §5's separation, one level up: the person leaves, the
    collection stays."""
    _seed_two_libraries(store)
    assert store.delete_membership(USR2.id, "lib-2") is True
    assert store.delete_membership(USR2.id, "lib-2") is False
    assert store.get_library("lib-2") is not None
    assert {lib.id for lib, _ in store.list_libraries(USR.id)} == {"lib-1", "lib-2"}


@tenancy_contract
def list_members_returns_the_whole_list_the_domain_rules_need(store):
    """`set_role`/`remove_member` take the WHOLE member list, because "is
    there still an admin?" is unanswerable from one row. Admins first, so a
    members screen does not have to re-sort what the store already knows."""
    _seed_two_libraries(store)
    members = store.list_members("lib-2")
    assert [m.user_id for m in members] == [USR.id, USR2.id]
    assert [m.role for m in members] == [Role.ADMIN, Role.EDITOR]
    assert store.list_members("lib-nobody") == ()


@tenancy_contract
def a_library_is_readable_by_id_even_by_a_caller_with_no_membership(store):
    """⚠ Deliberate: 404-not-403 is about what the API SAYS, and the route
    needs "no such library" and "not yours" to stay distinguishable INSIDE the
    server to answer correctly. A store that conflated them would make the
    two indistinguishable everywhere, including in a log."""
    _seed_two_libraries(store)
    assert store.get_library("lib-1") is not None
    assert store.membership(USR2.id, "lib-1") is None
    assert store.get_library("lib-nothing") is None


# --- registration ---------------------------------------------------------

# ⚠ Every sqlite store here starts from a COPY of an already-migrated file,
# not from an empty one. `migrate()` walks thirteen DDL steps, ~49ms, and this
# module builds 109 databases — half its runtime was re-deriving a schema that
# is byte-identical every time.
#
# It changes nothing the contract asserts. The store constructor still runs
# `migrate()`, which is exactly what a real deployment does on a file that is
# already current: it reads `user_version`, finds 12, and applies nothing. The
# template itself is built by the real migration, so a broken step still fails
# — loudly, at the first sqlite test rather than in all of them.
#
# The MIGRATION tests (`test_a_v1_database_upgrades_and_backfills_...`) build
# their own old-version files and are deliberately untouched: replaying the
# steps is the whole point there.
_TEMPLATE_DIR: Path | None = None


def _template() -> Path:
    """A directory holding `books.db` at the current schema version."""
    global _TEMPLATE_DIR
    if _TEMPLATE_DIR is None:
        tmp = Path(tempfile.mkdtemp(prefix="booksnap-template-"))
        SqliteBookStore(tmp / "books.db")      # constructing it runs migrate()
        _TEMPLATE_DIR = tmp
    return _TEMPLATE_DIR


@contextmanager
def _fresh_db(prefix: str):
    """A private copy of the migrated template, removed afterwards.

    The whole directory is copied, not just `books.db`: the adapter opens in
    WAL mode, so a `-wal`/`-shm` pair may be sitting beside the file, and a
    copy that took only the `.db` could hand a test a database missing
    whatever had not been checkpointed yet.
    """
    tmp = tempfile.mkdtemp(prefix=prefix)
    try:
        dest = Path(tmp) / "db"
        shutil.copytree(_template(), dest)
        yield dest / "books.db"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@contextmanager
def _memory_store():
    yield MemoryBookStore()


@contextmanager
def _sqlite_store():
    with _fresh_db("booksnap-store-") as path:
        yield SqliteBookStore(path)


@contextmanager
def _memory_shelf_store():
    yield MemoryShelfStore()


@contextmanager
def _sqlite_shelf_store():
    with _fresh_db("booksnap-shelf-") as path:
        yield SqliteShelfStore(path)


@contextmanager
def _memory_read_store():
    yield MemoryReadStore()


@contextmanager
def _sqlite_read_store():
    with _fresh_db("booksnap-read-") as path:
        yield SqliteReadStore(path)


@contextmanager
def _memory_decision_store():
    yield MemoryDecisionStore()


@contextmanager
def _sqlite_decision_store():
    with _fresh_db("booksnap-decision-") as path:
        yield SqliteDecisionStore(path)


@contextmanager
def _memory_duplicate_queue():
    yield MemoryDuplicateQueue()


@contextmanager
def _sqlite_duplicate_queue():
    with _fresh_db("booksnap-duplicates-") as path:
        yield SqliteDuplicateQueue(path)


@contextmanager
def _memory_tenancy_store():
    yield MemoryTenancyStore()


@contextmanager
def _sqlite_tenancy_store():
    with _fresh_db("booksnap-tenancy-") as path:
        yield SqliteTenancyStore(path)


IMPLEMENTATIONS = (("memory", _memory_store), ("sqlite", _sqlite_store))
SHELF_IMPLEMENTATIONS = (("memory", _memory_shelf_store),
                         ("sqlite", _sqlite_shelf_store))
READ_IMPLEMENTATIONS = (("memory", _memory_read_store),
                        ("sqlite", _sqlite_read_store))
DECISION_IMPLEMENTATIONS = (("memory", _memory_decision_store),
                            ("sqlite", _sqlite_decision_store))
DUPLICATE_IMPLEMENTATIONS = (("memory", _memory_duplicate_queue),
                             ("sqlite", _sqlite_duplicate_queue))
TENANCY_IMPLEMENTATIONS = (("memory", _memory_tenancy_store),
                           ("sqlite", _sqlite_tenancy_store))


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

for _label, _factory in SHELF_IMPLEMENTATIONS:
    for _fn in SHELF_CONTRACT:
        _name = f"test_{_fn.__name__}__{_label}"
        globals()[_name] = _bind(_fn, _factory, _name)

for _label, _factory in READ_IMPLEMENTATIONS:
    for _fn in READ_CONTRACT:
        _name = f"test_{_fn.__name__}__{_label}"
        globals()[_name] = _bind(_fn, _factory, _name)

for _label, _factory in DECISION_IMPLEMENTATIONS:
    for _fn in DECISION_CONTRACT:
        _name = f"test_{_fn.__name__}__{_label}"
        globals()[_name] = _bind(_fn, _factory, _name)

for _label, _factory in DUPLICATE_IMPLEMENTATIONS:
    for _fn in DUPLICATE_CONTRACT:
        _name = f"test_{_fn.__name__}__{_label}"
        globals()[_name] = _bind(_fn, _factory, _name)

for _label, _factory in TENANCY_IMPLEMENTATIONS:
    for _fn in TENANCY_CONTRACT:
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


def test_a_v1_database_upgrades_and_backfills_its_derived_columns():
    """H6, the case that actually matters: an EXISTING database with data in
    it, not a fresh one. The owner's work/product.db was written at v1 with
    251 books; if a backfill were wrong, the books that predate the upgrade
    would silently drop out of search (v2) or file under the wrong letter
    (v3) while everything saved afterwards looked fine.
    """
    import sqlite3

    from app.adapters.migrations import MIGRATIONS, current_version, migrate

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v1.db"
        conn = sqlite3.connect(str(path))
        try:
            # Stop at v1, exactly as a database written before P1.5 would be.
            conn.executescript(MIGRATIONS[0][1])
            conn.execute("PRAGMA user_version = 1")
            conn.execute(
                "INSERT INTO books (id, library_id, title, author, norm_title,"
                " norm_author, book_key, notes) VALUES"
                " ('b1', ?, 'מלכי הכופרים', 'פול קארני', 'מלכי הכופרימ',"
                " 'פול קארני', 'מלכי הכופרימ|פול קארני', '')",
                (LIB.id,),
            )
            conn.execute(
                "INSERT INTO copies (id, book_id, library_id, position, status)"
                " VALUES ('c1', 'b1', ?, 0, 'auto')", (LIB.id,))
            conn.commit()
            assert current_version(conn) == 1
        finally:
            conn.close()

        store = SqliteBookStore(path)          # migrates on construction
        conn = sqlite3.connect(str(path))
        try:
            assert current_version(conn) == SCHEMA_VERSION
            # v3's backfill runs the DOMAIN rule over the old rows, so the
            # migrated book files under its surname like any newly saved one.
            assert conn.execute(
                "SELECT sort_author FROM books WHERE id = 'b1'"
            ).fetchone()[0] == "קארני פול"
            # v4 needs no backfill (P1.7 is the feature that introduces
            # lending, so no v1 row could have any) — but the column and its
            # DEFAULT must exist, or the pre-existing copy 404s out of every
            # `lent_out` query instead of correctly reading as "not out".
            assert conn.execute(
                "SELECT lent_out FROM copies WHERE id = 'c1'"
            ).fetchone()[0] == 0
        finally:
            conn.close()

        # The pre-existing row is searchable, which is the whole point.
        assert [b.id for b in store.search(LIB, "כופרים").items] == ["b1"]
        assert store.get(LIB, "b1").title == "מלכי הכופרים"
        assert store.list(LIB, lent_out=False).total == 1
        # v5: the copy predates shelves entirely, so it must read back
        # UNLOCATED — not "on shelf None at depth 1", which the domain refuses
        # anyway, and not at a depth with no shelf.
        assert store.get(LIB, "b1").copies[0].location is None
        assert SqliteShelfStore(path).list_shelves(LIB) == ()

        # A book saved AFTER the upgrade must interleave with the migrated
        # ones, not sort into its own group — the failure mode of a backfill
        # that used a different rule from the write path.
        store.save(LIB, _book(2, title="א", author="ורד אבן"))
        assert [b.id for b in store.list(LIB, sort=BookSort.AUTHOR).items] == \
            ["b2", "b1"]

        # And the pre-existing copy can be lent, exercising the write path
        # that maintains `lent_out` on a row that predates the column.
        migrated = lend(store.get(LIB, "b1"), "c1", lent_to="דנה",
                        lent_at="2026-08-01")
        store.save(LIB, migrated)
        assert store.list(LIB, lent_out=True).total == 1


def test_a_v5_database_upgrades_its_shelf_index_in_place():
    """v6 exists as a separate step rather than an edit to v5 because v5 had
    already run on the owner's real work/product.db — anything importing
    `app.main` opens and migrates it, and `tools/api_contract.py` does. An
    edited v5 would never re-run there, so the real database would keep the old
    index while every fresh clone got the new one, and the two would disagree
    about where unnamed shelves sort.

    This asserts the upgrade path that fact requires: a database stopped at v5
    reaches SCHEMA_VERSION and comes out ordering by the full sort key.
    """
    import sqlite3

    from app.adapters.migrations import MIGRATIONS

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v5.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 5:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 5")
            conn.commit()
            assert current_version(conn) == 5
            index = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'shelves_by_label'"
            ).fetchone()[0]
            assert "created_at" not in index, "the fixture is not really v5"
        finally:
            conn.close()

        store = SqliteShelfStore(path)          # migrates on construction
        conn = sqlite3.connect(str(path))
        try:
            assert current_version(conn) == SCHEMA_VERSION
            index = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'shelves_by_label'"
            ).fetchone()[0]
            assert "created_at" in index, "v6 did not replace the index"
        finally:
            conn.close()

        store.save_shelf(LIB, _sh(1, label="", created_at="2026-08-05"))
        store.save_shelf(LIB, _sh(2, label="", created_at="2026-08-02"))
        assert [s.id for s in store.list_shelves(LIB)] == ["sh2", "sh1"]


def test_a_v6_database_upgrades_and_creates_the_reads_tables():
    """H6: v7 is pure SQL with no backfill (P2.4 is a brand-new feature, so no
    row anywhere predates it) — but the upgrade path itself still has to be
    asserted, or a typo in the CREATE TABLE statements would only be caught by
    a fresh database, never by the owner's real, already-migrated file."""
    import sqlite3

    from app.adapters.migrations import MIGRATIONS

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v6.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 6:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 6")
            conn.commit()
            assert current_version(conn) == 6
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()}
            assert "reads" not in tables and "claims" not in tables, \
                "the fixture is not really v6"
        finally:
            conn.close()

        store = SqliteReadStore(path)          # migrates on construction
        conn = sqlite3.connect(str(path))
        try:
            assert current_version(conn) == SCHEMA_VERSION
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()}
            assert {"reads", "claims"} <= tables, "v7 did not create its tables"
        finally:
            conn.close()

        # And the store built on the upgraded file actually works.
        r = _read(1)
        r = append_claim(r, Claim(id="cl1", spine_id="sp1", capture_id="cap1"))
        store.save_read(LIB, r)
        assert store.get_read(LIB, "rd1").claims[0].id == "cl1"


def test_a_v8_database_upgrades_and_creates_the_duplicate_questions_table():
    """H6, same shape as the v6->v7 test above: v9 is pure SQL with no
    backfill (P2.6 is brand new, so no row anywhere predates it), but the
    CREATE TABLE itself has to be exercised against an upgrade path, not
    only a fresh database."""
    import sqlite3

    from app.adapters.migrations import MIGRATIONS

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v8.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 8:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 8")
            conn.commit()
            assert current_version(conn) == 8
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()}
            assert "duplicate_questions" not in tables, \
                "the fixture is not really v8"
        finally:
            conn.close()

        store = SqliteDuplicateQueue(path)     # migrates on construction
        conn = sqlite3.connect(str(path))
        try:
            assert current_version(conn) == SCHEMA_VERSION
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()}
            assert "duplicate_questions" in tables, "v9 did not create its table"
        finally:
            conn.close()

        # And the store built on the upgraded file actually works.
        store.save_question(LIB, _dq())
        assert store.get_question(LIB, "sh1", 1, "k|a") is not None


def test_a_v11_database_backfills_a_library_row_for_the_data_it_already_holds():
    """H6, and the migration in this file with the most to lose (P3.1).

    Every row the owner already owns carries `library_id = 'dev-library'`, and
    from P3.1 on the resolver only serves a library it can FIND. Without a
    backfilled row per existing library_id, the first request after the
    upgrade answers 404 and 251 books look deleted — the failure mode is not a
    missing column, it is an empty library.

    The label is left blank on purpose: a migration cannot know what the owner
    calls their collection, and inventing an English "My library" would write
    one of our strings into a Hebrew switcher. Naming it is the composition
    root's job.
    """
    import sqlite3

    from app.adapters.migrations import MIGRATIONS

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v11.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 11:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 11")
            # Two libraries' worth of data, in two different tables — the
            # backfill has to find both, and a shelf with no book is exactly
            # the row a books-only UNION would miss.
            conn.execute(
                "INSERT INTO books (id, library_id, title, author, norm_title,"
                " norm_author, book_key, notes, search_text, sort_author)"
                " VALUES ('b1', 'dev-library', 'ספר', 'מחבר', 'ספר', 'מחבר',"
                " 'ספר|מחבר', '', 'ספר | מחבר', 'מחבר')"
            )
            conn.execute(
                "INSERT INTO shelves (id, library_id, label) VALUES"
                " ('sh1', 'lib-second', '')"
            )
            conn.commit()
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()}
            assert "libraries" not in tables, "the fixture is not really v11"
        finally:
            conn.close()

        store = SqliteTenancyStore(path)        # migrates on construction
        conn = sqlite3.connect(str(path))
        try:
            assert current_version(conn) == SCHEMA_VERSION
        finally:
            conn.close()

        for library_id in ("dev-library", "lib-second"):
            found = store.get_library(library_id)
            assert found is not None, f"{library_id} lost its books to a 404"
            assert found.label == "", "the migration invented a name"

        # Nobody is a member yet — users arrive at composition time, not
        # from a migration, because before this item nothing recorded a person.
        assert store.list_libraries("usr-anyone") == ()


def test_a_v12_database_renames_its_accounts_to_users_and_keeps_every_grant():
    """v13 (P3.7a): the person stops being called an account.

    A rename with a real failure mode. `memberships.account_id` is half of the
    PRIMARY KEY and carries a foreign key into `accounts`; if the rename left
    either behind, the first request after the upgrade would find no
    membership and answer 404 for a library the owner has always had — the
    same "everything looks deleted" shape v12's backfill exists to prevent,
    one version later.

    So this asserts the GRANT survives, not merely that a column exists: the
    membership is read back through the store, by the same call
    ``deps.current_library`` makes on every request.
    """
    import sqlite3

    from app.adapters.migrations import MIGRATIONS

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v12.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 12:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 12")
            conn.execute(
                "INSERT INTO accounts (id, display_name, email) VALUES"
                " ('dev-owner', 'משה', 'owner@example.com')"
            )
            conn.execute(
                "INSERT INTO libraries (id, label) VALUES ('dev-library', 'הבית')"
            )
            conn.execute(
                "INSERT INTO memberships (account_id, library_id, role,"
                " joined_at) VALUES ('dev-owner', 'dev-library', 'admin', NULL)"
            )
            conn.commit()
        finally:
            conn.close()

        store = SqliteTenancyStore(path)        # migrates on construction

        user = store.get_user("dev-owner")
        assert user is not None and user.display_name == "משה"
        assert user.email == "owner@example.com"

        held = store.membership("dev-owner", "dev-library")
        assert held is not None, "the upgrade dropped an existing grant"
        assert held.user_id == "dev-owner" and held.role is Role.ADMIN
        assert [lib.id for lib, _m in store.list_libraries("dev-owner")] == [
            "dev-library"
        ]

        # ⚠ WRITE through the store, not just read. Reading proves the ROWS
        # survived; only a write proves the CONSTRAINT under them did.
        # `save_membership` upserts `ON CONFLICT(user_id, library_id)`, which
        # SQLite refuses unless that pair is still a real PRIMARY KEY — so a
        # migration that carried every row across while rebuilding the table
        # without its composite key passes every assertion above and breaks the
        # first time somebody changes a role. (Found by P3.7a's migration
        # review, which mutated exactly that and watched this test stay green.)
        store.save_membership(Membership("dev-owner", "dev-library", Role.VIEWER))
        again = store.membership("dev-owner", "dev-library")
        assert again is not None and again.role is Role.VIEWER
        assert len(store.list_members("dev-library")) == 1, "upsert appended"

        conn = sqlite3.connect(str(path))
        try:
            assert current_version(conn) == SCHEMA_VERSION
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','index')"
            ).fetchall()}
            # The old spellings are GONE, not shadowed: an `accounts` table or
            # an `accounts_by_email` index surviving beside the new ones is the
            # residue that makes the next reader guess which is authoritative.
            assert "users" in names and "accounts" not in names
            assert "users_by_email" in names and "accounts_by_email" not in names
            # The foreign key followed the rename, or `PRAGMA foreign_keys`
            # would be enforcing nothing at all on this table.
            assert ("users", "user_id") in {
                (r[2], r[3])
                for r in conn.execute("PRAGMA foreign_key_list(memberships)")
            }
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            conn.close()


def test_deleting_a_shelf_never_touches_the_books_that_stood_on_it():
    """Two aggregates, one file — so the cascade has to be checked, not
    assumed. §5.6's direction is that a book is never removed automatically;
    if `shelves` cascaded into `copies`, deleting a mistyped shelf would delete
    every book on it, and the destructive direction is exactly the one the
    whole reconciliation design refuses to take.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "books.db"
        books, shelves = SqliteBookStore(path), SqliteShelfStore(path)
        shelves.save_shelf(LIB, _sh(1))
        books.save(LIB, _book(1, shelf_id="sh1"))

        assert shelves.delete_shelf(LIB, "sh1") is True
        kept = books.get(LIB, "b1")
        assert kept is not None, "deleting a shelf deleted its books"
        # The copy still names the shelf it stood on: clearing it is
        # `remove_from_shelf`, a domain operation, and P2.2 owns the sequence
        # in the API where both stores are in hand. Asserted so the gap is a
        # recorded decision rather than a surprise.
        assert kept.copies[0].shelf_id == "sh1"


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
