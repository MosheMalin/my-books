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

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import API_PREFIX, __version__
from app.api import deps
from app.api.app import create_app
from app.domain import LibraryRef

TEST_LIBRARY = LibraryRef(id="lib-test", label="Test library")


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


def _app(principal: StubPrincipal | None = None):
    p = principal or StubPrincipal()
    return create_app(principal_provider=lambda: p)


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


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))
