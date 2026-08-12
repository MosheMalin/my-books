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

import hashlib
import os
from dataclasses import replace
from pathlib import Path

from app.adapters.booksnap_reader import BooksnapReader
from app.adapters.dev_identity import DevPrincipal, SystemClock, UuidIdGen
from app.adapters.disk_blobs import DiskBlobStore
from app.adapters.queued_jobs import QueuedJobRunner
from app.adapters.sqlite_store import (
    SqliteBookStore,
    SqliteDecisionStore,
    SqliteDuplicateQueue,
    SqliteReadStore,
    SqliteShelfStore,
    SqliteTenancyStore,
)
from app.api.app import create_app
from app.domain import Library, Membership, Role, User, new_account

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


def _bootstrap_dev_user(tenancy: SqliteTenancyStore, principal) -> None:
    """Make the dev principal a real, stored user with a real membership.

    P3.1's resolver serves ``principal.library`` without a store lookup (the
    dev-trusted case), but ``GET /libraries`` deliberately does NOT patch that
    library into its answer — one copy of that rule, in one module. So the
    switcher would be missing the very library on screen unless the row
    exists. Creating it here is what keeps the two in step, and
    ``test_the_library_meta_resolves_is_always_one_the_switcher_lists`` is
    what fails if this is dropped.

    It also names the library that schema v12 backfilled. The migration
    deliberately leaves ``label`` blank — it cannot know what the owner calls
    their collection, and an invented English "My library" would be our string
    in a Hebrew switcher. The name comes from the same env var that has been
    producing the label on screen since P1.0, so nothing visibly changes.

    Idempotent, and it never renames a library the owner has named: only a
    blank label is filled in. P4.1 replaces this whole function with a real
    sign-up.

    ⚠ Since P3.7b it mints the ACCOUNT too, because that is now the thing a
    membership names. On the owner's own database this branch never fires —
    schema v14 derived an account from the existing membership graph — so what
    it really covers is a database with no tenancy rows at all: a fresh clone,
    a test, a `work/` someone deleted. The id is derived from the library id
    rather than random for the same reason v14's is: running this twice
    against the same file must not produce two customers.
    """
    user = tenancy.get_user(principal.id)
    if user is None:
        user = User(id=principal.id)
        tenancy.save_user(user)
    ref = principal.library
    library = tenancy.get_library(ref.id)
    if library is None:
        account_id = _dev_account_id(ref.id)
        if tenancy.get_account(account_id) is None:
            account, first = new_account(id=account_id, owner=user)
            tenancy.save_account(account)
            tenancy.save_membership(first)
        tenancy.save_library(
            Library(id=ref.id, account_id=account_id, label=ref.label)
        )
        library = tenancy.get_library(ref.id)
    elif not library.label and ref.label:
        library = replace(library, label=ref.label)
        tenancy.save_library(library)
    if library is not None and tenancy.membership(
        principal.id, library.account_id
    ) is None:
        # ADMIN: this is the household's own owner, and §4.2 puts every
        # capability behind that role. P3.2 gives the role meaning; the
        # composition root only has to store the true one.
        tenancy.save_membership(
            Membership(principal.id, library.account_id, Role.ADMIN)
        )


def _dev_account_id(library_id: str) -> str:
    """Derived, never random — see :func:`_bootstrap_dev_user`.

    Mirrors the SHAPE of ``app.adapters.migrations._account_id`` without
    importing it, deliberately: a migration's ids are frozen history the
    moment they are written to somebody's file, and a composition root that
    called into that function would make a future edit there silently rewrite
    what this one answers.

    ⚠ They currently agree by VALUE too, for a one-library group — which is
    the only shape this function is ever asked for. That is a coincidence
    worth knowing rather than a contract: if either changes, a bootstrapped
    database and a migrated one simply get different account ids, and neither
    is wrong.
    """
    return hashlib.blake2s(
        library_id.encode("utf-8"), digest_size=16
    ).hexdigest()


def build() -> object:
    """Bind adapters to ports and return the ASGI app."""
    # One instance is correct today (a hardcoded dev identity is immutable and
    # request-independent). P4.1 replaces this with a per-request session read;
    # the signature does not change, which is the point of the stub.
    principal = DevPrincipal()
    path = db_path()
    blobs = DiskBlobStore(blob_root())
    books = SqliteBookStore(path)
    tenancy = SqliteTenancyStore(path)
    _bootstrap_dev_user(tenancy, principal)
    return create_app(
        principal_provider=lambda: principal,
        # P3.1: users, libraries and memberships — the SIXTH aggregate in
        # this one file, and the sharpest version of the reason they share it.
        # "May this person see this?" and "what is there to see?" must never be
        # answerable from two databases that could disagree about the moment.
        tenancy_store=tenancy,
        book_store=books,
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
        # read, and to save the spine crops a read produces. It also takes the
        # book store, so the owner's already-confirmed books join the retrieval
        # chain: a book confirmed once should match instantly on every later
        # shelf, which is what the tuning server gets from ConfirmedCatalog.
        reader=BooksnapReader(blob_store=blobs, book_store=books),
        # P3.4: a bounded queue with per-tenant round-robin fairness. Two
        # workers on a 4-core machine that is also serving HTTP — a read is
        # either engine-CPU (spines) or a paid API call (llmpage), and ten at
        # once helps neither. One instance here, on the composition root, is
        # what H2/§1.3 asks for — every job's state lives on THIS object,
        # never a module global.
        job_runner=QueuedJobRunner(workers=2),
        clock=SystemClock(),
        id_gen=UuidIdGen(),
        web_dist=WEB_DIST,
    )


app = build()
