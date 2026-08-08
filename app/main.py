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

from app.adapters.booksnap_reader import BooksnapReader
from app.adapters.dev_identity import DevPrincipal, SystemClock, UuidIdGen
from app.adapters.disk_blobs import DiskBlobStore
from app.adapters.inprocess_jobs import InProcessJobRunner
from app.adapters.sqlite_store import (
    SqliteBookStore,
    SqliteDecisionStore,
    SqliteDuplicateQueue,
    SqliteReadStore,
    SqliteShelfStore,
)
from app.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = REPO_ROOT / "app" / "web" / "dist"


def _load_dotenv() -> None:
    """Read ``REPO_ROOT/.env`` into ``os.environ`` (existing vars win).

    A COPY of ``booksnap/server.py``'s, not an import — the product must not
    import the tuning server (that is the whole point of H1, and the layering
    test enforces it). Eight lines duplicated is the intended cost.

    Without this the product had no ``ANTHROPIC_API_KEY``/``NLI_API_KEY`` at
    all: `.env` was read by the tuning server only, so `:8756` could reach the
    catalogues and the LLM reader while `:8757` silently could not. It went
    unnoticed because the default mode was the free offline one — the moment
    llmpage became the default, every read would have failed inside a worker
    thread with a missing key.

    Deliberately tiny — no dependency, and it never logs or echoes a value.
    """
    path = REPO_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()


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
    blobs = DiskBlobStore(blob_root())
    return create_app(
        principal_provider=lambda: principal,
        book_store=SqliteBookStore(path),
        # The SAME file, three aggregates now. Separate ports because their
        # lifetimes are independent (a shelf exists before any book is on it;
        # a read is created, runs, and settles), separate stores because a
        # Postgres move should not have to port all three at once — but one
        # database, so a capture, the reads of it and the books they produce
        # cannot end up in different places.
        shelf_store=SqliteShelfStore(path),
        read_store=SqliteReadStore(path),
        # P2.5: a fourth aggregate, same file, same reasoning — a decision
        # made about a claim from a specific read must live next to that
        # read, not in a database a Postgres move could split off alone.
        decision_store=SqliteDecisionStore(path),
        # P2.6: a fifth aggregate, same file, same reasoning again — a
        # queued question and the decision that eventually closes it must
        # never end up in different databases.
        duplicate_queue=SqliteDuplicateQueue(path),
        # Bytes on disk, keys in rows (D1). The layout is already P3.5's, so
        # pillar 3 inherits retention and orphan work, not a path migration.
        blob_store=blobs,
        # BooksnapReader wraps booksnap.Pipeline (P2.4) — it needs the SAME
        # blob store to turn a capture's image_id into bytes the engine can
        # read, and to save the spine crops a read produces.
        reader=BooksnapReader(blob_store=blobs),
        # In-process, single-user (P2.4; P3.4 replaces it with a real queue).
        # One instance here, on the composition root, is what H2/§1.3 asks
        # for — every job's state lives on THIS object, never a module global.
        job_runner=InProcessJobRunner(),
        clock=SystemClock(),
        id_gen=UuidIdGen(),
        web_dist=WEB_DIST,
    )


app = build()
