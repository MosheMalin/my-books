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
    BOOKSNAP_BLOBS  uploaded photos. Defaults to ``<work>/product_blobs``.
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
from app.adapters.disk_blobs import DiskBlobStore
from app.adapters.sqlite_store import SqliteBookStore, SqliteShelfStore
from app.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = REPO_ROOT / "app" / "web" / "dist"


def _work() -> Path:
    return Path(os.environ.get("BOOKSNAP_WORK", REPO_ROOT / "work"))


def db_path() -> Path:
    explicit = os.environ.get("BOOKSNAP_DB")
    if explicit:
        return Path(explicit)
    return _work() / "product.db"


def blob_root() -> Path:
    """Where uploaded photos live.

    A DIFFERENT directory from the tuning server's ``work/runs/`` — that is its
    archive, and the product reads its own store or nothing. Sharing one would
    turn P3.5's tenant re-keying into a migration of somebody else's data.
    """
    explicit = os.environ.get("BOOKSNAP_BLOBS")
    return Path(explicit) if explicit else _work() / "product_blobs"


def build() -> object:
    """Bind adapters to ports and return the ASGI app."""
    # One instance is correct today (a hardcoded dev identity is immutable and
    # request-independent). P4.1 replaces this with a per-request session read;
    # the signature does not change, which is the point of the stub.
    principal = DevPrincipal()
    path = db_path()
    return create_app(
        principal_provider=lambda: principal,
        book_store=SqliteBookStore(path),
        # The SAME file, two aggregates. Separate ports because their
        # lifetimes are independent (a shelf exists before any book is on it),
        # separate stores because a Postgres move should not have to port both
        # at once — but one database, so a capture and the books it produces
        # cannot end up in different places.
        shelf_store=SqliteShelfStore(path),
        # Bytes on disk, keys in rows (D1). The layout is already P3.5's, so
        # pillar 3 inherits retention and orphan work, not a path migration.
        blob_store=DiskBlobStore(blob_root()),
        clock=SystemClock(),
        id_gen=UuidIdGen(),
        web_dist=WEB_DIST,
    )


app = build()
