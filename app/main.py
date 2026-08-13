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
from app.adapters.console_mailer import ConsoleMailer
from app.adapters.smtp_mailer import SmtpMailer
from app.adapters.dev_identity import SystemClock, UuidIdGen
from app.adapters.disk_blobs import DiskBlobStore
from app.adapters.queued_jobs import QueuedJobRunner
from app.adapters.sqlite_store import (
    SqliteAuthStore,
    SqliteInviteStore,
    SqliteOAuthStateStore,
    SqliteBookStore,
    SqliteDecisionStore,
    SqliteDuplicateQueue,
    SqliteReadStore,
    SqliteShelfStore,
    SqliteTenancyStore,
)
from app.api.app import create_app
from app.api.principal import session_principal

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


def _lan_base_url() -> str:
    """Where the sign-in link should land when BOOKSNAP_PUBLIC_URL is unset.

    `localhost:5173` on the PHONE is the phone (P4.1b's UX review, MAJOR
    8) — and capture is a phone flow, which is the stated reason the
    servers bind 0.0.0.0. Best-effort LAN address via a connectionless
    UDP socket (nothing is sent); localhost when the machine is offline.
    """
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 80))   # TEST-NET; no packet leaves
            return f"http://{probe.getsockname()[0]}:5173"
    except OSError:
        return "http://localhost:5173"


def blob_root() -> Path:
    """Where uploaded photos live.

    A DIFFERENT directory from the tuning server's ``work/runs/`` — that is its
    archive, and the product reads its own store or nothing. Sharing one would
    turn P3.5's tenant re-keying into a migration of somebody else's data.
    """
    explicit = os.environ.get("BOOKSNAP_BLOBS")
    return Path(explicit) if explicit else _work() / "product_blobs"


def _identity_providers() -> dict:
    """Google and Apple, each present only if CONFIGURED.

    Configuration decides, exactly like the mailer: a deployment with no
    Google client signs in by link, and the login screen asks which
    buttons exist rather than showing one that cannot work. Apple needs
    four values because its client secret is a signed JWT, not a string.
    """
    from app.adapters.oidc import AppleProvider, OidcProvider

    public = os.environ.get("BOOKSNAP_PUBLIC_URL") or _lan_base_url()
    providers: dict = {}

    google_id = os.environ.get("BOOKSNAP_GOOGLE_CLIENT_ID", "").strip()
    if google_id:
        providers["google"] = OidcProvider(
            client_id=google_id,
            client_secret=os.environ.get("BOOKSNAP_GOOGLE_CLIENT_SECRET", ""),
            redirect_uri=f"{public}/api/v1/auth/oauth/google/callback",
        )

    apple_id = os.environ.get("BOOKSNAP_APPLE_CLIENT_ID", "").strip()
    apple_key = os.environ.get("BOOKSNAP_APPLE_PRIVATE_KEY", "").strip()
    if apple_id and apple_key:
        providers["apple"] = AppleProvider(
            client_id=apple_id,
            team_id=os.environ.get("BOOKSNAP_APPLE_TEAM_ID", ""),
            key_id=os.environ.get("BOOKSNAP_APPLE_KEY_ID", ""),
            # A PEM is multi-line and .env is not: the key is stored with
            # literal backslash-n, and a PEM without real newlines does
            # not parse.
            private_key=apple_key.replace("\\n", "\n"),
            redirect_uri=f"{public}/api/v1/auth/oauth/apple/callback",
        )
    return providers


def _session_secure() -> bool:
    """Whether this deployment puts TLS in front.

    Accepts the spellings an operator actually types: a `.env` reading
    `BOOKSNAP_SESSION_SECURE=true` silently gave a NON-Secure 90-day
    cookie behind TLS before this (P4.4's security review) — failing open
    on a typo is the wrong direction for a flag whose whole job is
    tightening.
    """
    raw = os.environ.get("BOOKSNAP_SESSION_SECURE", "").strip().lower()
    if raw in ("", "0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    raise RuntimeError(
        f"BOOKSNAP_SESSION_SECURE={raw!r} is not a yes or a no; "
        f"use 1 or 0"
    )


def _mailer():
    """The real mailer when SMTP is configured, the dev one otherwise.

    Configuration decides, not a flag: a deployment that has an SMTP host
    wants mail, and a laptop that does not wants the link in its log. The
    Mailer PORT is what makes this the composition root's one-line choice
    rather than a branch inside a route (the credential-preflight rule).
    """
    host = os.environ.get("BOOKSNAP_SMTP_HOST", "").strip()
    public = os.environ.get("BOOKSNAP_PUBLIC_URL") or _lan_base_url()
    if not host:
        # ⚠ REFUSE in a deployed posture. ConsoleMailer prints the raw
        # sign-in link, which is the inversion its own module note says
        # must never reach production: with no SMTP configured, a public
        # server would put a live credential in the container log for
        # anyone who can read it (P4.4's security review). The same flag
        # that says "TLS is in front" says "this is not a laptop".
        if _session_secure():
            raise RuntimeError(
                "BOOKSNAP_SESSION_SECURE is set but no BOOKSNAP_SMTP_HOST: "
                "the dev mailer prints sign-in links to the log, which is "
                "not a thing to do on a deployed server. Configure SMTP "
                "(see .env.example) or unset BOOKSNAP_SESSION_SECURE."
            )
        return ConsoleMailer(public)
    return SmtpMailer(
        host=host,
        port=int(os.environ.get("BOOKSNAP_SMTP_PORT", "587")),
        username=os.environ.get("BOOKSNAP_SMTP_USER", ""),
        password=os.environ.get("BOOKSNAP_SMTP_PASSWORD", ""),
        sender=os.environ.get("BOOKSNAP_MAIL_FROM", "")
        or os.environ.get("BOOKSNAP_SMTP_USER", ""),
        base_url=public,
    )


def build() -> object:
    """Bind adapters to ports and return the ASGI app."""
    path = db_path()
    blobs = DiskBlobStore(blob_root())
    books = SqliteBookStore(path)
    tenancy = SqliteTenancyStore(path)
    return create_app(
        docs=os.environ.get("BOOKSNAP_DOCS") == "1",
        # P4.1b: identity is the session cookie, resolved per request —
        # the dev principal and its bootstrap are DELETED, not parked
        # behind a flag (a flag that restores an auth bypass is the
        # landmine this item removes). A fresh database now starts EMPTY:
        # sign-in mints the bare user, P4.1c's sign-up mints the account
        # and first library.
        principal_provider=session_principal,
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
        # P4.1a: sessions and login tokens, same file as everything else — a
        # session and the user it authenticates must never disagree about
        # the moment. The mailer is the DEV one until P4.4 deploys a real
        # provider; its base URL is Vite's dev client, which serves the
        # login route the link lands on.
        auth_store=SqliteAuthStore(path),
        invite_store=SqliteInviteStore(path),
        oauth_state_store=SqliteOAuthStateStore(path),
        identity_providers=_identity_providers(),
        mailer=_mailer(),
        # TLS is in front only when the deployment says so (P4.4's compose
        # file sets it); a Secure cookie on plain HTTP is silently dropped.
        session_secure=_session_secure(),
        clock=SystemClock(),
        id_gen=UuidIdGen(),
        web_dist=WEB_DIST,
    )


app = build()
