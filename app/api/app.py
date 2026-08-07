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
from app.api.deps import get_principal
from app.api.routers import meta
from app.ports import Principal

API_TITLE = "booksnap product API"


def create_app(
    principal_provider: Callable[[], Principal],
    web_dist: Path | None = None,
) -> FastAPI:
    """Build the product API.

    :param principal_provider: request-scoped identity; FastAPI may inject
        request state into it, so it follows the normal dependency rules.
    :param web_dist: built client assets to serve in production. ``None`` in
        dev, where Vite serves the client and proxies ``/api`` here.
    """
    app = FastAPI(
        title=API_TITLE,
        version=__version__,
        # Every route is versioned (H3). The prefix lives on the router, not
        # on each path, so an unversioned route cannot be added by accident.
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )
    app.include_router(meta.router, prefix=API_PREFIX)
    app.dependency_overrides[get_principal] = principal_provider

    # Static client last: mounting at "/" first would shadow the API routes.
    # Same ordering hazard as booksnap/server.py:1018.
    if web_dist is not None and web_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")

    return app
