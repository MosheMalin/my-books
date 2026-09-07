# -*- coding: utf-8 -*-
"""Application factory.

A factory rather than a module-level ``app = FastAPI()`` because H2 forbids
module-level mutable state, and because the API tests need to build an app
with a stub principal without touching the one uvicorn serves.

Note the argument list: ports and paths only. No adapter is imported in this
module — see ``app/main.py`` for the wiring.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import API_PREFIX, __version__
from app.api.deps import (
    get_auth_store,
    get_identity_providers,
    get_invite_store,
    get_oauth_state_store,
    get_session_secure,
    get_visitor_header,
    get_blob_store,
    get_book_store,
    get_clock,
    get_decision_store,
    get_duplicate_queue,
    get_id_gen,
    get_job_runner,
    get_mailer,
    get_principal,
    get_read_store,
    get_reader,
    get_journal,
    get_map_store,
    get_shelf_store,
    get_tenancy_store,
)
from app.api.routers import (
    auth,
    books,
    members,
    duplicates,
    images,
    libraries,
    map,
    meta,
    reads,
    shelves,
)
from app.ports import Clock, IdGen, Principal
from app.ports.auth import AuthStore, Mailer
from app.ports.invites import InviteStore
from app.ports.oauth import OAuthStateStore
from app.ports.blobs import BlobStore
from app.ports.decisions import DecisionStore
from app.ports.duplicates import DuplicateQueue
from app.ports.jobs import JobRunner
from app.map_undo import Journal
from app.ports.map import MapStore
from app.ports.map_undo import MapUndoStore
from app.ports.reader import Reader
from app.ports.store import BookStore, ReadStore, ShelfStore
from app.ports.tenancy import TenancyStore

API_TITLE = "booksnap product API"


def _always(value):
    """A zero-argument provider returning ``value``.

    Must take NO parameters. The obvious ``lambda v=value: v`` is a trap:
    FastAPI analyses a dependency's signature and treats a defaulted parameter
    as a field to resolve, which runs the default through pydantic — and
    pydantic DEEP-COPIES mutable defaults. The endpoint then receives a *copy*
    of the store, so every write lands in a throwaway object, every read looks
    right, and nothing ever persists. Reads pass, writes silently vanish.
    """

    def provide():
        return value

    return provide


def bind_ports(
    app: FastAPI,
    *,
    principal_provider: Callable[[], Principal],
    book_store: BookStore | None = None,
    clock: Clock | None = None,
    id_gen: IdGen | None = None,
    shelf_store: ShelfStore | None = None,
    map_store: MapStore | None = None,
    blob_store: BlobStore | None = None,
    read_store: ReadStore | None = None,
    map_undo_store: MapUndoStore | None = None,
    decision_store: DecisionStore | None = None,
    duplicate_queue: DuplicateQueue | None = None,
    reader: Reader | None = None,
    job_runner: JobRunner | None = None,
    tenancy_store: TenancyStore | None = None,
    auth_store: AuthStore | None = None,
    mailer: Mailer | None = None,
    invite_store: InviteStore | None = None,
    oauth_state_store: OAuthStateStore | None = None,
    identity_providers: dict | None = None,
    session_secure: bool | None = None,
    visitor_header: str | None = None,
) -> None:
    """Point an already-built app's ports at these implementations.

    Extracted from ``create_app`` so that the API ring can rebuild an app's
    bindings without rebuilding the app. FastAPI resolves a route's dependency
    graph lazily, on that route's first request, and the analysis is ~50ms per
    app — paid 153 times by ``tests/test_api.py``, which was 29 of its 39
    seconds. Reusing one app across tests and rebinding here skips all of it.

    ⚠ Rebinding must go through this one function, never a second copy of the
    loop in a test helper: ``_always`` is the whole point (see its docstring),
    and a test harness that bound its stores some other way would stop
    exercising the trap ``test_a_write_through_the_api_reaches_the_real_store``
    exists to catch.
    """
    app.dependency_overrides[get_principal] = principal_provider
    if session_secure is not None:
        app.dependency_overrides[get_session_secure] = _always(session_secure)
    if visitor_header is not None:
        app.dependency_overrides[get_visitor_header] = _always(visitor_header)
    for dep, impl in ((get_book_store, book_store), (get_clock, clock),
                      (get_id_gen, id_gen), (get_shelf_store, shelf_store),
                      (get_map_store, map_store),
                      (get_blob_store, blob_store), (get_read_store, read_store),
                      (get_decision_store, decision_store),
                      (get_duplicate_queue, duplicate_queue),
                      (get_reader, reader), (get_job_runner, job_runner),
                      (get_tenancy_store, tenancy_store),
                      (get_auth_store, auth_store), (get_mailer, mailer),
                      (get_invite_store, invite_store),
                      (get_oauth_state_store, oauth_state_store),
                      (get_identity_providers, identity_providers)):
        if impl is not None:
            app.dependency_overrides[dep] = _always(impl)
    # The journal is bound as one bundle (P6.4b) — see `deps.get_journal`.
    # Loud rather than lazy about the trio: an entry with no id cannot be
    # found again and one with no time cannot be ordered, so a journal bound
    # without them is a journal that records unusable inverses and says
    # nothing about it.
    if map_undo_store is not None:
        if id_gen is None or clock is None:
            raise ValueError(
                "binding a map undo journal needs an IdGen and a Clock too")
        # ⚠ And the three the MERGE's inverse needs (P6.4d). Same sentence as
        # the trio above, one item later: an entry that moved books,
        # photographs and standing answers cannot be digested — let alone
        # replayed — by a journal that can only see the map.
        if book_store is None or decision_store is None \
                or duplicate_queue is None:
            raise ValueError(
                "binding a map undo journal needs the BookStore, "
                "DecisionStore and DuplicateQueue too: a merge's inverse "
                "moves copies, photographs and standing answers")
        app.dependency_overrides[get_journal] = _always(
            Journal(store=map_undo_store, ids=id_gen, clock=clock,
                    books=book_store, decisions=decision_store,
                    duplicates=duplicate_queue))


def create_app(
    principal_provider: Callable[[], Principal],
    *,
    docs: bool = True,
    book_store: BookStore | None = None,
    clock: Clock | None = None,
    id_gen: IdGen | None = None,
    shelf_store: ShelfStore | None = None,
    map_store: MapStore | None = None,
    map_undo_store: MapUndoStore | None = None,
    blob_store: BlobStore | None = None,
    read_store: ReadStore | None = None,
    decision_store: DecisionStore | None = None,
    duplicate_queue: DuplicateQueue | None = None,
    reader: Reader | None = None,
    job_runner: JobRunner | None = None,
    tenancy_store: TenancyStore | None = None,
    auth_store: AuthStore | None = None,
    mailer: Mailer | None = None,
    invite_store: InviteStore | None = None,
    oauth_state_store: OAuthStateStore | None = None,
    identity_providers: dict | None = None,
    session_secure: bool | None = None,
    visitor_header: str | None = None,
    web_dist: Path | None = None,
    root_path: str = "",
    lifespan: Callable | None = None,
) -> FastAPI:
    """Build the product API.

    Takes PORTS, never adapters (H1) — ``app/main.py`` decides which
    implementation satisfies each, and the layering test enforces that this
    module never imports one.

    :param principal_provider: request-scoped identity; FastAPI may inject
        request state into it, so it follows the normal dependency rules.
    :param book_store: persistence. Optional only so a caller that just wants
        the OpenAPI document doesn't have to build one; a route that needs it
        without it bound fails loudly rather than serving nothing.
    :param web_dist: built client assets to serve in production. ``None`` in
        dev, where Vite serves the client and proxies ``/api`` here.
    :param root_path: the URL prefix the whole product lives under when it
        shares a domain with something else (``/booksnap`` on
        ``malinvishne.com/booksnap``). ``""`` means the domain root. Starlette
        strips it from an incoming path that carries it and leaves one that
        does not alone, so the proxy in front need not rewrite anything —
        and the two places that BUILD a browser-facing path (the OAuth
        redirects and the OAuth cookie) read it back off the request scope.
    :param lifespan: start-up/shutdown context, for checks that must refuse
        to SERVE without refusing to IMPORT — the contract tool and the
        pre-commit hook both import ``app.main``.
    """
    app = FastAPI(
        lifespan=lifespan,
        title=API_TITLE,
        version=__version__,
        root_path=root_path,
        # Every route is versioned (H3). The prefix lives on the router, not
        # on each path, so an unversioned route cannot be added by accident.
        openapi_url="/api/v1/openapi.json",
        # ⚠ The docs page loads swagger-ui from a CDN, unpinned — a script
        # that runs same-origin with a 90-day session cookie since P4.1b
        # (security review). Off by default; BOOKSNAP_DOCS=1 opts a dev
        # machine in. The OpenAPI document itself stays on — the contract
        # tooling reads it and it carries no credential.
        docs_url="/api/v1/docs" if docs else None,
        redoc_url=None,
    )
    app.include_router(meta.router, prefix=API_PREFIX)
    # PRE-AUTH, the narrowest scope of all: these are the routes a caller
    # uses to BECOME a principal (see the router's own docstring, and the
    # closed _PRE_AUTH list in tests/test_api.py).
    app.include_router(auth.router, prefix=API_PREFIX)
    # User-scoped, unlike every other router here — these are the routes a
    # caller uses to find out which libraries it may name (see the router's
    # own ⚠⚠, and the closed exemption list in tests/test_api.py).
    app.include_router(libraries.router, prefix=API_PREFIX)
    # User-scoped too (P4.3): membership is a fact about the ACCOUNT.
    app.include_router(members.router, prefix=API_PREFIX)
    app.include_router(books.router, prefix=API_PREFIX)
    app.include_router(shelves.router, prefix=API_PREFIX)
    app.include_router(shelves.captures, prefix=API_PREFIX)
    app.include_router(images.router, prefix=API_PREFIX)
    app.include_router(reads.router, prefix=API_PREFIX)
    app.include_router(duplicates.router, prefix=API_PREFIX)
    # P6.2: the physical map. Last of the library-scoped routers, and the
    # only one whose writes declare EDIT_MAP — §4.2's row 7, in the policy
    # matrix since P4.0 waiting for exactly these routes.
    app.include_router(map.router, prefix=API_PREFIX)

    bind_ports(
        app,
        principal_provider=principal_provider,
        book_store=book_store, clock=clock, id_gen=id_gen,
        shelf_store=shelf_store, map_store=map_store,
        map_undo_store=map_undo_store,
        blob_store=blob_store,
        read_store=read_store, decision_store=decision_store,
        duplicate_queue=duplicate_queue, reader=reader,
        job_runner=job_runner, tenancy_store=tenancy_store,
        auth_store=auth_store, mailer=mailer, invite_store=invite_store,
        oauth_state_store=oauth_state_store,
        identity_providers=identity_providers,
        session_secure=session_secure,
        visitor_header=visitor_header,
    )

    # Static client last: mounting at "/" first would shadow the API routes.
    # Same ordering hazard as booksnap/server.py:1018.
    if web_dist is not None and web_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")

    return app
