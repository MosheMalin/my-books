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
    get_invite_store,
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
    meta,
    reads,
    shelves,
)
from app.ports import Clock, IdGen, Principal
from app.ports.auth import AuthStore, Mailer
from app.ports.invites import InviteStore
from app.ports.blobs import BlobStore
from app.ports.decisions import DecisionStore
from app.ports.duplicates import DuplicateQueue
from app.ports.jobs import JobRunner
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
    for dep, impl in ((get_book_store, book_store), (get_clock, clock),
                      (get_id_gen, id_gen), (get_shelf_store, shelf_store),
                      (get_blob_store, blob_store), (get_read_store, read_store),
                      (get_decision_store, decision_store),
                      (get_duplicate_queue, duplicate_queue),
                      (get_reader, reader), (get_job_runner, job_runner),
                      (get_tenancy_store, tenancy_store),
                      (get_auth_store, auth_store), (get_mailer, mailer),
                      (get_invite_store, invite_store)):
        if impl is not None:
            app.dependency_overrides[dep] = _always(impl)


def create_app(
    principal_provider: Callable[[], Principal],
    *,
    docs: bool = True,
    book_store: BookStore | None = None,
    clock: Clock | None = None,
    id_gen: IdGen | None = None,
    shelf_store: ShelfStore | None = None,
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
    web_dist: Path | None = None,
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
    """
    app = FastAPI(
        title=API_TITLE,
        version=__version__,
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

    bind_ports(
        app,
        principal_provider=principal_provider,
        book_store=book_store, clock=clock, id_gen=id_gen,
        shelf_store=shelf_store, blob_store=blob_store,
        read_store=read_store, decision_store=decision_store,
        duplicate_queue=duplicate_queue, reader=reader,
        job_runner=job_runner, tenancy_store=tenancy_store,
        auth_store=auth_store, mailer=mailer, invite_store=invite_store,
    )

    # Static client last: mounting at "/" first would shadow the API routes.
    # Same ordering hazard as booksnap/server.py:1018.
    if web_dist is not None and web_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")

    return app
