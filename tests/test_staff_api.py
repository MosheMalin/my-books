# -*- coding: utf-8 -*-
"""The system-admin service: the cross-tenant read model and its credential.

`app/staff_api/` is a SECOND application (D2's "strangle, don't refactor"
shape, the same way the tuning server and the product coexist), because a
system administrator cannot be expressed inside `/api/v1`: every route there
resolves a library through the caller's MEMBERSHIPS (§4.2 — a foreign record
reads as ABSENT), and an operator who oversees tenants is a member of none of
them. Loosening that resolver to serve a console would weaken the product's
isolation for everyone.

What earns a test here, and what does not: the read model duplicates SCHEMA
knowledge on purpose (see `app/staff_api/queries.py`), so the cases worth
having are the ones that catch that duplication going stale — plus the two
rules a system console must never get wrong: the §5.1 status ladder, and the
credential.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.adapters.migrations import migrate  # noqa: E402
from app.adapters.sqlite_store import SqliteBookStore, SqliteTenancyStore  # noqa: E402
from app.domain import LibraryRef, new_book  # noqa: E402
from app.domain.book import Status, add_copy  # noqa: E402
from app.domain.tenancy import Account, Library, Membership, Role  # noqa: E402
from app.staff_api.app import STAFF_TOKEN_ENV, create_app  # noqa: E402
from app.staff_api.queries import SchemaMismatch, StaffQueries, _open  # noqa: E402


def _seed(path: Path) -> None:
    """Two libraries, two accounts, three books — through the REAL stores.

    ⚠ Written with the product's own write path rather than raw INSERTs. The
    read model's whole risk is disagreeing with how the product actually
    stores things; a fixture built from hand-written SQL would encode the same
    assumption twice and then agree with itself.
    """
    tenancy = SqliteTenancyStore(path)
    books = SqliteBookStore(path)

    tenancy.save_account(Account(id="acc-1", display_name="משה",
                                 created_at="2026-01-01T00:00:00Z"))
    tenancy.save_account(Account(id="acc-2", display_name="שותף",
                                 created_at="2026-01-02T00:00:00Z"))
    for lib_id, label in (("lib-a", "הבית"), ("lib-b", "החנות")):
        tenancy.save_library(Library(id=lib_id, label=label,
                                     created_at="2026-01-01T00:00:00Z"))
    tenancy.save_membership(Membership(account_id="acc-1", library_id="lib-a",
                                       role=Role.ADMIN))
    tenancy.save_membership(Membership(account_id="acc-1", library_id="lib-b",
                                       role=Role.ADMIN))
    tenancy.save_membership(Membership(account_id="acc-2", library_id="lib-a",
                                       role=Role.VIEWER))

    ref_a, ref_b = LibraryRef(id="lib-a"), LibraryRef(id="lib-b")
    books.save(ref_a, new_book(id="b1", library_id="lib-a", copy_id="c1",
                               title="המנהרה", author="ארנסטו סבאטו",
                               status=Status.AUTO, added_at="2026-02-01"))
    books.save(ref_a, new_book(id="b2", library_id="lib-a", copy_id="c2",
                               title="אבק כוכבים", author="אסימוב, אייזיק",
                               status=Status.APPROVED, added_at="2026-02-02"))
    books.save(ref_b, new_book(id="b3", library_id="lib-b", copy_id="c3",
                               title="Sapiens", author="Yuval Harari",
                               status=Status.AUTO, added_at="2026-02-03"))


@contextmanager
def _db():
    """A real product database on a temp dir, seeded and migrated."""
    tmp = tempfile.mkdtemp(prefix="booksnap-staff-")
    try:
        path = Path(tmp) / "product.db"
        _seed(path)
        yield path
    finally:
        # ⚠ `ignore_errors`: on Windows a connection left open by a failing
        # assertion keeps the file locked, and a teardown that raised would
        # replace the real failure with a PermissionError several tests away.
        shutil.rmtree(tmp, ignore_errors=True)


@contextmanager
def _queries():
    with _db() as path:
        yield StaffQueries(path), path


@contextmanager
def _client(token: str | None):
    """A TestClient over a freshly-seeded database, with the env var set.

    ⚠ The app reads `BOOKSNAP_STAFF_TOKEN` when it is BUILT, so each case
    builds its own — which is also what stops one test's token leaking into
    the next.
    """
    saved = os.environ.get(STAFF_TOKEN_ENV)
    if token is None:
        os.environ.pop(STAFF_TOKEN_ENV, None)
    else:
        os.environ[STAFF_TOKEN_ENV] = token
    try:
        with _db() as path:
            yield TestClient(create_app(StaffQueries(path)))
    finally:
        if saved is None:
            os.environ.pop(STAFF_TOKEN_ENV, None)
        else:
            os.environ[STAFF_TOKEN_ENV] = saved


def _user_version(path: Path) -> int:
    """⚠ `with sqlite3.connect(...)` is a TRANSACTION context manager, not a
    closing one — it commits and leaves the handle open. On Windows that is
    not a style nit: the open handle makes the temp directory undeletable and
    the test errors in teardown, several tests away from the line at fault."""
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


# --- the read model --------------------------------------------------------

def test_the_overview_counts_every_tenant_not_just_one():
    """The whole reason this service exists. `/api/v1` cannot answer it: its
    resolver narrows to the caller's memberships by design."""
    with _queries() as (q, _):
        o = q.overview()
        assert o["libraries"] == 2
        assert o["accounts"] == 2
        assert o["books"] == 3
        assert o["memberships"] == 3


def test_status_is_derived_by_the_5_1_ladder_not_read_off_a_column():
    """⚠ A book's status is the STRONGEST claim among its copies, and `manual`
    OUTRANKS `approved`. Adding a manual copy to an auto book must make the
    book manual — if this read model ever counted the first copy, or a stored
    column, the dashboard would report a book the owner typed by hand as
    "awaiting approval"."""
    with _queries() as (q, path):
        store = SqliteBookStore(path)
        ref = LibraryRef(id="lib-a")
        book = store.get(ref, "b1")
        assert book is not None
        store.save(ref, add_copy(book, copy_id="c1b", status=Status.MANUAL))

        o = q.overview()
        assert o["manual"] == 1
        assert o["auto"] == 1, "the promoted book must leave `auto`"

        rows, _total = q.books(library_id="lib-a")
        assert {r.id: r.status for r in rows}["b1"] == "manual"


def test_books_span_tenants_and_narrow_to_one():
    with _queries() as (q, _):
        rows, total = q.books()
        assert total == 3
        assert {r.library_id for r in rows} == {"lib-a", "lib-b"}

        rows, total = q.books(library_id="lib-b")
        assert total == 1
        assert rows[0].title == "Sapiens"


def test_search_uses_the_products_measured_hebrew_rules():
    """⚠ Not a second, subtly different implementation. P1.5's rules tolerate
    a leading particle in the QUERY, which is why a search for `מנהרה` finds
    the stored `המנהרה` — a plain LIKE on the raw title would not, and
    re-deriving those rules here is how two search behaviours drift apart."""
    with _queries() as (q, _):
        rows, total = q.books(q="מנהרה")
        assert total == 1
        assert rows[0].title == "המנהרה"


def test_search_crosses_tenants():
    with _queries() as (q, _):
        rows, total = q.books(q="Sapiens")
        assert total == 1
        assert rows[0].library_id == "lib-b"


def test_accounts_report_every_membership_they_hold():
    with _queries() as (q, _):
        by_id = {a.id: a for a in q.accounts()}
        assert {(m.library_id, m.role) for m in by_id["acc-1"].memberships} == {
            ("lib-a", "admin"), ("lib-b", "admin")}
        assert [(m.library_id, m.role) for m in by_id["acc-2"].memberships] == [
            ("lib-a", "viewer")]


def test_a_library_row_counts_its_members_and_its_admins():
    with _queries() as (q, _):
        rows = {r.id: r for r in q.libraries()}
        assert (rows["lib-a"].members, rows["lib-a"].admins) == (2, 1)
        assert rows["lib-a"].books == 2
        assert rows["lib-b"].books == 1


def test_a_library_nobody_belongs_to_is_reported_as_an_orphan():
    """`new_library` mints an admin membership in the same call precisely so
    this stays empty. A row here is a library nobody can see or administer,
    and a system console is the only place it is visible at all."""
    with _queries() as (q, path):
        assert q.orphan_libraries() == ()
        SqliteTenancyStore(path).save_library(
            Library(id="lib-lost", label="יתומה", created_at="2026-03-01")
        )
        assert q.orphan_libraries() == ("lib-lost",)


def test_a_shelf_row_counts_distinct_books_not_copies():
    """⚠ Two copies of one book on one shelf is ONE book standing there, and
    the shelf screen's question is "what is on it"."""
    with _queries() as (q, path):
        from app.adapters.sqlite_store import SqliteShelfStore
        from app.domain.shelf import Shelf

        store = SqliteBookStore(path)
        ref = LibraryRef(id="lib-a")
        SqliteShelfStore(path).save_shelf(
            ref, Shelf(id="sh-1", library_id="lib-a", label="מדף",
                       created_at="2026-03-01"))
        book = store.get(ref, "b1")
        assert book is not None
        book = add_copy(book, copy_id="c1b", shelf_id="sh-1", depth=1,
                        status=Status.MANUAL)
        book = add_copy(book, copy_id="c1c", shelf_id="sh-1", depth=1,
                        status=Status.MANUAL)
        store.save(ref, book)

        shelves = {s.id: s for s in q.shelves("lib-a")}
        assert shelves["sh-1"].books == 1, "two copies of one book is one book"


def test_reading_never_migrates_the_owners_database():
    """⚠⚠ The rule the whole service is shaped around. CLAUDE.md records that
    merely importing `app.main` advances the real database's schema; a console
    that opened the file the usual way would upgrade the owner's data as a
    side effect of being LOOKED at. Every question this service answers must
    leave `user_version` exactly where it found it."""
    with _queries() as (q, path):
        before = _user_version(path)

        q.overview()
        q.libraries()
        q.accounts()
        q.books(q="מנהרה")
        q.shelves("lib-a")
        q.recent_reads()

        assert _user_version(path) == before


def test_a_write_through_this_service_is_refused_by_the_connection():
    """`PRAGMA query_only` makes read-only a property of the CONNECTION, not
    of everyone's good intentions — belt to the braces of "every statement in
    that module is a SELECT"."""
    with _db() as path:
        with _open(path) as conn:
            try:
                conn.execute("DELETE FROM books")
            except sqlite3.OperationalError:
                pass
            else:
                raise AssertionError("a write was NOT refused")


def test_a_moved_schema_is_refused_loudly_at_startup():
    """The cost of duplicating schema knowledge, paid up front. A missing
    column must be a refusal to serve, never a plausible wrong number on a
    dashboard nobody double-checks."""
    with _db() as path:
        other = path.parent / "empty.db"
        conn = sqlite3.connect(other)
        try:
            migrate(conn)
            conn.execute("DROP TABLE memberships")
            conn.commit()
        finally:
            conn.close()

        try:
            StaffQueries(other)
        except SchemaMismatch as exc:
            assert "memberships" in str(exc)
        else:
            raise AssertionError("a moved schema was accepted")


# --- the credential --------------------------------------------------------
#
# ⚠ `/api/v1` has no authentication, deliberately, and that trade does NOT
# carry over: a route returning every account and every household's books is a
# different exposure from one returning your own.

def test_without_a_token_configured_it_serves_and_says_so():
    """Refusing to start would leave the owner with a console that cannot be
    opened and no obvious reason. Serving while REPORTING the exposure is the
    same posture the product takes about its own missing login."""
    with _client(None) as client:
        res = client.get("/api/staff/v1/overview")
        assert res.status_code == 200
        assert res.json()["authenticated"] is False


def test_with_a_token_configured_every_route_refuses_without_it():
    with _client("s3cret") as client:
        for path in ("/api/staff/v1/overview", "/api/staff/v1/libraries",
                     "/api/staff/v1/accounts", "/api/staff/v1/books",
                     "/api/staff/v1/reads"):
            assert client.get(path).status_code == 401, path


def test_the_token_is_accepted_in_either_transport():
    with _client("s3cret") as client:
        assert client.get("/api/staff/v1/overview",
                          headers={"X-Booksnap-Staff": "s3cret"}).status_code == 200
        assert client.get("/api/staff/v1/overview",
                          headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_a_wrong_token_is_refused():
    with _client("s3cret") as client:
        res = client.get("/api/staff/v1/overview",
                         headers={"X-Booksnap-Staff": "s3cre"})
        assert res.status_code == 401


def test_the_overview_reports_that_it_is_authenticated():
    with _client("s3cret") as client:
        res = client.get("/api/staff/v1/overview",
                         headers={"X-Booksnap-Staff": "s3cret"})
        assert res.json()["authenticated"] is True


# --- the routes ------------------------------------------------------------

def test_books_page_across_tenants():
    with _client(None) as client:
        body = client.get("/api/staff/v1/books", params={"limit": 2}).json()
        assert body["total"] == 3
        assert len(body["items"]) == 2
        assert body["truncated"] is False


def test_an_unknown_status_is_a_400_not_an_empty_page():
    """An empty page and a rejected filter look identical on screen, and only
    one of them is the caller's mistake."""
    with _client(None) as client:
        assert client.get("/api/staff/v1/books",
                          params={"status": "nope"}).status_code == 400


def test_every_route_is_under_the_staff_prefix():
    """A meta-test, like the product's own: the staff surface must never leak
    a route into a path a proxy or a reader would mistake for the product
    API."""
    with _db() as path:
        app = create_app(StaffQueries(path))
        paths = [str(r.path) for r in app.routes if str(r.path).startswith("/api")]
        assert paths
        for p in paths:
            assert p.startswith("/api/staff/v1/"), p


if __name__ == "__main__":
    import sys as _sys

    failed = 0
    for name, fn in sorted(vars().copy().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"FAIL {name}: {exc}")
    print(f"{failed} failed")
    _sys.exit(0)
