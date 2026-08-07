# -*- coding: utf-8 -*-
"""Composition root — the ONE module allowed to import across every layer.

``tests/test_layering.py`` names this file as its single exemption. Everything
else obeys the one-way rule; wiring has to happen somewhere, and confining it
to one file is what keeps "who constructs the adapters?" from leaking back
into the api layer.

Run it with::

    uvicorn app.main:app --port 8757

Port 8757 by convention, one above the tuning server's 8756, so both can run
side by side through pillars 1-2 (Risk 1 in the plan).

Environment:

    BOOKSNAP_DB     product database file. Defaults to ``<work>/product.db``.
    BOOKSNAP_WORK   existing convention, reused so dev and server agree.

The database lives under ``work/`` because that directory is already gitignored
and already the "state this machine produced" directory. It is a DIFFERENT
file from the tuning server's ``store.json`` — the product never writes into
the run archive, and the run archive is not the product's source of truth.
Populate it once with::

    python tools/import_legacy.py --db work/product.db
"""
from __future__ import annotations

import os
from pathlib import Path

from app.adapters.dev_identity import DevPrincipal, SystemClock, UuidIdGen
from app.adapters.sqlite_store import SqliteBookStore
from app.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = REPO_ROOT / "app" / "web" / "dist"


def db_path() -> Path:
    explicit = os.environ.get("BOOKSNAP_DB")
    if explicit:
        return Path(explicit)
    work = Path(os.environ.get("BOOKSNAP_WORK", REPO_ROOT / "work"))
    return work / "product.db"


def build() -> object:
    """Bind adapters to ports and return the ASGI app."""
    # One instance is correct today (a hardcoded dev identity is immutable and
    # request-independent). P4.1 replaces this with a per-request session read;
    # the signature does not change, which is the point of the stub.
    principal = DevPrincipal()
    return create_app(
        principal_provider=lambda: principal,
        book_store=SqliteBookStore(db_path()),
        clock=SystemClock(),
        id_gen=UuidIdGen(),
        web_dist=WEB_DIST,
    )


app = build()
