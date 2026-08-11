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
import re
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
from app.domain.text import book_key  # noqa: E402
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


# --- works: books, aggregated across every tenant ---------------------------
#
# Revision 4 of the console plan: an operator's question about a book is "how
# widespread is it", never "whose is it". These pin the two rules that makes
# possible — one row per `book_key` across tenants, and a filter that selects
# works without changing what one reports.

def _also_in_lib_b(path: Path, *, title: str, author: str = "ארנסטו סבאטו",
                   status: Status = Status.AUTO, added_at: str = "2026-05-01",
                   book_id: str = "b1b", copy_id: str = "c1b") -> None:
    """The same WORK in the second library, optionally spelled differently.

    Written through the real store like `_seed`, so the `norm_title` /
    `norm_author` the aggregate keys on are the ones the product's own write
    path produces — not two hand-typed strings that agree with each other.
    """
    SqliteBookStore(path).save(
        LibraryRef(id="lib-b"),
        new_book(id=book_id, library_id="lib-b", copy_id=copy_id, title=title,
                 author=author, status=status, added_at=added_at),
    )


def test_a_work_is_one_row_across_tenants_not_one_per_library():
    """The whole frame change. Three books in two libraries where two of them
    are the same title is THREE works, and the shared one says so."""
    with _queries() as (q, path):
        _also_in_lib_b(path, title="המנהרה")
        rows, total = q.works()
        assert total == 3, "four books, three distinct works"
        shared = {r.title: r for r in rows}["המנהרה"]
        assert (shared.libraries, shared.instances, shared.copies) == (2, 2, 2)


def test_the_display_title_is_the_strongest_claim_then_the_earliest():
    """⚠ Two households may hold one work under two spellings that normalize
    alike — that is what the key is FOR — so one has to be shown, and the
    choice must be a rule rather than whatever SQLite returned first. A human
    typing a title (`manual`) outranks the engine's reading (`auto`), even
    though this one was added three months later."""
    with _queries() as (q, path):
        _also_in_lib_b(path, title="המנהרה!", status=Status.MANUAL,
                       added_at="2026-05-01")
        rows, _ = q.works()
        by_key = {r.key: r for r in rows}
        work = by_key[book_key("המנהרה", "ארנסטו סבאטו")]
        assert work.title == "המנהרה!", "the manual spelling wins"
        assert work.first_added == "2026-02-01", "…but 'first found' is honest"
        assert work.last_added == "2026-05-01"


def test_a_filter_selects_works_but_never_changes_what_one_reports():
    """⚠⚠ The reason every narrowing is a HAVING and not a WHERE. Narrowing to
    one library must not make "in 2 libraries" read "in 1": a number that
    changes meaning when you filter is a number nobody can trust, and it is
    this screen's central column."""
    with _queries() as (q, path):
        _also_in_lib_b(path, title="המנהרה")
        rows, total = q.works(library_id="lib-b")
        assert total == 2, "lib-b holds two of the three works"
        shared = {r.title: r for r in rows}["המנהרה"]
        assert shared.libraries == 2, "still held by two households"
        assert shared.copies == 2


def test_a_status_filter_matches_a_work_with_any_instance_at_that_status():
    """"Anything unapproved out there?" must find a work that one household
    has approved and another has not."""
    with _queries() as (q, path):
        # b2 is APPROVED in lib-a; the same work arrives AUTO in lib-b.
        _also_in_lib_b(path, title="אבק כוכבים", author="אסימוב, אייזיק",
                       status=Status.AUTO, book_id="b2b", copy_id="c2b")
        rows, _ = q.works(status="auto")
        titles = {r.title for r in rows}
        assert "אבק כוכבים" in titles
        work = {r.title: r for r in rows}["אבק כוכבים"]
        assert work.status == "approved", "the badge shows the strongest claim"
        assert work.mixed is True, "…and says the households disagree"


def test_a_work_is_found_by_any_households_spelling():
    """The search matches an INSTANCE's stored text, not the display row's:
    otherwise a book would be unfindable because another tenant's copy won the
    tiebreak for which spelling to show."""
    with _queries() as (q, path):
        _also_in_lib_b(path, title="המנהרה", status=Status.MANUAL,
                       added_at="2020-01-01")
        rows, total = q.works(q="מנהרה")
        assert total == 1 and rows[0].libraries == 2


def test_work_instances_name_the_households_strongest_first():
    with _queries() as (q, path):
        _also_in_lib_b(path, title="המנהרה", status=Status.MANUAL)
        instances = q.work_instances(book_key("המנהרה", "ארנסטו סבאטו"))
        assert [(i.library_id, i.status) for i in instances] == [
            ("lib-b", "manual"), ("lib-a", "auto")]


def test_an_unknown_work_key_is_an_empty_list_not_an_error():
    """A console asking about a work that has just been deleted elsewhere gets
    "nobody holds it", which is the true answer."""
    with _queries() as (q, _):
        assert q.work_instances("no|such") == ()


# --- images: the photograph is the entity ----------------------------------
#
# Revision 4 again: a shelf today is an identity minted per photograph
# (VISION §4.1a's recorded placeholder), so a console shelf list was a
# photograph list under the wrong noun. These pin what the image row actually
# reports — and the one thing this service must NEVER do, which is serve the
# bytes.

def _photograph(path: Path, *, capture_id: str = "cap-1",
                shelf_id: str = "sh-1", library_id: str = "lib-a",
                depth: int = 1, order: int = 0,
                image_key: str | None = None) -> None:
    """A shelf, and a capture filed on it — through the real stores."""
    from app.adapters.sqlite_store import SqliteShelfStore
    from app.domain.shelf import Capture, Shelf

    ref = LibraryRef(id=library_id)
    shelves = SqliteShelfStore(path)
    if shelves.get_shelf(ref, shelf_id) is None:
        shelves.save_shelf(ref, Shelf(id=shelf_id, library_id=library_id,
                                      label="מדף", created_at="2026-03-01"))
    shelves.save_capture(ref, Capture(
        id=capture_id, library_id=library_id, shelf_id=shelf_id, depth=depth,
        order=order, image_id=image_key, captured_at="2026-03-02T10:00:00Z"))


def _a_read_over(path: Path, *, capture_ids: list[str],
                 claims: list[tuple[str, str]], library_id: str = "lib-a",
                 shelf_id: str = "sh-1", read_id: str = "read-1") -> None:
    """One engine pass over those captures, with those (tier, capture) claims."""
    from app.adapters.sqlite_store import SqliteReadStore
    from app.domain.read import Claim, ClaimTier, Read, ReadStatus

    SqliteReadStore(path).save_read(LibraryRef(id=library_id), Read(
        id=read_id, library_id=library_id, shelf_id=shelf_id, depth=1,
        capture_ids=tuple(capture_ids), mode="llmpage",
        status=ReadStatus.DONE, started_at="2026-03-03T09:00:00Z",
        finished_at="2026-03-03T09:01:00Z",
        claims=tuple(
            Claim(id=f"{read_id}-{i}", spine_id=f"sp-{i}", capture_id=cap,
                  title="כותרת", tier=ClaimTier(tier))
            for i, (tier, cap) in enumerate(claims)
        ),
    ))


def _a_real_jpeg(size: tuple[int, int] = (40, 30)) -> bytes:
    """⚠ Synthetic, and it is enough HERE — this test is about the LAYOUT the
    store writes to, not about decoding a phone's MPO (the lesson `test_api.py`
    records). The store's own suite owns the real-input case."""
    import io as _io

    from PIL import Image

    out = _io.BytesIO()
    Image.new("RGB", size, (30, 90, 200)).save(out, format="JPEG")
    return out.getvalue()


def test_an_image_reports_its_binding_rather_than_being_named_by_it():
    """The row leads with the photograph; the shelf and depth are the SLOT it
    is filed at — the pair pillar 6 replaces with a real address."""
    with _queries() as (q, path):
        _photograph(path)
        rows, total = q.images()
        assert total == 1
        image = rows[0]
        assert (image.id, image.shelf_id, image.depth) == ("cap-1", "sh-1", 1)
        assert image.shelf_label == "מדף"


def test_an_image_with_no_bytes_on_disk_says_so_rather_than_showing_blank():
    """⚠ A capture whose blob is gone is a photograph the household can no
    longer see. It is a finding, not a rounding error, and the console is the
    only place anyone would notice — so `present` is false and the row still
    renders."""
    with _queries() as (q, path):
        _photograph(path, image_key="0" * 64 + ".jpg")
        rows, _ = q.images()
        assert rows[0].present is False and rows[0].bytes == 0


def test_a_run_that_found_nothing_in_an_image_still_counts_as_a_run():
    """⚠ `reads` comes from `reads.capture_ids` (what a run CONSUMED) while the
    tier figures come from `claims.capture_id` (what it FOUND). Deriving the
    run count from the claims would hide the case an operator is hunting: a
    photograph the engine read and got nothing from."""
    with _queries() as (q, path):
        _photograph(path)
        _a_read_over(path, capture_ids=["cap-1"], claims=[])
        rows, _ = q.images()
        assert (rows[0].reads, rows[0].findings) == (1, 0)


def test_an_images_findings_are_broken_down_by_tier():
    with _queries() as (q, path):
        _photograph(path)
        _a_read_over(path, capture_ids=["cap-1"],
                     claims=[("auto", "cap-1"), ("review", "cap-1"),
                             ("unmatched", "cap-1")])
        rows, _ = q.images()
        image = rows[0]
        assert (image.findings, image.auto, image.review, image.unmatched) == (
            3, 1, 1, 1)


def test_images_narrow_to_one_library_and_otherwise_span_every_tenant():
    with _queries() as (q, path):
        _photograph(path, capture_id="cap-a", shelf_id="sh-a",
                    library_id="lib-a")
        _photograph(path, capture_id="cap-b", shelf_id="sh-b",
                    library_id="lib-b")
        _, total = q.images()
        assert total == 2
        rows, total = q.images(library_id="lib-b")
        assert total == 1 and rows[0].id == "cap-b"


def test_the_staff_service_never_serves_image_bytes():
    """⚠⚠ Metadata crosses tenants; photographs do not.

    An operator looking at a household's actual pictures is a larger power than
    counting them, and this service has no login, no audit trail and nobody to
    explain it to. The console renders a thumbnail only for a library the
    operator is a MEMBER of, through the product API — the same read/write
    asymmetry, one axis over. Structural, because "we just didn't add that
    route" is not a guarantee.
    """
    source = (REPO_ROOT / "app" / "staff_api" / "app.py").read_text("utf-8")
    for way_to_send_bytes in ("FileResponse", "StreamingResponse",
                              "PlainTextResponse", "Response("):
        assert way_to_send_bytes not in source, way_to_send_bytes

    with _db() as path:
        app = create_app(StaffQueries(path))
        served = [r for r in app.routes if str(r.path).startswith("/api/")]
        assert served
        for route in served:
            # Every route answers with a declared pydantic model, i.e. JSON.
            # A byte-serving route is exactly the one that would not.
            assert getattr(route, "response_model", None) is not None, route.path


# --- storage: the bytes are on disk, not in the database ---------------------

def test_storage_agrees_with_the_store_that_wrote_the_blob():
    """⚠⚠ The layout-drift guard.

    `app/staff_api/storage.py` knows the blob layout on purpose — it may not
    import `DiskBlobStore` (`tests/test_layering.py` keeps this service free of
    `app.adapters`, which is the recorded reason its composition root is not in
    `COMPOSITION_ROOTS`). So the two are checked against each OTHER here: the
    real store writes a real image, and the staff reader must find it, with the
    same size and the same digest. A layout change fails this test instead of
    quietly reporting 0 MB.
    """
    from app.adapters.disk_blobs import DiskBlobStore
    from app.staff_api.storage import BlobTree

    tmp = tempfile.mkdtemp(prefix="booksnap-blobs-")
    try:
        store = DiskBlobStore(tmp)
        ref = LibraryRef(id="lib-a")
        blob = store.put(ref, _a_real_jpeg(), filename="shelf.jpg")

        tree = BlobTree(tmp)
        facts = tree.facts("lib-a", blob.key)
        assert facts.present is True
        assert facts.sha256 == blob.sha256
        assert facts.bytes == blob.size
        assert (facts.width, facts.height) == (blob.width, blob.height)

        usage = tree.usage()["lib-a"]
        assert usage.bytes >= blob.size
        assert usage.files >= 2, "the image and its sidecar, at least"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_missing_blob_root_is_zero_storage_not_a_failed_dashboard():
    """The database and the photographs can live on different machines. A
    console that 500'd on a missing directory would be unopenable for a reason
    nobody could guess."""
    from app.staff_api.storage import BlobTree

    assert BlobTree(None).usage() == {}
    assert BlobTree("D:/no/such/blob/root").usage() == {}
    with _queries() as (q, _):
        assert q.overview()["image_bytes"] == 0


def test_a_key_that_is_not_a_content_address_resolves_to_nothing():
    """⚠ The key arrives from a database column, and `../` in a path segment is
    how a reader that just joins strings walks out of the blob root. Validated,
    never trusted — the same rule `DiskBlobStore` states for the same reason."""
    from app.staff_api.storage import BlobTree

    tree = BlobTree("D:/tmp/whatever")
    for bad in ("../../etc/passwd", "..\\..\\secrets.txt", "short.jpg",
                "0" * 64 + ".jp g", "0" * 63 + "z.jpg"):
        assert tree._path("lib-a", bad) is None, bad
    assert tree._path("lib-a", "0" * 64 + ".jpg") is not None


def test_storage_lands_on_the_library_row_and_the_overview():
    from app.adapters.disk_blobs import DiskBlobStore
    from app.staff_api.storage import BlobTree

    tmp = tempfile.mkdtemp(prefix="booksnap-blobs-")
    try:
        blob = DiskBlobStore(tmp).put(LibraryRef(id="lib-a"), _a_real_jpeg())
        with _db() as path:
            q = StaffQueries(path, BlobTree(tmp))
            rows = {r.id: r for r in q.libraries()}
            assert rows["lib-a"].image_bytes >= blob.size
            assert rows["lib-b"].image_bytes == 0, "a tenant with no photos"
            assert q.overview()["image_bytes"] == rows["lib-a"].image_bytes
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
    """⚠ A META-test over `app.routes`, not a hand-written list.

    The list came first, and it had already fallen behind: five paths for six
    routes, with `/libraries/{id}/shelves` missing. Removing that route's
    `dependencies=guard` therefore kept the whole suite green while serving
    every tenant's shelf contents to anyone who could reach port 8758 — found
    by a data-integrity review that executed exactly that mutation.

    The guard is opt-in per route and this service's own docstring says the
    credential IS its whole security model, so the enforcement has to be the
    kind that catches a route nobody remembered to add here. The product API
    closed the same gap the same way
    (`test_every_api_route_declares_exactly_one_policy_capability`): a route
    with no declaration FAILS rather than defaulting to open.
    """
    with _client("s3cret") as client:
        paths = [str(r.path) for r in client.app.routes  # type: ignore[attr-defined]
                 if str(r.path).startswith("/api/staff/v1/")]
        assert len(paths) >= 6, paths
        for path in paths:
            # A path parameter needs something to stand in for it. The refusal
            # must happen in the DEPENDENCY, before any lookup, so a value that
            # matches nothing is exactly right — a 404 here would mean the
            # credential was checked too late to protect the answer.
            concrete = re.sub(r"\{[^}]+\}", "no-such-id", path)
            assert client.get(concrete).status_code == 401, concrete


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


def test_the_works_route_pages_the_aggregate_not_the_books():
    with _client(None) as client:
        body = client.get("/api/staff/v1/works", params={"limit": 2}).json()
        assert body["total"] == 3
        assert len(body["items"]) == 2
        assert "library_id" not in body["items"][0], (
            "a work has no library — that is the entire point of the type")


def test_an_unknown_status_is_a_400_on_works_too():
    with _client(None) as client:
        assert client.get("/api/staff/v1/works",
                          params={"status": "nope"}).status_code == 400


def test_the_work_key_travels_as_a_query_parameter():
    """It is `normalize(title)|normalize(author)` — Hebrew, spaces and a pipe.
    A path segment would put the console one missed `encodeURIComponent` away
    from a 404 nobody can explain."""
    with _client(None) as client:
        key = book_key("Sapiens", "Yuval Harari")
        rows = client.get("/api/staff/v1/works/instances",
                          params={"key": key}).json()
        assert [r["library_id"] for r in rows] == ["lib-b"]


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


def test_a_schema_that_moves_UNDER_a_running_service_answers_503():
    """⚠ `self_check()` runs once, at construction — so on its own it can only
    refuse a database that was already wrong when the service STARTED.

    The way this actually happens is the other one: the product server
    migrates `work/product.db` while the console is up. Until a review pointed
    it out, that surfaced as a raw `OperationalError` — a 500 with a SQL
    fragment in a log nobody is watching — and the 503 this service documents
    was unreachable code.
    """
    # Built from `_db` rather than `_client` because this case needs the PATH
    # as well as the client — it has to move the schema out from under a
    # service that is already up.
    with _db() as path:
        client = TestClient(create_app(StaffQueries(path)))

        # ⚠ `with sqlite3.connect(...)` commits but does NOT close, and on
        # Windows the open handle makes the temp directory undeletable — see
        # `_user_version`'s note, which this test would otherwise repeat as a
        # teardown error several tests away.
        conn = sqlite3.connect(path)
        try:
            conn.execute("ALTER TABLE books RENAME COLUMN title TO name")
            conn.commit()
        finally:
            conn.close()

        res = client.get("/api/staff/v1/books")
        assert res.status_code == 503, res.status_code
        # It must NAME what moved. "Service unavailable" alone leaves the
        # operator guessing between a crash, a lock and a stale console.
        assert "title" in res.json()["detail"]


def test_an_ordinary_sql_error_is_NOT_dressed_up_as_a_schema_problem():
    """The other half of the rule above, and what keeps it honest: the handler
    re-runs the shape check and re-raises untouched when the shape is fine.
    Reporting every `OperationalError` as "the schema moved" would send the
    next person looking for a migration that never happened."""
    original = StaffQueries.books

    def boom(self, *a, **kw):  # noqa: ANN001, ANN002, ANN003
        raise sqlite3.OperationalError("database is locked")

    StaffQueries.books = boom  # type: ignore[assignment]
    try:
        with _client(None) as client:
            try:
                client.get("/api/staff/v1/books")
            except sqlite3.OperationalError as exc:
                assert "locked" in str(exc)
            else:
                raise AssertionError("a genuine SQL error must not become a 503")
    finally:
        StaffQueries.books = original  # type: ignore[assignment]


# --- the shape of the service ----------------------------------------------

def test_exactly_one_place_in_the_service_opens_a_connection():
    """Read-only is enforced in three independent places — the layering ring
    forbids importing a migration, `_open` sets `PRAGMA query_only`, and a
    write is refused at the connection. This is the fourth: that every
    connection actually goes THROUGH `_open`. Without it a new query function
    calling `sqlite3.connect` directly would quietly opt out of the pragma,
    and nothing else would notice."""
    package = REPO_ROOT / "app" / "staff_api"
    opens = [
        f"{p.relative_to(REPO_ROOT).as_posix()}:{i}"
        for p in sorted(package.rglob("*.py")) if "__pycache__" not in p.parts
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if "sqlite3.connect(" in line
    ]
    assert len(opens) == 1, (
        "every connection must go through queries._open, which is what sets "
        f"PRAGMA query_only; found: {opens}"
    )
    assert opens[0].startswith("app/staff_api/queries.py"), opens


def test_a_missing_database_is_refused_rather_than_created():
    """⚠ `sqlite3.connect` CREATES an empty file for a path that does not
    exist. Without this guard a mistyped `BOOKSNAP_DB` would leave a phantom
    `product.db` beside the real one and a console reporting a system with
    nothing in it — which reads as data loss, not as a typo."""
    tmp = tempfile.mkdtemp(prefix="booksnap-staff-missing-")
    try:
        missing = Path(tmp) / "not-here.db"
        try:
            StaffQueries(missing)
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("a missing database must be refused")
        assert not missing.exists(), "it must not be created on the way past"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
