# -*- coding: utf-8 -*-
"""H4 ring 3 — API tests: shapes, status codes, and the two meta-tests.

The meta-tests matter more than the endpoint test. They are structural rules
over *every* route, so they keep holding as routes are added by later items:

  - every API route is under ``/api/v1`` (H3 — no unversioned endpoint ever
    ships, not even by accident during a hurried item);
  - every API route resolves its library through ``deps.current_library``
    (H2 — a route that reaches for "the" library works fine today and has to
    be rewritten at pillar 3; this is what makes that impossible).

Pillar 3 adds a third to this file: every route is policy-checked, and a route
with no policy declaration FAILS rather than defaulting to open.

Built with a stub principal, so nothing here depends on the dev adapter.
"""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import API_PREFIX, __version__
from app.adapters.disk_blobs import DiskBlobStore
from app.adapters.inprocess_jobs import InProcessJobRunner
from app.adapters.memory_store import (
    MemoryBookStore,
    MemoryDecisionStore,
    MemoryDuplicateQueue,
    MemoryReadStore,
    MemoryShelfStore,
)
from app.api import deps
from app.api.app import create_app
from app.domain import LibraryRef, Provenance, Status, new_book
from app.ports.reader import ReadAlternative, ReadClaim

TEST_LIBRARY = LibraryRef(id="lib-test", label="Test library")


class StubClock:
    def now_iso(self) -> str:
        return "2026-08-07T12:00:00+00:00"


class SeqIdGen:
    """Deterministic ids, so a test can name what it just created."""

    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"id-{self._n}"


class StubPrincipal:
    """Implements app.ports.Principal without touching any adapter."""

    def __init__(self, library: LibraryRef = TEST_LIBRARY, pid: str = "p-test"):
        self._library = library
        self._id = pid

    @property
    def id(self) -> str:
        return self._id

    @property
    def library(self) -> LibraryRef:
        return self._library


def _app(principal: StubPrincipal | None = None, store=None, shelves=None,
         blobs=None, reads=None, reader=None, jobs=None, decisions=None,
         duplicates=None):
    p = principal or StubPrincipal()
    return create_app(
        principal_provider=lambda: p,
        book_store=store if store is not None else MemoryBookStore(),
        shelf_store=shelves if shelves is not None else MemoryShelfStore(),
        blob_store=blobs,
        read_store=reads if reads is not None else MemoryReadStore(),
        decision_store=decisions if decisions is not None else MemoryDecisionStore(),
        duplicate_queue=duplicates if duplicates is not None else MemoryDuplicateQueue(),
        reader=reader,
        job_runner=jobs if jobs is not None else InProcessJobRunner(),
        clock=StubClock(),
        id_gen=SeqIdGen(),
    )


@contextmanager
def _blobs():
    """A real DiskBlobStore on a temp dir.

    Not a stub: the whole point of P2.3 is that the bytes survive a round trip
    and come back decodable, and a fake that returns whatever it was handed
    would assert nothing about the part that can actually be wrong.
    """
    tmp = tempfile.mkdtemp(prefix="booksnap-blobs-")
    try:
        yield DiskBlobStore(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _png(size=(40, 30), colour=(200, 30, 30)) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format="PNG")
    return out.getvalue()


def _mpo(size=(60, 40), *, orientation: int | None = None) -> bytes:
    """A GENUINE Multi-Picture Object — what a phone camera actually emits.

    ⚠ This helper exists because `_jpeg()` does not reproduce reality. A modern
    iPhone or Samsung "JPEG" is usually an MPO: a JPEG container carrying a
    second embedded frame (HDR, depth, the second lens). PIL reports
    `format='MPO'`, and the upload validator's format whitelist rejected it —
    so every synthetic test passed while EVERY REAL PHOTO 415'd.

    A real MPO, written by PIL's own MPO encoder, not a stand-in.
    """
    from PIL import Image

    first = Image.new("RGB", size, (200, 40, 40))
    second = Image.new("RGB", size, (40, 40, 200))
    out = io.BytesIO()
    kw = {}
    if orientation is not None:
        exif = first.getexif()
        exif[0x0112] = orientation
        kw["exif"] = exif
    first.save(out, format="MPO", save_all=True, append_images=[second], **kw)
    return out.getvalue()


def _heic_header() -> bytes:
    """Just enough of a HEIC container to be recognised, not decoded.

    The point is the ERROR MESSAGE: HEIC is the iPhone default whenever the
    camera is not on "Most Compatible", so a refusal has to say what to change.
    """
    return b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1" + b"\x00" * 64


def _jpeg(size=(40, 30), *, orientation: int | None = None) -> bytes:
    """A JPEG, optionally carrying an EXIF rotation flag like a phone photo."""
    from PIL import Image

    img = Image.new("RGB", size, (30, 90, 200))
    out = io.BytesIO()
    if orientation is None:
        img.save(out, format="JPEG")
    else:
        exif = img.getexif()
        exif[0x0112] = orientation
        img.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def _seed(store, library: LibraryRef, *titles: str, status=Status.AUTO,
          author: str = "פול קארני"):
    """Ids continue from what is already there, so two _seed calls in one test
    don't overwrite each other — the first book is always b1."""
    base = store.count(library)
    for i, title in enumerate(titles, start=base + 1):
        store.save(library, new_book(
            id=f"b{i}", library_id=library.id, title=title,
            author=author, copy_id=f"c{i}", status=status,
            added_at="2026-01-01T00:00:00+00:00",
        ))


def _api_routes(app) -> list[tuple[str, APIRoute]]:
    """(effective path, route) for every product API route.

    FastAPI >= 0.13x defers ``include_router`` into an ``_IncludedRouter``
    node, so ``app.routes`` is no longer flat and a route's own ``.path`` is
    router-relative (``/meta``, not ``/api/v1/meta``). ``iter_route_contexts``
    is the public flattener; the fallback keeps this suite working on the
    older layout that ``requirements.txt`` still allows.

    Schema/docs endpoints are plain starlette Routes, so filtering on APIRoute
    already excludes them.
    """
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:
        return [(r.path, r) for r in app.routes if isinstance(r, APIRoute)]
    return [(c.path, c.original_route) for c in iter_route_contexts(app.routes)
            if isinstance(c.original_route, APIRoute)]


# --- the endpoint ---------------------------------------------------------

def test_meta_returns_service_and_library():
    with TestClient(_app()) as client:
        r = client.get(f"{API_PREFIX}/meta")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["app"] == "booksnap"
    assert body["version"] == __version__
    assert body["api_version"] == "v1"
    assert body["library"] == {"id": "lib-test", "label": "Test library"}


def test_meta_follows_the_principal_not_a_global():
    """Two apps, two principals, no leakage — the shape §1.3 requires before a
    second tenant exists."""
    other = StubPrincipal(LibraryRef(id="lib-other", label="Other"), pid="p-2")
    with TestClient(_app()) as c1, TestClient(_app(other)) as c2:
        a = c1.get(f"{API_PREFIX}/meta").json()
        b = c2.get(f"{API_PREFIX}/meta").json()
    assert a["library"]["id"] == "lib-test"
    assert b["library"]["id"] == "lib-other"


# --- books: the P1.4 surface ---------------------------------------------

def test_a_write_through_the_api_reaches_the_real_store():
    """The bug this exists for: binding a port with ``lambda v=value: v`` gives
    the provider a defaulted PARAMETER, FastAPI treats it as a field to
    resolve, and pydantic DEEP-COPIES mutable defaults. Every endpoint then
    gets a copy of the store — reads look perfect and writes vanish. Nothing
    else in this file catches it, because every other assertion reads back
    through the same request-scoped copy.
    """
    store = MemoryBookStore()
    with TestClient(_app(store=store)) as client:
        created = client.post(f"{API_PREFIX}/books",
                              json={"title": "ספר", "author": "מחבר"}).json()
    assert store.get(TEST_LIBRARY, created["id"]) is not None, \
        "the API served a copy of the store; the write was discarded"


def test_lists_books_with_paging_and_a_total():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "גדר", "אבן", "בית")
    with TestClient(_app(store=store)) as client:
        body = client.get(f"{API_PREFIX}/books?limit=2").json()
    assert [b["title"] for b in body["items"]] == ["אבן", "בית"]
    assert body["total"] == 3 and body["limit"] == 2 and body["offset"] == 0


def test_list_rejects_an_unbounded_limit():
    """A client asking for everything must not be able to page the server out
    of memory by accident."""
    with TestClient(_app()) as client:
        assert client.get(f"{API_PREFIX}/books?limit=100000").status_code == 422


def test_list_filters_by_status():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    _seed(store, TEST_LIBRARY, "בית", status=Status.MANUAL)
    with TestClient(_app(store=store)) as client:
        assert [b["title"] for b in
                client.get(f"{API_PREFIX}/books?status=auto").json()["items"]] \
            == ["אבן"]
        assert [b["title"] for b in
                client.get(f"{API_PREFIX}/books?status=manual").json()["items"]] \
            == ["בית"]


def test_list_filters_by_author_key():
    """The author chip is a grouping over NORMALIZED strings (§5.1), so the
    key round-trips: a book's ``author_key`` is what you filter with, and a
    differently-spelled-but-equal name comes back with it."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן", "בית", author="ג'ראלד דארל")
    _seed(store, TEST_LIBRARY, "גדר", author="אסימוב")
    with TestClient(_app(store=store)) as client:
        key = client.get(f"{API_PREFIX}/books/b1").json()["author_key"]
        page = client.get(f"{API_PREFIX}/books", params={"author_key": key}).json()
    assert [b["title"] for b in page["items"]] == ["אבן", "בית"]
    assert page["total"] == 2


def test_search_ranks_by_relevance_and_ignores_the_sort_control():
    """Relevance IS the order when searching, so a `sort` arriving alongside
    `q` is ignored rather than rejected — a UI that keeps a sort control on
    screen while the user types must not start returning 400s mid-keystroke."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "מהעיר הדוממת", "עיר", "עיר הזמן")
    with TestClient(_app(store=store)) as client:
        body = client.get(f"{API_PREFIX}/books",
                          params={"q": "עיר", "sort": "title"}).json()
    assert body["items"][0]["title"] == "עיר", [b["title"] for b in body["items"]]
    assert body["total"] == 3


def test_an_empty_q_falls_back_to_listing_rather_than_returning_nothing():
    """A cleared search box shows the library again; it does not show zero
    books because `q=` was still on the URL."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן", "בית")
    with TestClient(_app(store=store)) as client:
        assert client.get(f"{API_PREFIX}/books", params={"q": ""}).json()["total"] == 2
        assert client.get(f"{API_PREFIX}/books", params={"q": "  "}).json()["total"] == 2
        assert client.get(f"{API_PREFIX}/books", params={"q": "זזז"}).json()["total"] == 0


def test_get_returns_the_book_with_its_copies():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        body = client.get(f"{API_PREFIX}/books/b1").json()
    assert body["copy_count"] == 1 and len(body["copies"]) == 1
    assert body["copies"][0]["shelf_id"] is None  # §1.1, until the map


def test_patch_marks_the_book_manual_and_persists():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        body = client.patch(f"{API_PREFIX}/books/b1",
                            json={"title": "אבן מתוקנת"}).json()
    assert body["title"] == "אבן מתוקנת"
    assert body["status"] == "manual", "an edit did not outrank the auto claim"
    assert store.get(TEST_LIBRARY, "b1").title == "אבן מתוקנת"


def test_patch_with_no_fields_is_a_400_not_a_silent_no_op():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        assert client.patch(f"{API_PREFIX}/books/b1", json={}).status_code == 400


def test_renaming_onto_a_book_you_already_own_is_a_409():
    """A real case — fixing a misread title to one you own. Resolving it is a
    decision (merge? keep both?), so the API refuses rather than defaulting."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן", "בית")
    with TestClient(_app(store=store)) as client:
        r = client.patch(f"{API_PREFIX}/books/b2", json={"title": "אבן"})
    assert r.status_code == 409
    assert store.get(TEST_LIBRARY, "b2").title == "בית", "the refused edit stuck"


def test_manual_add_lands_as_manual_with_one_copy():
    with TestClient(_app()) as client:
        r = client.post(f"{API_PREFIX}/books",
                        json={"title": "  ספר ידני  ", "author": " מחבר "})
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "ספר ידני", "whitespace was not trimmed"
    assert body["status"] == "manual" and body["copy_count"] == 1
    assert body["added_at"] == "2026-08-07T12:00:00+00:00"


def test_manual_add_of_a_book_you_own_is_a_409():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        r = client.post(f"{API_PREFIX}/books",
                        json={"title": "אבן", "author": "פול קארני"})
    assert r.status_code == 409


def test_delete_removes_from_the_library_and_is_not_idempotent_about_it():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        assert client.delete(f"{API_PREFIX}/books/b1").status_code == 204
        assert client.delete(f"{API_PREFIX}/books/b1").status_code == 404
    assert store.count(TEST_LIBRARY) == 0


# --- copies (P1.7) ---------------------------------------------------------

def test_add_copy_creates_a_second_manual_copy():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        r = client.post(f"{API_PREFIX}/books/b1/copies",
                        json={"label": "כריכה רכה", "tags": [" מתנה ", ""],
                             "condition": " טוב "})
    assert r.status_code == 201
    body = r.json()
    assert body["copy_count"] == 2
    new = next(c for c in body["copies"] if c["label"] == "כריכה רכה")
    assert new["status"] == "manual"
    assert new["tags"] == ["מתנה"], "blank tags should be dropped, others trimmed"
    assert new["condition"] == "טוב"
    original = next(c for c in body["copies"] if c["id"] != new["id"])
    assert original["status"] == "auto", "the original copy must be untouched"


def test_patch_copy_edits_metadata_without_touching_status():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        r = client.patch(f"{API_PREFIX}/books/b1/copies/c1",
                         json={"condition": "קרוע"})
    assert r.status_code == 200
    copy = r.json()["copies"][0]
    assert copy["condition"] == "קרוע"
    assert copy["status"] == "auto", "metadata edit must not mark it manual"


def test_lend_then_return_a_copy():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        lent = client.post(f"{API_PREFIX}/books/b1/copies/c1/lend",
                           json={"lent_to": "דנה", "due_at": "2026-09-01"})
        assert lent.status_code == 200
        lending = lent.json()["copies"][0]["lending"]
        assert lending == {"lent_to": "דנה", "lent_at": "2026-08-07T12:00:00+00:00",
                           "due_at": "2026-09-01", "returned_at": None,
                           "is_out": True}

        returned = client.post(f"{API_PREFIX}/books/b1/copies/c1/return")
    assert returned.status_code == 200
    lending = returned.json()["copies"][0]["lending"]
    assert lending["is_out"] is False
    assert lending["returned_at"] == "2026-08-07T12:00:00+00:00"
    assert lending["lent_to"] == "דנה", "the loan history must not be cleared"


def test_lending_an_already_out_copy_is_a_409_naming_the_borrower():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        client.post(f"{API_PREFIX}/books/b1/copies/c1/lend",
                    json={"lent_to": "דנה"})
        r = client.post(f"{API_PREFIX}/books/b1/copies/c1/lend",
                        json={"lent_to": "יוסי"})
    assert r.status_code == 409
    assert "דנה" in r.json()["detail"]


def test_returning_a_copy_that_was_never_lent_is_a_409():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        r = client.post(f"{API_PREFIX}/books/b1/copies/c1/return")
    assert r.status_code == 409


def test_a_copy_action_on_an_unknown_copy_id_is_404():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        assert client.patch(f"{API_PREFIX}/books/b1/copies/nope",
                            json={"condition": "x"}).status_code == 404
        assert client.post(f"{API_PREFIX}/books/b1/copies/nope/lend",
                           json={"lent_to": "דנה"}).status_code == 404
        assert client.post(
            f"{API_PREFIX}/books/b1/copies/nope/return").status_code == 404


def test_a_copy_action_on_a_book_in_another_library_is_404():
    """§4.2, same as every other book route: foreign reads as absent."""
    other = LibraryRef("lib-other", "Other")
    store = MemoryBookStore()
    store.save(other, new_book(id="b9", library_id=other.id, title="סוד",
                               copy_id="c9"))
    with TestClient(_app(store=store)) as client:
        assert client.post(f"{API_PREFIX}/books/b9/copies",
                           json={}).status_code == 404
        assert client.post(f"{API_PREFIX}/books/b9/copies/c9/lend",
                           json={"lent_to": "דנה"}).status_code == 404


def test_list_filters_by_lent_out():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן", "בית")
    with TestClient(_app(store=store)) as client:
        client.post(f"{API_PREFIX}/books/b1/copies/c1/lend",
                    json={"lent_to": "דנה"})
        r = client.get(f"{API_PREFIX}/books?lent_out=true")
    assert [b["id"] for b in r.json()["items"]] == ["b1"]


def test_export_is_reachable_and_not_swallowed_by_the_id_route():
    """/books/export is declared BEFORE /books/{book_id}. Registered the other
    way round, "export" arrives as a book id and 404s — invisible until
    someone clicks Export."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        assert client.get(f"{API_PREFIX}/books/export").status_code == 200


def test_csv_export_carries_a_bom_so_excel_reads_hebrew():
    """Without it Excel shows mojibake, and "my export is broken" becomes
    indistinguishable from "your data is broken"."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן", "בית")
    with TestClient(_app(store=store)) as client:
        r = client.get(f"{API_PREFIX}/books/export?format=csv")
    assert r.status_code == 200
    assert r.content.startswith(b"\xef\xbb\xbf")
    assert "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("title,author,status")
    assert "אבן" in text and "בית" in text


def test_export_is_the_whole_library_not_a_page():
    """An export that stops at page 1 is worse than no export — it looks
    complete."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, *[f"ספר {i:03d}" for i in range(1, 121)])
    with TestClient(_app(store=store)) as client:
        rows = client.get(f"{API_PREFIX}/books/export?format=csv") \
            .content.decode("utf-8-sig").strip().splitlines()
        data = client.get(f"{API_PREFIX}/books/export?format=json").json()
    assert len(rows) == 121, "header + 120 books"
    assert len(data["books"]) == 120


def test_the_download_is_named_for_the_library_and_the_day():
    """An export lands in a Downloads folder next to everyone else's files,
    and it is a SNAPSHOT — the same generic name twice becomes
    "booksnap-library (1).csv" and neither file says what it holds or when."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        for fmt in ("csv", "json"):
            cd = client.get(f"{API_PREFIX}/books/export?format={fmt}") \
                .headers["content-disposition"]
            assert f"books-Test-library-2026-08-07.{fmt}" in cd, cd


def test_a_hebrew_library_name_survives_the_download_header():
    """A bare `filename=` is ASCII-only, so a Hebrew library name would arrive
    mangled or be dropped. RFC 6266's `filename*` carries the real one; the
    ASCII fallback keeps the DATE rather than degrading to a generic name."""
    hebrew = LibraryRef(id="lib-he", label="הספרייה שלי")
    store = MemoryBookStore()
    _seed(store, hebrew, "אבן")
    with TestClient(_app(principal=StubPrincipal(library=hebrew),
                         store=store)) as client:
        cd = client.get(f"{API_PREFIX}/books/export").headers[
            "content-disposition"]
    assert "filename*=UTF-8''" in cd
    assert quote("הספרייה-שלי") in cd, cd
    assert 'filename="books-2026-08-07.csv"' in cd, cd


def test_export_rejects_an_unknown_format():
    with TestClient(_app()) as client:
        assert client.get(
            f"{API_PREFIX}/books/export?format=pdf").status_code == 422


def test_a_book_in_another_library_is_404_not_403():
    """§4.2 / P3.3: don't leak existence. The store already answers 'absent',
    so the route cannot leak it even by accident."""
    store = MemoryBookStore()
    other = LibraryRef("lib-other", "Other")
    store.save(other, new_book(id="b9", library_id=other.id, title="סוד",
                               copy_id="c9"))
    with TestClient(_app(store=store)) as client:
        assert client.get(f"{API_PREFIX}/books/b9").status_code == 404
        assert client.patch(f"{API_PREFIX}/books/b9",
                            json={"title": "x"}).status_code == 404
        assert client.delete(f"{API_PREFIX}/books/b9").status_code == 404
    assert store.get(other, "b9") is not None, "a foreign book was modified"


def test_unbound_principal_fails_loudly():
    """An app built without an identity adapter must error, not serve a
    default library. Silent defaults are how cross-tenant leaks start."""
    from fastapi import FastAPI
    from fastapi import Depends

    app = FastAPI()

    @app.get("/x")
    def x(lib: LibraryRef = Depends(deps.current_library)):
        return {"id": lib.id}

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/x")
    assert r.status_code == 500, r.status_code


def test_unknown_route_is_404():
    with TestClient(_app()) as client:
        assert client.get(f"{API_PREFIX}/nope").status_code == 404


# --- meta-tests over every route -----------------------------------------

def test_every_api_route_is_versioned():
    routes = _api_routes(_app())
    assert routes, "no API routes found — the meta-tests would pass vacuously"
    bad = [p for p, _ in routes if not p.startswith(API_PREFIX + "/")]
    assert not bad, f"unversioned API routes: {bad} (H3)"


def test_openapi_paths_are_all_under_v1():
    """The same rule read off the published contract rather than the router —
    it is the schema that clients and the TS generator actually see."""
    schema = _app().openapi()
    bad = [p for p in schema["paths"] if not p.startswith(API_PREFIX + "/")]
    assert not bad, f"schema paths outside {API_PREFIX}: {bad} (H3)"


def _dependency_calls(route: APIRoute) -> set:
    """Every callable in a route's dependency tree, flattened."""
    seen = set()
    stack = [route.dependant]
    while stack:
        d = stack.pop()
        if d.call is not None:
            seen.add(d.call)
        stack.extend(d.dependencies)
    return seen


def test_every_api_route_resolves_its_library_from_the_principal():
    routes = _api_routes(_app())
    assert routes, "no API routes found — this meta-test would pass vacuously"
    bad = [p for p, r in routes
           if deps.current_library not in _dependency_calls(r)]
    assert not bad, (
        f"routes not library-scoped: {bad} — every route resolves its library "
        f"through deps.current_library (H2)"
    )


def test_library_resolution_has_exactly_one_implementation():
    """H2 says 'exactly one function'. Assert the count, so a second resolver
    added for convenience is a test failure and not a discovery at pillar 3."""
    import inspect

    src = inspect.getsource(deps)
    assert src.count("def current_library") == 1
    assert src.count("principal.library") == 1, \
        "principal.library is read in more than one place in app/api/deps.py"


def test_no_module_level_mutable_state_in_api():
    """H2/§1.3: the tuning server's module-global job dict is exactly what a
    second tenant breaks. Assert the new api layer has no module-level dict,
    list or set — the shape that bug takes."""
    import ast

    offenders = []
    for f in sorted((REPO_ROOT / "app").rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in tree.body:  # module level only
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if isinstance(value, (ast.Dict, ast.List, ast.Set, ast.DictComp,
                                  ast.ListComp, ast.SetComp)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [t.id for t in targets if isinstance(t, ast.Name)]
                # Exempt by convention, because neither is the failure mode
                # this test exists for (a per-request cache or registry):
                #   SHOUTING_CASE — constants, not written to at runtime;
                #   __dunder__    — module protocol, e.g. __all__.
                def _exempt(n: str) -> bool:
                    return n.isupper() or (n.startswith("__") and n.endswith("__"))

                if any(not _exempt(n) for n in names):
                    offenders.append(
                        f"{f.relative_to(REPO_ROOT).as_posix()}:{node.lineno} {names}"
                    )
    assert not offenders, "module-level mutable state: " + "; ".join(offenders)


# --- shelves and captures (P2.2) -----------------------------------------

def test_a_photo_with_no_shelf_still_gets_one():
    """The binding, and the item's whole point. A capture with no shelf is a
    read with nothing to reconcile against (§5.6), so "assign it later" is not
    a state the model offers — the photo lands on a fresh UNNAMED shelf, and
    *Unassigned* on screen means not yet named.

    The response carries the shelf as well as the capture: when the shelf was
    auto-created the client has no other way to learn its id.
    """
    c = TestClient(_app())
    r = c.post(f"{API_PREFIX}/captures", json={"image_id": "IMG_6082"})
    assert r.status_code == 201, r.text
    body = r.json()

    assert body["shelf_created"] is True
    assert body["shelf"]["label"] == "", "an auto-created shelf was named"
    assert body["shelf"]["depth_count"] == 1
    assert body["capture"]["shelf_id"] == body["shelf"]["id"]
    assert body["capture"]["depth"] == 1
    assert body["capture"]["image_id"] == "IMG_6082"

    listed = c.get(f"{API_PREFIX}/shelves").json()
    assert [s["id"] for s in listed] == [body["shelf"]["id"]]
    assert listed[0]["capture_count"] == 1


def test_a_photo_can_name_an_existing_shelf_and_appends_after_the_last():
    """Several captures of one shelf are ordered (§5.3), and the order is
    computed rather than asked for: intake is "photograph it left to right",
    so a caller supplying its own number is two clients waiting to disagree."""
    c = TestClient(_app())
    shelf = c.post(f"{API_PREFIX}/shelves", json={"label": "סלון"}).json()

    first = c.post(f"{API_PREFIX}/captures",
                   json={"shelf_id": shelf["id"], "image_id": "a"}).json()
    second = c.post(f"{API_PREFIX}/captures",
                    json={"shelf_id": shelf["id"], "image_id": "b"}).json()

    assert first["shelf_created"] is False
    assert [first["capture"]["order"], second["capture"]["order"]] == [0, 1]
    got = c.get(f"{API_PREFIX}/shelves/{shelf['id']}/captures").json()
    assert [x["image_id"] for x in got] == ["a", "b"]


def test_a_photo_cannot_be_filed_at_a_row_that_was_never_declared():
    """§5.7: depth is declared, never detected. A 409 naming the declared
    depth, not a silent clamp to 1 — filing a photo at a row that does not
    exist gives reconciliation a location with no counterpart in the room."""
    c = TestClient(_app())
    shelf = c.post(f"{API_PREFIX}/shelves", json={}).json()

    r = c.post(f"{API_PREFIX}/captures",
               json={"shelf_id": shelf["id"], "depth": 2})
    assert r.status_code == 409, r.text
    assert "2" in r.json()["detail"]

    deeper = c.post(f"{API_PREFIX}/shelves/{shelf['id']}/depths").json()
    assert deeper["depth_count"] == 2
    ok = c.post(f"{API_PREFIX}/captures",
                json={"shelf_id": shelf["id"], "depth": 2})
    assert ok.status_code == 201, ok.text


def test_rebinding_a_photo_moves_it_and_gives_it_a_fresh_position():
    """The inline assignment the intake UI performs. A photo moved to another
    shelf keeps no memory of where it sat on the old one — an inherited order
    would collide with whatever already occupies that slot."""
    c = TestClient(_app())
    auto = c.post(f"{API_PREFIX}/captures", json={"image_id": "a"}).json()
    target = c.post(f"{API_PREFIX}/shelves", json={"label": "מטבח"}).json()
    c.post(f"{API_PREFIX}/captures",
           json={"shelf_id": target["id"], "image_id": "resident"})

    moved = c.patch(f"{API_PREFIX}/captures/{auto['capture']['id']}",
                    json={"shelf_id": target["id"]})
    assert moved.status_code == 200, moved.text
    assert moved.json()["capture"]["shelf_id"] == target["id"]
    assert moved.json()["capture"]["order"] == 1, "it collided with the resident"

    # The shelf it left is now empty, and therefore deletable.
    assert c.delete(f"{API_PREFIX}/shelves/{auto['shelf']['id']}"
                    ).status_code == 204


def test_naming_a_shelf_is_optional_in_both_directions():
    """Identity is free (owner's call): a shelf may be created unnamed, named
    later, and un-named again. `""` is a legal value, not a missing one."""
    c = TestClient(_app())
    shelf = c.post(f"{API_PREFIX}/shelves", json={}).json()
    assert shelf["label"] == ""

    named = c.patch(f"{API_PREFIX}/shelves/{shelf['id']}",
                    json={"label": "סלון, כוננית 2"}).json()
    assert named["label"] == "סלון, כוננית 2"

    cleared = c.patch(f"{API_PREFIX}/shelves/{shelf['id']}",
                      json={"label": ""}).json()
    assert cleared["label"] == "", "clearing a label was treated as absent"


def test_a_shelf_with_photos_cannot_be_deleted():
    """§5.6 at the HTTP edge: 409, not a cascade. Its captures are the record
    a re-read diffs against, and destroying them on a misclick is exactly the
    destructive direction the whole design refuses."""
    c = TestClient(_app())
    made = c.post(f"{API_PREFIX}/captures", json={"image_id": "a"}).json()
    shelf_id = made["shelf"]["id"]

    r = c.delete(f"{API_PREFIX}/shelves/{shelf_id}")
    assert r.status_code == 409, r.text
    assert c.get(f"{API_PREFIX}/shelves/{shelf_id}").status_code == 200

    assert c.delete(f"{API_PREFIX}/captures/{made['capture']['id']}"
                    ).status_code == 204
    assert c.delete(f"{API_PREFIX}/shelves/{shelf_id}").status_code == 204


def test_the_wishlist_is_absent_from_the_shelf_list_unless_asked_for():
    c = TestClient(_app())
    c.post(f"{API_PREFIX}/shelves", json={"label": "סלון"})
    wish = c.post(f"{API_PREFIX}/shelves",
                  json={"label": "משאלות", "virtual": True}).json()

    assert wish["id"] not in [s["id"] for s in
                             c.get(f"{API_PREFIX}/shelves").json()]
    assert wish["id"] in [
        s["id"] for s in
        c.get(f"{API_PREFIX}/shelves", params={"include_virtual": True}).json()
    ]
    # And it never gains a row behind — it is not furniture.
    assert c.post(f"{API_PREFIX}/shelves/{wish['id']}/depths"
                  ).status_code == 409


def test_a_shelf_in_another_library_is_404_not_403():
    """§4.2: absent and forbidden are the same answer, so the API cannot leak
    which shelf ids exist in someone else's library."""
    shared = MemoryShelfStore()
    mine = TestClient(_app(shelves=shared))
    theirs = TestClient(_app(
        StubPrincipal(LibraryRef("lib-other", "Other"), "p-other"),
        shelves=shared,
    ))
    made = mine.post(f"{API_PREFIX}/captures", json={"image_id": "a"}).json()
    shelf_id, cap_id = made["shelf"]["id"], made["capture"]["id"]

    assert theirs.get(f"{API_PREFIX}/shelves/{shelf_id}").status_code == 404
    assert theirs.get(f"{API_PREFIX}/captures/{cap_id}").status_code == 404
    assert theirs.delete(f"{API_PREFIX}/shelves/{shelf_id}").status_code == 404
    assert theirs.get(f"{API_PREFIX}/shelves").json() == []
    # Filing a photo onto a foreign shelf is the same answer, not a 403.
    assert theirs.post(f"{API_PREFIX}/captures",
                       json={"shelf_id": shelf_id}).status_code == 404
    assert mine.get(f"{API_PREFIX}/shelves/{shelf_id}").status_code == 200


# --- images (P2.3) --------------------------------------------------------

def test_a_photo_round_trips_and_comes_back_decodable():
    """The item in one test: bytes in, bytes out, still an image. Dimensions
    come back too, so the review grid can reserve an aspect ratio before the
    picture arrives instead of reflowing on every tile."""
    from PIL import Image

    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        r = c.post(f"{API_PREFIX}/images",
                   files={"file": ("IMG_6082.png", _png((40, 30)), "image/png")})
        assert r.status_code == 201, r.text
        meta = r.json()
        assert (meta["width"], meta["height"]) == (40, 30)
        assert meta["content_type"] == "image/png"
        assert meta["filename"] == "IMG_6082.png"

        full = c.get(f"{API_PREFIX}/images/{meta['key']}/full")
        assert full.status_code == 200
        assert Image.open(io.BytesIO(full.content)).size == (40, 30)

        thumb = c.get(f"{API_PREFIX}/images/{meta['key']}/thumb")
        assert thumb.status_code == 200
        assert thumb.headers["content-type"] == "image/jpeg"
        assert Image.open(io.BytesIO(thumb.content)).size[0] <= 480


def test_uploading_the_same_photo_twice_stores_it_once():
    """§12.3 #13. Re-uploading after a browser refresh is the NORMAL case with
    a camera roll, not an edge one — so the second attempt must cost a hash
    rather than a duplicate, and hand back the same key."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        data = _png()
        first = c.post(f"{API_PREFIX}/images",
                       files={"file": ("a.png", data, "image/png")}).json()
        again = c.post(f"{API_PREFIX}/images",
                       files={"file": ("b.png", data, "image/png")}).json()

        assert first["key"] == again["key"]
        stored = list((Path(blobs.root)).rglob("*.png"))
        assert len(stored) == 1, f"stored twice: {stored}"
        # The filename follows the LATEST upload — same photo, but this time
        # the name may be the better one.
        assert c.get(f"{API_PREFIX}/images/{first['key']}"
                     ).json()["filename"] == "b.png"


def test_a_rotated_phone_photo_is_stored_upright():
    """Phone photos carry an EXIF rotation flag. `cv2.imread` honours it and
    PIL does not unless asked, so left alone the engine would read an upright
    shelf while the review grid showed it on its side — and the person
    reviewing would reasonably conclude the reader was broken.

    Normalising at STORE time is what makes those two agree, and it is also why
    the same photo uploaded upright and rotated must not store twice: identical
    pixels, one key.
    """
    from PIL import Image

    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        # orientation 6 = rotate 90°: a 40x30 image displays as 30x40.
        r = c.post(f"{API_PREFIX}/images",
                   files={"file": ("p.jpg", _jpeg((40, 30), orientation=6),
                                   "image/jpeg")})
        meta = r.json()
        assert (meta["width"], meta["height"]) == (30, 40), \
            "EXIF orientation was not applied at store time"

        served = Image.open(io.BytesIO(
            c.get(f"{API_PREFIX}/images/{meta['key']}/full").content))
        assert served.size == (30, 40)
        assert served.getexif().get(0x0112) in (None, 1), \
            "the stored bytes still carry a rotation flag"


def test_a_file_that_is_not_an_image_is_refused_by_decoding_it():
    """Never by trusting the filename or the declared content type — both are
    the client's own claim, and a store that believes them will serve whatever
    was really uploaded back to a browser under an image content type."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        r = c.post(f"{API_PREFIX}/images",
                   files={"file": ("shelf.jpg", b"#!/bin/sh\nrm -rf /",
                                   "image/jpeg")})
        assert r.status_code == 415, r.text


def test_a_key_cannot_escape_the_library_directory():
    """The key arrives in a URL. `../` in a path segment is how a store that
    just joins strings ends up serving somebody's private key file, so a key is
    validated as `<64 hex>.<ext>` rather than trusted."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        for evil in ("..%2f..%2fproduct.db", "....%2f%2fetc%2fpasswd.jpg"):
            r = c.get(f"{API_PREFIX}/images/{evil}/full")
            assert r.status_code == 404, (evil, r.status_code)


def test_a_photo_in_another_library_is_404_not_403():
    """§4.2 again, and here it also means one tenant cannot read another's
    photos by guessing a hash they happen to know."""
    with _blobs() as blobs:
        mine = TestClient(_app(blobs=blobs))
        theirs = TestClient(_app(
            StubPrincipal(LibraryRef("lib-other", "Other"), "p-other"),
            blobs=blobs,
        ))
        key = mine.post(f"{API_PREFIX}/images",
                        files={"file": ("a.png", _png(), "image/png")}
                        ).json()["key"]

        assert theirs.get(f"{API_PREFIX}/images/{key}").status_code == 404
        assert theirs.get(f"{API_PREFIX}/images/{key}/full").status_code == 404
        assert theirs.get(f"{API_PREFIX}/images/{key}/thumb").status_code == 404
        assert theirs.delete(f"{API_PREFIX}/images/{key}").status_code == 404
        assert mine.get(f"{API_PREFIX}/images/{key}/full").status_code == 200


def test_a_missing_thumbnail_is_re_derived_rather_than_reported_absent():
    """A variant is a CACHE. On screen "no thumbnail yet" and "this photo is
    gone" look identical, and only one of them is a real problem — so a
    deleted rendition must cost a re-render, not a broken tile."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        key = c.post(f"{API_PREFIX}/images",
                     files={"file": ("a.png", _png(), "image/png")}
                     ).json()["key"]
        cached = list(Path(blobs.root).rglob("*~thumb.jpg"))
        assert cached, "no thumbnail was cached at upload"
        for f in cached:
            f.unlink()

        assert c.get(f"{API_PREFIX}/images/{key}/thumb").status_code == 200
        assert list(Path(blobs.root).rglob("*~thumb.jpg")), "not re-cached"


def test_deleting_a_photo_takes_its_renditions_with_it():
    """Variants are a cache OF this original. A stale rendition surviving a
    delete means a wrong picture on a screen, which is worse than the directory
    scan that prevents it."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        key = c.post(f"{API_PREFIX}/images",
                     files={"file": ("a.png", _png(), "image/png")}
                     ).json()["key"]

        assert c.delete(f"{API_PREFIX}/images/{key}").status_code == 204
        assert list(Path(blobs.root).rglob("*~thumb.jpg")) == []
        assert c.get(f"{API_PREFIX}/images/{key}/full").status_code == 404
        assert c.delete(f"{API_PREFIX}/images/{key}").status_code == 404


# --- reads (P2.4) ----------------------------------------------------------
#
# StubReader/SlowStubReader implement app.ports.reader.Reader without
# booksnap, cv2 or tesseract — H4 ring 3's rule: this ring never invokes the
# real engine. InProcessJobRunner IS real (it is fast and pure-Python); only
# the engine is stubbed.

class StubReader:
    """Returns exactly the claims it is holding, ignoring `mode`. `_claims`
    is mutable so a test can set it up AFTER learning a real capture id from
    the API, then let the (already-submitted-later) job pick it up."""

    def __init__(self, claims: list[ReadClaim] | None = None,
                 unavailable: str | None = None):
        self._claims = claims or []
        # Every mode is available to a stub — it needs no credential, which is
        # exactly why the preflight lives on the port and not in the route.
        # A test that wants the refusal sets this.
        self._unavailable = unavailable

    def read(self, library, requests, *, mode, progress=None, should_stop=None):
        if progress:
            progress({"stage": "done", "total": len(requests)})
        return list(self._claims)

    def unavailable(self, mode: str) -> str | None:
        return self._unavailable

    def code_version(self) -> dict:
        return {"sha": "stub", "branch": "test", "dirty": False}

    def config_snapshot(self) -> dict:
        return {"stub": True}


class SlowStubReader:
    """Produces one claim at a time with a short pause between each, checking
    `should_stop` before every one — enough real time for a test to call the
    stop endpoint mid-read and see it actually take effect, without waiting
    anywhere near a real engine's ~10s/spine."""

    def __init__(self, capture_id: str, steps: int = 200, step_s: float = 0.01):
        self._capture_id = capture_id
        self._steps = steps
        self._step_s = step_s

    def read(self, library, requests, *, mode, progress=None, should_stop=None):
        out = []
        for i in range(self._steps):
            if should_stop and should_stop():
                break
            out.append(ReadClaim(spine_id=f"sp{i}", capture_id=self._capture_id,
                                 title=f"claim {i}", tier="auto"))
            time.sleep(self._step_s)
        return out

    def unavailable(self, mode: str) -> str | None:
        return None

    def code_version(self) -> dict:
        return {"sha": "stub", "dirty": False}

    def config_snapshot(self) -> dict:
        return {}


def _wait_until_settled(client, shelf_id: str, read_id: str, *, timeout: float = 2.0):
    """Poll GET .../reads/{id} until its status leaves 'running'. The job
    runs on a real background thread even with a stub engine, so a test has
    to synchronise on it somehow — this is that somehow."""
    deadline = time.monotonic() + timeout
    body = None
    while time.monotonic() < deadline:
        body = client.get(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.01)
    raise AssertionError(f"read did not settle within {timeout}s: {body}")


def test_starting_a_read_needs_captures_at_that_depth():
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        shelf = c.post(f"{API_PREFIX}/shelves", json={"label": "סלון"}).json()
        r = c.post(f"{API_PREFIX}/shelves/{shelf['id']}/reads", json={"depth": 1})
    assert r.status_code == 409, r.text


def test_starting_a_read_needs_uploaded_photos_not_just_captures():
    """A shelf can have a capture before it has a photo (P2.2's recorded
    gap). Refusing this loudly is clearer than letting the job run and
    silently produce zero claims."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        made = c.post(f"{API_PREFIX}/captures", json={}).json()   # no image_id
        r = c.post(f"{API_PREFIX}/shelves/{made['shelf']['id']}/reads",
                   json={"depth": 1})
    assert r.status_code == 409, r.text


def test_a_read_at_an_undeclared_depth_is_409():
    """§5.7: depth is declared, never detected — the same rule captures
    enforce, reached through this door too."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        shelf = c.post(f"{API_PREFIX}/shelves", json={}).json()
        r = c.post(f"{API_PREFIX}/shelves/{shelf['id']}/reads", json={"depth": 2})
    assert r.status_code == 409, r.text
    assert "2" in r.json()["detail"]


def test_a_read_runs_via_a_stub_reader_and_produces_claims():
    """The whole flow: upload a photo, bind it to a shelf via a capture,
    start a read, poll until it settles, and see the claims the (stub)
    engine produced — including a crop round-tripped through BlobStore, the
    same way a real spine crop would be."""
    with _blobs() as blobs:
        reader = StubReader()
        c = TestClient(_app(blobs=blobs, reader=reader))

        img_key = c.post(f"{API_PREFIX}/images",
                         files={"file": ("a.png", _png(), "image/png")}
                         ).json()["key"]
        made = c.post(f"{API_PREFIX}/captures", json={"image_id": img_key}).json()
        shelf_id, cap_id = made["shelf"]["id"], made["capture"]["id"]

        # Set up now that the real capture id is known — the job reads
        # `reader._claims` only once the background thread actually runs,
        # which is after this line.
        reader._claims = [
            ReadClaim(spine_id="sp1", capture_id=cap_id, text="קריאה גולמית",
                     title="מלכי הכופרים", author="פול קארני", tier="auto",
                     score=91.0, crop=_png((10, 40)), box=(1, 2, 3, 4),
                     alternatives=[
                         ReadAlternative(title="ספינות מן המערב",
                                        author="פול קארני", score=61.2),
                     ]),
            ReadClaim(spine_id="sp2", capture_id=cap_id, tier="unmatched"),
        ]

        started = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1, "mode": "spines"})
        assert started.status_code == 202, started.text
        assert started.json()["status"] == "running"
        read_id = started.json()["id"]

        body = _wait_until_settled(c, shelf_id, read_id)
        assert body["status"] == "done"
        assert body["error"] is None
        assert body["capture_ids"] == [cap_id]
        assert body["code_version"] == {"sha": "stub", "branch": "test",
                                        "dirty": False}
        assert len(body["claims"]) == 2

        auto = next(cl for cl in body["claims"] if cl["tier"] == "auto")
        assert auto["title"] == "מלכי הכופרים"
        assert auto["box"] == [1, 2, 3, 4]
        assert auto["crop_key"], "the crop was not stored/keyed"
        assert c.get(f"{API_PREFIX}/images/{auto['crop_key']}/full"
                     ).status_code == 200
        # P2.7's "why?" data rides on the claim itself (see the module
        # docstring's cost reasoning) — GET .../reads/{id} is its only route.
        assert auto["alternatives"] == [
            {"title": "ספינות מן המערב", "author": "פול קארני", "score": 61.2,
             "reason": ""},
        ]

        unmatched = next(cl for cl in body["claims"] if cl["tier"] == "unmatched")
        assert unmatched["crop_key"] is None
        assert unmatched["alternatives"] == []

        # The list endpoint is a SUMMARY — status and a count, no claims.
        listed = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads").json()
        assert [r["id"] for r in listed] == [read_id]
        assert listed[0]["claim_count"] == 2
        assert "claims" not in listed[0], "the summary must not embed claims"


def test_a_read_can_be_stopped_and_keeps_its_partial_claims():
    """§ app.domain.read: a stopped read is a REAL partial result. Stopping
    early must leave SOME claims (proving the partial result was kept) and
    FEWER than the full run would have produced (proving the stop actually
    took effect rather than the job racing to completion anyway)."""
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        setup = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store))
        img_key = setup.post(f"{API_PREFIX}/images",
                             files={"file": ("a.png", _png(), "image/png")}
                             ).json()["key"]
        made = setup.post(f"{API_PREFIX}/captures", json={"image_id": img_key}).json()
        shelf_id, cap_id = made["shelf"]["id"], made["capture"]["id"]

        reader = SlowStubReader(capture_id=cap_id, steps=200, step_s=0.01)
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                            reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]

        # Let the worker produce a handful of claims (~5 at 10ms/step), then
        # stop it — long before its 200 simulated steps would finish alone.
        time.sleep(0.05)
        stopped = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/stop")
        assert stopped.status_code == 202, stopped.text

        body = _wait_until_settled(c, shelf_id, read_id, timeout=3.0)
        assert body["status"] == "stopped"
        assert body["error"] is None
        assert 0 < len(body["claims"]) < 200, (
            "expected a partial result — neither none (the stop lost the "
            "evidence) nor the full 200 (the stop had no effect)"
        )


def test_a_read_id_reached_through_the_wrong_shelf_is_404():
    """A real read id, but not this shelf's — must read as absent, not
    silently serve one shelf's evidence at another shelf's address."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        img_key = c.post(f"{API_PREFIX}/images",
                         files={"file": ("a.png", _png(), "image/png")}
                         ).json()["key"]
        made = c.post(f"{API_PREFIX}/captures", json={"image_id": img_key}).json()
        shelf_id = made["shelf"]["id"]
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        other = c.post(f"{API_PREFIX}/shelves", json={"label": "אחר"}).json()
        assert c.get(f"{API_PREFIX}/shelves/{other['id']}/reads/{read_id}"
                     ).status_code == 404


def test_a_read_in_another_library_is_404_not_403():
    """§4.2, same as every other aggregate: absent and forbidden are the
    same answer."""
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        mine = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                               reader=StubReader()))
        img_key = mine.post(f"{API_PREFIX}/images",
                            files={"file": ("a.png", _png(), "image/png")}
                            ).json()["key"]
        made = mine.post(f"{API_PREFIX}/captures", json={"image_id": img_key}).json()
        shelf_id = made["shelf"]["id"]
        read_id = mine.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                            json={"depth": 1}).json()["id"]
        _wait_until_settled(mine, shelf_id, read_id)

        theirs = TestClient(_app(
            StubPrincipal(LibraryRef("lib-other", "Other"), "p-other"),
            blobs=blobs, shelves=shelves, reads=reads_store, reader=StubReader(),
        ))
        assert theirs.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}"
                          ).status_code == 404
        assert theirs.get(f"{API_PREFIX}/shelves/{shelf_id}/reads").status_code == 404
        assert theirs.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                           json={"depth": 1}).status_code == 404
        assert mine.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}"
                        ).status_code == 200


def test_reads_are_listed_per_shelf_most_recent_first():
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                            reader=StubReader()))
        img_key = c.post(f"{API_PREFIX}/images",
                         files={"file": ("a.png", _png(), "image/png")}
                         ).json()["key"]
        made = c.post(f"{API_PREFIX}/captures", json={"image_id": img_key}).json()
        shelf_id = made["shelf"]["id"]

        first = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                       json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, first)
        second = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                        json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, second)

        listed = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads").json()
        assert [r["id"] for r in listed] == [second, first]


def test_a_capture_with_no_photo_is_skipped_not_fatal():
    """Two captures at one depth, one with a photo and one without (P2.2's
    recorded gap): the read still runs on the one that has evidence, rather
    than refusing the whole depth because of the other."""
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store))
        shelf = c.post(f"{API_PREFIX}/shelves", json={}).json()
        img_key = c.post(f"{API_PREFIX}/images",
                         files={"file": ("a.png", _png(), "image/png")}
                         ).json()["key"]
        with_photo = c.post(f"{API_PREFIX}/captures",
                            json={"shelf_id": shelf["id"], "image_id": img_key}
                            ).json()["capture"]
        c.post(f"{API_PREFIX}/captures", json={"shelf_id": shelf["id"]})  # no photo

        reader = StubReader([ReadClaim(spine_id="sp1",
                                       capture_id=with_photo["id"], tier="auto")])
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                            reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf['id']}/reads",
                         json={"depth": 1}).json()["id"]
        body = _wait_until_settled(c, shelf["id"], read_id)
        assert body["status"] == "done"
        assert len(body["claims"]) == 1
        assert body["claims"][0]["capture_id"] == with_photo["id"]


def test_a_capture_can_carry_the_key_of_an_uploaded_photo():
    """The join P2.3 exists for: upload returns a key, and the capture that
    files the photo onto a shelf references it. Two calls, deliberately — the
    owner drops twelve photos and decides shelf and depth while looking at the
    thumbnails."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        key = c.post(f"{API_PREFIX}/images",
                     files={"file": ("IMG_6082.png", _png(), "image/png")}
                     ).json()["key"]

        made = c.post(f"{API_PREFIX}/captures", json={"image_id": key}).json()
        assert made["capture"]["image_id"] == key
        assert made["shelf_created"] is True
        # And the bytes are reachable from what the capture carries.
        assert c.get(f"{API_PREFIX}/images/{made['capture']['image_id']}/thumb"
                     ).status_code == 200


# --- reconciliation (P2.5) --------------------------------------------------

def _read_shelf_and_capture(c, *, image_key: str | None = None):
    """Common setup: a shelf, one uploaded photo, one capture at depth 1."""
    key = image_key or c.post(
        f"{API_PREFIX}/images",
        files={"file": ("a.png", _png(), "image/png")},
    ).json()["key"]
    made = c.post(f"{API_PREFIX}/captures", json={"image_id": key}).json()
    return made["shelf"]["id"], made["capture"]["id"]


def test_diff_reports_added_unchanged_and_not_seen():
    """GET .../diff RECOMPUTES live (its own contract, `diff_for`'s docstring)
    — and since P2.9, a settled read has already applied itself server-side
    before this GET ever runs (see `test_a_settled_read_applies_its_diff_
    with_no_client_call_at_all` below), so "ספר חדש" already stands at this
    (shelf, depth) by the time this test asks. That is WHY it shows up
    `unchanged` here rather than `added` — not a weaker assertion, a
    consequence of the diff being live rather than a fixed record of the
    moment the read finished (that fixed record is `Read.diff_summary`,
    checked separately)."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        # A book already on this shelf, unclaimed by this read -> not_seen.
        store.save(TEST_LIBRARY, new_book(
            id="b-missing", library_id=TEST_LIBRARY.id, title="לא נקרא",
            author="", copy_id="c-missing", shelf_id=shelf_id, depth=1,
        ))
        # A book already here that this read DOES claim -> unchanged.
        store.save(TEST_LIBRARY, new_book(
            id="b-here", library_id=TEST_LIBRARY.id, title="כבר כאן",
            author="מחבר", copy_id="c-here", shelf_id=shelf_id, depth=1,
        ))

        reader = StubReader([
            ReadClaim(spine_id="sp1", capture_id=cap_id, title="כבר כאן",
                     author="מחבר", tier="auto", score=91.0),
            ReadClaim(spine_id="sp2", capture_id=cap_id, title="ספר חדש",
                     author="סופר", tier="auto", score=88.0),
        ])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        assert not diff["added"], "already applied automatically by the time GET ran"
        unchanged_titles = {o["existing_book"]["title"] for o in diff["unchanged"]}
        assert unchanged_titles == {"כבר כאן", "ספר חדש"}
        assert len(diff["not_seen"]) == 1
        assert diff["not_seen"][0]["book"]["id"] == "b-missing"
        # b-missing + b-here + the automatically-applied "ספר חדש" — GET
        # itself is still read-only; calling it twice must not change this.
        assert store.count(TEST_LIBRARY) == 3
        again = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        assert store.count(TEST_LIBRARY) == 3
        assert {o["existing_book"]["title"] for o in again["unchanged"]} == unchanged_titles


def test_diff_asks_for_a_book_claimed_on_another_shelf():
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        store.save(TEST_LIBRARY, new_book(
            id="b-elsewhere", library_id=TEST_LIBRARY.id, title="ספר אחר",
            author="מחבר", copy_id="c-elsewhere", shelf_id="some-other-shelf",
            depth=1,
        ))
        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר אחר", author="מחבר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        assert not diff["added"] and not diff["unchanged"]
        assert len(diff["needs_decision"]) == 1
        assert diff["needs_decision"][0]["reason"] == "ambiguous_location"
        assert diff["needs_decision"][0]["existing_book"]["id"] == "b-elsewhere"


# --- P2.9: a settled read applies itself, server-side, with no client -------
#
# The bug this section guards against, from live phone use: upload -> press
# Run -> switch app -> come back. The read had finished; nothing had been
# added, because the ONLY thing that ever called POST .../apply was the
# browser's own poll loop noticing the read settle — and a backgrounded
# mobile tab does not reliably keep running that loop (§5.6's own inversion,
# "a read is an event that UPDATES the list", was being violated by the
# implementation). The fix moves the apply into `_job` itself, right where
# P2.8 already computes the settle-time diff for its snapshot.

class RaisingBookStore:
    """Wraps a real `BookStore` but makes `.save()` explode — the tool for
    proving that a failed AUTOMATIC apply does not take the read down with
    it. Every other method (`.list`, `.get`, `.count`, ...) is forwarded
    untouched via `__getattr__`, so the job's own claim-processing (which
    never calls `.save()` — only `apply_diff` does) is unaffected."""

    def __init__(self, inner):
        self._inner = inner

    def save(self, library, book):
        raise RuntimeError("boom: simulated apply-time storage failure")

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_a_settled_read_applies_its_diff_with_no_client_call_at_all():
    """THE regression test for the bug: reproduces "no client ever calls
    apply" by never calling it — not even the usual `POST .../apply` this
    file's other tests make out of habit. If this fails, the fix regressed
    back to depending on a client that might not be there."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר חדש", author="סופר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        # No GET .../diff, no POST .../apply — the read settling is the only
        # thing that happened. The book must already be in the library.
        assert store.count(TEST_LIBRARY) == 1
        got = store.list(TEST_LIBRARY).items[0]
        assert got.title == "ספר חדש" and got.status is Status.AUTO
        assert got.copies[0].shelf_id == shelf_id
        sighting = got.copies[0].provenance[0].sighting
        assert sighting == (read_id, "sp1"), (
            "the sighting must carry THIS read's own (run_id, spine_id), the "
            "same provenance an explicit client apply would have written"
        )


def test_the_automatic_apply_never_auto_resolves_a_needs_decision_claim():
    """§5.4's central rule, re-asserted at the exact new call site: settling
    automatically must NEVER stand in for a human's answer. An
    `ambiguous_location` claim is opened in the duplicates queue (same as an
    explicit no-answer apply would do) rather than resolved one way or the
    other, and a `review_tier_new_book` claim (a bare REVIEW-tier read, no
    prior record anywhere) is left open rather than promoted to a real book."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        duplicates = MemoryDuplicateQueue()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, duplicates=duplicates,
                            reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        store.save(TEST_LIBRARY, new_book(
            id="b-elsewhere", library_id=TEST_LIBRARY.id, title="ספר אחר",
            author="מחבר", copy_id="c-elsewhere", shelf_id="some-other-shelf",
            depth=1,
        ))
        reader = StubReader([
            ReadClaim(spine_id="sp1", capture_id=cap_id, title="ספר אחר",
                     author="מחבר", tier="auto", score=90.0),
            ReadClaim(spine_id="sp2", capture_id=cap_id, title="ספר חדש ולא ברור",
                     author="", tier="review", score=55.0),
        ])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, duplicates=duplicates, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        # Nothing new was CREATED — only the pre-existing book still has its
        # one original copy, and no book exists for the REVIEW-tier claim.
        assert store.count(TEST_LIBRARY) == 1
        assert store.get(TEST_LIBRARY, "b-elsewhere").copy_count == 1

        # The ambiguous claim is durably queued, exactly as an explicit
        # no-answer `POST .../apply` would have left it (P2.6, §5.4).
        open_qs = duplicates.list_open_questions(TEST_LIBRARY)
        assert len(open_qs) == 1
        assert open_qs[0].book_key == store.get(TEST_LIBRARY, "b-elsewhere").key

        # Both claims are still open on a live GET .../diff.
        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        reasons = {o["reason"] for o in diff["needs_decision"]}
        assert reasons == {"ambiguous_location", "review_tier_new_book"}


def test_the_diff_summary_snapshot_is_captured_before_the_automatic_apply_runs():
    """P2.8's `diff_summary` must keep meaning "what this read changed" even
    though the automatic apply (P2.9) now runs moments later in the SAME
    call — reversing the order would let the book this apply just added
    reconcile as `unchanged` in the very summary meant to record it as
    `added`, silently rewriting the read's own history."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר חדש", author="סופר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        body = _wait_until_settled(c, shelf_id, read_id)

        # By now the book IS in the library (the automatic apply already
        # ran) — but the archived snapshot must still say "added", the truth
        # at the moment reconcile() looked, before that apply touched it.
        assert store.count(TEST_LIBRARY) == 1
        assert body["diff_summary"] == {
            "added": 1, "corrected": 0, "unchanged": 0, "needs_decision": 0,
            "not_seen": 0, "rejected": 0, "ignored": 0,
        }


def test_a_failed_read_applies_nothing():
    """A read whose engine blew up mid-way has an arbitrary partial claim
    list — §5.5/§5.6 already say that is not evidence worth summarising, and
    the same reasoning means it must not be applied either."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        class BlowingUpReader:
            def read(self, library, requests, *, mode, progress=None,
                     should_stop=None):
                raise RuntimeError("engine exploded")

            def unavailable(self, mode: str) -> str | None:
                return None

            def code_version(self) -> dict:
                return {}

            def config_snapshot(self) -> dict:
                return {}

        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=BlowingUpReader()))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        body = _wait_until_settled(c, shelf_id, read_id)

        assert body["status"] == "failed"
        assert body["diff_summary"] is None
        assert store.count(TEST_LIBRARY) == 0


def test_the_automatic_apply_is_idempotent_against_a_later_client_apply_call():
    """The client's own `commitDiff` still calls `POST .../apply` on every
    settle (harmless-by-design, kept for the moment the server-side apply
    itself fails) — this proves "harmless" rather than assuming it:
    `Provenance.sighting` (`run_id`, `spine_id`) makes `observe()` idempotent,
    so the SAME claim reconciling twice must not create a second copy, a
    second sighting, or a second book."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר חדש", author="סופר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)
        assert store.count(TEST_LIBRARY) == 1

        # The client's own apply, exactly as it fires today — twice, even,
        # since a flaky connection can retry it.
        for _ in range(2):
            r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
                      json={"answers": []})
            assert r.status_code == 200, r.text

        assert store.count(TEST_LIBRARY) == 1, "a repeat apply must not add a second book"
        got = store.list(TEST_LIBRARY).items[0]
        assert got.copy_count == 1, "a repeat apply must not add a second copy"
        assert len(got.copies[0].provenance) == 1, (
            "the SAME (run_id, spine_id) sighting must not be recorded twice"
        )


def test_a_failed_automatic_apply_does_not_fail_the_read():
    """If the automatic apply itself blows up (a store hiccup, a shelf
    deleted in the instant between finishing and applying), the read is
    still a real record of a successful attempt — the claims and the P2.8
    snapshot survive; only the write-through is lost, and the client's own
    apply (still called on every settle) is the retry path for it. This is
    NOT a case that should ever surface as a `failed` read — that status
    means the ENGINE failed, and here it plainly did not."""
    with _blobs() as blobs:
        store = RaisingBookStore(MemoryBookStore())
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר חדש", author="סופר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        body = _wait_until_settled(c, shelf_id, read_id)

        assert body["status"] == "done", (
            "the read itself succeeded; only its automatic follow-up apply "
            "failed, and that must not relabel the read as failed"
        )
        assert len(body["claims"]) == 1, "the claim the engine found is kept"
        assert body["diff_summary"] == {
            "added": 1, "corrected": 0, "unchanged": 0, "needs_decision": 0,
            "not_seen": 0, "rejected": 0, "ignored": 0,
        }, "the summary, computed before the failed apply, must still be saved"


def test_apply_persists_added_and_unchanged_without_any_answers():
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר חדש", author="סופר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        applied = c.post(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
            json={"answers": []},
        )
        assert applied.status_code == 200, applied.text
        assert store.count(TEST_LIBRARY) == 1
        assert not applied.json()["added"], (
            "the returned diff is the POST-apply state; a persisted book is "
            "no longer 'added' against the library that now holds it"
        )
        assert store.list(TEST_LIBRARY).items[0].title == "ספר חדש"


def test_apply_with_an_already_listed_answer_relinks_the_copy():
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        store.save(TEST_LIBRARY, new_book(
            id="b1", library_id=TEST_LIBRARY.id, title="ספר נודד",
            author="מחבר", copy_id="c1", shelf_id="old-shelf", depth=1,
        ))
        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר נודד", author="מחבר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        claim_id = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff"
                         ).json()["needs_decision"][0]["claim"]["id"]
        applied = c.post(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
            json={"answers": [{"claim_id": claim_id, "kind": "already_listed"}]},
        )
        assert applied.status_code == 200, applied.text
        assert not applied.json()["needs_decision"], "the answered claim is still open"
        assert store.get(TEST_LIBRARY, "b1").copies[0].shelf_id == shelf_id
        assert store.count(TEST_LIBRARY) == 1, "already-listed must not duplicate the book"


def test_apply_rejects_an_unknown_answer_kind():
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
                  json={"answers": [{"claim_id": "nope", "kind": "maybe"}]})
        assert r.status_code == 400, r.text


def test_apply_rejects_an_answer_for_a_claim_that_is_not_open():
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                            reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)
        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר", author="", tier="auto",
                                       score=90.0)])
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                            reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
                  json={"answers": [{"claim_id": "not-a-real-claim-id",
                                    "kind": "confirm"}]})
        assert r.status_code == 400, r.text


def test_diff_and_apply_refuse_a_still_running_read():
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        setup = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store))
        shelf_id, cap_id = _read_shelf_and_capture(setup)

        reader = SlowStubReader(capture_id=cap_id, steps=200, step_s=0.01)
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                            reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]

        assert c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff"
                     ).status_code == 409
        assert c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
                      json={"answers": []}).status_code == 409
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/stop")
        _wait_until_settled(c, shelf_id, read_id, timeout=3.0)


def test_diff_for_a_read_in_another_library_is_404_not_403():
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        mine = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                               reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(mine)
        read_id = mine.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                            json={"depth": 1}).json()["id"]
        _wait_until_settled(mine, shelf_id, read_id)

        theirs = TestClient(_app(
            StubPrincipal(LibraryRef("lib-other", "Other"), "p-other"),
            blobs=blobs, shelves=shelves, reads=reads_store, reader=StubReader(),
        ))
        assert theirs.get(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff"
        ).status_code == 404
        assert theirs.post(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
            json={"answers": []},
        ).status_code == 404


# --- the durable duplicates queue (P2.6, §5.4) ------------------------------

def _ambiguous_read(blobs):
    """A shelf/capture/read whose one claim collides with a book already
    confirmed on ANOTHER shelf — the real §5.4 ambiguous case, settled and
    ready for ``POST .../apply``. Mirrors `test_diff_asks_for_a_book_claimed_
    on_another_shelf`'s own setup; factored out because every test below
    needs it as its starting point, not its subject.

    Returns ``(store, shelves, reads_store, duplicates, client, shelf_id,
    read_id)``.
    """
    store = MemoryBookStore()
    shelves = MemoryShelfStore()
    reads_store = MemoryReadStore()
    duplicates = MemoryDuplicateQueue()
    c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                        blobs=blobs, duplicates=duplicates, reader=StubReader()))
    shelf_id, cap_id = _read_shelf_and_capture(c)

    store.save(TEST_LIBRARY, new_book(
        id="b-elsewhere", library_id=TEST_LIBRARY.id, title="ספר אחר",
        author="מחבר", copy_id="c-elsewhere", shelf_id="some-other-shelf",
        depth=1,
    ))
    reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                   title="ספר אחר", author="מחבר",
                                   tier="auto", score=90.0)])
    c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                        blobs=blobs, duplicates=duplicates, reader=reader))
    read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                     json={"depth": 1}).json()["id"]
    _wait_until_settled(c, shelf_id, read_id)
    return store, shelves, reads_store, duplicates, c, shelf_id, read_id


def test_a_skipped_ambiguous_claim_appears_in_the_duplicates_queue():
    with _blobs() as blobs:
        _, _, _, _, c, shelf_id, read_id = _ambiguous_read(blobs)
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
              json={"answers": []})

        got = c.get(f"{API_PREFIX}/duplicates").json()
        assert len(got) == 1
        q = got[0]
        assert q["shelf_id"] == shelf_id and q["depth"] == 1
        assert q["existing_book"]["id"] == "b-elsewhere"
        assert q["claim_title"] == "ספר אחר"
        assert q["prompt_kind"] == "three_way"
        assert q["default_copy_id"] == "c-elsewhere"


def test_the_books_duplicates_filter_returns_only_books_with_open_questions():
    with _blobs() as blobs:
        store, _, _, _, c, shelf_id, read_id = _ambiguous_read(blobs)
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
              json={"answers": []})
        store.save(TEST_LIBRARY, new_book(
            id="b-unrelated", library_id=TEST_LIBRARY.id, title="ספר שקט",
            author="", copy_id="c-unrelated",
        ))

        page = c.get(f"{API_PREFIX}/books", params={"duplicates": "true"}).json()
        assert [b["id"] for b in page["items"]] == ["b-elsewhere"]
        # Omitted entirely: every book, same as any other filter (§6).
        every = c.get(f"{API_PREFIX}/books").json()
        assert {b["id"] for b in every["items"]} == {"b-elsewhere", "b-unrelated"}


def test_answering_a_queued_question_relinks_and_closes_it():
    with _blobs() as blobs:
        store, _, _, _, c, shelf_id, read_id = _ambiguous_read(blobs)
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
              json={"answers": []})
        question_id = c.get(f"{API_PREFIX}/duplicates").json()[0]["id"]

        r = c.post(f"{API_PREFIX}/duplicates/{question_id}/answer",
                  json={"kind": "already_listed"})
        assert r.status_code == 200, r.text
        assert r.json()["copies"][0]["shelf_id"] == shelf_id
        assert store.count(TEST_LIBRARY) == 1, "already-listed must not duplicate the book"
        assert c.get(f"{API_PREFIX}/duplicates").json() == []


def test_skipping_a_queued_question_applies_the_safe_default():
    """§5.4, verbatim: 'default when the question is skipped or the run is
    never reviewed: already listed copy'. The end-to-end proof, over real
    HTTP: reversing the default (`app.domain.copy_resolution.DEFAULT_RESOLUTION`)
    to ANOTHER_COPY would make ``copy_count`` come back 2, not 1 — the
    phantom-copy regression §5.1/§5.4 both exist to rule out."""
    with _blobs() as blobs:
        _, _, _, _, c, shelf_id, read_id = _ambiguous_read(blobs)
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
              json={"answers": []})
        question_id = c.get(f"{API_PREFIX}/duplicates").json()[0]["id"]

        r = c.post(f"{API_PREFIX}/duplicates/{question_id}/skip")
        assert r.status_code == 200, r.text
        book = r.json()
        assert book["copy_count"] == 1
        assert book["copies"][0]["shelf_id"] == shelf_id, "the copy was not relinked"
        assert c.get(f"{API_PREFIX}/duplicates").json() == []


def test_answering_or_skipping_an_unknown_question_is_404():
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        r = c.post(f"{API_PREFIX}/duplicates/nope/answer",
                  json={"kind": "already_listed"})
        assert r.status_code == 404, r.text
        assert c.post(f"{API_PREFIX}/duplicates/nope/skip").status_code == 404


def test_a_question_whose_book_was_deleted_meanwhile_is_409_and_cleaned_up():
    """Defence in depth: the queue stores a POINTER, not a snapshot (same
    idiom as GET .../diff) — if the book it concerns is gone by the time a
    human answers, re-deriving the outcome finds nothing to answer, and the
    stale row must not be left to confuse the next listing."""
    with _blobs() as blobs:
        _, _, _, _, c, shelf_id, read_id = _ambiguous_read(blobs)
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
              json={"answers": []})
        question_id = c.get(f"{API_PREFIX}/duplicates").json()[0]["id"]

        assert c.delete(f"{API_PREFIX}/books/b-elsewhere").status_code == 204

        r = c.post(f"{API_PREFIX}/duplicates/{question_id}/answer",
                  json={"kind": "already_listed"})
        assert r.status_code == 409, r.text
        assert c.get(f"{API_PREFIX}/duplicates").json() == []


# --- P2.8: the shelf-detail screen ------------------------------------------

def test_shelf_overview_shows_no_staleness_signal_before_any_read_ever_happened():
    """The depth bar is always visible, even at `depth_count` 1 (§5.7) — and
    with nothing read yet at all, there is no fresher sibling to be stale
    against, so the soft line must stay quiet rather than flag the only row
    a shelf has."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        shelf = c.post(f"{API_PREFIX}/shelves", json={"label": "סלון"}).json()

        overview = c.get(f"{API_PREFIX}/shelves/{shelf['id']}/overview").json()
        assert overview["depths"] == [
            {"depth": 1, "last_read_at": None, "is_stale": False},
        ]
        assert overview["last_read_at"] is None


def test_shelf_overview_flags_a_row_stale_relative_to_its_read_sibling():
    """UI_PLAN §3's own example, ` "rows 2, 3 not read since 11.3.2026"` —
    staleness is relative to the shelf's OWN freshest row, never a clock."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/depths")  # now 2 rows deep
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        overview = c.get(f"{API_PREFIX}/shelves/{shelf_id}/overview").json()
        by_depth = {d["depth"]: d for d in overview["depths"]}
        assert by_depth[1]["last_read_at"] is not None
        assert by_depth[1]["is_stale"] is False
        assert by_depth[2]["last_read_at"] is None
        assert by_depth[2]["is_stale"] is True
        assert overview["last_read_at"] == by_depth[1]["last_read_at"]


def test_shelf_overview_for_an_absent_shelf_is_404():
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        assert c.get(f"{API_PREFIX}/shelves/nope/overview").status_code == 404


def test_shelf_books_lists_only_the_books_located_at_the_requested_depth():
    """§5.7 #1, at the API's own door: a shelf's books are per DEPTH, never
    a mixed list of two physical rows."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        c = TestClient(_app(store=store, shelves=shelves, blobs=blobs,
                            reader=StubReader()))
        shelf = c.post(f"{API_PREFIX}/shelves", json={"label": "סלון"}).json()
        c.post(f"{API_PREFIX}/shelves/{shelf['id']}/depths")  # 2 rows

        store.save(TEST_LIBRARY, new_book(
            id="b1", library_id=TEST_LIBRARY.id, title="קדמי", author="",
            copy_id="c1", shelf_id=shelf["id"], depth=1))
        store.save(TEST_LIBRARY, new_book(
            id="b2", library_id=TEST_LIBRARY.id, title="אחורי", author="",
            copy_id="c2", shelf_id=shelf["id"], depth=2))

        front = c.get(f"{API_PREFIX}/shelves/{shelf['id']}/books",
                      params={"depth": 1}).json()
        assert [b["id"] for b in front] == ["b1"]
        back = c.get(f"{API_PREFIX}/shelves/{shelf['id']}/books",
                     params={"depth": 2}).json()
        assert [b["id"] for b in back] == ["b2"]


def test_shelf_books_at_an_undeclared_depth_is_409():
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        shelf = c.post(f"{API_PREFIX}/shelves", json={}).json()
        r = c.get(f"{API_PREFIX}/shelves/{shelf['id']}/books", params={"depth": 2})
        assert r.status_code == 409, r.text


def test_shelf_books_for_an_absent_shelf_is_404():
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        assert c.get(f"{API_PREFIX}/shelves/nope/books").status_code == 404


def test_shelf_books_orders_by_the_engines_own_spine_index_when_available():
    """No true physical position is stored (see `_physical_order_key`'s own
    docstring); the best available proxy is the spine id's numeric suffix,
    numeric so spine 10 does not sort before spine 2, and a copy with no
    spine at all (a manual add) sorts last rather than first."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        c = TestClient(_app(store=store, blobs=blobs, reader=StubReader()))
        shelf = c.post(f"{API_PREFIX}/shelves", json={}).json()

        store.save(TEST_LIBRARY, new_book(
            id="b10", library_id=TEST_LIBRARY.id, title="עשירי", author="",
            copy_id="b10c", shelf_id=shelf["id"], depth=1,
            provenance=(Provenance(run_id="r1", spine_id="IMG_1_b0_s10",
                                   shelf_id=shelf["id"], depth=1),)))
        store.save(TEST_LIBRARY, new_book(
            id="b2", library_id=TEST_LIBRARY.id, title="שני", author="",
            copy_id="b2c", shelf_id=shelf["id"], depth=1,
            provenance=(Provenance(run_id="r1", spine_id="IMG_1_b0_s02",
                                   shelf_id=shelf["id"], depth=1),)))
        store.save(TEST_LIBRARY, new_book(
            id="bx", library_id=TEST_LIBRARY.id, title="בלי שדרה", author="",
            copy_id="bxc", shelf_id=shelf["id"], depth=1))  # no provenance

        got = c.get(f"{API_PREFIX}/shelves/{shelf['id']}/books",
                    params={"depth": 1}).json()
        assert [b["id"] for b in got] == ["b2", "b10", "bx"]


def test_shelf_books_reports_a_not_seen_streak_and_never_removes_the_book():
    """§5.6's central rule, exercised through the door a careless "cleanup"
    feature would most plausibly be added to: two re-reads in a row that do
    not reconfirm a book must grow its badge to 2, and MUST NOT touch the
    book itself — it is listed exactly as before, and still fetchable
    directly from the store the endpoint reads from."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        read_a = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                        json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_a)
        store.save(TEST_LIBRARY, new_book(
            id="b1", library_id=TEST_LIBRARY.id, title="ספר קבוע", author="",
            copy_id="c1", shelf_id=shelf_id, depth=1,
            provenance=(Provenance(run_id=read_a, spine_id="sp1",
                                   shelf_id=shelf_id, depth=1,
                                   captured_at="2026-08-01T00:00:00+00:00"),),
        ))

        # Two re-reads of the SAME (shelf, depth); the (stub) engine finds
        # nothing either time -- two consecutive misses.
        for _ in range(2):
            read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                             json={"depth": 1}).json()["id"]
            _wait_until_settled(c, shelf_id, read_id)

        books = c.get(f"{API_PREFIX}/shelves/{shelf_id}/books",
                      params={"depth": 1}).json()
        assert len(books) == 1, "the book was removed after being unseen twice"
        assert books[0]["id"] == "b1"
        assert books[0]["copies"][0]["not_seen_streak"] == 2
        assert store.get(TEST_LIBRARY, "b1") is not None, \
            "computing the badge must not have touched the store"


def test_a_finished_read_carries_a_diff_summary_and_it_is_archived_not_repainted():
    """§5.5's headline example, end to end: a read that added one book must
    say so — in its own GET, in the shelf's history list — and that count
    must survive `apply` unchanged, because the book it added being "already
    here" from now on is not the same statement as "this read added it"."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר חדש", tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        body = _wait_until_settled(c, shelf_id, read_id)
        assert body["diff_summary"] == {
            "added": 1, "corrected": 0, "unchanged": 0, "needs_decision": 0,
            "not_seen": 0, "rejected": 0, "ignored": 0,
        }

        listed = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads").json()
        assert listed[0]["diff_summary"]["added"] == 1

        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
              json={"answers": []})
        after_apply = c.get(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}").json()
        assert after_apply["diff_summary"]["added"] == 1, (
            "the archived snapshot must not repaint itself once the book it "
            "added is, correctly, 'already here' on every later look"
        )


def test_a_stopped_or_failed_read_summary_is_none_or_reflects_the_partial_claims():
    """A `failed` read has no reliable diff to freeze (its claims may be an
    arbitrary partial slice from whatever blew up); a `stopped` one is a
    real partial result (§ app.domain.read) and gets a real summary over
    whatever it did collect."""
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        setup = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store))
        img_key = setup.post(f"{API_PREFIX}/images",
                             files={"file": ("a.png", _png(), "image/png")}
                             ).json()["key"]
        made = setup.post(f"{API_PREFIX}/captures", json={"image_id": img_key}).json()
        shelf_id, cap_id = made["shelf"]["id"], made["capture"]["id"]

        reader = SlowStubReader(capture_id=cap_id, steps=200, step_s=0.01)
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                            reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        time.sleep(0.05)
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/stop")
        body = _wait_until_settled(c, shelf_id, read_id, timeout=3.0)
        assert body["status"] == "stopped"
        assert body["diff_summary"] is not None
        assert body["diff_summary"]["added"] == len(body["claims"])


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))


# --- the default reading mode, and its preflight (2026-08-08) -------------

def test_a_read_defaults_to_the_llm_mode():
    """Owner's call. The measured gap is not close: the Tesseract path is
    ~10s/spine and tops out near 76% title-correct, and CLAUDE.md already
    records llmpage as the engine's own default.

    The project's deterministic-first rule is about not paying an LLM for work
    cheap code can do — it was never an argument for making the worse reader
    the one everybody meets first. Pinned because "restore the deterministic
    default" is exactly the kind of tidy-looking change that would quietly
    hand every new user the weaker engine.
    """
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        key = c.post(f"{API_PREFIX}/images",
                     files={"file": ("a.png", _png(), "image/png")}).json()["key"]
        made = c.post(f"{API_PREFIX}/captures", json={"image_id": key}).json()
        # A body with no `mode` at all — the default is what is under test.
        started = c.post(f"{API_PREFIX}/shelves/{made['shelf']['id']}/reads",
                         json={})
    assert started.status_code == 202, started.text
    assert started.json()["mode"] == "llmpage"


def test_a_mode_whose_credential_is_missing_is_refused_at_the_door():
    """A read runs in a WORKER THREAD. A missing key discovered there surfaces
    as a `failed` read with a traceback in a log nobody is watching, minutes
    after the click — and the owner is left guessing whether the photo, the
    shelf or the engine was the problem.

    The answer comes from the Reader, not from this route: which credential
    which engine needs is the adapter's knowledge, and encoding it in the API
    layer would couple the route to whichever adapter is bound — and would
    give this ring an environment it deliberately does not have.
    """
    with _blobs() as blobs:
        refuses = StubReader(unavailable="needs A_KEY — set it and restart")
        c = TestClient(_app(blobs=blobs, reader=refuses))
        key = c.post(f"{API_PREFIX}/images",
                     files={"file": ("a.png", _png(), "image/png")}).json()["key"]
        made = c.post(f"{API_PREFIX}/captures", json={"image_id": key}).json()
        r = c.post(f"{API_PREFIX}/shelves/{made['shelf']['id']}/reads",
                   json={"mode": "llmpage"})

    assert r.status_code == 409, r.text
    # The message must say what to DO, not merely what is absent — it is shown
    # to the owner, who cannot read a traceback.
    assert "set it and restart" in r.json()["detail"]


def test_the_real_reader_names_the_key_each_mode_needs():
    """The adapter is the one place that knows the mapping. Asserted directly
    because the API ring stubs the Reader, so nothing else exercises it — and
    a preflight that never fires is indistinguishable from no preflight."""
    import os as _os

    from app.adapters.booksnap_reader import BooksnapReader

    reader = BooksnapReader.__new__(BooksnapReader)   # no engine construction
    saved = {k: _os.environ.pop(k, None)
             for k in ("ANTHROPIC_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS")}
    try:
        assert "ANTHROPIC_API_KEY" in (reader.unavailable("llmpage") or "")
        assert "GOOGLE_APPLICATION_CREDENTIALS" in (
            reader.unavailable("fullpage") or "")
        # Tesseract needs nothing, and stays the answer when no key exists.
        assert reader.unavailable("spines") is None
        assert "unknown reading mode" in (reader.unavailable("nope") or "")
    finally:
        for k, v in saved.items():
            if v is not None:
                _os.environ[k] = v


# --- what phones actually send (2026-08-08) -------------------------------

def test_a_real_phone_photo_uploads():
    """The regression that shipped. Every one of the owner's real shelf photos
    is an MPO — a JPEG container with a second embedded frame — and the upload
    validator's whitelist only knew JPEG/PNG/WEBP, so every real upload 415'd
    while every test passed.

    The tests passed because `Image.new(...).save(format='JPEG')` produces
    plain JPEG. **A synthetic image is not a sample of the input domain.**
    """
    from PIL import Image

    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        data = _mpo()
        assert Image.open(io.BytesIO(data)).format == "MPO", "not a real MPO"

        r = c.post(f"{API_PREFIX}/images",
                   files={"file": ("IMG_6082.jpg", data, "image/jpeg")})
        assert r.status_code == 201, r.text
        meta = r.json()
        # Served as JPEG: frame 0 of an MPO is an ordinary JPEG, which is what
        # a browser and cv2 both read.
        assert meta["content_type"] == "image/jpeg"
        assert (meta["width"], meta["height"]) == (60, 40)

        assert c.get(f"{API_PREFIX}/images/{meta['key']}/full").status_code == 200
        thumb = c.get(f"{API_PREFIX}/images/{meta['key']}/thumb")
        assert thumb.status_code == 200
        assert Image.open(io.BytesIO(thumb.content)).format == "JPEG"


def test_a_rotated_phone_photo_that_is_an_mpo_is_stored_upright_as_jpeg():
    """The two phone realities together: MPO *and* an EXIF rotation flag. An
    MPO cannot be written back as an MPO from one transposed frame, so
    correcting orientation must re-encode as JPEG — and the earlier code would
    have thrown trying to save `format='MPO'`."""
    from PIL import Image

    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        r = c.post(f"{API_PREFIX}/images",
                   files={"file": ("p.jpg", _mpo((60, 40), orientation=6),
                                   "image/jpeg")})
        assert r.status_code == 201, r.text
        meta = r.json()
        assert (meta["width"], meta["height"]) == (40, 60), "not transposed"

        served = Image.open(io.BytesIO(
            c.get(f"{API_PREFIX}/images/{meta['key']}/full").content))
        assert served.format == "JPEG", "an MPO was re-saved as MPO"
        assert served.getexif().get(0x0112) in (None, 1)


def test_an_unsupported_format_says_what_to_change():
    """"Not a decodable image" is true and useless — the owner is holding a
    photo that plainly IS one. HEIC is the iPhone default whenever the camera
    is not on "Most Compatible", so the refusal names it and says what to do."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        r = c.post(f"{API_PREFIX}/images",
                   files={"file": ("IMG_1.heic", _heic_header(), "image/heic")})
        assert r.status_code == 415, r.text
        detail = r.json()["detail"]
        assert "HEIC" in detail
        assert "Most Compatible" in detail, "the message does not say what to do"


def test_the_owners_real_photos_upload_if_they_are_on_this_machine():
    """Self-skipping, like the spotchecks: `work/` is gitignored, so a fresh
    clone has no photos and this cannot be a hard gate. But on the machine that
    HAS them it is the only test that runs the real input domain through the
    real validator — which is the check whose absence let MPO ship broken.
    """
    real = sorted(Path(REPO_ROOT / "work" / "library").glob("*.jpeg"))[:3]
    if not real:
        return  # no local photo archive; the committed MPO test still ran

    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        for path in real:
            r = c.post(f"{API_PREFIX}/images",
                       files={"file": (path.name, path.read_bytes(),
                                       "image/jpeg")})
            assert r.status_code == 201, f"{path.name}: {r.status_code} {r.text[:200]}"
            key = r.json()["key"]
            assert c.get(f"{API_PREFIX}/images/{key}/thumb").status_code == 200
