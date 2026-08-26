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
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.memory_store import (
    MemoryBookStore,
    MemoryDecisionStore,
    MemoryDuplicateQueue,
    MemoryMapStore,
    MemoryMapUndoStore,
    MemoryReadStore,
    MemoryShelfStore,
    MemoryTenancyStore,
)
from app.adapters.migrations import SCHEMA_VERSION, current_version, migrate
from app.adapters.sqlite_store import (
    SqliteBookStore,
    SqliteDecisionStore,
    SqliteDuplicateQueue,
    SqliteMapStore,
    SqliteMapUndoStore,
    SqliteReadStore,
    SqliteShelfStore,
    SqliteTenancyStore,
)
from app.domain import (
    Account,
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
    new_account,
    new_book,
    new_capture,
    new_library,
    new_bookcase,
    new_floor,
    new_place,
    new_read,
    new_section,
    new_shelf,
    new_site,
    observe,
    remove_from_shelf,
    rename_shelf,
    return_copy,
    stop_read,
    with_diff_summary,
)
from app.domain import NotEmpty, NotOnThisFloor, Rect, ShelfAddress
from app.ports.map import UnknownParent
from app.ports.store import (
    BookPage,
    BookSort,
    DuplicateBookKey,
    DuplicateCaptureSlot,
    DuplicateSectionOrdinal,
    DuplicateShelfSlot,
    ShelfHasAliases,
    ShelfNotEmpty,
    UnknownShelf,
    WrongLibrary,
)
from app.ports.tenancy import UnknownAccount, UnknownUser

LIB = LibraryRef("lib-a", "Library A")
OTHER = LibraryRef("lib-b", "Library B")

CONTRACT: list = []
SHELF_CONTRACT: list = []
READ_CONTRACT: list = []
DECISION_CONTRACT: list = []
DUPLICATE_CONTRACT: list = []
TENANCY_CONTRACT: list = []
MAP_CONTRACT: list = []
UNDO_CONTRACT: list = []

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


def undo_contract(fn):
    """Mark a function as part of the MapUndoStore spec (P6.4b).

    ⚠ This list exists because its absence had already cost something. The
    SQLite store's codec dropped ``MapRestore.created`` — not in
    ``RESTORE_ORDER`` — and every entry carrying one became permanently
    un-undoable while refusing with the name of a shelf that had not changed.
    Nothing went red, because every test of the journal ran on the memory
    store, and two docstrings asserted that a shared contract already caught
    exactly this. A migration review found it by hand.
    """
    UNDO_CONTRACT.append(fn)
    return fn


def duplicate_contract(fn):
    """Mark a function as part of the DuplicateQueue spec (P2.6). A fifth
    list, same reasoning as the others."""
    DUPLICATE_CONTRACT.append(fn)
    return fn


def map_contract(fn):
    """Mark a function as part of the MapStore spec (P6.1).

    ⚠ A seventh list, and the only one whose cases take a PAIR — the map store
    and the shelf store, over one library. A slot and the shelf standing in it
    are different aggregates by design (MAP_PLAN §3.1), so a case that could
    only see one of them could not assert the rule that matters: an occupied
    slot is never deleted out from under its books.
    """
    MAP_CONTRACT.append(fn)
    return fn


def tenancy_contract(fn):
    """Mark a function as part of the TenancyStore spec (P3.1).

    ⚠ A sixth list, and the only one whose cases take no ``LibraryRef`` — this
    is the store that ANSWERS which libraries exist, so it is scoped by the
    USER instead (see the port's own ⚠⚠). Everything above narrows by
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

    ⚠ **Named FIRST, then the unnamed by age.** This assertion used to read
    `["sh3", "sh1", "sh2"]` — the unnamed pair ahead of the named shelf —
    which is what a key beginning with the label does, since an empty string
    sorts first. `Shelf.sort_key`'s own docstring, `GET /shelves`'s docstring
    and this one all said the opposite, and both implementations agreed with
    each other, so nothing was ever red. P6.4c's picker is the first screen
    where the order is a decision aid, and a review reading it counted
    fifteen unnamed rows before the twenty-six the owner had named.
    """
    store.save_shelf(LIB, _sh(1, label="", created_at="2026-08-05"))
    store.save_shelf(LIB, _sh(2, label="אכסדרה", created_at="2026-08-01"))
    store.save_shelf(LIB, _sh(3, label="", created_at="2026-08-02"))
    assert [s.id for s in store.list_shelves(LIB)] == ["sh2", "sh3", "sh1"]


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
    """Two customers: one owning two libraries, one owning a third.

    ⚠ The shape this suite needs after P3.7b. `USR2` is deliberately a member
    of BOTH accounts — an editor of one and the admin of the other — because
    almost every isolation bug below is invisible against a user who belongs
    to exactly one customer.
    """
    store.save_user(USR)
    store.save_user(USR2)
    acc, mine = new_account(id="acc-1", owner=USR, label="Malin",
                            created_at="2026-01-01T00:00:00+00:00")
    other, theirs = new_account(id="acc-2", owner=USR2, label="Shop",
                                created_at="2026-03-01T00:00:00+00:00")
    for account, membership in ((acc, mine), (other, theirs)):
        store.save_account(account)
        store.save_membership(membership)
    store.save_membership(Membership(USR2.id, acc.id, Role.EDITOR))
    for lib in (
        new_library(id="lib-1", label="משפחת מלין", account=acc,
                    created_at="2026-01-01T00:00:00+00:00"),
        new_library(id="lib-2", label="Office", account=acc,
                    created_at="2026-02-01T00:00:00+00:00"),
        new_library(id="lib-3", label="Stock", account=other,
                    created_at="2026-03-01T00:00:00+00:00"),
    ):
        store.save_library(lib)
    return acc, other


@tenancy_contract
def a_user_round_trips(store):
    store.save_user(USR)
    got = store.get_user(USR.id)
    assert got is not None and got.display_name == "משה"
    assert store.get_user("nobody") is None


@tenancy_contract
def an_account_round_trips(store):
    store.save_user(USR)
    acc, membership = new_account(id="acc-1", owner=USR, label="Malin")
    store.save_account(acc)
    store.save_membership(membership)
    got = store.get_account("acc-1")
    assert got is not None and got.label == "Malin"
    assert store.get_account("acc-nobody") is None


@tenancy_contract
def a_library_round_trips_and_yields_the_tenant_key(store):
    """`Library.ref` is the one-way door to `LibraryRef`, so nothing
    downstream has to know which of the two it was handed — and the ref
    deliberately does NOT carry the account (see `Library.ref`)."""
    store.save_user(USR)
    acc, membership = new_account(id="acc-1", owner=USR)
    store.save_account(acc)
    store.save_membership(membership)
    store.save_library(new_library(id="lib-1", label="משפחת מלין", account=acc))
    got = store.get_library("lib-1")
    assert got is not None and got.ref == LibraryRef("lib-1", "משפחת מלין")
    assert got.account_id == "acc-1"


@tenancy_contract
def an_account_owns_its_libraries_and_sees_no_others(store):
    """The isolation property of THIS store. Every other aggregate leaks one
    record when its scope is dropped; this one leaks a whole customer."""
    _seed_two_libraries(store)
    # A set: the ORDER is a separate rule with its own case below, and a
    # Latin label sorts before a Hebrew one, which says nothing about scope.
    assert {lib.id for lib in store.list_libraries("acc-1")} == {"lib-1", "lib-2"}
    assert [lib.id for lib in store.list_libraries("acc-2")] == ["lib-3"]
    assert store.list_libraries("acc-nobody") == ()


@tenancy_contract
def a_user_only_ever_sees_the_accounts_it_belongs_to(store):
    """The other half of the same property, on the identity axis: this is the
    call that answers *which customers may I name at all*."""
    _seed_two_libraries(store)
    assert [a.id for a, _m in store.list_accounts(USR.id)] == ["acc-1"]
    assert {a.id for a, _m in store.list_accounts(USR2.id)} == {"acc-1", "acc-2"}
    assert store.list_accounts("usr-nobody") == ()


@tenancy_contract
def a_listed_account_carries_the_role_that_was_granted(store):
    """The switcher renders the libraries of these accounts and labels each
    with this role, and P3.2's policy reads it — a listing that dropped it
    would send every caller back for a second lookup per row."""
    _seed_two_libraries(store)
    assert {a.id: m.role for a, m in store.list_accounts(USR2.id)} == {
        "acc-1": Role.EDITOR, "acc-2": Role.ADMIN,
    }
    assert {a.id: m.role for a, m in store.list_accounts(USR.id)} == {
        "acc-1": Role.ADMIN,
    }


@tenancy_contract
def libraries_are_listed_in_the_domains_order_not_the_adapters(store):
    """`Library.sort_key`: named alphabetically, then the nameless v12
    backfill oldest-first, id last. An order that varies between adapters is
    an order the user experiences as the switcher reshuffling itself."""
    store.save_user(USR)
    acc, membership = new_account(id="acc-1", owner=USR)
    store.save_account(acc)
    store.save_membership(membership)
    rows = [
        Library(id="l-z", account_id="acc-1", label="Zebra",
                created_at="2026-01-01"),
        Library(id="l-a", account_id="acc-1", label="Aleph",
                created_at="2026-03-01"),
        # The backfilled shape: no label, no created_at.
        Library(id="l-old", account_id="acc-1"),
        Library(id="l-mid", account_id="acc-1", created_at="2020-01-01"),
    ]
    for lib in rows:
        store.save_library(lib)
    assert [lib.id for lib in store.list_libraries("acc-1")] == \
        ["l-old", "l-mid", "l-a", "l-z"]


@tenancy_contract
def a_role_change_replaces_the_membership_rather_than_adding_one(store):
    """One membership per (user, account) — the store declares it as a
    composite key, so `save_membership` is a plain upsert."""
    _seed_two_libraries(store)
    store.save_membership(Membership(USR2.id, "acc-1", Role.ADMIN))
    rows = {a.id: m.role for a, m in store.list_accounts(USR2.id)}
    assert rows == {"acc-1": Role.ADMIN, "acc-2": Role.ADMIN}


@tenancy_contract
def a_membership_naming_a_missing_user_or_account_is_refused(store):
    """The row it would create is a permission granted to nobody, or over
    nothing. SQLite declares it as a foreign key; the memory store has none,
    so both check explicitly or the two adapters disagree."""
    store.save_user(USR)
    acc, membership = new_account(id="acc-1", owner=USR)
    store.save_account(acc)
    store.save_membership(membership)
    _raises(UnknownUser, store.save_membership,
            Membership("usr-ghost", "acc-1", Role.EDITOR))
    _raises(UnknownAccount, store.save_membership,
            Membership(USR.id, "acc-ghost", Role.EDITOR))


@tenancy_contract
def a_library_owned_by_no_account_is_refused(store):
    """A library saved against an owner nobody has is unreachable by every
    caller — `current_library` resolves THROUGH the account — while still
    holding books and still occupying blob storage. That is the phantom shape
    §4.1 refuses one level down, so the store refuses it here."""
    store.save_user(USR)
    acc, membership = new_account(id="acc-1", owner=USR)
    store.save_account(acc)
    store.save_membership(membership)
    ghost = Library(id="lib-x", account_id="acc-ghost", label="Nowhere")
    _raises(UnknownAccount, store.save_library, ghost)
    assert store.get_library("lib-x") is None


@tenancy_contract
def membership_answers_the_resolvers_question_and_nothing_else(store):
    """The hot path: `deps.owner_membership` calls it on every request that
    names a library, with the account read off that library's own row."""
    _seed_two_libraries(store)
    assert store.membership(USR.id, "acc-1").role is Role.ADMIN
    assert store.membership(USR.id, "acc-2") is None
    assert store.membership("usr-nobody", "acc-1") is None


@tenancy_contract
def removing_a_member_removes_nobody_elses_membership_and_no_library(store):
    """UI_PLAN §5's separation, one level up: the person leaves, the
    collection stays."""
    _seed_two_libraries(store)
    assert store.delete_membership(USR2.id, "acc-1") is True
    assert store.delete_membership(USR2.id, "acc-1") is False
    assert {lib.id for lib in store.list_libraries("acc-1")} == {"lib-1", "lib-2"}

    # ⚠ USR2 held TWO memberships and lost exactly one. Without a second one
    # this case cannot detect a DELETE that dropped its account narrowing —
    # "delete this pair" and "delete every row for this user" would remove the
    # same thing — and the first person ever removed from one customer would
    # silently lose every customer they belong to, including ones they are the
    # last admin of, which is the state `NoAdminLeft` exists to make
    # unreachable. (P3.7a's data-integrity review mutated exactly this shape
    # and watched the whole ring stay green.)
    assert [a.id for a, _m in store.list_accounts(USR2.id)] == ["acc-2"]
    assert store.membership(USR2.id, "acc-2") is not None


@tenancy_contract
def list_members_returns_the_whole_list_the_domain_rules_need(store):
    """`set_role`/`remove_member` take the WHOLE member list, because "is
    there still an admin?" is unanswerable from one row. Admins first, so a
    members screen does not have to re-sort what the store already knows."""
    _seed_two_libraries(store)
    members = store.list_members("acc-1")
    assert [m.user_id for m in members] == [USR.id, USR2.id]
    assert [m.role for m in members] == [Role.ADMIN, Role.EDITOR]
    assert store.list_members("acc-nobody") == ()


@tenancy_contract
def a_library_is_readable_by_id_even_by_a_caller_with_no_membership(store):
    """⚠ Deliberate: 404-not-403 is about what the API SAYS, and the route
    needs "no such library" and "not yours" to stay distinguishable INSIDE the
    server to answer correctly. A store that conflated them would make the
    two indistinguishable everywhere, including in a log."""
    _seed_two_libraries(store)
    lib = store.get_library("lib-3")
    assert lib is not None and lib.account_id == "acc-2"
    assert store.membership(USR.id, lib.account_id) is None
    assert store.get_library("lib-nothing") is None


# --- the map (P6.1) -------------------------------------------------------
#
# A seventh contract list, and the only one whose cases get TWO stores: a slot
# and the shelf standing in it live in different aggregates on purpose
# (MAP_PLAN §3.1 — a drawn shelf IS a Shelf, not a second concept), so every
# rule about "may this bookcase be deleted" is a rule about both.


def _drawn(maps, shelves, *, library=LIB, columns=2, levels=5, depth=1):
    """One site, one floor, one room, one case, one section — the smallest
    drawing that has every level of the address in it."""
    maps.save_site(library, new_site(id=f"{library.id}-st",
                                     library_id=library.id, name="הבית"))
    maps.save_floor(library, new_floor(id=f"{library.id}-fl",
                                       library_id=library.id,
                                       site_id=f"{library.id}-st",
                                       name="קומת קרקע"))
    maps.save_place(library, new_place(id=f"{library.id}-pl",
                                       library_id=library.id,
                                       floor_id=f"{library.id}-fl",
                                       rect=Rect(0, 0, 10, 8), name="סלון"))
    maps.save_bookcase(library, new_bookcase(id=f"{library.id}-bc",
                                             library_id=library.id,
                                             floor_id=f"{library.id}-fl",
                                             rect=Rect(0, 0, 4, 1),
                                             place_id=f"{library.id}-pl"))
    section = new_section(id=f"{library.id}-se", library_id=library.id,
                          bookcase_id=f"{library.id}-bc", columns=columns,
                          default_levels=levels, default_depth=depth)
    maps.save_section(library, section)
    return section


@map_contract
def saves_and_reads_back_the_whole_drawing(stores):
    """`load_map` is the plan screen's ONE query, and it comes back ordered —
    sites by the owner's order, sections bottom-first — so no caller sorts and
    then disagrees with another caller that sorted differently."""
    maps, shelves, books = stores
    _drawn(maps, shelves)
    snap = maps.load_map(LIB)
    assert [s.name for s in snap.sites] == ["הבית"]
    assert [f.name for f in snap.floors] == ["קומת קרקע"]
    assert [p.rect for p in snap.places] == [Rect(0, 0, 10, 8)]
    assert snap.bookcases[0].place_id == "lib-a-pl"
    assert snap.sections[0].column_levels == (5, 5)
    assert not snap.is_empty


@map_contract
def a_sections_gaps_survive_a_round_trip_and_leave_the_extent_alone(stores):
    """P6.3.2: the cells switched off are part of the section, so they come
    back with it — through `load_map`, which is the only query the elevation
    makes, and through `get_section`, which every edit re-reads.

    ⚠ It asserts the EXTENT as well, in the same breath. A store that
    persisted the mask by shrinking the columns it masks would round-trip the
    holes perfectly and quietly renumber every shelf below one — which is the
    single behaviour this feature exists to avoid, and the one a test that
    only checked `gaps` would never see.
    """
    maps, shelves, books = stores
    section = _drawn(maps, shelves, columns=3, levels=4)
    maps.save_section(LIB, replace(section, gaps=((2, 2), (2, 3))))

    read = maps.get_section(LIB, section.id)
    assert read.gaps == ((2, 2), (2, 3))
    assert read.column_levels == (4, 4, 4), (
        "the mask was stored by resizing the case it masks"
    )
    assert {(a.col, a.level) for a in read.addresses if a.col == 2} == {
        (2, 1), (2, 4)}
    assert maps.load_map(LIB).sections[0].gaps == ((2, 2), (2, 3))

    # And back off again: a section written with no gaps HAS no gaps. An
    # UPSERT that omitted the column would leave the old mask in place, and
    # the cell the owner just restored would come back a hole on reload.
    maps.save_section(LIB, replace(read, gaps=()))
    assert maps.get_section(LIB, section.id).gaps == ()


@map_contract
def the_whole_drawing_comes_back_in_the_order_the_screens_want(stores):
    """⚠ Two of everything, deliberately. A review found the round-trip case
    building ONE of each, which makes order unobservable — the same defect
    class as "even column heights make dropping from the front and from the
    end indistinguishable", and both implementations' sort keys survived
    being reversed.

    It matters most for P6.3: the lab's elevation reverses the section array
    to draw top-down, so a section order the port disagrees with silently
    inverts a bookcase — the hutch is drawn as the base.
    """
    maps, shelves, books = stores
    # ⚠ The ids sort OPPOSITE to the order, deliberately: with `s1`/`s2` a
    # store that ignored `order` and fell back to id produced the same list,
    # and the mutation check caught this assertion passing either way.
    for order, name, sid in ((2, "אצל ההורים", "a-parents"),
                             (1, "הבית", "z-home")):
        maps.save_site(LIB, new_site(id=sid, library_id=LIB.id, name=name,
                                     order=order))
    for sid, fid, order, name in (("z-home", "f-up", 2, "קומה א"),
                                  ("z-home", "f-down", 1, "קרקע")):
        maps.save_floor(LIB, new_floor(id=fid, library_id=LIB.id, site_id=sid,
                                       name=name, order=order))
    for pid, fid, order in (("p2", "f-down", 2), ("p1", "f-down", 1)):
        maps.save_place(LIB, new_place(id=pid, library_id=LIB.id,
                                       floor_id=fid, rect=Rect(0, 0, 5, 5),
                                       order=order))
    for bid, order in (("bc2", 2), ("bc1", 1)):
        maps.save_bookcase(LIB, new_bookcase(id=bid, library_id=LIB.id,
                                             floor_id="f-down",
                                             rect=Rect(0, 0, 3, 1),
                                             order=order))
    for sec, ordinal in (("hutch", 2), ("base", 1)):
        maps.save_section(LIB, new_section(id=sec, library_id=LIB.id,
                                           bookcase_id="bc1", ordinal=ordinal))

    snap = maps.load_map(LIB)
    assert [s.id for s in snap.sites] == ["z-home", "a-parents"], (
        "sites came back in id order, so `order` is ignored"
    )
    assert [f.id for f in snap.floors] == ["f-down", "f-up"]
    assert [p.id for p in snap.places] == ["p1", "p2"]
    assert [b.id for b in snap.bookcases] == ["bc1", "bc2"]
    assert [s.id for s in snap.sections] == ["base", "hutch"], (
        "sections came back top-first; the elevation would draw the hutch "
        "as the base"
    )


@map_contract
def an_undrawn_library_reads_as_empty_and_one_room_does_not(stores):
    """`is_empty` answers a SCREEN's question — *is there anything to show?* —
    so it counts rooms and furniture, not the site and floor every library
    starts with. Stated in the port and, until a review said so, nowhere
    enforced."""
    maps, shelves, books = stores
    assert maps.load_map(LIB).is_empty
    maps.save_site(LIB, new_site(id="st", library_id=LIB.id, name="הבית"))
    maps.save_floor(LIB, new_floor(id="fl", library_id=LIB.id, site_id="st",
                                   name="קרקע"))
    assert maps.load_map(LIB).is_empty, (
        "a library with only its starting site and floor looked drawn"
    )
    maps.save_place(LIB, new_place(id="pl", library_id=LIB.id, floor_id="fl",
                                   rect=Rect(0, 0, 4, 4)))
    assert not maps.load_map(LIB).is_empty


@map_contract
def a_drawing_in_another_library_reads_as_absent(stores):
    """§4.2's rule, one level out: a foreign record is ABSENT, never
    forbidden, so the API can answer 404 without leaking existence."""
    maps, shelves, books = stores
    _drawn(maps, shelves)
    assert maps.get_site(OTHER, "lib-a-st") is None
    assert maps.get_floor(OTHER, "lib-a-fl") is None
    assert maps.get_place(OTHER, "lib-a-pl") is None
    assert maps.get_bookcase(OTHER, "lib-a-bc") is None
    assert maps.get_section(OTHER, "lib-a-se") is None
    assert maps.load_map(OTHER).is_empty


@map_contract
def a_record_written_to_the_wrong_library_raises(stores):
    """Never a user error — always a wiring bug, and the kind that files one
    tenant's furniture in another's house."""
    maps, shelves, books = stores
    _raises(WrongLibrary, maps.save_site, OTHER,
            new_site(id="x", library_id=LIB.id, name="הבית"))


@map_contract
def a_floor_whose_site_is_missing_is_refused(stores):
    """The parent check is in BOTH stores rather than left to SQLite's foreign
    key: a rule only one implementation holds is a rule the API ring never
    exercises."""
    maps, shelves, books = stores
    _raises(UnknownParent, maps.save_floor, LIB,
            new_floor(id="f", library_id=LIB.id, site_id="nope", name="x"))


@map_contract
def a_bookcase_may_not_attach_to_a_room_on_another_storey(stores):
    """MAP_PLAN §3.7: a room is found only on its own storey. Without this a
    case drawn upstairs attaches to the kitchen underneath it — and then moves
    with it."""
    maps, shelves, books = stores
    _drawn(maps, shelves)
    maps.save_floor(LIB, new_floor(id="fl2", library_id=LIB.id,
                                   site_id="lib-a-st", name="קומה א"))
    _raises(NotOnThisFloor, maps.save_bookcase, LIB,
            new_bookcase(id="bc2", library_id=LIB.id, floor_id="fl2",
                         rect=Rect(0, 0, 3, 1), place_id="lib-a-pl"))


@map_contract
def deleting_a_room_leaves_its_bookcases_standing(stores):
    """The lab's rule, and the product's own: deleting a container never
    destroys what it held. The case stays where it is, attached to no room."""
    maps, shelves, books = stores
    _drawn(maps, shelves)
    assert maps.delete_place(LIB, "lib-a-pl") is True
    case = maps.get_bookcase(LIB, "lib-a-bc")
    assert case is not None, "the room took its furniture with it"
    assert case.place_id is None
    assert case.rect == Rect(0, 0, 4, 1), "the case moved when its room went"


@map_contract
def a_storey_with_anything_on_it_is_never_removed(stores):
    """§3.7 — and the message says what is in the way, because "cannot
    delete" without a reason is what makes the next reader delete the
    guard."""
    maps, shelves, books = stores
    _drawn(maps, shelves)
    maps.save_floor(LIB, new_floor(id="fl2", library_id=LIB.id,
                                   site_id="lib-a-st", name="קומה א"))
    err = _raises(NotEmpty, maps.delete_floor, LIB, "lib-a-fl")
    assert "room" in str(err) and "bookcase" in str(err), str(err)
    assert maps.get_floor(LIB, "lib-a-fl") is not None


@map_contract
def the_last_storey_of_a_site_and_the_last_site_are_kept(stores):
    """A plan has somewhere to be — the lab refused the last floor for the
    same reason, and an empty picker is not a simpler editor."""
    maps, shelves, books = stores
    _drawn(maps, shelves)
    maps.delete_bookcase(LIB, "lib-a-bc")
    maps.delete_place(LIB, "lib-a-pl")
    _raises(NotEmpty, maps.delete_floor, LIB, "lib-a-fl")
    _raises(NotEmpty, maps.delete_site, LIB, "lib-a-st")


@contract
def counting_the_copies_on_each_shelf_is_one_question_per_library(store):
    """What a destructive gesture has to be able to SAY, and what lets it stay
    quiet: a slot holding nothing needs no dialog at all.

    The companion to `deepest_copy_depth` — how many, not how far back — and
    whole-library for the same reason: the shelf list renders every shelf a
    household has, and a query per row is tens of queries for one screen.
    """
    assert store.copies_per_shelf(LIB) == {}, "an empty library counted something"

    store.save(LIB, _book(1, shelf_id="sh1"))
    store.save(LIB, _book(2, shelf_id="sh1"))
    store.save(LIB, _book(3, shelf_id="sh2"))
    store.save(LIB, _book(4))                       # located nowhere
    assert store.copies_per_shelf(LIB) == {"sh1": 2, "sh2": 1}

    # …and it is library-scoped, like every method on this port (H2).
    store.save(OTHER, _book(9, library=OTHER, shelf_id="sh1"))
    assert store.copies_per_shelf(LIB) == {"sh1": 2, "sh2": 1}
    assert store.copies_per_shelf(OTHER) == {"sh1": 1}


@map_contract
def a_shelf_holding_books_is_not_deleted_by_either_implementation(stores):
    """⚠⚠ The refusal no foreign key can make.

    `copies.shelf_id` names a shelf in a plain column — the table predates
    `shelves` by four schema versions — so SQLite cannot police this and
    `PRAGMA foreign_key_check` reports a clean file over a library whose
    locations have been silently emptied. Measured on a real migrated database
    before this spec existed: shelf deleted, copy still naming it, nothing
    anywhere complaining.

    It lives in THIS group because the map fixture is the one that holds all
    three stores, and its own docstring already says why: *"whether that shelf
    may be erased depends on a BookStore one"*. It was the only sentence in
    that docstring nothing asserted.

    The captures refusal beside it (`deleting_a_shelf_with_captures_is_refused
    _not_cascaded`) is the same rule about the other aggregate; this is the
    half that was documented as the caller's job and that no caller did.
    """
    _maps, shelves, books = stores
    shelves.save_shelf(LIB, _sh(1))
    books.save(LIB, _book(1, shelf_id="sh1"))

    _raises(ShelfNotEmpty, shelves.delete_shelf, LIB, "sh1")
    assert shelves.get_shelf(LIB, "sh1") is not None, "refused and deleted"
    # …and the book is untouched by the refusal — no half-cascade.
    kept = books.get(LIB, "b1")
    assert kept is not None and kept.copies[0].shelf_id == "sh1"

    # Off the shelf, and it goes. `remove_from_shelf` is the domain operation
    # the port's docstring names; the store simply stops refusing.
    books.save(LIB, _book(1))
    assert shelves.delete_shelf(LIB, "sh1") is True
    assert shelves.get_shelf(LIB, "sh1") is None


@map_contract
def a_site_drawn_by_mistake_can_be_removed_with_its_empty_storeys(stores):
    """⚠ Measured at review: these two refusals used to DEADLOCK. Removing a
    site was refused while it held any floor, and removing its only floor was
    refused because a site keeps at least one — so "the parents' place", drawn
    by mistake, was permanent.

    The refusal is about what the storeys HOLD. An empty floor leaves with its
    site: a floor with no rooms and no bookcases is not something "nothing
    auto-removes" is protecting, and the last site is still kept.
    """
    maps, shelves, books = stores
    _drawn(maps, shelves)
    maps.save_site(LIB, new_site(id="oops", library_id=LIB.id, name="בטעות"))
    maps.save_floor(LIB, new_floor(id="oops-g", library_id=LIB.id,
                                   site_id="oops", name="קרקע"))

    assert maps.delete_site(LIB, "oops") is True
    assert maps.get_floor(LIB, "oops-g") is None, "an orphan storey survived"
    assert maps.get_site(LIB, "oops") is None
    assert maps.get_floor(LIB, "lib-a-fl") is not None, (
        "removing one site took another site's storey"
    )

    # …but a site holding an actual room is still refused, naming it.
    maps.save_site(LIB, new_site(id="real", library_id=LIB.id, name="אמיתי"))
    maps.save_floor(LIB, new_floor(id="real-g", library_id=LIB.id,
                                   site_id="real", name="קרקע"))
    maps.save_place(LIB, new_place(id="real-pl", library_id=LIB.id,
                                   floor_id="real-g", rect=Rect(0, 0, 5, 5)))
    err = _raises(NotEmpty, maps.delete_site, LIB, "real")
    assert "1 room(s)" in str(err), str(err)
    assert maps.get_floor(LIB, "real-g") is not None


@map_contract
def a_foreign_librarys_map_cannot_be_deleted_either(stores):
    """Tenant isolation in the DESTRUCTIVE direction, which is the one worth
    pinning. A foreign object is ABSENT — `False`, not an error and not a
    refusal — so the API answers 404 and cannot leak existence even by the
    shape of the failure (§4.2)."""
    maps, shelves, books = stores
    a = _drawn(maps, shelves)
    _drawn(maps, shelves, library=OTHER)
    for delete, target in ((maps.delete_site, "lib-a-st"),
                           (maps.delete_floor, "lib-a-fl"),
                           (maps.delete_place, "lib-a-pl"),
                           (maps.delete_bookcase, "lib-a-bc"),
                           (maps.delete_section, a.id)):
        assert delete(OTHER, target) is False, (
            f"{delete.__name__} reached into another library"
        )
    assert maps.get_site(LIB, "lib-a-st") is not None
    assert maps.get_bookcase(LIB, "lib-a-bc") is not None
    assert maps.get_section(LIB, a.id) is not None
    assert len(maps.load_map(LIB).places) == 1


@map_contract
def a_bookcase_with_a_shelf_still_in_it_is_never_deleted(stores):
    """The silent-data-loss path MAP_PLAN §2 predicted for this item. The
    store refuses; emptying the slots is `app/map_edit.py`'s explicit job."""
    maps, shelves, books = stores
    section = _drawn(maps, shelves)
    shelves.save_shelf(LIB, new_shelf(id="sh1", library_id=LIB.id,
                                      address=ShelfAddress(section.id, 1, 1)))
    err = _raises(NotEmpty, maps.delete_bookcase, LIB, "lib-a-bc")
    assert "stand" in str(err)
    assert maps.get_bookcase(LIB, "lib-a-bc") is not None


@map_contract
def an_emptied_bookcase_takes_its_sections_with_it(stores):
    """A section is not addressable on its own, so it has no life after its
    bookcase — the one place a cascade is right."""
    maps, shelves, books = stores
    section = _drawn(maps, shelves)
    assert maps.delete_bookcase(LIB, "lib-a-bc") is True
    assert maps.get_section(LIB, section.id) is None
    assert maps.load_map(LIB).sections == ()


@map_contract
def two_sections_of_one_bookcase_may_not_share_a_number(stores):
    """`ordinal` is what an address PRINTS (§3.6). Two sections both at 1 make
    *"section 1, column 2, level 3"* name two different shelves, so the owner
    is sent to the wrong half of the furniture. The lab could not express the
    state at all — its sections are an array — so the constraint arrives with
    the table rather than after somebody hits it."""
    maps, shelves, books = stores
    section = _drawn(maps, shelves)
    assert section.ordinal == 1
    _raises(DuplicateSectionOrdinal, maps.save_section, LIB,
            new_section(id="twin", library_id=LIB.id,
                        bookcase_id="lib-a-bc", ordinal=1))
    # …the next one up is fine, and re-saving the SAME section is an edit.
    maps.save_section(LIB, new_section(id="hutch", library_id=LIB.id,
                                       bookcase_id="lib-a-bc", ordinal=2))
    maps.save_section(LIB, new_section(id=section.id, library_id=LIB.id,
                                       bookcase_id="lib-a-bc", ordinal=1,
                                       columns=3))
    assert maps.get_section(LIB, section.id).column_count == 3


@map_contract
def the_last_section_of_a_bookcase_is_kept(stores):
    """A bookcase with no sections is not a simpler bookcase, it is an
    unaddressable one."""
    maps, shelves, books = stores
    section = _drawn(maps, shelves)
    _raises(NotEmpty, maps.delete_section, LIB, section.id)


@map_contract
def deleting_something_that_is_not_there_is_false_not_an_error(stores):
    """A second delete is not a failure — the client that retried is right."""
    maps, shelves, books = stores
    assert maps.delete_site(LIB, "nope") is False
    assert maps.delete_floor(LIB, "nope") is False
    assert maps.delete_place(LIB, "nope") is False
    assert maps.delete_bookcase(LIB, "nope") is False
    assert maps.delete_section(LIB, "nope") is False


@map_contract
def two_shelves_may_not_stand_in_one_slot(stores):
    """MAP_PLAN §3.1: a slot in a drawing is ONE physical shelf. Two rows
    addressed to it make "the books on level 3" answer differently on
    different page loads."""
    maps, shelves, books = stores
    section = _drawn(maps, shelves)
    at = ShelfAddress(section.id, 1, 1)
    shelves.save_shelf(LIB, new_shelf(id="sh1", library_id=LIB.id, address=at))
    _raises(DuplicateShelfSlot, shelves.save_shelf, LIB,
            new_shelf(id="sh2", library_id=LIB.id, address=at))
    # …but re-saving the SAME shelf at its own slot is an edit, not a clash.
    shelves.save_shelf(LIB, new_shelf(id="sh1", library_id=LIB.id,
                                      label="עליון", address=at))
    assert shelves.get_shelf_at(LIB, at).label == "עליון"


@map_contract
def a_shelf_may_not_be_addressed_to_a_section_that_is_not_there(stores):
    """Found at review: sqlite raised a raw `IntegrityError` and the memory
    store accepted it silently — so the API ring, which runs on memory stores,
    would have taken an address the real database refuses and turned it into
    a 500 in production.

    A foreign library's section counts as absent, which is §4.2's rule again:
    the foreign key cannot express "in THIS library", so the check is in
    Python — exactly as `save_capture` already does for a capture's shelf.
    """
    maps, shelves, books = stores
    _drawn(maps, shelves)
    other = _drawn(maps, shelves, library=OTHER)
    _raises(UnknownParent, shelves.save_shelf, LIB,
            new_shelf(id="sh", library_id=LIB.id,
                      address=ShelfAddress("no-such-section", 1, 1)))
    _raises(UnknownParent, shelves.save_shelf, LIB,
            new_shelf(id="sh", library_id=LIB.id,
                      address=ShelfAddress(other.id, 1, 1)))
    assert shelves.get_shelf(LIB, "sh") is None


@map_contract
def a_shelf_holding_a_book_is_found_even_with_no_photograph(stores):
    """The half of "is this slot occupied?" a reasonable person leaves out,
    and the DEPTH it answers with in the same breath.

    A shelf can hold books with no capture at all — a MANUAL entry, or a photo
    deleted later. Asking only about captures calls it empty and hands it to
    the DELETE branch of `plan_slot_removal`. And the depth is not a second
    question: `map_edit` needs *how far back* to clamp a section's depth
    default, and two queries that could disagree is how a copy ends up
    recorded at a depth its shelf no longer declares.
    """
    maps, shelves, books = stores
    section = _drawn(maps, shelves)
    shelves.save_shelf(LIB, new_shelf(id="sh1", library_id=LIB.id,
                                      depth_count=2,
                                      address=ShelfAddress(section.id, 1, 1)))
    assert books.deepest_copy_depth(LIB) == {}
    books.save(LIB, _book(9, shelf_id="sh1", depth=2))
    assert books.deepest_copy_depth(LIB) == {"sh1": 2}, (
        "the deepest occupied depth is wrong, so the clamp would shallow it"
    )
    assert books.deepest_copy_depth(OTHER) == {}, (
        "one library's occupied shelves leaked into another's"
    )


@map_contract
def a_shelfs_address_survives_a_round_trip_and_orders_by_slot(stores):
    """`list_shelves_in_section` comes back in the address's own order, so a
    caller never sorts and then disagrees with the elevation on screen."""
    maps, shelves, books = stores
    section = _drawn(maps, shelves)
    for col, level in ((2, 3), (1, 2), (1, 1)):
        shelves.save_shelf(LIB, new_shelf(
            id=f"sh{col}{level}", library_id=LIB.id, depth_count=2,
            address=ShelfAddress(section.id, col, level)))
    got = shelves.list_shelves_in_section(LIB, section.id)
    assert [(s.address.col, s.address.level) for s in got] == [
        (1, 1), (1, 2), (2, 3)]
    assert got[0].depth_count == 2, "the shelf's own depth did not survive"
    assert all(s.is_addressed for s in got)


@map_contract
def an_unaddressed_shelf_is_normal_and_stays_out_of_the_slot_queries(stores):
    """Every shelf that exists today is unaddressed, and that stays legal
    forever — §3.1 makes the drawn and the photographed ONE population, and
    P6.4 binds them rather than this item requiring it."""
    maps, shelves, books = stores
    section = _drawn(maps, shelves)
    shelves.save_shelf(LIB, new_shelf(id="photo", library_id=LIB.id,
                                      label="מהתמונה"))
    assert shelves.get_shelf(LIB, "photo").address is None
    assert shelves.get_shelf(LIB, "photo").is_addressed is False
    assert shelves.list_shelves_in_section(LIB, section.id) == ()
    assert len(shelves.list_shelves(LIB)) == 1


@map_contract
def one_librarys_slots_are_invisible_to_another(stores):
    """Tenant isolation on the newest aggregate — the same suite every other
    port here carries, written against two refs from the first day."""
    maps, shelves, books = stores
    a = _drawn(maps, shelves)
    b = _drawn(maps, shelves, library=OTHER)
    shelves.save_shelf(LIB, new_shelf(id="sh-a", library_id=LIB.id,
                                      address=ShelfAddress(a.id, 1, 1)))
    shelves.save_shelf(OTHER, new_shelf(id="sh-b", library_id=OTHER.id,
                                        address=ShelfAddress(b.id, 1, 1)))
    assert [s.id for s in shelves.list_shelves_in_section(LIB, a.id)] == ["sh-a"]
    assert shelves.get_shelf_at(OTHER, ShelfAddress(a.id, 1, 1)) is None
    assert len(maps.load_map(OTHER).sites) == 1


@map_contract
def a_whole_bookcase_of_shelves_is_written_as_one_unit(stores):
    """`save_shelves` exists because the SQL adapter opens a connection per
    operation: a security review measured 40 columns of 40 costing 16.5s and
    1600 connections. All-or-nothing, so a rejected member leaves none of
    them written — the same contract as one `save_shelf`, applied to each."""
    maps, shelves, books = stores
    section = _drawn(maps, shelves)
    batch = tuple(new_shelf(id=f"sh{i}", library_id=LIB.id,
                            address=ShelfAddress(section.id, 1, i + 1))
                  for i in range(5))
    shelves.save_shelves(LIB, batch)
    assert len(shelves.list_shelves_in_section(LIB, section.id)) == 5

    # One bad member and NOTHING lands — here, a second shelf claiming a slot
    # the first of the batch already took.
    clash = (new_shelf(id="ok", library_id=LIB.id,
                       address=ShelfAddress(section.id, 2, 1)),
             new_shelf(id="clash", library_id=LIB.id,
                       address=ShelfAddress(section.id, 2, 1)))
    _raises(DuplicateShelfSlot, shelves.save_shelves, LIB, clash)
    assert shelves.get_shelf(LIB, "ok") is None, (
        "a batch wrote some of its shelves and then refused the rest"
    )
    shelves.save_shelves(LIB, ())          # empty is a no-op, not an error


@map_contract
def the_deepest_photograph_on_each_shelf_comes_back_in_one_query(stores):
    """The captures half of "is anything standing here?", grouped.

    Asking `list_captures` once per shelf is the correlated-per-row pattern
    that made `/images` take 13.6s for one page — CLAUDE.md records it, and a
    review measured this router repeating it.
    """
    maps, shelves, books = stores
    section = _drawn(maps, shelves)
    shelf = new_shelf(id="sh1", library_id=LIB.id, depth_count=3,
                      address=ShelfAddress(section.id, 1, 1))
    shelves.save_shelf(LIB, shelf)
    assert shelves.deepest_capture_depth(LIB) == {}
    shelves.save_capture(LIB, new_capture(shelf, id="c1", depth=1))
    shelves.save_capture(LIB, new_capture(shelf, id="c2", depth=3))
    assert shelves.deepest_capture_depth(LIB) == {"sh1": 3}
    assert shelves.deepest_capture_depth(OTHER) == {}, (
        "one library's photographs leaked into another's"
    )


@map_contract
def a_bookcases_sections_are_renumbered_as_one_unit(stores):
    """⚠ Inserting at the BOTTOM pushes every section up an ordinal, and
    `ordinal` is unique per bookcase AND is what an address prints.

    A review measured the one-at-a-time version failing part-way: sections
    shifted, the new one never created, a GAP at 3, and the request answering
    an error while having permanently changed the drawing. Every retry
    widened it. So the whole set is one write — and it must survive the
    transient collision that "push everything up by one" always produces.
    """
    maps, shelves, books = stores
    base = _drawn(maps, shelves)
    maps.save_section(LIB, new_section(id="mid", library_id=LIB.id,
                                       bookcase_id="lib-a-bc", ordinal=2))
    # Every existing section up one, and a new one on the floor. Written one
    # at a time in any order this collides; as a set it must not.
    maps.save_sections(LIB, (
        new_section(id="plinth", library_id=LIB.id, bookcase_id="lib-a-bc",
                    ordinal=1),
        new_section(id=base.id, library_id=LIB.id, bookcase_id="lib-a-bc",
                    ordinal=2),
        new_section(id="mid", library_id=LIB.id, bookcase_id="lib-a-bc",
                    ordinal=3),
    ))
    got = [(s.id, s.ordinal) for s in maps.load_map(LIB).sections]
    assert got == [("plinth", 1), (base.id, 2), ("mid", 3)], got

    # …and a set that would leave two sections on one number is refused
    # WHOLE — nothing half-applied.
    _raises(DuplicateSectionOrdinal, maps.save_sections, LIB, (
        new_section(id="plinth", library_id=LIB.id, bookcase_id="lib-a-bc",
                    ordinal=9),
        new_section(id="twin", library_id=LIB.id, bookcase_id="lib-a-bc",
                    ordinal=9),
    ))
    assert maps.get_section(LIB, "plinth").ordinal == 1, (
        "a refused renumbering left one of its writes behind"
    )


@map_contract
def a_room_that_changes_storey_takes_its_furniture_with_it(stores):
    """⚠ Measured at review, through the routes: a room moved upstairs and
    its bookcase stayed on the ground floor — the state `NotOnThisFloor`
    exists to make unreachable. The case was then BRICKED: rename, move,
    resize and re-order all answered 409 forever, citing a mismatch the owner
    never created.

    A bookcase belongs to a room the way furniture does (§3.7), so it goes
    where the room goes, in one call.
    """
    maps, shelves, books = stores
    _drawn(maps, shelves)
    maps.save_floor(LIB, new_floor(id="up", library_id=LIB.id,
                                   site_id="lib-a-st", name="קומה א"))
    loose = new_bookcase(id="loose", library_id=LIB.id, floor_id="lib-a-fl",
                         rect=Rect(9, 9, 2, 1))
    maps.save_bookcase(LIB, loose)

    moved = maps.move_place(LIB, maps.get_place(LIB, "lib-a-pl"), "up")
    assert moved.floor_id == "up"
    assert maps.get_place(LIB, "lib-a-pl").floor_id == "up"
    assert maps.get_bookcase(LIB, "lib-a-bc").floor_id == "up", (
        "the room moved storeys and left its bookcase behind"
    )
    assert maps.get_bookcase(LIB, "loose").floor_id == "lib-a-fl", (
        "a case attached to no room was dragged along"
    )
    # …and the case is still writable, which is what being bricked cost.
    maps.save_bookcase(LIB, replace(maps.get_bookcase(LIB, "lib-a-bc"),
                                    name="renamed"))
    _raises(UnknownParent, maps.move_place, LIB,
            maps.get_place(LIB, "lib-a-pl"), "no-such-floor")


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
    # ⚠ Bound to books it will never be given any, which is the point: an
    # unbound store REFUSES to delete (it cannot answer "does a book stand
    # here"), and the shelf specs below delete shelves. SQLite needs no
    # binding — same file — but it needs the same rule, and that is what the
    # spec in the map group pins across both.
    shelves = MemoryShelfStore()
    shelves.bind_books(MemoryBookStore())
    # …and a §5.4 queue, because deleting a shelf now takes its unanswerable
    # questions with it (P6.4e). SQLite gets it from one file.
    shelves.bind_duplicates(MemoryDuplicateQueue())
    yield shelves


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
def _memory_map_stores():
    """The map, the shelves and the books, over one in-memory world.

    All three, because the rules this suite exists for span all three: a slot
    is a ``MapStore`` row, the shelf standing in it is a ``ShelfStore`` row,
    and whether that shelf may be erased depends on a ``BookStore`` one.

    ``bind_shelves``/``bind_map`` are the in-memory stand-in for what SQLite
    gets free — one file, so "does a shelf still stand in this section" and
    "is that section real" are joins. Without them the memory store would
    accept what the SQL one refuses, and the contract would be asserting
    SQLite's behaviour instead of the spec's.
    """
    shelves = MemoryShelfStore()
    maps = MemoryMapStore()
    books = MemoryBookStore()
    maps.bind_shelves(shelves)
    shelves.bind_map(maps)
    shelves.bind_books(books)
    yield maps, shelves, books


@contextmanager
def _sqlite_map_stores():
    with _fresh_db("booksnap-map-") as path:
        yield (SqliteMapStore(path), SqliteShelfStore(path),
               SqliteBookStore(path))


@contextmanager
def _memory_undo_store():
    yield MemoryMapUndoStore()


@contextmanager
def _sqlite_undo_store():
    with _fresh_db("booksnap-undo-") as path:
        yield SqliteMapUndoStore(path)


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
MAP_IMPLEMENTATIONS = (("memory", _memory_map_stores),
                       ("sqlite", _sqlite_map_stores))
UNDO_IMPLEMENTATIONS = (("memory", _memory_undo_store),
                        ("sqlite", _sqlite_undo_store))


def _bind(fn, factory, name):
    def run():
        with factory() as store:
            fn(store)

    # run_all.py reports fn.__name__, so without this every bound case prints
    # as "run" and a failure doesn't say WHICH implementation broke.
    run.__name__ = name
    run.__doc__ = fn.__doc__
    return run


# The map's factory yields a PAIR, which `_bind` passes through as one
# argument — the cases unpack it. No second binder needed.
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

        # Stops AT v13 rather than constructing a store, which would migrate
        # all the way to SCHEMA_VERSION: this case is about what v13 alone
        # does, and v14 rebuilds `memberships` again on top of it.
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version != 13:
                    continue
                with conn:
                    step(conn)
                    conn.execute("PRAGMA user_version = 13")

            person = conn.execute(
                "SELECT display_name, email FROM users WHERE id = 'dev-owner'"
            ).fetchone()
            assert person == ("משה", "owner@example.com")

            grant = conn.execute(
                "SELECT user_id, library_id, role FROM memberships"
            ).fetchall()
            assert grant == [("dev-owner", "dev-library", "admin")], (
                "the upgrade dropped an existing grant"
            )

            # ⚠ WRITE, not just read. Reading proves the ROWS survived; only a
            # write proves the CONSTRAINT under them did. This upsert is the
            # one `SqliteTenancyStore.save_membership` performs, and SQLite
            # refuses `ON CONFLICT` unless that pair is still a real PRIMARY
            # KEY — so a migration that carried every row across while
            # rebuilding the table without its composite key passes every
            # assertion above and breaks the first time somebody changes a
            # role. (Found by P3.7a's migration review, which mutated exactly
            # that and watched this test stay green.)
            with conn:
                conn.execute(
                    "INSERT INTO memberships (user_id, library_id, role,"
                    " joined_at) VALUES ('dev-owner','dev-library','viewer',NULL)"
                    " ON CONFLICT(user_id, library_id) DO UPDATE SET"
                    " role=excluded.role"
                )
            assert conn.execute(
                "SELECT COUNT(*) FROM memberships"
            ).fetchone()[0] == 1, "upsert appended"

            assert current_version(conn) == 13
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','index')"
            ).fetchall()}
            # The old spellings are GONE, not shadowed: an `accounts` table or
            # an `accounts_by_email` index surviving beside the new ones is the
            # residue that makes the next reader guess which is authoritative.
            assert "users" in names and "accounts" not in names
            assert "users_by_email" in names and "accounts_by_email" not in names
            # ⚠ And the SECONDARY index survived. `RENAME COLUMN` preserves it
            # for free, so this cannot fail today — it is here for v14, which
            # re-keys `memberships` to (user_id, account_id) and is therefore a
            # real table rebuild: the one operation that drops secondary
            # indexes silently while every row and every read still looks
            # right. Same shape as the PRIMARY KEY assertion below, one line
            # away (P3.7a's quality review mutated exactly this and watched
            # 418 tests pass).
            assert "memberships_of_library" in names
            # The foreign key followed the rename, or `PRAGMA foreign_keys`
            # would be enforcing nothing at all on this table.
            assert ("users", "user_id") in {
                (r[2], r[3])
                for r in conn.execute("PRAGMA foreign_key_list(memberships)")
            }
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            conn.close()


def test_a_migration_that_dies_halfway_leaves_the_database_openable():
    """The tenancy steps roll back whole: a crash costs an upgrade, not the
    file.

    The failure this exists to prevent is not data loss, it is a BRICK: kill
    the process between two of v13's statements without a transaction and the
    file is left half-renamed with `user_version` still 12 — every subsequent
    open re-enters the step and dies on `no such index: accounts_by_email`,
    naming an index while the real state is a half-renamed tenancy schema.
    The owner's 286 books would be behind a database no code path will open
    (measured, P3.7a's data-integrity review).

    Since P4.0a the RUNNER owns the transaction, so this drives the REAL
    `migrate()` through the dying connection rather than a hand-rolled
    simulation of its shape — an earlier version open-coded the runner's
    BEGIN/rollback and stayed green under three runner mutations that
    `tests/test_migrations.py` caught (its own ⚠ below, one level up: never
    re-state the thing you are trying to gate). All partial states must be
    invisible, and the retry must still work.
    """
    import sqlite3

    from app.adapters.migrations import MIGRATIONS, SCHEMA_VERSION, migrate

    class DiesAt:
        """The real connection, until the nth statement — then the crash.

        ⚠ The step under test is the REAL one, driven through this. An earlier
        version of this test re-listed v13's statements inline and interrupted
        the copy: deleting the ``BEGIN`` from the real ``_v13`` left it green,
        which made it a test of the test. Never re-state the thing you are
        trying to gate.
        """

        def __init__(self, conn, n):
            self._conn, self._n, self._seen = conn, n, 0
            self.tripped = False

        def execute(self, *args, **kwargs):
            self._seen += 1
            if self._seen > self._n:
                self.tripped = True
                raise RuntimeError("simulated crash")
            return self._conn.execute(*args, **kwargs)

        # The runner's own transaction management passes through uncounted:
        # the crash budget is statements, and commit/rollback are the
        # machinery under test, not the workload.
        def commit(self):
            return self._conn.commit()

        def rollback(self):
            return self._conn.rollback()

        @property
        def in_transaction(self):
            return self._conn.in_transaction

    def shape(conn):
        return (
            conn.execute("PRAGMA user_version").fetchone()[0],
            sorted(r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            )),
            [r[1] for r in conn.execute("PRAGMA table_info(memberships)")],
            [r[1] for r in conn.execute("PRAGMA table_info(libraries)")],
        )

    # EVERY tenancy step, at every statement boundary. Naming one step was
    # this test's first version and it was not enough: v14's guard could be
    # deleted with the whole ring green, and v14 is the longer and far more
    # destructive of the two (found by P3.7b's migration review). The counter
    # includes the runner's own preamble (version reads, the lock) — the
    # over-reach is deliberate, as below.
    fired: dict[int, int] = {}
    cases = [(12, n) for n in range(1, 8)]
    cases += [(13, n) for n in range(1, 25)]
    for upto, survive in cases:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "half.db"
            conn = sqlite3.connect(str(path))
            try:
                for version, one in MIGRATIONS:
                    if version > upto:
                        break
                    if isinstance(one, str):
                        conn.executescript(one)
                    else:
                        with conn:
                            one(conn)
                conn.execute(f"PRAGMA user_version = {upto}")
                people = "accounts" if upto == 12 else "users"
                person = "account_id" if upto == 12 else "user_id"
                conn.execute(
                    f"INSERT INTO {people} (id, display_name) VALUES"
                    " ('dev-owner', 'משה')"
                )
                conn.execute("INSERT INTO libraries (id, label) VALUES"
                             " ('lib', 'הבית')")
                conn.execute(
                    f"INSERT INTO memberships ({person}, library_id, role)"
                    " VALUES ('dev-owner', 'lib', 'admin')")
                conn.commit()
                before = shape(conn)

                # The REAL runner, through the dying connection, interrupted
                # partway. migrate() must roll the whole pending chain back.
                dying = DiesAt(conn, survive)
                try:
                    migrate(dying)
                except RuntimeError:
                    pass

                if not dying.tripped:
                    # `survive` ran past the end of the chain, so it simply
                    # finished — the correct outcome, and not evidence of
                    # anything. The counter deliberately over-reaches rather
                    # than hardcoding a statement count that would silently
                    # stop covering the step the day it grows a line.
                    fired[upto] = fired.get(upto, 0)
                    assert shape(conn)[0] == SCHEMA_VERSION
                    continue
                fired[upto] = fired.get(upto, 0) + 1
                assert shape(conn) == before, (
                    f"v{upto + 1} dying after {survive} statements left the "
                    f"file half-upgraded: {shape(conn)}"
                )
            finally:
                conn.close()

            # And the retry that a restart performs still works — all the way
            # to the current schema, where the grant is held per ACCOUNT.
            store = SqliteTenancyStore(path)
            owner = store.get_library("lib")
            assert owner is not None
            held = store.membership("dev-owner", owner.account_id)
            assert held is not None and held.role is Role.ADMIN

    # Every step must actually have been interrupted at least once, or the
    # loop above degenerates into "the migration works" and stops being a
    # crash test at all.
    assert fired.get(12, 0) >= 3 and fired.get(13, 0) >= 3, fired


def test_a_v13_database_groups_libraries_into_accounts_by_their_members():
    """v14 (P3.7b): who owns what, inferred from the only evidence there is.

    Nothing in a v13 file says which libraries belong to the same customer.
    The conservative rule is the one the owner approved: libraries whose
    member set is IDENTICAL — same users, same roles — collapse into one
    account; everything else gets its own.

    The failure this pins is a GRANT widening, and it is silent. Group
    `lib-a` {alice:admin} with `lib-b` {alice:admin, bob:editor} — which
    "same admin" or "same owner" would do — and bob reaches `lib-a`, a
    library he was never invited to, because a role is now account-wide.
    There is no undo for that and no error to notice.
    """
    import sqlite3

    from app.adapters.migrations import MIGRATIONS

    def seed(conn, libraries, memberships, joined=None):
        for version, step in MIGRATIONS:
            if version > 13:
                break
            if isinstance(step, str):
                conn.executescript(step)
            else:
                with conn:
                    step(conn)
        conn.execute("PRAGMA user_version = 13")
        for user in {u for u, _lib, _role in memberships}:
            conn.execute("INSERT INTO users (id, display_name) VALUES (?,?)",
                         (user, user.upper()))
        for lib in libraries:
            conn.execute("INSERT INTO libraries (id, label) VALUES (?,?)",
                         (lib, lib))
        for user, lib, role in memberships:
            conn.execute(
                "INSERT INTO memberships (user_id, library_id, role,"
                " joined_at) VALUES (?,?,?,?)",
                (user, lib, role, (joined or {}).get((user, lib))))
        conn.commit()

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v13.db"
        conn = sqlite3.connect(str(path))
        try:
            seed(
                conn,
                # lib-1 and lib-2 have IDENTICAL members -> one account.
                # lib-a and lib-b differ by one person -> two accounts.
                # lib-dead has nobody at all -> its own account, never pooled
                # with another orphan.
                ["lib-1", "lib-2", "lib-a", "lib-b", "lib-dead", "lib-gone",
                 "lib-r1", "lib-r2", "lib-two-admins",
                 # ⚠ A library id containing the character the account
                 # seed used to join on. {"a", "b"} group together, so
                 # a "|"-joined seed hashes "a|b" for that group — and
                 # the same string for the lone library literally named
                 # "a|b". Two accounts, one id: the PRIMARY KEY refuses
                 # the second INSERT, v14 rolls back, and the owner is
                 # left with a v13 file the product cannot upgrade.
                 "a", "b", "a|b"],
                [
                    ("alice", "lib-1", "admin"), ("bob", "lib-1", "editor"),
                    ("alice", "lib-2", "admin"), ("bob", "lib-2", "editor"),
                    ("alice", "lib-a", "admin"),
                    ("alice", "lib-b", "admin"), ("bob", "lib-b", "editor"),
                    # Same PEOPLE, different ROLES — the half of the rule that
                    # grouping by user ids alone gets wrong, silently promoting
                    # or demoting bob depending on which library sorts first.
                    ("alice", "lib-r1", "admin"), ("bob", "lib-r1", "viewer"),
                    ("alice", "lib-r2", "admin"), ("bob", "lib-r2", "editor"),
                    # Two admins: no single name to take, so no name.
                    ("alice", "lib-two-admins", "admin"),
                    ("bob", "lib-two-admins", "admin"),
                    ("alice", "a", "viewer"), ("alice", "b", "viewer"),
                    ("bob", "a|b", "viewer"),
                ],
                # alice joined lib-2 first; the collapsed membership must
                # carry THAT date, not lib-1's.
                {("alice", "lib-1"): "2024-06-01",
                 ("alice", "lib-2"): "2020-01-01"},
            )
        finally:
            conn.close()

        store = SqliteTenancyStore(path)        # migrates on construction

        owners = {lib: store.get_library(lib).account_id
                  for lib in ("lib-1", "lib-2", "lib-a", "lib-b",
                              "lib-dead", "lib-gone", "lib-r1", "lib-r2",
                              "lib-two-admins", "a", "b", "a|b")}

        assert owners["lib-1"] == owners["lib-2"], (
            "identical member sets are one customer"
        )
        assert owners["lib-a"] != owners["lib-b"], (
            "a member set that differs by one person is a DIFFERENT customer "
            "— merging them would hand bob a library he was never invited to"
        )
        assert owners["lib-dead"] != owners["lib-gone"], (
            "two libraries nobody belongs to share an EMPTY member set, which "
            "is no evidence at all — pooling them invents a customer"
        )

        assert owners["lib-r1"] != owners["lib-r2"], (
            "same users, DIFFERENT roles is a different customer — grouping "
            "by user ids alone would silently rewrite one of bob's roles"
        )
        assert store.membership("bob", owners["lib-r1"]).role is Role.VIEWER
        assert store.membership("bob", owners["lib-r2"]).role is Role.EDITOR

        # The grant that must not widen: bob can reach lib-b and lib-1/2, and
        # must not have been handed lib-a.
        reachable = {
            lib for lib, account in owners.items()
            if store.membership("bob", account) is not None
        }
        assert reachable == {"lib-1", "lib-2", "lib-b", "lib-r1", "lib-r2",
                             "lib-two-admins", "a|b"}
        assert store.membership("bob", owners["lib-a"]) is None

        # Roles survive, and the account keeps exactly one row per person.
        assert store.membership("alice", owners["lib-1"]).role is Role.ADMIN
        assert store.membership("bob", owners["lib-1"]).role is Role.EDITOR
        assert len(store.list_members(owners["lib-1"])) == 2
        assert store.list_members(owners["lib-dead"]) == ()

        # An account's name is its SOLE admin's, or blank — never invented
        # and never one of several. lib-b has two members but one admin;
        # a group with two admins has no name to choose between them, and
        # a migration that picked either would be writing a preference.
        assert store.get_account(owners["lib-1"]).label == "ALICE"
        assert store.get_account(owners["lib-dead"]).label == ""
        assert store.get_account(owners["lib-two-admins"]).label == ""

        # The seed collision above: three distinct accounts, three ids.
        assert owners["a"] == owners["b"] != owners["a|b"]

        # Earliest sighting wins: you have belonged to this customer since
        # the first library you were added to, not the last.
        assert store.membership("alice", owners["lib-1"]).joined_at == \
            "2020-01-01"

        conn = sqlite3.connect(str(path))
        try:
            assert current_version(conn) == SCHEMA_VERSION
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
            # ⚠ The rebuild below depends on `memberships` being the ONLY
            # table with a REFERENCES clause into `libraries`. Asserted, not
            # assumed: a future table that references it would have to be
            # dropped and recreated in v14's order too, and the symptom would
            # be a FK error on somebody's real file.
            # Enumerated, not listed: a literal tuple cannot contain the
            # future table this exists to catch, which is the whole difference
            # between asserting and assuming.
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
                " AND name NOT LIKE 'sqlite_%'")]
            for table in (t for t in tables
                          if t not in ("memberships", "libraries")):
                refs = {r[2] for r in conn.execute(
                    f"PRAGMA foreign_key_list({table})")}
                assert "libraries" not in refs, (
                    f"{table} references libraries; v14's rebuild order is "
                    "no longer safe"
                )
        finally:
            conn.close()


def test_an_unbound_memory_shelf_store_refuses_rather_than_answering_weakly():
    """⚠ The memory store's two bindings, and what an UNBOUND one must do.

    SQLite gets the first free — one file, one foreign key, so "is that section
    real" is a join — and gets the second free NOT AT ALL, because
    `copies.shelf_id` has no foreign key. Either way the memory store has to be
    told, and `memory_store.py`'s own comment says what happens if it treats
    being untold as permission: *"a guard whose default is 'skip me' is the
    same shape as the `occupied_ids` default a review already measured"*.

    Both guards fail closed, and until this test neither said so out loud: a
    mutation removing the second one left every ring green, and asking "what
    else enforces this?" turned up nothing for the first one either. So this
    gates the pattern rather than one instance of it — the next binding added
    to this store belongs in the list below.
    """
    bare = MemoryShelfStore()
    addressed = _sh(1)
    addressed = replace(addressed, address=ShelfAddress("sec", 1, 1))
    _raises(RuntimeError, bare.save_shelf, LIB, addressed)

    # Bound to a map, it can answer the address question — and still refuses
    # the delete, because nobody has told it where the books are.
    maps = MemoryMapStore()
    maps.bind_shelves(bare)
    bare.bind_map(maps)
    bare.save_shelf(LIB, _sh(2))
    _raises(RuntimeError, bare.delete_shelf, LIB, "sh2")

    # Told both, it answers both.
    bare.bind_books(MemoryBookStore())
    assert bare.delete_shelf(LIB, "sh2") is True


def test_deleting_a_shelf_never_touches_the_books_that_stood_on_it():
    """Two aggregates, one file — so the cascade has to be checked, not
    assumed. §5.6's direction is that a book is never removed automatically;
    if `shelves` cascaded into `copies`, deleting a mistyped shelf would delete
    every book on it, and the destructive direction is exactly the one the
    whole reconciliation design refuses to take.

    ⚠⚠ **This test used to assert the opposite of its second half**, and said
    so on purpose: the shelf was deleted, the copy went on naming it, and the
    comment read *"clearing it is `remove_from_shelf`, a domain operation, and
    P2.2 owns the sequence in the API where both stores are in hand. Asserted
    so the gap is a recorded decision rather than a surprise."*

    The decision was recorded. The sequence was not written. No caller
    anywhere cleared the copies first, `copies.shelf_id` has no foreign key to
    catch it, and the result was measured on a real migrated database: a shelf
    holding a book and no photograph deleted cleanly, `PRAGMA
    foreign_key_check` clean, the book left with a location nothing can open.

    So the assertion flips and the test keeps its name: nothing here touches
    the books — because nothing here deletes the shelf while they stand on it.
    A recorded decision that depends on a caller doing something is worth
    exactly as much as that caller.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "books.db"
        books, shelves = SqliteBookStore(path), SqliteShelfStore(path)
        shelves.save_shelf(LIB, _sh(1))
        books.save(LIB, _book(1, shelf_id="sh1"))

        _raises(ShelfNotEmpty, shelves.delete_shelf, LIB, "sh1")
        kept = books.get(LIB, "b1")
        assert kept is not None, "the refusal touched the books"
        assert kept.copies[0].shelf_id == "sh1"
        assert shelves.get_shelf(LIB, "sh1") is not None

        # Cleared through the domain operation the port names, the shelf goes
        # — and the book is still there, unlocated, which is the no-cascade
        # rule this test is named for.
        books.save(LIB, _book(1))
        assert shelves.delete_shelf(LIB, "sh1") is True
        after = books.get(LIB, "b1")
        assert after is not None, "deleting a shelf deleted its books"
        assert after.copies[0].shelf_id is None


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


# --- the AuthStore contract (P4.1a) ---------------------------------------
#
# One spec x both implementations, in a loop -- the generated matrix above
# is per-library and this store is user-scoped, so the loop is the honest
# equivalent. The sqlite side runs on a private copy of the migrated
# template like every other sqlite case here.

@contextmanager
def _auth_stores():
    """Both implementations, each fresh."""
    from app.adapters.memory_store import MemoryAuthStore
    from app.adapters.sqlite_store import SqliteAuthStore, SqliteTenancyStore

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "auth.db"
        sqlite_store = SqliteAuthStore(path)
        # sessions.user_id has a foreign key; give both stores their users.
        tenancy = SqliteTenancyStore(path)
        tenancy.save_user(User(id="u1"))
        tenancy.save_user(User(id="u9"))
        memory = MemoryAuthStore()
        yield (memory, sqlite_store)


def test_a_session_round_trips_and_a_tombstone_keeps_its_first_timestamp():
    from app.domain.auth import new_session

    with _auth_stores() as stores:
        for store in stores:
            s = new_session("tok", "u1", "2026-08-13T12:00:00+00:00")
            store.save_session(s)
            assert store.get_session(s.token_hash) == s
            assert store.get_session("no-such-hash") is None

            assert store.revoke_session(s.token_hash, at="2026-08-13T13:00:00+00:00")
            assert not store.revoke_session(s.token_hash, at="2026-08-13T14:00:00+00:00"), (
                "a second revoke reported doing something")
            got = store.get_session(s.token_hash)
            assert got.revoked_at == "2026-08-13T13:00:00+00:00", (
                "the tombstone moved -- when trust ended is a fact")
            assert not store.revoke_session("no-such-hash", at="2026-08-13T13:00:00+00:00")


def test_a_login_token_is_consumed_exactly_once_even_when_raced():
    """The single-use gate, sequentially and raced. N threads redeeming one
    link get one token between them -- the sqlite adapter's guarded UPDATE
    and the memory adapter's lock both must hold.

    ⚠ Four threads and a near-zero switch interval, not two and the
    default: P4.1a's migration review measured the 2-thread version passing
    0/4000 against a memory adapter with NO lock at all (the race arm was a
    no-op), and 2299/4000 failing under this configuration."""
    import sys
    import threading

    from app.domain.auth import new_login_token

    with _auth_stores() as stores:
        for store in stores:
            t = new_login_token("tok-seq", "a@b.com", "2026-08-13T12:00:00+00:00")
            store.save_login_token(t)
            first = store.consume_login_token(t.token_hash, now="2026-08-13T12:05:00+00:00")
            assert first is not None and first.consumed_at == "2026-08-13T12:05:00+00:00"
            assert store.consume_login_token(t.token_hash, now="2026-08-13T12:06:00+00:00") is None

            old_interval = sys.getswitchinterval()
            sys.setswitchinterval(1e-9)
            try:
                # 15 rounds, not 50: the P4.1a quality review measured an
                # unlocked adapter caught 20/20 within 5 rounds (median 0,
                # worst 4); 15 keeps a 3x margin and returns ~3s to the
                # ring's longest module.
                for round_ in range(15):
                    raced = new_login_token(f"tok-race-{round_}", "a@b.com",
                                            "2026-08-13T12:00:00+00:00")
                    store.save_login_token(raced)
                    barrier = threading.Barrier(4, timeout=30)
                    wins: list = []

                    def worker():
                        barrier.wait()
                        got = store.consume_login_token(
                            raced.token_hash, now="2026-08-13T12:05:00+00:00")
                        if got is not None:
                            wins.append(got)

                    threads = [threading.Thread(target=worker)
                               for _ in range(4)]
                    for th in threads:
                        th.start()
                    for th in threads:
                        th.join()
                    assert len(wins) == 1, (
                        f"{type(store).__name__}: {len(wins)} redeems of one "
                        f"link (round {round_})")
            finally:
                sys.setswitchinterval(old_interval)


def test_an_expired_login_token_cannot_be_consumed_and_nothing_changes():
    from app.domain.auth import new_login_token

    with _auth_stores() as stores:
        for store in stores:
            t = new_login_token("tok", "a@b.com", "2026-08-13T12:00:00+00:00")
            store.save_login_token(t)
            # At the boundary and after: dead. Expiry is exclusive.
            assert store.consume_login_token(t.token_hash, now=t.expires_at) is None
            assert store.consume_login_token(
                t.token_hash, now="2026-08-13T13:00:00+00:00") is None
            # The failed consume left it unconsumed (nothing changed) --
            # visible through a consume back inside the window.
            assert store.consume_login_token(
                t.token_hash, now="2026-08-13T12:10:00+00:00") is not None


def test_the_rate_window_counts_by_address_and_by_source_separately():
    from app.domain.auth import new_login_token

    with _auth_stores() as stores:
        for store in stores:
            mk = new_login_token
            store.save_login_token(mk("t1", "a@b.com", "2026-08-13T12:00:00+00:00",
                                      source_hash="s1"))
            store.save_login_token(mk("t2", "a@b.com", "2026-08-13T12:30:00+00:00",
                                      source_hash="s2"))
            store.save_login_token(mk("t3", "c@d.com", "2026-08-13T12:45:00+00:00",
                                      source_hash="s1"))
            # An OLD one, outside any window asked below.
            store.save_login_token(mk("t4", "a@b.com", "2026-08-13T09:00:00+00:00",
                                      source_hash="s1"))

            since = "2026-08-13T11:50:00+00:00"
            assert store.count_recent_login_tokens(email="a@b.com", since=since) == 2
            assert store.count_recent_login_tokens(email="c@d.com", since=since) == 1
            assert store.count_recent_login_tokens(email="x@y.com", since=since) == 0
            assert store.count_recent_login_tokens(source_hash="s1", since=since) == 2
            assert store.count_recent_login_tokens(source_hash="s2", since=since) == 1


def test_the_tenancy_store_finds_a_user_by_exact_email():
    """`user_by_email` is the redeem route's lookup (P4.1a). EXACT match:
    normalization happens once, in the domain, and a store that folded case
    again would be a second copy of that rule."""
    from app.adapters.memory_store import MemoryTenancyStore
    from app.adapters.sqlite_store import SqliteTenancyStore

    with tempfile.TemporaryDirectory() as tmp:
        for store in (MemoryTenancyStore(),
                      SqliteTenancyStore(Path(tmp) / "t.db")):
            store.save_user(User(id="u1", email="moshe@example.com"))
            store.save_user(User(id="u2"))  # no email at all
            found = store.user_by_email("moshe@example.com")
            assert found is not None and found.id == "u1"
            assert store.user_by_email("MOSHE@example.com") is None, (
                "the store normalized -- that rule lives in the domain, once")
            assert store.user_by_email("") is None, (
                "an empty address matched a user with none")


def test_a_v14_database_gains_the_auth_tables_and_keeps_its_rows():
    """The v15 upgrade on an UPGRADED file, not only a fresh one -- the
    owner's file is an upgraded file, and this is the first step whose
    tables a fresh-only suite would never open there. Also pins the three
    index names: each exists for a stated query (the lost-phone revoke-all,
    the two rate windows), and an index is exactly the kind of line a
    refactor drops with every test green (adopted from P4.1a's migration
    review, which measured that)."""
    import sqlite3

    from app.adapters.migrations import MIGRATIONS, SCHEMA_VERSION, current_version
    from app.adapters.sqlite_store import SqliteAuthStore
    from app.domain.auth import new_login_token, new_session

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v14.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 14:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 14")
            conn.execute("INSERT INTO users (id, display_name, email) VALUES"
                         " ('dev-owner', 'משה', 'owner@example.com')")
            conn.execute("INSERT INTO accounts (id, label) VALUES ('acc', '')")
            conn.execute("INSERT INTO libraries (id, account_id, label) VALUES"
                         " ('lib', 'acc', 'הבית')")
            conn.execute("INSERT INTO memberships (user_id, account_id, role)"
                         " VALUES ('dev-owner', 'acc', 'admin')")
            conn.execute(
                "INSERT INTO books (id, library_id, title, author, norm_title,"
                " norm_author, book_key, notes, search_text, sort_author)"
                " VALUES ('b1','lib','ספר','','ספר','','k','','ספר','')")
            conn.commit()
        finally:
            conn.close()

        auth = SqliteAuthStore(path)          # migrates 14 -> 15 on open
        check = sqlite3.connect(str(path))
        try:
            assert current_version(check) == SCHEMA_VERSION
            assert check.execute("SELECT count(*) FROM books").fetchone()[0] == 1
            assert check.execute("PRAGMA foreign_key_check").fetchall() == []
            names = {r[0] for r in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'")}
            for required in ("sessions_by_user", "login_tokens_by_email",
                             "login_tokens_by_source"):
                assert required in names, f"v15's {required} index is gone"
        finally:
            check.close()

        # The FK points at `users` even though that table was `accounts`
        # until v13 renamed it -- and the store works on the UPGRADED file.
        s = new_session("tok", "dev-owner", "2026-08-13T12:00:00+00:00")
        auth.save_session(s)
        assert auth.get_session(s.token_hash) == s
        t = new_login_token("lt", "owner@example.com",
                            "2026-08-13T12:00:00+00:00")
        auth.save_login_token(t)
        assert auth.consume_login_token(
            t.token_hash, now="2026-08-13T12:01:00+00:00") is not None


def test_saving_over_a_revoked_session_keeps_the_tombstone():
    """"A tombstone, never a delete" is enforced in the STORE, not only
    promised by the callers: a fresh Session written over a revoked one --
    unreachable today, but one refactor away -- must not resurrect it
    (P4.1a's migration review found the upsert clearing it)."""
    from dataclasses import replace

    from app.domain.auth import new_session

    with _auth_stores() as stores:
        for store in stores:
            s = new_session("tok", "u1", "2026-08-13T12:00:00+00:00")
            store.save_session(s)
            store.revoke_session(s.token_hash, at="2026-08-13T13:00:00+00:00")
            store.save_session(replace(s, revoked_at=None))
            got = store.get_session(s.token_hash)
            assert got.revoked_at == "2026-08-13T13:00:00+00:00", (
                f"{type(store).__name__} resurrected a tombstoned session")


def test_an_email_belongs_to_one_user_in_both_adapters():
    """The identity anchor's uniqueness, enforced as a PORT rule
    (`EmailTaken`) rather than left to the sqlite index alone — the memory
    adapter minted silent duplicates, so the contract suite was testing
    the one adapter that cannot fail (P4.1a's data-integrity review)."""
    from app.adapters.memory_store import MemoryTenancyStore
    from app.adapters.sqlite_store import SqliteTenancyStore
    from app.ports.tenancy import EmailTaken

    with tempfile.TemporaryDirectory() as tmp:
        for store in (MemoryTenancyStore(),
                      SqliteTenancyStore(Path(tmp) / "t.db")):
            store.save_user(User(id="u1", email="a@b.com"))
            try:
                store.save_user(User(id="u2", email="a@b.com"))
            except EmailTaken:
                pass
            else:
                raise AssertionError(
                    f"{type(store).__name__} gave two users one address")
            # Re-saving the HOLDER is not a conflict; two NULLs are fine.
            store.save_user(User(id="u1", email="a@b.com", display_name="x"))
            store.save_user(User(id="u3"))
            store.save_user(User(id="u4"))


def test_revoking_every_session_of_a_user_is_one_call():
    """The lost-phone answer (P4.1a's data-integrity review): the 90-day
    lifetime is paid for by revocation, and revocation must reach the
    sessions whose cookies you do NOT hold. Another user's sessions are
    untouched, and the call is idempotent (0 the second time)."""
    from app.domain.auth import new_session

    with _auth_stores() as stores:
        for store in stores:
            for i, user in enumerate(("u1", "u1", "u1", "u9")):
                store.save_session(new_session(f"t{i}", user,
                                               "2026-08-13T12:00:00+00:00"))
            n = store.revoke_sessions_of_user("u1", at="2026-08-13T13:00:00+00:00")
            assert n == 3, f"{type(store).__name__}: revoked {n}"
            assert store.revoke_sessions_of_user(
                "u1", at="2026-08-13T14:00:00+00:00") == 0
            from app.domain.auth import hash_token
            assert store.get_session(hash_token("t3")).revoked_at is None, (
                "another user's session was revoked")
            assert store.get_session(hash_token("t0")).revoked_at == \
                "2026-08-13T13:00:00+00:00"


def test_expired_login_tokens_can_be_purged_and_live_ones_survive():
    """Retention (P4.1a's data-integrity review): a token row outliving
    its expiry serves no redeem and no rate window — what it keeps is an
    ADDRESS in cleartext. The purge floor sits at the rate window's start,
    so the counters never lose a row they still read."""
    from app.domain.auth import new_login_token

    with _auth_stores() as stores:
        for store in stores:
            store.save_login_token(new_login_token(
                "old", "a@b.com", "2026-08-13T09:00:00+00:00"))
            store.save_login_token(new_login_token(
                "new", "a@b.com", "2026-08-13T12:00:00+00:00"))
            gone = store.purge_login_tokens(before="2026-08-13T11:00:00+00:00")
            assert gone == 1, f"{type(store).__name__}: purged {gone}"
            assert store.count_recent_login_tokens(
                email="a@b.com", since="2026-08-13T08:00:00+00:00") == 1
            assert store.consume_login_token(
                "no-such", now="2026-08-13T12:01:00+00:00") is None
            from app.domain.auth import hash_token
            assert store.consume_login_token(
                hash_token("new"), now="2026-08-13T12:01:00+00:00") is not None


def test_the_rate_window_counts_the_address_source_pair():
    """The narrow rate door counts the (address × source) PAIR — an
    address-wide count let a stranger burn the owner's budget from
    elsewhere and lock them out (P4.1a's security review, measured)."""
    from app.domain.auth import new_login_token

    with _auth_stores() as stores:
        for store in stores:
            mk = new_login_token
            store.save_login_token(mk("p1", "a@b.com",
                                      "2026-08-13T12:00:00+00:00",
                                      source_hash="attacker"))
            store.save_login_token(mk("p2", "a@b.com",
                                      "2026-08-13T12:10:00+00:00",
                                      source_hash="attacker"))
            store.save_login_token(mk("p3", "a@b.com",
                                      "2026-08-13T12:20:00+00:00",
                                      source_hash="owner"))
            since = "2026-08-13T11:50:00+00:00"
            assert store.count_recent_login_tokens(
                email="a@b.com", source_hash="attacker", since=since) == 2
            assert store.count_recent_login_tokens(
                email="a@b.com", source_hash="owner", since=since) == 1
            assert store.count_recent_login_tokens(
                email="a@b.com", since=since) == 3
            try:
                store.count_recent_login_tokens(since=since)
            except ValueError:
                pass
            else:
                raise AssertionError("no filter at all was accepted")


def test_a_spent_login_token_cannot_be_rearmed_by_a_rewrite():
    """`save_login_token` is INSERT, in both adapters: silently replacing
    an existing hash resets consumed_at and re-arms a spent link
    (measured divergence, P4.1a's data-integrity review)."""
    from app.domain.auth import hash_token, new_login_token

    with _auth_stores() as stores:
        for store in stores:
            t = new_login_token("dup", "a@b.com", "2026-08-13T12:00:00+00:00")
            store.save_login_token(t)
            assert store.consume_login_token(
                t.token_hash, now="2026-08-13T12:01:00+00:00") is not None
            try:
                store.save_login_token(new_login_token(
                    "dup", "a@b.com", "2026-08-13T12:02:00+00:00"))
            except ValueError:
                pass
            else:
                raise AssertionError(
                    f"{type(store).__name__} re-armed a spent link")
            assert store.consume_login_token(
                hash_token("dup"), now="2026-08-13T12:03:00+00:00") is None


def test_a_session_rewrite_cannot_change_whose_it_is():
    """`save_session` updates expiry (the rolling refresh) and may only
    ADD a revocation; identity fields are the ORIGINAL row's. The sqlite
    upsert always behaved so; the memory adapter replaced wholesale, and
    one cookie answering two user_ids between adapters is the divergence
    the contract exists to catch (P4.1a's data-integrity review)."""
    from dataclasses import replace

    from app.domain.auth import new_session

    with _auth_stores() as stores:
        for store in stores:
            s = new_session("tok", "u1", "2026-08-13T12:00:00+00:00")
            store.save_session(s)
            stolen = replace(new_session("tok", "u9",
                                         "2026-09-01T12:00:00+00:00"))
            store.save_session(stolen)
            got = store.get_session(s.token_hash)
            assert got.user_id == "u1", (
                f"{type(store).__name__}: a rewrite changed the session's user")
            assert got.created_at == "2026-08-13T12:00:00+00:00"
            assert got.expires_at == stolen.expires_at, (
                "the refresh write stopped moving the expiry")


# --- the InviteStore contract (P4.3) --------------------------------------

@contextmanager
def _invite_stores():
    from app.adapters.memory_store import MemoryInviteStore
    from app.adapters.sqlite_store import SqliteInviteStore, SqliteTenancyStore
    from app.domain import Account, User

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "invites.db"
        store = SqliteInviteStore(path)
        tenancy = SqliteTenancyStore(path)
        tenancy.save_user(User(id="u-admin"))
        for account_id in ("acc-a", "acc-b"):
            tenancy.save_account(Account(id=account_id))
        yield (MemoryInviteStore(), store)


def test_an_invite_round_trips_is_consumed_once_and_lists_while_open():
    import threading

    from app.domain import Role
    from app.domain.invites import new_invite

    with _invite_stores() as stores:
        for store in stores:
            i = new_invite("tok", "acc-a", Role.EDITOR, "u-admin",
                           "2026-08-13T12:00:00+00:00")
            store.save_invite(i)
            assert store.get_invite(i.token_hash) == i
            assert [x.token_hash for x in store.list_open_invites(
                "acc-a", now="2026-08-13T13:00:00+00:00")] == [i.token_hash]
            assert store.list_open_invites(
                "acc-b", now="2026-08-13T13:00:00+00:00") == ()
            # Expiry (7 days) is exclusive, like every other credential.
            assert store.list_open_invites("acc-a", now=i.expires_at) == ()
            try:
                store.save_invite(new_invite("tok", "acc-a", Role.VIEWER,
                                             "u-admin",
                                             "2026-08-13T12:01:00+00:00"))
            except ValueError:
                pass
            else:
                raise AssertionError("a duplicate hash was re-armed")

            # Raced accepts: one winner, same shape as the login token.
            barrier = threading.Barrier(4, timeout=30)
            wins: list = []

            def worker():
                barrier.wait()
                got = store.consume_invite(i.token_hash, by="u-x",
                                           now="2026-08-13T14:00:00+00:00")
                if got is not None:
                    wins.append(got)

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            assert len(wins) == 1, f"{type(store).__name__}: {len(wins)}"
            assert wins[0].consumed_by == "u-x"
            assert store.list_open_invites(
                "acc-a", now="2026-08-13T14:30:00+00:00") == ()
            assert store.consume_invite(
                i.token_hash, by="u-y",
                now="2026-08-13T15:00:00+00:00") is None


def test_revoking_an_invite_is_scoped_to_its_account():
    from app.domain import Role
    from app.domain.invites import new_invite

    with _invite_stores() as stores:
        for store in stores:
            i = new_invite("tok", "acc-a", Role.VIEWER, "u-admin",
                           "2026-08-13T12:00:00+00:00")
            store.save_invite(i)
            assert not store.revoke_invite("acc-b", i.token_hash), (
                "another account revoked a foreign invite")
            assert store.revoke_invite("acc-a", i.token_hash)
            assert not store.revoke_invite("acc-a", i.token_hash)
            assert store.get_invite(i.token_hash) is None
            # A CONSUMED invite is history, not a door — revoke refuses.
            spent = new_invite("tok2", "acc-a", Role.VIEWER, "u-admin",
                               "2026-08-13T12:00:00+00:00")
            store.save_invite(spent)
            store.consume_invite(spent.token_hash, by="u-x",
                                 now="2026-08-13T12:30:00+00:00")
            assert not store.revoke_invite("acc-a", spent.token_hash)
            assert store.get_invite(spent.token_hash) is not None


def test_a_v15_database_gains_the_invites_table_and_keeps_its_rows():
    """v16 on an UPGRADED file, not only a fresh one — the owner's file is
    an upgraded file, and a fresh-only suite is blind to the repo's own
    forbidden edit: fold v16's DDL into _V15 and every clone stays green
    while the ONE database that matters never gains the table (measured,
    P4.3's migration review). Pins the index the admin screen queries
    through and the two FKs across v13's accounts->users rename."""
    import sqlite3

    from app.adapters.migrations import MIGRATIONS, SCHEMA_VERSION, current_version
    from app.adapters.sqlite_store import SqliteInviteStore
    from app.domain import Role
    from app.domain.invites import new_invite

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v15.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 15:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 15")
            conn.execute("INSERT INTO users (id, display_name, email) VALUES"
                         " ('dev-owner', 'משה', 'owner@example.com')")
            conn.execute("INSERT INTO accounts (id, label) VALUES ('acc', '')")
            conn.execute("INSERT INTO libraries (id, account_id, label) VALUES"
                         " ('lib', 'acc', 'הבית')")
            conn.execute("INSERT INTO memberships (user_id, account_id, role)"
                         " VALUES ('dev-owner', 'acc', 'admin')")
            conn.execute(
                "INSERT INTO books (id, library_id, title, author, norm_title,"
                " norm_author, book_key, notes, search_text, sort_author)"
                " VALUES ('b1','lib','ספר','','ספר','','k','','ספר','')")
            conn.commit()
        finally:
            conn.close()

        store = SqliteInviteStore(path)          # migrates 15 -> 16 on open
        check = sqlite3.connect(str(path))
        try:
            assert current_version(check) == SCHEMA_VERSION
            assert check.execute("SELECT count(*) FROM books").fetchone()[0] == 1
            assert check.execute("PRAGMA foreign_key_check").fetchall() == []
            names = {r[0] for r in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'")}
            assert "invites_by_account" in names, "v16's index is gone"
        finally:
            check.close()

        # The store works on the UPGRADED file, with the rows that were
        # already there...
        i = new_invite("tok", "acc", Role.EDITOR, "dev-owner",
                       "2026-08-13T12:00:00+00:00")
        store.save_invite(i)
        assert store.get_invite(i.token_hash) == i
        assert store.consume_invite(i.token_hash, by="dev-owner",
                                    now="2026-08-13T13:00:00+00:00") is not None

        # ...and the FOREIGN KEYS are live on it: an invite naming an
        # account or a creator that does not exist is refused, which is
        # what proves they survived v13's rename of `accounts` to `users`.
        for bad in (new_invite("t2", "ghost-account", Role.VIEWER,
                               "dev-owner", "2026-08-13T12:00:00+00:00"),
                    new_invite("t3", "acc", Role.VIEWER, "ghost-user",
                               "2026-08-13T12:00:00+00:00")):
            try:
                store.save_invite(bad)
            except ValueError as exc:
                assert "unknown account or user" in str(exc), str(exc)
            else:
                raise AssertionError(
                    "an invite naming a nonexistent row was stored")


def test_the_last_admin_rule_holds_when_two_admins_act_at_once():
    """The rule is about the LIST, so a list read outside the write is a
    list that can be stale: two admins demoting each other at the same
    moment each saw an admin beside them, and the account reached ZERO
    admins — and the removal version reached zero MEMBERS, which makes
    every library that account owns permanently unreachable (measured,
    P4.3's data-integrity review). Both adapters, both interleavings."""
    import sys
    import threading

    from app.adapters.memory_store import MemoryTenancyStore
    from app.adapters.sqlite_store import SqliteTenancyStore
    from app.domain import Account, Membership, Role, User

    with tempfile.TemporaryDirectory() as tmp:
        for i, store in enumerate((MemoryTenancyStore(),
                                   SqliteTenancyStore(Path(tmp) / "t.db"))):
            for act in ("demote", "remove"):
                account = f"acc-{i}-{act}"
                store.save_account(Account(id=account))
                for who in ("u-a", "u-b"):
                    store.save_user(User(id=who))
                    store.save_membership(
                        Membership(who, account, Role.ADMIN))

                # ⚠ DETERMINISTIC, not raced: the first version released
                # two threads at a barrier and the mutation that deletes
                # `BEGIN IMMEDIATE` survived it — the window is too narrow
                # to hit by chance. Instead the FIRST caller is held
                # inside the read-write window (the domain rule is called
                # between the read and the writes), which is exactly where
                # the second caller's read must not be allowed to see a
                # stale list.
                import app.adapters.memory_store as mem
                import app.adapters.sqlite_store as sq

                module = mem if isinstance(store, MemoryTenancyStore) else sq
                real_rule = module.set_role if act == "demote" \
                    else module.remove_member
                inside = threading.Event()
                started = threading.Event()
                first = {"done": False}

                def slow_rule(*args, **kwargs):
                    if not first["done"]:
                        first["done"] = True
                        inside.set()
                        # Only until the second caller has ENTERED its
                        # own call — waiting for it to FINISH deadlocks
                        # (it is blocked behind this very lock), which
                        # cost the ring 34s before this line said so.
                        started.wait(timeout=5)
                    return real_rule(*args, **kwargs)

                errors: list = []

                def worker(target: str, second: bool) -> None:
                    if second:
                        inside.wait(timeout=5)
                        started.set()
                    try:
                        if act == "demote":
                            store.change_member_role(account, target,
                                                     Role.VIEWER)
                        else:
                            store.remove_member_row(account, target)
                    except Exception as exc:   # NoAdminLeft is the WIN
                        errors.append(exc)

                name = "set_role" if act == "demote" else "remove_member"
                setattr(module, name, slow_rule)
                try:
                    threads = [
                        threading.Thread(target=worker, args=("u-a", False)),
                        threading.Thread(target=worker, args=("u-b", True)),
                    ]
                    for th in threads:
                        th.start()
                    for th in threads:
                        th.join(timeout=30)
                finally:
                    setattr(module, name, real_rule)

                left = store.list_members(account)
                assert any(m.role is Role.ADMIN for m in left), (
                    f"{type(store).__name__}/{act}: the account reached "
                    f"zero admins ({left})"
                )


def test_an_invite_goes_inert_once_its_membership_has_landed():
    """`consumed_at` says the link was spent; `granted_at` says the
    membership EXISTS. Only the second makes a removal final — without it
    a spent invite was a permanent re-entry ticket its own consumer could
    replay (both P4.3 reviews, independently)."""
    from app.domain import Role
    from app.domain.invites import new_invite

    with _invite_stores() as stores:
        for store in stores:
            i = new_invite("tok", "acc-a", Role.EDITOR, "u-admin",
                           "2026-08-13T12:00:00+00:00")
            store.save_invite(i)
            spent = store.consume_invite(i.token_hash, by="u-x",
                                         now="2026-08-13T12:05:00+00:00")
            assert spent is not None and spent.granted_at is None
            # The crash window: consumed, not granted — its own consumer
            # may finish, nobody else, and not past the expiry.
            assert spent.may_finish("u-x", "2026-08-13T12:06:00+00:00")
            assert not spent.may_finish("u-other", "2026-08-13T12:06:00+00:00")
            assert not spent.may_finish("u-x", "2026-08-21T12:00:00+00:00")

            assert store.mark_granted(i.token_hash, at="2026-08-13T12:06:00+00:00")
            assert not store.mark_granted(i.token_hash,
                                          at="2026-08-13T13:00:00+00:00"), (
                "the first stamp must win, like a session's tombstone")
            after = store.get_invite(i.token_hash)
            assert after.granted_at == "2026-08-13T12:06:00+00:00"
            assert not after.may_finish("u-x", "2026-08-13T12:07:00+00:00"), (
                f"{type(store).__name__}: a granted invite is still a door")


def test_expired_invites_can_be_purged():
    from app.domain import Role
    from app.domain.invites import new_invite

    with _invite_stores() as stores:
        for store in stores:
            store.save_invite(new_invite("old", "acc-a", Role.VIEWER,
                                         "u-admin",
                                         "2026-08-01T12:00:00+00:00"))
            store.save_invite(new_invite("new", "acc-a", Role.VIEWER,
                                         "u-admin",
                                         "2026-08-13T12:00:00+00:00"))
            gone = store.purge_invites(before="2026-08-13T00:00:00+00:00")
            assert gone == 1, f"{type(store).__name__}: purged {gone}"
            assert len(store.list_open_invites(
                "acc-a", now="2026-08-13T12:30:00+00:00")) == 1


def test_a_v16_database_gains_granted_at_and_the_backfill_closes_the_hole():
    """v17 on an UPGRADED file. Two mutations survived the whole ring
    without this (P4.4's migration review): folding `granted_at` into
    _V16 (the repo's own forbidden edit — green board, dead invites on
    the one database that matters), and deleting the backfill (leaving
    the permanent-re-entry CRITICAL alive on pre-v17 rows).

    The backfill is fail-CLOSED, and this pins each row shape: an OPEN
    invite stays NULL (reopening nothing — `may_finish` also needs the
    consumer to match), a consumed one becomes granted, and the migrated
    consumed row is inert to the very person who consumed it."""
    import sqlite3

    from app.adapters.migrations import MIGRATIONS, SCHEMA_VERSION, current_version
    from app.adapters.sqlite_store import SqliteInviteStore
    from app.domain.auth import hash_token

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v16.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 16:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 16")
            conn.execute("INSERT INTO users (id, display_name) VALUES"
                         " ('u-admin', ''), ('u-x', '')")
            conn.execute("INSERT INTO accounts (id, label) VALUES ('acc', '')")
            conn.execute(
                "INSERT INTO invites (token_hash, account_id, role,"
                " created_by, created_at, expires_at, consumed_at,"
                " consumed_by) VALUES"
                # open, and consumed — the two shapes that existed at v16
                " (?, 'acc', 'editor', 'u-admin', '2026-08-13T12:00:00+00:00',"
                "  '2026-08-20T12:00:00+00:00', NULL, NULL),"
                " (?, 'acc', 'admin', 'u-admin', '2026-08-13T12:00:00+00:00',"
                "  '2026-08-20T12:00:00+00:00', '2026-08-13T12:05:00+00:00',"
                "  'u-x')",
                (hash_token("open"), hash_token("spent")),
            )
            conn.commit()
        finally:
            conn.close()

        store = SqliteInviteStore(path)          # migrates 16 -> 17
        check = sqlite3.connect(str(path))
        try:
            assert current_version(check) == SCHEMA_VERSION
            assert "granted_at" in {
                r[1] for r in check.execute("PRAGMA table_info(invites)")}
            assert check.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            check.close()

        still_open = store.get_invite(hash_token("open"))
        assert still_open.granted_at is None, "an OPEN invite was marked granted"
        assert store.consume_invite(hash_token("open"), by="u-x",
                                    now="2026-08-14T12:00:00+00:00") is not None

        migrated = store.get_invite(hash_token("spent"))
        assert migrated.granted_at == "2026-08-13T12:05:00+00:00"
        assert not migrated.may_finish("u-x", "2026-08-14T12:00:00+00:00"), (
            "a pre-v17 consumed invite is still a re-entry ticket for its "
            "own consumer — the backfill did not close the hole"
        )


def test_an_oauth_state_is_consumed_once_and_swept_when_stale():
    """The CSRF guard's storage, both adapters. A replayed callback must
    find nothing — that is the entire property the state parameter has."""
    from app.adapters.memory_store import MemoryOAuthStateStore
    from app.adapters.sqlite_store import SqliteOAuthStateStore
    from app.domain.auth import hash_token
    from app.domain.oauth import new_state

    with tempfile.TemporaryDirectory() as tmp:
        for store in (MemoryOAuthStateStore(),
                      SqliteOAuthStateStore(Path(tmp) / "s.db")):
            state = new_state("tok", "google", "nonce-1", "verifier-1",
                              "2026-08-13T12:00:00+00:00",
                              next_hash="#/invite?token=x")
            store.save_state(state)
            try:
                store.save_state(state)
            except ValueError:
                pass
            else:
                raise AssertionError("a duplicate state was re-armed")

            got = store.consume_state(hash_token("tok"),
                                      now="2026-08-13T12:05:00+00:00")
            assert got is not None
            assert got.nonce == "nonce-1" and got.verifier == "verifier-1"
            assert got.next_hash == "#/invite?token=x"
            assert store.consume_state(
                hash_token("tok"), now="2026-08-13T12:06:00+00:00") is None, (
                f"{type(store).__name__}: a state was consumed twice")

            # Expiry is exclusive, like every other credential here.
            stale = new_state("old", "google", "n", "v",
                              "2026-08-13T12:00:00+00:00")
            store.save_state(stale)
            assert store.consume_state(hash_token("old"),
                                       now=stale.expires_at) is None
            assert store.purge_states(before="2026-08-14T00:00:00+00:00") >= 1
            assert store.consume_state(hash_token("old"),
                                       now="2026-08-13T12:05:00+00:00") is None


def test_a_v17_database_gains_the_oauth_states_table_and_keeps_its_rows():
    """v18 on an UPGRADED file — the third time this has been the finding
    (v16's and v17's reviews both measured that a fresh-only suite lets
    the repo's own forbidden edit through: fold the DDL into the previous
    step and every clone stays green while the ONE database that matters
    never gains the table). Pins the index too."""
    import sqlite3

    from app.adapters.migrations import MIGRATIONS, SCHEMA_VERSION, current_version
    from app.adapters.sqlite_store import SqliteOAuthStateStore
    from app.domain.auth import hash_token
    from app.domain.oauth import new_state

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v17.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 17:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 17")
            conn.execute("INSERT INTO users (id, display_name) VALUES"
                         " ('u1', 'משה')")
            conn.execute("INSERT INTO accounts (id, label) VALUES ('acc', '')")
            conn.execute("INSERT INTO libraries (id, account_id, label)"
                         " VALUES ('lib', 'acc', 'הבית')")
            conn.execute(
                "INSERT INTO books (id, library_id, title, author, norm_title,"
                " norm_author, book_key, notes, search_text, sort_author)"
                " VALUES ('b1','lib','ספר','','ספר','','k','','ספר','')")
            conn.commit()
        finally:
            conn.close()

        store = SqliteOAuthStateStore(path)      # migrates 17 -> 18
        check = sqlite3.connect(str(path))
        try:
            assert current_version(check) == SCHEMA_VERSION
            assert check.execute("SELECT count(*) FROM books").fetchone()[0] == 1
            assert check.execute("PRAGMA foreign_key_check").fetchall() == []
            names = {r[0] for r in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'")}
            assert "oauth_states_by_expiry" in names, "v18's index is gone"
        finally:
            check.close()

        # …and the store works on the UPGRADED file.
        store.save_state(new_state("tok", "google", "n", "v",
                                   "2026-08-13T12:00:00+00:00"))
        assert store.consume_state(hash_token("tok"),
                                   now="2026-08-13T12:05:00+00:00") is not None


def test_the_browser_binding_survives_a_round_trip_through_both_stores():
    """v19's column, and the rule that fails CLOSED: a state with no
    binding recorded (the shape every pre-v19 row has) belongs to
    nobody."""
    from app.adapters.memory_store import MemoryOAuthStateStore
    from app.adapters.sqlite_store import SqliteOAuthStateStore
    from app.domain.auth import hash_token
    from app.domain.oauth import new_state

    with tempfile.TemporaryDirectory() as tmp:
        for store in (MemoryOAuthStateStore(),
                      SqliteOAuthStateStore(Path(tmp) / "b.db")):
            store.save_state(new_state("tok", "google", "n", "v",
                                       "2026-08-13T12:00:00+00:00",
                                       binding="the-browsers-secret"))
            got = store.consume_state(hash_token("tok"),
                                      now="2026-08-13T12:05:00+00:00")
            assert got is not None
            assert got.belongs_to("the-browsers-secret")
            assert not got.belongs_to("some-other-browser")
            assert not got.belongs_to(""), "an empty binding matched"

            # Unbound (pre-v19, or a caller that forgot): nobody owns it.
            store.save_state(new_state("old", "google", "n", "v",
                                       "2026-08-13T12:00:00+00:00"))
            unbound = store.consume_state(hash_token("old"),
                                          now="2026-08-13T12:05:00+00:00")
            assert not unbound.belongs_to("anything at all")


def test_a_v19_database_gains_the_map_and_keeps_its_shelves_unaddressed():
    """v20 on an UPGRADED file — CLAUDE.md rule 11, whose whole point is that
    folding new DDL into the previous step keeps every clone green while the
    one database that matters never gains the tables.

    It asserts the thing this migration is actually FOR: a library that has
    been photographed for months arrives with real shelves, and after the
    upgrade those shelves are still there, still theirs, and simply have no
    address yet (MAP_PLAN §3.1 — one population, and P6.4 binds them). Index
    names are pinned too, including the partial one that makes a slot unique.
    """
    import sqlite3

    from app.adapters.migrations import MIGRATIONS, SCHEMA_VERSION, current_version
    from app.adapters.sqlite_store import SqliteMapStore, SqliteShelfStore

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v19.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 19:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 19")
            conn.execute("INSERT INTO users (id, display_name) VALUES"
                         " ('u1', 'משה')")
            conn.execute("INSERT INTO accounts (id, label) VALUES ('acc', '')")
            conn.execute("INSERT INTO libraries (id, account_id, label)"
                         " VALUES ('lib', 'acc', 'הבית')")
            conn.execute(
                "INSERT INTO shelves (id, library_id, label, depth_count,"
                " virtual, created_at) VALUES"
                " ('sh-old', 'lib', 'מדף הסלון', 2, 0, '2026-01-02T00:00:00Z')")
            conn.execute(
                "INSERT INTO captures (id, shelf_id, library_id, depth,"
                ' "order", image_id, captured_at) VALUES'
                " ('cap', 'sh-old', 'lib', 1, 0, 'img', '2026-01-02T00:00:00Z')")
            conn.execute(
                "INSERT INTO books (id, library_id, title, author, norm_title,"
                " norm_author, book_key, notes, search_text, sort_author)"
                " VALUES ('b1','lib','ספר','','ספר','','k','','ספר','')")
            conn.commit()
        finally:
            conn.close()

        # ⚠ BEFORE the store opens it: at v19 none of this exists. Without
        # these four lines the test follows `MIGRATIONS` wherever the DDL is
        # written, so folding v20's tables into `_V19` — the exact forbidden
        # edit rule 11 names — leaves it GREEN. Measured at review: the
        # mutation passed the whole suite while the one database that matters,
        # sitting at 19, never gained a table.
        before = sqlite3.connect(str(path))
        try:
            at19 = {r[0] for r in before.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            assert not at19 & {"sites", "floors", "places", "bookcases",
                               "sections"}, "v20's tables arrived before v20"
            assert "section_id" not in {
                r[1] for r in before.execute("PRAGMA table_info(shelves)")}
        finally:
            before.close()

        shelves = SqliteShelfStore(path)          # migrates 19 -> 20
        maps = SqliteMapStore(path)
        check = sqlite3.connect(str(path))
        try:
            assert current_version(check) == SCHEMA_VERSION
            assert check.execute(
                "SELECT count(*) FROM shelves").fetchone()[0] == 1
            assert check.execute(
                "SELECT count(*) FROM captures").fetchone()[0] == 1
            assert check.execute("PRAGMA foreign_key_check").fetchall() == []
            tables = {r[0] for r in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            for wanted in ("sites", "floors", "places", "bookcases", "sections"):
                assert wanted in tables, f"v20's {wanted} table is gone"
            names = {r[0] for r in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'")}
            for wanted in ("sites_by_library", "floors_by_site",
                           "places_by_floor", "bookcases_by_floor",
                           "bookcases_by_place", "sections_by_bookcase",
                           "shelves_by_slot"):
                assert wanted in names, f"v20's {wanted} index is gone"
        finally:
            check.close()

        # The shelf that predates the map kept everything, and stands nowhere.
        lib = LibraryRef("lib")
        carried = shelves.get_shelf(lib, "sh-old")
        assert carried is not None
        assert carried.label == "מדף הסלון" and carried.depth_count == 2
        assert carried.address is None and carried.is_addressed is False
        # Counted, not `is_empty` — that property answers a SCREEN's question
        # ("is there anything to show?") and ignores sites and floors, so it
        # would pass with stray rows a bad step left behind.
        empty = sqlite3.connect(str(path))
        try:
            for table in ("sites", "floors", "places", "bookcases", "sections"):
                assert empty.execute(
                    f"SELECT count(*) FROM {table}").fetchone()[0] == 0, (
                    f"the migration invented {table} rows")
        finally:
            empty.close()

        # …and the upgraded file takes a drawing, with a real shelf in a slot.
        maps.save_site(lib, new_site(id="st", library_id="lib", name="הבית"))
        maps.save_floor(lib, new_floor(id="fl", library_id="lib",
                                       site_id="st", name="קרקע"))
        maps.save_place(lib, new_place(id="pl", library_id="lib",
                                       floor_id="fl", rect=Rect(0, 0, 9, 7)))
        maps.save_bookcase(lib, new_bookcase(id="bc", library_id="lib",
                                             floor_id="fl",
                                             rect=Rect(1, 0, 4, 1),
                                             place_id="pl"))
        section = new_section(id="se", library_id="lib", bookcase_id="bc")
        maps.save_section(lib, section)
        shelves.save_shelf(lib, new_shelf(
            id="sh-drawn", library_id="lib",
            address=ShelfAddress("se", 1, 1)))
        assert shelves.get_shelf_at(lib, ShelfAddress("se", 1, 1)).id == "sh-drawn"
        assert maps.load_map(lib).sections[0].column_levels == (5, 5)

        # ⚠ AGAIN, and this is the one that counts. The check above ran while
        # every map table was empty and every shelf's section_id was NULL, so
        # it tested v1–v19's constraints and not one of v20's. Now there is a
        # site → floor → place → bookcase → section → addressed shelf chain to
        # check.
        after = sqlite3.connect(str(path))
        try:
            assert after.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            after.close()


def test_a_section_whose_mask_is_unreadable_names_itself_and_not_the_library():
    """Measured by a security review, against the first cut of the loader.

    `gaps` is JSON, and the loader turned it into cells inside a comprehension.
    Seven stored shapes — `[[1,1,1]]`, `[1,1]`, `"abc"`, `null`, unparseable
    text — raised `ValueError`/`TypeError`, which is **not** a `DomainError`,
    so the API's `_translated()` never saw it: `GET /map` answered 500 for the
    WHOLE library, every bookcase and every floor, with no screen left that
    could repair the row.

    Nothing reachable through `/api/v1` can write such a value (the writer
    dumps normalised pairs, and both geometry columns move in one UPSERT), so
    this is about a restore, a hand-edit or a tool. It still REFUSES — a mask
    silently dropped is a hole the owner drew disappearing, and the shelves
    are gone whether or not the cells can be read — but it refuses by name.

    ⚠ Sqlite-only, and not a `@map_contract` case: the memory store holds
    `Section` objects, so it has no way to be handed a malformed one.
    """
    import sqlite3

    from app.adapters.sqlite_store import SqliteMapStore
    from app.ports.store import UnreadableSection

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bad.db"
        maps = SqliteMapStore(path)
        seed = sqlite3.connect(str(path))
        try:
            seed.execute("INSERT INTO accounts (id, label) VALUES ('acc','')")
            seed.execute("INSERT INTO libraries (id, account_id, label)"
                         " VALUES ('lib','acc','הבית')")
            seed.commit()
        finally:
            seed.close()
        lib = LibraryRef("lib")
        maps.save_site(lib, new_site(id="st", library_id="lib", name="הבית"))
        maps.save_floor(lib, new_floor(id="fl", library_id="lib",
                                       site_id="st", name="קרקע"))
        maps.save_place(lib, new_place(id="pl", library_id="lib",
                                       floor_id="fl", rect=Rect(0, 0, 9, 7)))
        maps.save_bookcase(lib, new_bookcase(id="bc", library_id="lib",
                                             floor_id="fl",
                                             rect=Rect(0, 0, 4, 1),
                                             place_id="pl"))
        maps.save_section(lib, new_section(id="se", library_id="lib",
                                           bookcase_id="bc", columns=2,
                                           default_levels=3))

        # Every shape the review measured, plus the two that used to load
        # SILENTLY as a different cell than the one stored.
        for bad in ('[[1,1,1]]', '[1,1]', '"abc"', 'null', 'not json',
                    '{"a":1}', '[[1.9,1.9]]', '[["1","1"]]'):
            broken = sqlite3.connect(str(path))
            try:
                broken.execute("UPDATE sections SET gaps = ?", (bad,))
                broken.commit()
            finally:
                broken.close()
            try:
                maps.load_map(lib)
            except UnreadableSection as exc:
                assert "se" in str(exc), (
                    f"{bad} refused without naming the section, so the owner "
                    f"is told the map is broken and not which row"
                )
            else:
                raise AssertionError(
                    f"{bad} loaded as a section — a mask that is not a list "
                    f"of [column, level] pairs was read as one"
                )

        # …and a well-formed mask still loads, so the guard did not simply
        # refuse everything.
        good = sqlite3.connect(str(path))
        try:
            good.execute("UPDATE sections SET gaps = '[[2, 3]]'")
            good.commit()
        finally:
            good.close()
        assert maps.get_section(lib, "se").gaps == ((2, 3),)


def test_a_v20_database_gains_the_gaps_column_and_keeps_its_drawing():
    """v21 on an UPGRADED file — CLAUDE.md rule 11, and the frame is the
    v19→v20 case above, deliberately.

    What it is FOR: a library whose map was drawn before P6.3.2 arrives with
    sections, shelves and books in them, and after the upgrade every one of
    those is still standing, with no holes it did not ask for. Then it USES
    the column — the ⚠ on the v19→v20 case records that its `foreign_key_check`
    ran while every new table was empty, so this one writes a gap through the
    real store, reads it back, and checks the file afterwards.
    """
    import sqlite3

    from app.adapters.migrations import MIGRATIONS, SCHEMA_VERSION, current_version
    from app.adapters.sqlite_store import SqliteMapStore, SqliteShelfStore
    from app.domain import with_gaps

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v20.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 20:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 20")
            conn.execute("INSERT INTO users (id, display_name) VALUES"
                         " ('u1', 'משה')")
            conn.execute("INSERT INTO accounts (id, label) VALUES ('acc', '')")
            conn.execute("INSERT INTO libraries (id, account_id, label)"
                         " VALUES ('lib', 'acc', 'הבית')")
            conn.execute("INSERT INTO sites (id, library_id, name, \"order\")"
                         " VALUES ('st', 'lib', 'הבית', 0)")
            conn.execute("INSERT INTO floors (id, library_id, site_id, name,"
                         " \"order\") VALUES ('fl', 'lib', 'st', 'קרקע', 0)")
            conn.execute(
                "INSERT INTO places (id, library_id, floor_id, name, x, y, w,"
                " h, \"order\") VALUES ('pl','lib','fl','סלון',0,0,9,7,0)")
            conn.execute(
                "INSERT INTO bookcases (id, library_id, floor_id, place_id,"
                " name, front, x, y, w, h, \"order\") VALUES"
                " ('bc','lib','fl','pl','ספרייה','S',1,0,4,1,0)")
            conn.execute(
                "INSERT INTO sections (id, library_id, bookcase_id, ordinal,"
                " column_levels, default_levels, default_depth) VALUES"
                " ('se','lib','bc',1,'[3, 3]',3,1)")
            conn.execute(
                "INSERT INTO shelves (id, library_id, label, depth_count,"
                " virtual, created_at, section_id, col, level) VALUES"
                " ('sh-old','lib','',1,0,'2026-02-01T00:00:00Z','se',1,3)")
            conn.commit()
        finally:
            conn.close()

        # ⚠ BEFORE the store opens it: at v20 the column does not exist. Its
        # absence is what the four lines on the v19→v20 case exist to prove —
        # without them this test follows `MIGRATIONS` wherever the DDL is
        # written, so folding the ALTER into `_V20` (the edit rule 11 forbids)
        # stays green while the one database that matters never gains it.
        before = sqlite3.connect(str(path))
        try:
            assert "gaps" not in {
                r[1] for r in before.execute("PRAGMA table_info(sections)")
            }, "v21's column arrived before v21"
        finally:
            before.close()

        maps = SqliteMapStore(path)               # migrates 20 -> 21
        shelves = SqliteShelfStore(path)
        lib = LibraryRef("lib")

        check = sqlite3.connect(str(path))
        try:
            assert current_version(check) == SCHEMA_VERSION
            assert "gaps" in {
                r[1] for r in check.execute("PRAGMA table_info(sections)")}
            assert check.execute(
                "SELECT gaps FROM sections").fetchone()[0] == "[]", (
                "an existing section arrived with holes in it"
            )
            assert check.execute("PRAGMA foreign_key_check").fetchall() == []
            names = {r[0] for r in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'")}
            for wanted in ("sections_by_bookcase", "shelves_by_slot"):
                assert wanted in names, f"the {wanted} index is gone"
        finally:
            check.close()

        # The drawing that predates the column is intact, and the shelf still
        # stands in its slot with the level number it had.
        section = maps.get_section(lib, "se")
        assert section.column_levels == (3, 3) and section.gaps == ()
        assert shelves.get_shelf_at(lib, ShelfAddress("se", 1, 3)).id == "sh-old"

        # …and the column is USED, through the real store, on the real file.
        maps.save_section(lib, with_gaps(section, [(2, 2)], gap=True).section)
        assert maps.get_section(lib, "se").gaps == ((2, 2),)
        assert maps.load_map(lib).sections[0].gaps == ((2, 2),)
        assert shelves.get_shelf_at(lib, ShelfAddress("se", 1, 3)).id == "sh-old", (
            "gapping a cell moved the shelf below it"
        )

        after = sqlite3.connect(str(path))
        try:
            assert after.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            after.close()


# --- shelf aliases (P6.4a, §3.11) -----------------------------------------

def _absorb(*, alias_id="sh-old", into="sh-new", at=None, label="",
            lib=None):
    from app.domain.alias import ShelfAlias

    lib = lib or LIB
    return ShelfAlias(alias_id=alias_id, library_id=lib.id, shelf_id=into,
                      address=at, label=label,
                      merged_at="2026-08-25T10:00:00+00:00")


def _two_shelves(shelves, lib=None):
    lib = lib or LIB
    for i in ("sh-old", "sh-new"):
        shelves.save_shelf(lib, new_shelf(id=i, library_id=lib.id))


@shelf_contract
def an_alias_answers_for_the_shelf_that_absorbed_it(shelves):
    """§3.11's first half: `alias_id -> shelf_id`, one hop.

    ⚠ The absorbed shelf's own row is expected to be GONE by then — P6.4d's
    merge deletes it — but this item stores the alias without touching it, so
    the round trip is what is asserted here.
    """
    from app.domain.alias import resolve

    _two_shelves(shelves)
    shelves.save_alias(LIB, _absorb(label="ספרי בישול"))

    aliases = shelves.list_aliases(LIB)
    assert len(aliases) == 1
    assert resolve("sh-old", aliases) == "sh-new"
    assert resolve("sh-new", aliases) == "sh-new", (
        "a shelf nothing absorbed must answer itself")
    assert resolve("never-heard-of-it", aliases) == "never-heard-of-it"
    assert aliases[0].label == "ספרי בישול", (
        "the name a household calls a shelf did not survive the merge")


@shelf_contract
def an_alias_remembers_where_it_stood(shelves):
    """§3.11's second half, and the one worth defending: *"the shelf that was
    at section 1, column 2, level 3"* is what a person reads off a drawing,
    and the half that survives in their memory when the id does not."""
    from app.domain.alias import resolve_address

    _two_shelves(shelves)
    where = ShelfAddress("se-1", 2, 3)
    shelves.save_alias(LIB, _absorb(at=where))

    aliases = shelves.list_aliases(LIB)
    assert aliases[0].address == where
    assert resolve_address(where, aliases) == "sh-new"
    assert resolve_address(ShelfAddress("se-1", 9, 9), aliases) is None


@shelf_contract
def two_identities_may_not_claim_one_former_address(shelves):
    """**[DECIDED 2026-08-23 — owner]** The address→survivor lookup must have
    exactly one answer; the alternative is a query that silently picks the
    first of several."""
    _two_shelves(shelves)
    shelves.save_shelf(LIB, new_shelf(id="sh-third", library_id=LIB.id))
    where = ShelfAddress("se-1", 2, 3)
    shelves.save_alias(LIB, _absorb(at=where))
    # ⚠ Named, not `except Exception`. The loose version passed while the
    # SQLite store raised a raw `sqlite3.IntegrityError` and the memory store
    # raised `DuplicateShelfSlot` — a driver exception crossing a port
    # boundary, which is a 500 where the answer is a 409.
    try:
        shelves.save_alias(LIB, _absorb(alias_id="sh-third", at=where))
    except DuplicateShelfSlot:
        pass
    else:
        raise AssertionError("two aliases claimed the same former address")


@shelf_contract
def an_id_is_absorbed_once_and_never_twice(shelves):
    """`alias_id` is the PRIMARY KEY. Re-absorbing an id elsewhere would
    silently move every book that arrived with it."""
    _two_shelves(shelves)
    shelves.save_shelf(LIB, new_shelf(id="sh-third", library_id=LIB.id))
    shelves.save_alias(LIB, _absorb())
    try:
        shelves.save_alias(LIB, _absorb(into="sh-third"))
    except DuplicateShelfSlot:
        pass
    else:
        raise AssertionError("one id was absorbed twice")
    assert shelves.list_aliases(LIB)[0].shelf_id == "sh-new"


@shelf_contract
def an_alias_may_only_point_at_a_live_shelf(shelves):
    """What keeps an alias of an alias unrepresentable, and therefore keeps
    the resolver one hop with no cycle guard."""
    shelves.save_shelf(LIB, new_shelf(id="sh-old", library_id=LIB.id))
    try:
        shelves.save_alias(LIB, _absorb(into="ghost"))
    except UnknownShelf:
        pass
    else:
        raise AssertionError("an alias was stored pointing at no shelf")


@shelf_contract
def deleting_a_shelf_other_identities_resolve_to_is_refused(shelves):
    """**[DECIDED 2026-08-23 — owner]**, naming the count.

    Cascading would discard *"the shelf that was at section 1, column 2, level
    3"* — the one thing the alias exists to answer — and would take the P6.4c
    census's baseline with it.
    """
    _two_shelves(shelves)
    shelves.save_alias(LIB, _absorb())
    try:
        shelves.delete_shelf(LIB, "sh-new")
    except ShelfHasAliases as exc:
        assert "1" in str(exc), f"the refusal did not say how many: {exc}"
    else:
        raise AssertionError("deleting a survivor discarded its aliases")
    # …and the absorbed id is still deletable, because nothing resolves to it.
    assert shelves.delete_shelf(LIB, "sh-old") is True


@shelf_contract
def aliases_are_scoped_to_their_library(shelves):
    """H2, and the same 404-not-403 shape as every other aggregate."""
    _two_shelves(shelves)
    shelves.save_alias(LIB, _absorb())
    assert shelves.list_aliases(OTHER) == ()
    assert shelves.aliases_of(OTHER, "sh-new") == ()
    try:
        shelves.save_alias(OTHER, _absorb())
    except WrongLibrary:
        pass
    else:
        raise AssertionError("an alias was filed under a library it disowns")


@shelf_contract
def one_library_may_not_block_another_from_absorbing_its_shelf(shelves):
    """H2, and the reason the key is `(library_id, alias_id)` rather than
    `alias_id` alone.

    ⚠ Every guard in `save_alias` reads `WHERE library_id = ? AND …`, so a
    global key let a row in one library decide an outcome in another: a review
    stored an alias in L2 naming a shelf that lives in L1, and L1 could then
    never absorb that shelf — its own store reported no alias and the write
    died on a constraint L1 cannot see.
    """
    _two_shelves(shelves)
    for i in ("far-a", "far-b"):
        shelves.save_shelf(OTHER, new_shelf(id=i, library_id=OTHER.id))
    # The other library absorbs one of ITS shelves under an id that also
    # names one of ours. (Nothing forbids the collision; ids are opaque.)
    shelves.save_alias(OTHER, _absorb(alias_id="far-a",
                                      into="far-b", lib=OTHER))
    shelves.save_alias(OTHER, _absorb(alias_id="sh-old",
                                      into="far-b", lib=OTHER))

    # …and we can still absorb our own shelf of that name.
    shelves.save_alias(LIB, _absorb())
    assert [a.alias_id for a in shelves.list_aliases(LIB)] == ["sh-old"]
    assert {a.alias_id for a in shelves.list_aliases(OTHER)} == {
        "far-a", "sh-old"}


@shelf_contract
def aliases_of_answers_only_for_the_shelf_asked_about(shelves):
    """The narrow query, behind the delete refusal and the *formerly …* line."""
    _two_shelves(shelves)
    shelves.save_shelf(LIB, new_shelf(id="sh-b", library_id=LIB.id))
    shelves.save_shelf(LIB, new_shelf(id="sh-c", library_id=LIB.id))
    shelves.save_alias(LIB, _absorb(alias_id="sh-old", into="sh-new"))
    shelves.save_alias(LIB, _absorb(alias_id="sh-b", into="sh-c"))

    assert [a.alias_id for a in shelves.aliases_of(LIB, "sh-new")] == ["sh-old"]
    assert [a.alias_id for a in shelves.aliases_of(LIB, "sh-c")] == ["sh-b"]
    assert shelves.aliases_of(LIB, "sh-old") == ()


@shelf_contract
def a_survivor_that_has_itself_been_absorbed_is_refused(shelves):
    """ONE HOP, and it is enforced here rather than by the foreign key.

    ⚠ A migration review stored this chain through the public API: the FK
    proves the survivor is a LIVE shelf, which is a different claim from
    "is not itself an alias_id". A chain hides an identity — `identities(C)`
    would not list A — so every book that arrived on A becomes unreachable
    from the only shelf still standing, with `foreign_key_check` clean.
    """
    # ⚠ Built in THIS order on purpose: B is absorbed FIRST, so the second
    # call names a survivor that is itself an alias. The other order trips a
    # different guard (the case below), and a mutation showed both tests
    # exercising that one — this check survived being deleted.
    for i in ("A", "B", "C"):
        shelves.save_shelf(LIB, new_shelf(id=i, library_id=LIB.id))
    shelves.save_alias(LIB, _absorb(alias_id="B", into="C"))
    try:
        shelves.save_alias(LIB, _absorb(alias_id="A", into="B"))
    except ShelfHasAliases as exc:
        assert "B" in str(exc), exc
    else:
        raise AssertionError("a chain A -> B -> C was stored")


@shelf_contract
def absorbing_a_shelf_that_others_resolve_to_is_refused(shelves):
    """The other end of the same rule, and the refusal P6.4d needs at the
    right moment: merging a shelf that has already absorbed one is the same
    conversation as deleting it, and must not arrive two statements later as
    `FOREIGN KEY constraint failed`."""
    for i in ("A", "B", "C"):
        shelves.save_shelf(LIB, new_shelf(id=i, library_id=LIB.id))
    shelves.save_alias(LIB, _absorb(alias_id="A", into="B"))
    try:
        shelves.save_alias(LIB, _absorb(alias_id="B", into="C"))
    except ShelfHasAliases:
        pass
    else:
        raise AssertionError("a survivor was absorbed, stranding its aliases")


@shelf_contract
def a_cycle_between_two_identities_is_refused(shelves):
    """Worse than a chain: with A -> B and B -> A neither shelf can ever be
    deleted again, because each is the other's survivor."""
    for i in ("A", "B"):
        shelves.save_shelf(LIB, new_shelf(id=i, library_id=LIB.id))
    shelves.save_alias(LIB, _absorb(alias_id="A", into="B"))
    try:
        shelves.save_alias(LIB, _absorb(alias_id="B", into="A"))
    except ShelfHasAliases:
        pass
    else:
        raise AssertionError("a cycle A <-> B was stored")
    assert shelves.delete_shelf(LIB, "A") is True, (
        "A is nobody's survivor, so it must still be deletable")


@shelf_contract
def absorbing_a_survivor_re_points_what_already_answered_to_it(shelves):
    """P6.4a's named trap, and the reason this is one method rather than two.

    ``save_alias`` refuses a survivor that has itself absorbed others — the
    one-hop rule, and correct. So the only way to merge B (which has already
    absorbed A) into C is to send A to C FIRST. Doing that in a separate call
    leaves the library, for one round trip, holding an identity that resolves
    to a shelf about to be deleted: every book that arrived with A becomes
    unreachable and `foreign_key_check` reports a clean file throughout.
    """
    from app.domain.alias import identities

    for i in ("A", "B", "C"):
        shelves.save_shelf(LIB, new_shelf(id=i, library_id=LIB.id))
    shelves.save_alias(LIB, _absorb(alias_id="A", into="B"))

    stood = shelves.absorb_shelf(LIB, _absorb(alias_id="B", into="C"))

    assert [a.alias_id for a in stood] == ["A"], (
        "the rows AS THEY STOOD are what the journal writes down; without "
        "them an undo has nothing to put A back to")
    assert stood[0].shelf_id == "B", "returned the row after the write"
    after = shelves.list_aliases(LIB)
    assert {(a.alias_id, a.shelf_id) for a in after} == {("A", "C"), ("B", "C")}
    assert set(identities("C", after)) == {"C", "A", "B"}, (
        "an identity fell out of the closure, so every book that arrived "
        "with it is unreachable from the only shelf still standing")


@shelf_contract
def absorbing_keeps_the_former_address_of_every_identity_it_moves(shelves):
    """Re-pointing changes WHO answers, never WHERE it stood.

    §3.11's address half is historical — *"the shelf that was at section 1,
    column 2, level 3"* — so it belongs to the absorbed identity, not to
    whichever shelf currently answers for it. Carrying the survivor's address
    across would make the library answer a question about wood with the wrong
    slot, and silently.
    """
    for i in ("A", "B", "C"):
        shelves.save_shelf(LIB, new_shelf(id=i, library_id=LIB.id))
    shelves.save_alias(LIB, _absorb(alias_id="A", into="B",
                                    at=ShelfAddress("se-1", 1, 1),
                                    label="ספרי בישול"))
    shelves.absorb_shelf(LIB, _absorb(alias_id="B", into="C",
                                      at=ShelfAddress("se-1", 2, 4)))

    moved = {a.alias_id: a for a in shelves.list_aliases(LIB)}
    assert moved["A"].address == ShelfAddress("se-1", 1, 1)
    assert moved["A"].label == "ספרי בישול"
    assert moved["B"].address == ShelfAddress("se-1", 2, 4)


@shelf_contract
def absorbing_into_a_shelf_that_was_itself_absorbed_is_still_refused(shelves):
    """Re-pointing is for the identities BELOW the merge, never above it.

    Absorbing into a shelf that has itself been absorbed would rewrite a merge
    somebody already made — a second answer to *"who answers for this?"* — so
    this end of the one-hop rule stands exactly as `save_alias` leaves it.
    """
    for i in ("A", "B", "C"):
        shelves.save_shelf(LIB, new_shelf(id=i, library_id=LIB.id))
    shelves.save_alias(LIB, _absorb(alias_id="B", into="C"))
    try:
        shelves.absorb_shelf(LIB, _absorb(alias_id="A", into="B"))
    except ShelfHasAliases as exc:
        assert "B" in str(exc), exc
    else:
        raise AssertionError("a chain A -> B -> C was stored")


@shelf_contract
def a_refused_absorb_re_points_nothing(shelves):
    """All of it or none of it.

    ⚠ The re-point comes FIRST, so a refusal after it is the state this method
    exists to make unreachable: A resolving to a shelf that is not being
    merged into anything, and no record anywhere that it ever answered to B.
    """
    for i in ("A", "B"):
        shelves.save_shelf(LIB, new_shelf(id=i, library_id=LIB.id))
    shelves.save_alias(LIB, _absorb(alias_id="A", into="B"))
    try:
        shelves.absorb_shelf(LIB, _absorb(alias_id="B", into="ghost"))
    except UnknownShelf:
        # ⚠ ONE class, not a tuple of three. A migration review pointed out
        # that a three-way `except` in the one spec that compares the two
        # implementations cannot report a class DISAGREEMENT — which is the
        # only thing this file exists to catch — and then found one next door
        # in `rewrite_aliases`.
        pass
    else:
        raise AssertionError("B was absorbed into a shelf that does not exist")
    assert [(a.alias_id, a.shelf_id) for a in shelves.list_aliases(LIB)] == [
        ("A", "B")], "a refused merge left A pointing somewhere else"


@shelf_contract
def rewriting_aliases_puts_a_merge_back_the_way_it_stood(shelves):
    """The undo's half: drop the minted row, send the re-pointed ones home.

    One method rather than a delete and a loop of saves, because between those
    statements the library holds identities resolving to a shelf whose row the
    undo is about to overwrite — a state no reader should see and, on a crash,
    one nothing would repair.
    """
    for i in ("A", "B", "C"):
        shelves.save_shelf(LIB, new_shelf(id=i, library_id=LIB.id))
    shelves.save_alias(LIB, _absorb(alias_id="A", into="B"))
    stood = shelves.absorb_shelf(LIB, _absorb(alias_id="B", into="C"))

    shelves.rewrite_aliases(LIB, remove=("B",), put=stood)

    assert [(a.alias_id, a.shelf_id) for a in shelves.list_aliases(LIB)] == [
        ("A", "B")]
    assert shelves.delete_shelf(LIB, "C") is True, (
        "C is nobody's survivor once the merge is taken back")


@shelf_contract
def rewriting_aliases_refuses_a_chain_it_would_create(shelves):
    """One hop, checked over the RESULT.

    ⚠ A per-row check cannot see this: each row here is legal against the
    table as it stands when that row is written, and the pair is illegal
    together. An undo is not a way around the rule `save_alias` exists to
    keep.
    """
    for i in ("A", "B", "C"):
        shelves.save_shelf(LIB, new_shelf(id=i, library_id=LIB.id))
    try:
        shelves.rewrite_aliases(LIB, put=(_absorb(alias_id="A", into="B"),
                                          _absorb(alias_id="B", into="C")))
    except ShelfHasAliases:
        pass
    else:
        raise AssertionError("an undo stored the chain A -> B -> C")


@shelf_contract
def removing_an_alias_that_is_not_there_is_not_an_error(shelves):
    """An undo is allowed to be a no-op about a row somebody else removed —
    the same reasoning as `delete_question` returning False rather than
    raising."""
    _two_shelves(shelves)
    shelves.rewrite_aliases(LIB, remove=("never-existed",))
    assert shelves.list_aliases(LIB) == ()


@shelf_contract
def rewriting_aliases_refuses_a_survivor_that_is_not_a_live_shelf(shelves):
    """One class, and it is the same class in both stores.

    ⚠ The SQLite path leaned on the foreign key here, and the key is
    `shelf_id REFERENCES shelves (id)` — by id ALONE, blind to `library_id`.
    So this store accepted an alias naming another library's shelf while the
    memory store refused it, and that shelf's own library could then never
    delete it: its `delete_shelf` guard reads `aliases_of` scoped to itself,
    finds nothing, and the key refuses with a raw `sqlite3.IntegrityError`
    crossing the port boundary — a 500 where a refusal was owed. The missing
    shelf was worse still: the driver's message reached the ADDRESS branch of
    the translation and answered *another identity already claims the slot
    None*, as a 409.
    """
    _two_shelves(shelves)
    try:
        shelves.rewrite_aliases(LIB, put=(_absorb(into="ghost"),))
    except UnknownShelf as exc:
        assert "ghost" in str(exc), exc
    else:
        raise AssertionError("an undo pointed an identity at no shelf")
    assert shelves.list_aliases(LIB) == ()


@shelf_contract
def deleting_a_shelf_takes_its_unanswerable_questions_with_it(shelves):
    """§3.10a's third orphaned kind, closed where every door meets it.

    ⚠ It was first closed in `app.map_edit._release`, which is ONE of four
    doors — and a review then walked `DELETE /api/v1/shelves/{id}`, the
    plainest route in the router, to the identical state: the question listed
    in `GET /duplicates`, counted on the Books tab, and both *answer* and
    *skip* answering 404 forever, with the queue's own stale-cleanup
    downstream of that 404 so it could not even be dismissed.

    ⚠ Standing DECISIONS are NOT touched, and the asymmetry is the rule. A
    question is a pending ask the owner can see and cannot dismiss; a decision
    is an answer that is merely inert — every read of one is shelf-scoped, no
    route enumerates them library-wide, and P6.4b's undo restores a deleted
    shelf under its ORIGINAL id, so the answer comes back with it.
    """
    from app.domain import Decision, DecisionKind, DuplicateQuestion

    # ⚠ The store's OWN queue where it has one (the memory pair is composed,
    # like `bind_books`); SQLite shares one file, so a queue opened on the
    # same path IS the same table — which is the point of one spec over both.
    queue = getattr(shelves, "_duplicates", None)
    decisions = MemoryDecisionStore()
    if queue is None:
        queue = SqliteDuplicateQueue(shelves.path)
        decisions = SqliteDecisionStore(shelves.path)
    _two_shelves(shelves)
    for shelf_id in ("sh-old", "sh-new"):
        queue.save_question(LIB, DuplicateQuestion(
            id=f"q-{shelf_id}", library_id=LIB.id, shelf_id=shelf_id, depth=1,
            book_key="עגנון|תמול שלשום", read_id="r", spine_id="s",
            claim_title="תמול שלשום", claim_author="עגנון",
            existing_book_id="b1", opened_at="2026-05-01T00:00:00Z"))
    decisions.save_decision(LIB, Decision(
        library_id=LIB.id, shelf_id="sh-old", depth=1,
        book_key="עגנון|רוח רפאים", kind=DecisionKind.REJECTED,
        decided_at="2026-02-01T00:00:00Z"))

    assert shelves.delete_shelf(LIB, "sh-old") is True

    assert [q.shelf_id for q in queue.list_open_questions(LIB)] == ["sh-new"], (
        "a question stands at a shelf that no longer exists; nothing can "
        "answer it and nothing can dismiss it")
    assert [d.book_key for d in
            decisions.decisions_at_shelf(LIB, "sh-old")] == ["עגנון|רוח רפאים"], (
        "the human's standing answer was destroyed with the shelf — it is "
        "inert, not in the way, and an undo brings the shelf back under the "
        "same id")


@shelf_contract
def absorbing_narrows_every_statement_to_this_library(shelves):
    """H2 on the RE-POINT, which is a raw UPDATE with nothing else to lean on.

    ⚠ A security review dropped `library_id = ?` from `absorb_shelf`'s UPDATE
    and from three of its lookups and the whole ring stayed green — because
    `shelves.id` is a GLOBAL primary key, so the collision those queries would
    need is unrepresentable. Redundant enforcement, correctly. But that is a
    property of a table two files away, not of these methods, and rule 7 says
    to ask *what else enforces this?* rather than to rest on it silently.
    """
    for lib in (LIB, OTHER):
        for i in ("A", "B", "C"):
            shelves.save_shelf(lib, new_shelf(id=f"{lib.id}-{i}",
                                              library_id=lib.id))
    shelves.save_alias(LIB, _absorb(alias_id=f"{LIB.id}-A",
                                    into=f"{LIB.id}-B"))
    shelves.save_alias(OTHER, _absorb(alias_id=f"{OTHER.id}-A",
                                      into=f"{OTHER.id}-B",
                                      lib=OTHER))

    shelves.absorb_shelf(LIB, _absorb(alias_id=f"{LIB.id}-B",
                                      into=f"{LIB.id}-C"))

    assert [(a.alias_id, a.shelf_id) for a in shelves.list_aliases(OTHER)] == [
        (f"{OTHER.id}-A", f"{OTHER.id}-B")], (
        "the re-point reached across the library boundary")
    shelves.rewrite_aliases(OTHER, remove=(f"{OTHER.id}-A",))
    assert shelves.list_aliases(OTHER) == ()
    assert len(shelves.list_aliases(LIB)) == 2, (
        "a removal in one library took a row out of another")


@shelf_contract
def an_alias_may_not_name_a_shelf_of_another_library(shelves):
    """H2, at the one door the composite primary key does not stand in.

    Both ends: the checked path and the undo's. A cross-library alias is
    unreachable through today's callers — `absorb_shelf` returns rows from the
    library it was handed — but this is the defence-in-depth INSIDE the
    boundary that CLAUDE.md keeps a rule about, and it is invisible to the API
    ring, which runs on memory stores.
    """
    _two_shelves(shelves)
    shelves.save_shelf(OTHER, new_shelf(id="far", library_id=OTHER.id))
    far = _absorb(alias_id="sh-old", into="far")
    for write in (lambda: shelves.save_alias(LIB, far),
                  lambda: shelves.absorb_shelf(LIB, far),
                  lambda: shelves.rewrite_aliases(LIB, put=(far,))):
        try:
            write()
        except UnknownShelf:
            pass
        else:
            raise AssertionError(
                "an alias in one library named a shelf in another; the shelf's "
                "own library can now never delete it")
    assert shelves.list_aliases(LIB) == ()
    assert shelves.delete_shelf(OTHER, "far") is True


@contract
def books_on_shelf_answers_for_every_identity_it_is_given(store):
    """P6.4a's read. §3.11 rewrites nothing when shelves merge, so a copy
    that arrived with an absorbed identity still names IT — which is why this
    takes a TUPLE of ids and the caller builds it with
    `app.domain.alias.identities`."""
    store.save(LIB, new_book(id="b1", library_id=LIB.id, title="בית",
                             author="א", copy_id="c1", shelf_id="sh-old"))
    store.save(LIB, new_book(id="b2", library_id=LIB.id, title="אור",
                             author="ב", copy_id="c2", shelf_id="sh-new"))
    store.save(LIB, new_book(id="b3", library_id=LIB.id, title="גן",
                             author="ג", copy_id="c3", shelf_id="sh-other"))

    both = store.books_on_shelf(LIB, ("sh-new", "sh-old"))
    assert [b.id for b in both] == ["b2", "b1"], (
        "answered in title order across both identities")
    assert [b.id for b in store.books_on_shelf(LIB, ("sh-new",))] == ["b2"]
    assert store.books_on_shelf(LIB, ()) == (), (
        "an empty identity list must answer nothing")
    assert store.books_on_shelf(LIB, ("nobody",)) == ()
    assert store.books_on_shelf(OTHER, ("sh-new", "sh-old")) == (), (
        "another library's shelf ids answered with this library's books")


@contract
def books_on_shelf_names_a_book_once_however_many_copies_stand_there(store):
    """Two copies of one work on one shelf are one book on the screen."""
    book = new_book(id="b1", library_id=LIB.id, title="בית", author="א",
                    copy_id="c1", shelf_id="sh-1")
    store.save(LIB, add_copy(book, copy_id="c2", shelf_id="sh-1"))
    assert [b.id for b in store.books_on_shelf(LIB, ("sh-1",))] == ["b1"]


# --- MapUndoStore (P6.4b) --------------------------------------------------

def _full_restore():
    """A restore with EVERY field populated, nested types and Hebrew.

    Every field on purpose: this is the one place the two implementations are
    compared, so a field left out here is a field the codec is free to drop.
    ``created`` is the field that WAS dropped, and it and ``minted_aliases``
    are last because they are not entity tuples and so are in neither
    ``RESTORE_ORDER`` nor ``LEDGER_ORDER``.

    ⚠ The five ledger tuples (P6.4d) are here for the same reason and are the
    riskier half: four of the five hold a type this file had never round
    tripped, and two of them — a decision and a question — are keyed by where
    they were asked rather than by an id, so a codec that lost the shelf would
    write them back at the wrong shelf rather than not at all.
    """
    from app.domain import (Bookcase, Capture, CopyPlacement, Decision,
                            DecisionKind, DuplicateQuestion, Floor, Place,
                            Rect, Section, Shelf, ShelfAddress, Site)
    from app.domain.alias import ShelfAlias
    from app.domain.map_undo import MapRestore

    return MapRestore(
        sites=(Site(id="st", library_id=LIB.id, name="הבית", order=2),),
        floors=(Floor(id="fl", library_id=LIB.id, site_id="st",
                      name="קומת קרקע", order=1),),
        places=(Place(id="pl", library_id=LIB.id, floor_id="fl",
                      rect=Rect(1, 2, 9, 7), name="סלון", order=3),),
        bookcases=(Bookcase(id="bc", library_id=LIB.id, floor_id="fl",
                            rect=Rect(1, 0, 4, 1), name="ספרייה", front="N",
                            place_id="pl", order=4),),
        sections=(Section(id="se", library_id=LIB.id, bookcase_id="bc",
                          ordinal=2, column_levels=(3, 4), gaps=((2, 2),),
                          default_levels=4, default_depth=2),),
        # ⚠ TWO shelves, and the second is the WISHLIST. `virtual` was the
        # one field across all eleven entity types left at its default, so a
        # codec that dropped `"virtual"` from every shelf reloaded it as
        # `False` and passed both the field-by-field assertions and the
        # whole-object `==`. Measured by a migration review. A default that
        # round-trips by accident is not round-tripped — and it needs a row of
        # its own, because a virtual shelf may have neither an address nor a
        # second depth (§5.7: it stands nowhere).
        shelves=(Shelf(id="sh", library_id=LIB.id, label="מדף עליון",
                       depth_count=2, created_at="2026-02-01T00:00:00Z",
                       address=ShelfAddress("se", 1, 3)),
                 Shelf(id="sh-wish", library_id=LIB.id, label="רשימת משאלות",
                       virtual=True, created_at="2026-02-02T00:00:00Z")),
        copies=(CopyPlacement(book_id="bk", copy_id="cp", shelf_id="sh",
                              depth=2),),
        # ⚠ TWO, with distinct orders and in the sequence a replay needs.
        # Every ledger tuple held one row, so a codec that SORTED `captures`
        # passed — and `MapRestore.captures` says in its own words that the
        # sequence is part of the inverse rather than a detail of writing it,
        # because `(shelf, depth, order)` is unique and a replay in the wrong
        # order lands on a slot whose occupant has not moved yet.
        captures=(Capture(id="cap-b", shelf_id="sh", library_id=LIB.id,
                          depth=2, order=3, image_id="img-b",
                          captured_at="2026-03-02T00:00:00Z"),
                  Capture(id="cap-a", shelf_id="sh", library_id=LIB.id,
                          depth=2, order=1, image_id="img-a",
                          captured_at="2026-03-01T00:00:00Z"),),
        decisions=(Decision(library_id=LIB.id, shelf_id="sh", depth=2,
                            book_key="עגנון|תמול שלשום",
                            kind=DecisionKind.WRONG_BOOK, copy_id="cp",
                            decided_at="2026-04-01T00:00:00Z"),),
        questions=(DuplicateQuestion(
            id="dq", library_id=LIB.id, shelf_id="sh", depth=2,
            book_key="עגנון|תמול שלשום", read_id="rd", spine_id="sp",
            claim_title="תמול שלשום", claim_author="ש״י עגנון",
            existing_book_id="bk", opened_at="2026-05-01T00:00:00Z",
            captured_at="2026-03-01T00:00:00Z"),),
        aliases=(ShelfAlias(alias_id="sh-old", library_id=LIB.id,
                            shelf_id="sh", merged_at="2026-06-01T00:00:00Z",
                            address=ShelfAddress("se", 2, 1),
                            label="מדף הבישול"),),
        created=("sh-minted", "sh-minted-2"),
        minted_aliases=("sh-absorbed",),
        minted_decisions=(("sh", 2, "עגנון|תמול שלשום"),),
        minted_questions=(("sh", 1, "עגנון|סיפור פשוט"),),
    )


def _entry(store_id="u1", **kw):
    from app.domain.map_undo import MapUndoEntry

    fields = dict(id=store_id, library_id=LIB.id, kind="remove_column",
                  tag="section:se", recorded_at="2026-08-24T10:00:00+00:00",
                  restore=_full_restore(), fingerprint={"sections:se": "abc123"})
    fields.update(kw)
    return MapUndoEntry(**fields)


@undo_contract
def an_entry_round_trips_every_field_it_was_given(journal):
    """The whole reason this spec exists.

    ⚠ Asserted field by field rather than with one ``==`` on the entry, so a
    failure says WHICH field the codec lost. Equality is checked too, at the
    end, because a field added tomorrow is covered by that and by nothing
    above it.
    """
    from app.domain import DecisionKind

    journal.record(LIB, _entry())
    back = journal.recent(LIB, limit=5)[0]

    assert back.id == "u1" and back.kind == "remove_column"
    assert back.tag == "section:se", "the coalescing tag did not survive"
    assert back.fingerprint == {"sections:se": "abc123"}
    assert back.undone_at is None and back.is_live
    r = back.restore
    assert r.sites[0].name == "הבית" and r.sites[0].order == 2
    # ⚠ Was `== "fl" or == "st"`. A hedge in the one spec whose stated job is
    # to say WHICH field the codec lost names none of them.
    assert r.floors[0].site_id == "st"
    assert r.places[0].rect == Rect(1, 2, 9, 7) and r.places[0].order == 3
    assert r.bookcases[0].front == "N" and r.bookcases[0].place_id == "pl"
    assert r.sections[0].column_levels == (3, 4)
    assert r.sections[0].gaps == ((2, 2),), "the mask was lost or reshaped"
    assert r.sections[0].ordinal == 2 and r.sections[0].default_depth == 2
    assert r.shelves[0].label == "מדף עליון" and r.shelves[0].depth_count == 2
    assert r.shelves[0].address == ShelfAddress("se", 1, 3)
    assert r.shelves[1].virtual is True, (
        "`virtual` reloaded as its default, which is what a DROPPED field "
        "looks like from here")
    assert r.created == ("sh-minted", "sh-minted-2"), (
        "`created` was dropped — the entry is now permanently un-undoable, "
        "because its fingerprint watches a key the restore no longer names")
    assert r.copies[0].copy_id == "cp" and r.copies[0].depth == 2
    assert [c.id for c in r.captures] == ["cap-b", "cap-a"], (
        "the photographs came back in a different ORDER — a replay in the "
        "wrong sequence lands on a slot whose occupant has not moved yet, "
        "and a half-replayed undo leaves an entry dead forever")
    assert r.captures[0].order == 3 and r.captures[0].image_id == "img-b"
    assert r.decisions[0].kind is DecisionKind.WRONG_BOOK, (
        "the decision came back as a bare string, so an undo would write a "
        "kind no reader can compare")
    assert r.decisions[0].shelf_id == "sh" and r.decisions[0].depth == 2
    assert r.questions[0].claim_author == "ש״י עגנון"
    assert r.aliases[0].address == ShelfAddress("se", 2, 1), (
        "the alias's FORMER address was lost — the half of §3.11 that answers "
        "\"the shelf that was at section 1, column 2, level 3\"")
    assert r.aliases[0].label == "מדף הבישול"
    assert r.minted_aliases == ("sh-absorbed",), (
        "`minted_aliases` was dropped — same failure as `created`, one table "
        "over: the undo would leave the merge standing")
    assert r.minted_decisions == (("sh", 2, "עגנון|תמול שלשום"),), (
        "a key triple came back as a LIST or not at all; either way it "
        "compares unequal to the one `target_keys` builds, so the entry can "
        "never be undone")
    assert r.minted_questions == (("sh", 1, "עגנון|סיפור פשוט"),)
    assert back.seq == 1, "the store did not number the first entry"
    # ⚠ Compared against the entry WITH the store's own `seq`, because that
    # one field is assigned by the store and not by the caller — handing it in
    # is what would let two processes pick the same number.
    from dataclasses import replace as _replace
    assert back == _replace(_entry(), seq=back.seq), (
        "a field this spec does not name was lost")
    from dataclasses import fields as _fields
    from app.domain.map_undo import MapRestore as _MR
    assert all(getattr(back.restore, f.name) for f in _fields(_MR)), (
        "a field of MapRestore is empty, so this spec is not exercising it — "
        "populate it in `_full_restore`, or the next dropped field is silent")


@undo_contract
def the_blob_carries_the_current_shape_stamp(journal):
    """⚠ Nothing read `v` and no test asserted it, so it said `1` for two
    different shapes — eight keys and seventeen — which is worse than no stamp
    because it looks like an answer. Skipped where the store keeps entries as
    objects: there is no blob to stamp, and asserting one would be asserting
    this test's own fixture."""
    import json

    journal.record(LIB, _entry())
    reader = getattr(journal, "_connect", None)
    if reader is None:
        return
    from app.adapters.sqlite_store import UNDO_BLOB_SHAPE

    with reader() as conn:
        blob = conn.execute(
            "SELECT inverse FROM map_undo WHERE id = 'u1'").fetchone()[0]
    assert json.loads(blob)["v"] == UNDO_BLOB_SHAPE, (
        "the payload's key set changed and the stamp did not, so a reader "
        "consulting it learns nothing")


@undo_contract
def recording_the_same_id_twice_replaces_rather_than_duplicates(journal):
    """Coalescing rewrites the head IN PLACE — two rows would make the merged
    entry the second-newest and leave the un-merged half at the front."""
    journal.record(LIB, _entry())
    journal.record(LIB, _entry(kind="delete_bookcase"))
    rows = journal.recent(LIB, limit=9)
    assert len(rows) == 1 and rows[0].kind == "delete_bookcase"


@undo_contract
def recent_returns_them_in_the_order_they_were_recorded(journal):
    """Newest LAST-RECORDED first, and never newest-by-timestamp.

    ⚠ Every entry here shares one ``recorded_at``, which is the case that
    matters and the one this spec used to avoid by giving each a distinct
    time. Production cannot: ``SystemClock`` has second resolution and the
    client sends a bookcase deletion as four requests, so a tie is the
    ordinary shape. A review measured the timestamp ordering picking the wrong
    head 165 times in 500 — undoing the wrong bookcase, and stranding the
    right one forever. The store numbers each entry as it arrives, and that
    number is what "which came last" means.
    """
    same = "2026-08-24T10:00:00+00:00"
    for n in (1, 2, 3):
        journal.record(LIB, _entry(store_id=f"u{n}", recorded_at=same))
    assert [e.id for e in journal.recent(LIB, limit=9)] == ["u3", "u2", "u1"]
    assert [e.id for e in journal.recent(LIB, limit=1)] == ["u3"]
    assert journal.recent(LIB, limit=0) == ()
    assert [e.seq for e in journal.recent(LIB, limit=9)] == [3, 2, 1]


@undo_contract
def rewriting_an_entry_moves_it_to_the_head(journal):
    """Coalescing takes a FRESH number, and the interleave is why.

    The opposite was written first, on the reasoning that a merged entry "is
    still the same edit in the order of things". It is not: the second half of
    an operation arriving is that OPERATION finishing, and what the owner
    wants back is the last thing they finished. Two removals in one flush
    interleave — clear B, clear A, delete B — so a merged B entry that kept
    its old number sat behind A's clearing, and undo took back A."""
    journal.record(LIB, _entry(store_id="u1"))
    journal.record(LIB, _entry(store_id="u2"))
    journal.record(LIB, _entry(store_id="u1", kind="delete_bookcase"))
    assert [e.id for e in journal.recent(LIB, limit=9)] == ["u1", "u2"]
    assert journal.recent(LIB, limit=1)[0].kind == "delete_bookcase"


@undo_contract
def numbering_is_per_library(journal):
    """Two libraries number independently — a busy collection must not push
    a quiet one's counter forward, and neither may see the other's rows."""
    journal.record(LIB, _entry(store_id="a1"))
    journal.record(LIB, _entry(store_id="a2"))
    journal.record(OTHER, _entry(store_id="b1", library_id=OTHER.id))
    assert journal.recent(OTHER, limit=9)[0].seq == 1
    assert [e.id for e in journal.recent(LIB, limit=9)] == ["a2", "a1"]


@undo_contract
def marking_an_entry_undone_keeps_the_row(journal):
    """No redo, and the journal is also the record that the undo happened —
    so the row is stamped, never deleted."""
    journal.record(LIB, _entry())
    assert journal.mark_undone(LIB, "u1", "2026-08-24T12:00:00+00:00")
    back = journal.recent(LIB, limit=9)
    assert len(back) == 1
    assert back[0].undone_at == "2026-08-24T12:00:00+00:00"
    assert not back[0].is_live
    assert not journal.mark_undone(LIB, "nope", "2026-08-24T12:00:00+00:00")


@undo_contract
def a_journal_is_scoped_to_its_library(journal):
    """H2. Another library's entries are absent, not merely unreachable — and
    an entry whose own `library_id` disagrees is refused rather than filed
    under the wrong customer."""
    journal.record(LIB, _entry())
    assert journal.recent(OTHER, limit=9) == ()
    assert not journal.mark_undone(OTHER, "u1", "2026-08-24T12:00:00+00:00")
    try:
        journal.record(OTHER, _entry(store_id="u2"))
    except WrongLibrary:
        pass
    else:
        raise AssertionError("an entry was filed under a library it disowns")


def test_a_v23_database_gains_the_alias_table_and_keeps_its_shelves():
    """v24 on an UPGRADED file — CLAUDE.md rule 11, frame from v22→v23.

    What it is FOR: a library drawn and photographed before P6.4a arrives with
    its map and its shelves, and after the upgrade every one of those is still
    standing with NO aliases — an existing library has merged nothing, and the
    upgrade must not invent an identity it never had.
    """
    import sqlite3

    from app.adapters.migrations import MIGRATIONS, SCHEMA_VERSION, current_version
    from app.adapters.sqlite_store import SqliteShelfStore
    from app.domain.alias import ShelfAlias, resolve, resolve_address

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v23.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 23:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 23")
            conn.execute("INSERT INTO users (id, display_name) VALUES"
                         " ('u1', 'משה')")
            conn.execute("INSERT INTO accounts (id, label) VALUES ('acc', '')")
            conn.execute("INSERT INTO libraries (id, account_id, label)"
                         " VALUES ('lib', 'acc', 'הבית')")
            conn.execute("INSERT INTO sites (id, library_id, name, \"order\")"
                         " VALUES ('st', 'lib', 'הבית', 0)")
            conn.execute("INSERT INTO floors (id, library_id, site_id, name,"
                         " \"order\") VALUES ('fl', 'lib', 'st', 'קרקע', 0)")
            conn.execute(
                "INSERT INTO bookcases (id, library_id, floor_id, place_id,"
                " name, front, x, y, w, h, \"order\") VALUES"
                " ('bc','lib','fl',NULL,'ספרייה','S',1,0,4,1,0)")
            conn.execute(
                "INSERT INTO sections (id, library_id, bookcase_id, ordinal,"
                " column_levels, gaps, default_levels, default_depth) VALUES"
                " ('se','lib','bc',1,'[3, 3]','[]',3,1)")
            conn.execute(
                "INSERT INTO shelves (id, library_id, label, depth_count,"
                " virtual, created_at, section_id, col, level) VALUES"
                " ('sh-drawn','lib','מדף עליון',1,0,'2026-02-01T00:00:00Z',"
                "'se',1,3)")
            conn.execute(
                "INSERT INTO shelves (id, library_id, label, depth_count,"
                " virtual, created_at) VALUES"
                " ('sh-photo','lib','מהתמונה',1,0,'2026-02-02T00:00:00Z')")
            conn.commit()
        finally:
            conn.close()

        # ⚠ BEFORE the store opens it: at v23 the TABLE does not exist. These
        # lines are what make folding the DDL into `_V23` fail.
        before = sqlite3.connect(str(path))
        try:
            assert "shelf_aliases" not in {
                r[0] for r in before.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'")
            }, "v24's table arrived before v24"
        finally:
            before.close()

        shelves = SqliteShelfStore(path)          # migrates 23 -> 24
        lib = LibraryRef("lib")

        check = sqlite3.connect(str(path))
        try:
            assert current_version(check) == SCHEMA_VERSION
            assert "shelf_aliases" in {
                r[0] for r in check.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'")}
            assert check.execute(
                "SELECT COUNT(*) FROM shelf_aliases").fetchone()[0] == 0, (
                "the upgrade invented an identity this library never merged"
            )
            assert check.execute("PRAGMA foreign_key_check").fetchall() == []
            names = {r[0] for r in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'")}
            for wanted in ("shelf_aliases_by_shelf", "shelf_aliases_by_address",
                           "shelves_by_slot"):
                assert wanted in names, f"the {wanted} index is gone"
        finally:
            check.close()

        # Both shelves survived, drawn and photographed alike.
        drawn = shelves.get_shelf(lib, "sh-drawn")
        assert drawn.label == "מדף עליון"
        assert drawn.address == ShelfAddress("se", 1, 3), (
            "the slot columns are the interesting ones on an upgrade "
            "that adds an index over the same shape")
        assert shelves.get_shelf(lib, "sh-photo").address is None

        # …and the table is USED, on the real file, through the real store:
        # the photo-born shelf is absorbed by the drawn one.
        shelves.save_alias(lib, ShelfAlias(
            alias_id="sh-photo", library_id="lib", shelf_id="sh-drawn",
            address=None, label="מהתמונה",
            merged_at="2026-08-25T10:00:00+00:00"))
        aliases = shelves.list_aliases(lib)
        assert resolve("sh-photo", aliases) == "sh-drawn"
        assert aliases[0].label == "מהתמונה"
        assert resolve_address(ShelfAddress("se", 1, 3), aliases) is None, (
            "a LIVE slot is not the alias table's question"
        )

        after = sqlite3.connect(str(path))
        try:
            assert after.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            after.close()


def test_a_v22_database_gains_the_undo_sequence_and_keeps_its_entries():
    """v23 on an UPGRADED file — CLAUDE.md rule 11, frame from v21→v22.

    What it is FOR: a library that recorded undo entries under v22, where the
    head was decided by `recorded_at` and a uuid4 tie-break. After the upgrade
    those entries are still there, still readable, and the NEW ones number
    from 1 and sort ahead of them — which is where an entry with no recorded
    order belongs.
    """
    import sqlite3

    from app.adapters.migrations import MIGRATIONS, SCHEMA_VERSION, current_version
    from app.adapters.sqlite_store import SqliteMapUndoStore
    from app.domain.map_undo import MapRestore, MapUndoEntry

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v22.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 22:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 22")
            conn.execute("INSERT INTO users (id, display_name) VALUES"
                         " ('u1', 'משה')")
            conn.execute("INSERT INTO accounts (id, label) VALUES ('acc', '')")
            conn.execute("INSERT INTO libraries (id, account_id, label)"
                         " VALUES ('lib', 'acc', 'הבית')")
            # ⚠ A real drawing too, not just the journal — the v19→v20 case's
            # own ⚠ records that its `foreign_key_check` ran while every new
            # table was empty, and this step must also be shown to leave the
            # REST of the schema alone.
            conn.execute("INSERT INTO sites (id, library_id, name, \"order\")"
                         " VALUES ('st', 'lib', 'הבית', 0)")
            conn.execute("INSERT INTO floors (id, library_id, site_id, name,"
                         " \"order\") VALUES ('fl', 'lib', 'st', 'קרקע', 0)")
            conn.execute(
                "INSERT INTO bookcases (id, library_id, floor_id, place_id,"
                " name, front, x, y, w, h, \"order\") VALUES"
                " ('bc','lib','fl',NULL,'ספרייה','S',1,0,4,1,0)")
            conn.execute(
                "INSERT INTO sections (id, library_id, bookcase_id, ordinal,"
                " column_levels, gaps, default_levels, default_depth) VALUES"
                " ('se','lib','bc',1,'[3, 3]','[]',3,1)")
            conn.execute(
                "INSERT INTO shelves (id, library_id, label, depth_count,"
                " virtual, created_at, section_id, col, level) VALUES"
                " ('sh-old','lib','מדף עליון',1,0,'2026-02-01T00:00:00Z',"
                "'se',1,3)")
            # Two entries recorded under v22 — the same second, which is the
            # shape that made this step necessary.
            for old in ("old-a", "old-b"):
                conn.execute(
                    "INSERT INTO map_undo (id, library_id, kind, recorded_at,"
                    " inverse, fingerprint, undone_at) VALUES (?,?,?,?,?,?,?)",
                    (old, "lib", "clear_bookcase",
                     "2026-08-24T10:00:00+00:00",
                     '{"sites": [], "floors": [], "places": [],'
                     ' "bookcases": [], "sections": [], "shelves": ['
                     '{"id": "sh-' + old + '", "library_id": "lib",'
                     ' "label": "מדף", "depth_count": 1,'
                     ' "virtual": false, "created_at": null,'
                     ' "address": null}],'
                     ' "created": [], "tag": "bookcase:bc", "v": 1}',
                     "{}", None))
            conn.commit()
        finally:
            conn.close()

        # ⚠ BEFORE the store opens it: at v22 the column does not exist.
        before = sqlite3.connect(str(path))
        try:
            assert "seq" not in {
                r[1] for r in before.execute("PRAGMA table_info(map_undo)")
            }, "v23's column arrived before v23"
        finally:
            before.close()

        journal = SqliteMapUndoStore(path)          # migrates 22 -> 23
        lib = LibraryRef("lib")

        check = sqlite3.connect(str(path))
        try:
            # ⚠ SCHEMA_VERSION, not 23. Opening the store migrates the WHOLE
            # pending chain, so pinning this to the step's own number makes
            # the test fail the day a later step exists — which it did, on
            # v24's first run. What pins THIS step is the ABSENT check above
            # and the column assertion below.
            assert current_version(check) == SCHEMA_VERSION
            assert "seq" in {
                r[1] for r in check.execute("PRAGMA table_info(map_undo)")}
            assert [r[0] for r in check.execute(
                "SELECT seq FROM map_undo ORDER BY id")] == [0, 0], (
                "the upgrade invented an order the old rows never had")
            assert check.execute("PRAGMA foreign_key_check").fetchall() == []
            names = {r[0] for r in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'")}
            assert "map_undo_by_library" in names, "the index is gone"
            assert "seq" in check.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND"
                " name = 'map_undo_by_library'").fetchone()[0], (
                "the index still orders by the column that ties")
        finally:
            check.close()

        # The v22 entries survived and are still readable whole…
        assert {e.id for e in journal.recent(lib, limit=9)} == {"old-a", "old-b"}

        # …and so did the drawing this step never claimed to touch.
        from app.adapters.sqlite_store import SqliteMapStore, SqliteShelfStore

        maps = SqliteMapStore(path)
        assert maps.get_section(lib, "se").column_levels == (3, 3)
        assert SqliteShelfStore(path).get_shelf_at(
            lib, ShelfAddress("se", 1, 3)).label == "מדף עליון"

        # …and the column is USED: a new entry numbers from 1 and takes the
        # head from both of the unordered ones.
        journal.record(lib, MapUndoEntry(
            id="new-1", library_id="lib", kind="remove_column",
            tag="section:se", recorded_at="2026-08-24T10:00:00+00:00",
            restore=MapRestore(created=("sh-1",)), fingerprint={}))
        head = journal.recent(lib, limit=9)
        assert head[0].id == "new-1" and head[0].seq == 1
        assert [e.id for e in head][1:] == sorted(["old-a", "old-b"],
                                                 reverse=True)

        after = sqlite3.connect(str(path))
        try:
            assert after.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            after.close()


def test_a_v21_database_gains_the_undo_journal_and_keeps_its_drawing():
    """v22 on an UPGRADED file — CLAUDE.md rule 11, frame copied from v20→v21.

    What it is FOR: a library drawn before P6.4b arrives with its map, its
    shelves and books on them, and after the upgrade every one of those is
    still standing and the journal is EMPTY — an existing library has no
    recorded history and must not be given a fabricated one.

    Then it USES the table, on the real file, through the real store: the
    ⚠ on the v19→v20 case records that its ``foreign_key_check`` ran while
    every new table was empty, so this one records an entry, reads it back
    whole, and checks the file again afterwards.
    """
    import sqlite3

    from app.adapters.migrations import MIGRATIONS, SCHEMA_VERSION, current_version
    from app.adapters.sqlite_store import (
        SqliteMapStore,
        SqliteMapUndoStore,
        SqliteShelfStore,
    )
    from app.domain.map_undo import MapRestore, MapUndoEntry

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v21.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 21:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 21")
            conn.execute("INSERT INTO users (id, display_name) VALUES"
                         " ('u1', 'משה')")
            conn.execute("INSERT INTO accounts (id, label) VALUES ('acc', '')")
            conn.execute("INSERT INTO libraries (id, account_id, label)"
                         " VALUES ('lib', 'acc', 'הבית')")
            conn.execute("INSERT INTO sites (id, library_id, name, \"order\")"
                         " VALUES ('st', 'lib', 'הבית', 0)")
            conn.execute("INSERT INTO floors (id, library_id, site_id, name,"
                         " \"order\") VALUES ('fl', 'lib', 'st', 'קרקע', 0)")
            conn.execute(
                "INSERT INTO bookcases (id, library_id, floor_id, place_id,"
                " name, front, x, y, w, h, \"order\") VALUES"
                " ('bc','lib','fl',NULL,'ספרייה','S',1,0,4,1,0)")
            conn.execute(
                "INSERT INTO sections (id, library_id, bookcase_id, ordinal,"
                " column_levels, gaps, default_levels, default_depth) VALUES"
                " ('se','lib','bc',1,'[3, 3]','[]',3,1)")
            conn.execute(
                "INSERT INTO shelves (id, library_id, label, depth_count,"
                " virtual, created_at, section_id, col, level) VALUES"
                " ('sh-old','lib','מדף עליון',1,0,'2026-02-01T00:00:00Z',"
                "'se',1,3)")
            conn.commit()
        finally:
            conn.close()

        # ⚠ BEFORE the store opens it: at v21 the TABLE does not exist. These
        # four lines are the ones rule 11 exists for — without them the test
        # follows `MIGRATIONS` wherever the DDL is written, so folding the
        # CREATE into `_V21` (the edit rule 11 forbids) stays green while the
        # one database that matters never gains the table.
        before = sqlite3.connect(str(path))
        try:
            assert "map_undo" not in {
                r[0] for r in before.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'")
            }, "v22's table arrived before v22"
        finally:
            before.close()

        maps = SqliteMapStore(path)               # migrates 21 -> 22
        shelves = SqliteShelfStore(path)
        journal = SqliteMapUndoStore(path)
        lib = LibraryRef("lib")

        check = sqlite3.connect(str(path))
        try:
            assert current_version(check) == SCHEMA_VERSION
            assert "map_undo" in {
                r[0] for r in check.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'")}
            assert check.execute(
                "SELECT COUNT(*) FROM map_undo").fetchone()[0] == 0, (
                "the upgrade invented a history this library never had"
            )
            assert check.execute("PRAGMA foreign_key_check").fetchall() == []
            names = {r[0] for r in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'")}
            for wanted in ("map_undo_by_library", "sections_by_bookcase",
                           "shelves_by_slot"):
                assert wanted in names, f"the {wanted} index is gone"
        finally:
            check.close()

        # The drawing that predates the table is intact, labels and all.
        section = maps.get_section(lib, "se")
        assert section.column_levels == (3, 3) and section.gaps == ()
        standing = shelves.get_shelf_at(lib, ShelfAddress("se", 1, 3))
        assert standing.id == "sh-old" and standing.label == "מדף עליון"

        # …and the table is USED, through the real store, on the real file —
        # a whole entry out and back, Hebrew label included.
        journal.record(lib, MapUndoEntry(
            id="u1", library_id="lib", kind="remove_column",
            tag="section:se", recorded_at="2026-08-24T09:00:00Z",
            restore=MapRestore(sections=(section,), shelves=(standing,)),
            fingerprint={"sections:se": "abc123abc123"},
        ))
        back = journal.recent(lib, limit=5)
        assert len(back) == 1
        assert back[0].restore.shelves[0].label == "מדף עליון"
        assert back[0].restore.sections[0].column_levels == (3, 3)
        assert back[0].tag == "section:se", "the coalescing tag did not survive"
        assert back[0].is_live

        after = sqlite3.connect(str(path))
        try:
            assert after.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            after.close()


def test_a_v18_database_gains_the_binding_column_and_keeps_its_rows():
    """v19 on an UPGRADED file — the rule CLAUDE.md now carries."""
    import sqlite3

    from app.adapters.migrations import MIGRATIONS, SCHEMA_VERSION, current_version
    from app.adapters.sqlite_store import SqliteOAuthStateStore
    from app.domain.auth import hash_token
    from app.domain.oauth import new_state

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "v18.db"
        conn = sqlite3.connect(str(path))
        try:
            for version, step in MIGRATIONS:
                if version > 18:
                    break
                if isinstance(step, str):
                    conn.executescript(step)
                else:
                    step(conn)
            conn.execute("PRAGMA user_version = 18")
            conn.execute(
                "INSERT INTO oauth_states (state_hash, provider, nonce,"
                " verifier, next_hash, created_at, expires_at) VALUES"
                " (?, 'google', 'n', 'v', '', '2026-08-13T12:00:00+00:00',"
                "  '2026-08-13T12:15:00+00:00')",
                (hash_token("pre-v19"),))
            conn.commit()
        finally:
            conn.close()

        store = SqliteOAuthStateStore(path)      # migrates 18 -> 19
        check = sqlite3.connect(str(path))
        try:
            assert current_version(check) == SCHEMA_VERSION
            assert "binding_hash" in {
                r[1] for r in check.execute("PRAGMA table_info(oauth_states)")}
        finally:
            check.close()

        # The row that predates the column belongs to no browser, so the
        # callback refuses it — fail closed, one retry, no fixation.
        carried = store.consume_state(hash_token("pre-v19"),
                                      now="2026-08-13T12:05:00+00:00")
        assert carried is not None and carried.binding_hash == ""
        assert not carried.belongs_to("whatever the attacker sends")

        store.save_state(new_state("fresh", "google", "n", "v",
                                   "2026-08-13T12:00:00+00:00",
                                   binding="mine"))
        assert store.consume_state(
            hash_token("fresh"), now="2026-08-13T12:05:00+00:00"
        ).belongs_to("mine")


# --- binding the contracts to their implementations -----------------------
#
# ⚠ **At the END of the file, all of them, and that is load-bearing.** A
# `@..._contract` case defined BELOW its binder is appended to a list the loop
# has already walked, so it binds NOTHING and the suite reports ok with fewer
# cases than the run before it. It happened twice in two items — P6.4b's
# `UNDO_CONTRACT` bound zero of seven, and P6.4a's alias cases bound zero of
# eight — because both were written next to the code they describe rather
# than above line 2445. Moving every loop here means "define a case anywhere"
# is simply true.
#
# The counts are the second half. A silent zero is what made this expensive
# both times, so each list states how many cases it should have: adding one
# without updating the number is a red test, which is exactly the noise a
# silent binder failed to make.
# ⚠ ONE list, of triples. Two parallel lists — counts in one, implementations
# in the other — let a ninth contract be added to the binder and not to the
# counts, which is the same silent gap wearing a different hat.
SUITES = (
    (CONTRACT, IMPLEMENTATIONS, 42),
    (SHELF_CONTRACT, SHELF_IMPLEMENTATIONS, 36),
    (READ_CONTRACT, READ_IMPLEMENTATIONS, 17),
    (DECISION_CONTRACT, DECISION_IMPLEMENTATIONS, 8),
    (DUPLICATE_CONTRACT, DUPLICATE_IMPLEMENTATIONS, 9),
    (TENANCY_CONTRACT, TENANCY_IMPLEMENTATIONS, 14),
    (MAP_CONTRACT, MAP_IMPLEMENTATIONS, 29),
    (UNDO_CONTRACT, UNDO_IMPLEMENTATIONS, 8),
)

for _cases, _impls, _expected in SUITES:
    assert len(_cases) == _expected, (
        f"a contract list holds {len(_cases)} cases, not {_expected} — if you "
        f"added one, say so here; if it reads 0 the decorator never ran"
    )
    for _label, _factory in _impls:
        for _fn in _cases:
            _name = f"test_{_fn.__name__}__{_label}"
            globals()[_name] = _bind(_fn, _factory, _name)
