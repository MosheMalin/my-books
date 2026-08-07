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

import sys
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import API_PREFIX, __version__
from app.adapters.memory_store import MemoryBookStore, MemoryShelfStore
from app.api import deps
from app.api.app import create_app
from app.domain import LibraryRef, Status, new_book

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


def _app(principal: StubPrincipal | None = None, store=None, shelves=None):
    p = principal or StubPrincipal()
    return create_app(
        principal_provider=lambda: p,
        book_store=store if store is not None else MemoryBookStore(),
        shelf_store=shelves if shelves is not None else MemoryShelfStore(),
        clock=StubClock(),
        id_gen=SeqIdGen(),
    )


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


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))
