# -*- coding: utf-8 -*-
"""The system-admin service: the cross-tenant read model and its credential.

⚠ **Why this lives in `tests_staff/` and not `tests/`.** `tests/run_all.py`
globs `test_*.py` out of `tests/`, so dropping a file there changes what a
concurrent session's test run executes. This build was made under a hard
"touch no existing file" constraint while exactly such a session was in
progress. Moving it is a one-line rename once that lands — the suite itself is
written to be moved, importing nothing from this directory.

What is worth testing here, and what is not: the read model duplicates SCHEMA
knowledge on purpose (see `app/staff_api/queries.py`), so the tests that earn
their place are the ones that would catch that duplication going stale, plus
the two rules a system console must not get wrong — the §5.1 status ladder,
and the credential.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
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
from app.staff_api.queries import SchemaMismatch, StaffQueries  # noqa: E402


def _fixture(path: Path) -> None:
    """Two libraries, one account, a handful of books — through the REAL
    stores.

    ⚠ Written with the product's own write path rather than raw INSERTs. The
    read model's whole risk is disagreeing with how the product actually
    stores things; a fixture built with hand-written SQL would encode the
    same assumption twice and agree with itself.
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


class StaffReadModelTest(unittest.TestCase):

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "product.db"
        _fixture(self.path)
        self.q = StaffQueries(self.path)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_the_overview_counts_every_tenant_not_just_one(self):
        """The whole reason this service exists. `/api/v1` cannot answer it:
        its resolver narrows to the caller's memberships by design."""
        o = self.q.overview()
        self.assertEqual(o["libraries"], 2)
        self.assertEqual(o["accounts"], 2)
        self.assertEqual(o["books"], 3)
        self.assertEqual(o["memberships"], 3)

    def test_status_is_derived_by_the_5_1_ladder_not_read_off_a_column(self):
        """⚠ A book's status is the STRONGEST claim among its copies, and
        `manual` outranks `approved`. Adding a manual copy to an auto book
        must make the book manual — if this read model ever counted the first
        copy, or a stored column, the dashboard would report a book the owner
        typed as "awaiting approval"."""
        store = SqliteBookStore(self.path)
        ref = LibraryRef(id="lib-a")
        book = store.get(ref, "b1")
        assert book is not None
        store.save(ref, add_copy(book, copy_id="c1b", status=Status.MANUAL))

        o = self.q.overview()
        self.assertEqual(o["manual"], 1)
        self.assertEqual(o["auto"], 1, "the promoted book must leave `auto`")

        rows, _ = self.q.books(library_id="lib-a")
        self.assertEqual({r.id: r.status for r in rows}["b1"], "manual")

    def test_books_span_tenants_and_narrow_to_one(self):
        rows, total = self.q.books()
        self.assertEqual(total, 3)
        self.assertEqual({r.library_id for r in rows}, {"lib-a", "lib-b"})

        rows, total = self.q.books(library_id="lib-b")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0].title, "Sapiens")

    def test_search_uses_the_products_measured_hebrew_rules(self):
        """⚠ Not a second, subtly different implementation. P1.5's rules
        tolerate a leading particle in the QUERY, which is why a search for
        `מנהרה` finds the stored `המנהרה` — a plain LIKE on the raw title
        would not, and re-deriving those rules here is how two search
        behaviours drift apart."""
        rows, total = self.q.books(q="מנהרה")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0].title, "המנהרה")

    def test_search_crosses_tenants(self):
        rows, total = self.q.books(q="Sapiens")
        self.assertEqual(total, 1)
        self.assertEqual(rows[0].library_id, "lib-b")

    def test_accounts_report_every_membership_they_hold(self):
        by_id = {a.id: a for a in self.q.accounts()}
        self.assertEqual(
            {(m.library_id, m.role) for m in by_id["acc-1"].memberships},
            {("lib-a", "admin"), ("lib-b", "admin")},
        )
        self.assertEqual(
            [(m.library_id, m.role) for m in by_id["acc-2"].memberships],
            [("lib-a", "viewer")],
        )

    def test_a_library_row_counts_its_members_and_its_admins(self):
        rows = {r.id: r for r in self.q.libraries()}
        self.assertEqual((rows["lib-a"].members, rows["lib-a"].admins), (2, 1))
        self.assertEqual(rows["lib-a"].books, 2)
        self.assertEqual(rows["lib-b"].books, 1)

    def test_a_library_nobody_belongs_to_is_reported_as_an_orphan(self):
        """`new_library` mints an admin membership in the same call precisely
        so this stays empty. A row here is a library nobody can see or
        administer, and a system console is the only place it is visible at
        all."""
        self.assertEqual(self.q.orphan_libraries(), ())
        SqliteTenancyStore(self.path).save_library(
            Library(id="lib-lost", label="יתומה", created_at="2026-03-01")
        )
        self.assertEqual(self.q.orphan_libraries(), ("lib-lost",))

    def _user_version(self, path: Path) -> int:
        """⚠ `with sqlite3.connect(...)` is a TRANSACTION context manager, not
        a closing one — it commits and leaves the handle open. On Windows that
        is not a style nit: the open handle makes the temporary directory
        undeletable and the test errors in teardown, several tests away from
        the line that caused it."""
        conn = sqlite3.connect(path)
        try:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])
        finally:
            conn.close()

    def test_reading_never_migrates_the_owners_database(self):
        """⚠⚠ The rule the whole service is shaped around. CLAUDE.md records
        that merely importing `app.main` advances the real database's schema;
        a console that opened the file the usual way would upgrade the owner's
        data as a side effect of being LOOKED at. Every question this service
        answers must leave `user_version` exactly where it found it."""
        before = self._user_version(self.path)

        self.q.overview()
        self.q.libraries()
        self.q.accounts()
        self.q.books(q="מנהרה")
        self.q.recent_reads()

        self.assertEqual(before, self._user_version(self.path))

    def test_a_write_through_this_service_is_refused_by_the_connection(self):
        """`PRAGMA query_only` makes read-only a property of the CONNECTION,
        not of everyone's good intentions. Belt to the braces of "every
        statement here is a SELECT"."""
        from app.staff_api.queries import _open
        with _open(self.path) as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM books")

    def test_a_moved_schema_is_refused_loudly_at_startup(self):
        """The cost of duplicating schema knowledge, paid up front. A missing
        column must be a refusal to serve, never a plausible wrong number on a
        dashboard nobody double-checks."""
        other = Path(self._dir.name) / "empty.db"
        conn = sqlite3.connect(other)
        try:
            migrate(conn)
            conn.execute("DROP TABLE memberships")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(SchemaMismatch) as caught:
            StaffQueries(other)
        self.assertIn("memberships", str(caught.exception))


class StaffCredentialTest(unittest.TestCase):
    """⚠ `/api/v1` has no authentication, deliberately, and that trade does
    NOT carry over: a route returning every account and every household's
    books is a different exposure from one returning your own."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "product.db"
        _fixture(self.path)
        self._saved = os.environ.get(STAFF_TOKEN_ENV)

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(STAFF_TOKEN_ENV, None)
        else:
            os.environ[STAFF_TOKEN_ENV] = self._saved
        self._dir.cleanup()

    def _client(self, token: str | None) -> TestClient:
        if token is None:
            os.environ.pop(STAFF_TOKEN_ENV, None)
        else:
            os.environ[STAFF_TOKEN_ENV] = token
        # The app reads the variable when it is BUILT, so each case builds its
        # own — which is also what stops one test's token leaking into another.
        return TestClient(create_app(StaffQueries(self.path)))

    def test_without_a_token_configured_it_serves_and_says_so(self):
        """Refusing to start would leave the owner with a console that cannot
        be opened and no obvious reason. Serving while REPORTING the exposure
        is the same posture the product takes about its own missing login."""
        res = self._client(None).get("/api/staff/v1/overview")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["authenticated"])

    def test_with_a_token_configured_every_route_refuses_without_it(self):
        client = self._client("s3cret")
        for path in ("/api/staff/v1/overview", "/api/staff/v1/libraries",
                     "/api/staff/v1/accounts", "/api/staff/v1/books",
                     "/api/staff/v1/reads"):
            self.assertEqual(client.get(path).status_code, 401, path)

    def test_the_token_is_accepted_in_either_transport(self):
        client = self._client("s3cret")
        self.assertEqual(
            client.get("/api/staff/v1/overview",
                       headers={"X-Booksnap-Staff": "s3cret"}).status_code, 200)
        self.assertEqual(
            client.get("/api/staff/v1/overview",
                       headers={"Authorization": "Bearer s3cret"}).status_code, 200)

    def test_a_wrong_token_is_refused(self):
        client = self._client("s3cret")
        res = client.get("/api/staff/v1/overview",
                         headers={"X-Booksnap-Staff": "s3cre"})
        self.assertEqual(res.status_code, 401)

    def test_the_overview_reports_that_it_is_authenticated(self):
        res = self._client("s3cret").get(
            "/api/staff/v1/overview", headers={"X-Booksnap-Staff": "s3cret"})
        self.assertTrue(res.json()["authenticated"])


class StaffRoutesTest(unittest.TestCase):

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "product.db"
        _fixture(self.path)
        os.environ.pop(STAFF_TOKEN_ENV, None)
        self.client = TestClient(create_app(StaffQueries(self.path)))

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_books_page_across_tenants(self):
        res = self.client.get("/api/staff/v1/books", params={"limit": 2})
        body = res.json()
        self.assertEqual(body["total"], 3)
        self.assertEqual(len(body["items"]), 2)
        self.assertFalse(body["truncated"])

    def test_an_unknown_status_is_a_400_not_an_empty_page(self):
        """An empty page and a rejected filter look identical on screen, and
        only one of them is the caller's mistake."""
        res = self.client.get("/api/staff/v1/books", params={"status": "nope"})
        self.assertEqual(res.status_code, 400)

    def test_every_route_is_under_the_staff_prefix(self):
        """A meta-test, like the product's own: the staff surface must never
        leak a route into a path a proxy or a reader would mistake for the
        product API."""
        app = create_app(StaffQueries(self.path))
        paths = [r.path for r in app.routes if str(r.path).startswith("/api")]
        self.assertTrue(paths)
        for path in paths:
            self.assertTrue(path.startswith("/api/staff/v1/"), path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
