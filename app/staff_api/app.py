# -*- coding: utf-8 -*-
"""The system-admin API: ``/api/staff/v1``.

Read-only and cross-tenant. See the package docstring for why this is a
separate application rather than a role inside the product API.

⚠ **The credential is the whole security model here, and it is not the same
one the product uses.** `/api/v1` has no authentication at all — a deliberate
single-household trade until pillar 4 — and that trade does NOT carry over: a
route that returns every account and every household's book list is a
different exposure from one that returns your own. So this service reads
``BOOKSNAP_STAFF_TOKEN`` and, when it is set, refuses every request that does
not present it.

When it is UNSET the service still serves — refusing to start would leave the
owner with a console that cannot be opened and no obvious reason — but it says
so in ``GET /api/staff/v1/overview`` (``authenticated: false``), and the client
puts that on screen where it cannot be missed. That is the same "say the true
thing rather than pretend" posture the rest of the product takes about its own
missing login.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.staff_api.queries import (
    RANKED_SCAN_CAP, SchemaMismatch, StaffQueries,
)

#: Header the console presents its token in. ``Authorization: Bearer …`` is
#: accepted too; this one exists because it survives a proxy that rewrites
#: Authorization, and because it reads as obviously not-a-user-login.
STAFF_HEADER = "X-Booksnap-Staff"

#: Env var holding the shared secret. Absent = unauthenticated, and reported.
STAFF_TOKEN_ENV = "BOOKSNAP_STAFF_TOKEN"


# --- DTOs -------------------------------------------------------------------
#
# ⚠ These are now the SOURCE of a committed contract, not a shape kept honest
# by reading. `tools/api_contract.py` publishes them as
# `app/staff_api/openapi.json` and generates the console's types from it
# (`app/admin/src/api/staff-schema.d.ts`) — the same pipeline and the same
# committed-artefact rule the product API has followed since D3.
#
# Until 2026-08-10 the console MIRRORED them by hand, because the build that
# created this service could not touch the contract tool. Renaming a field
# here is a compile error in the console now; before, it was an `undefined`
# appearing in a table.
#
# So: after any change below, run `python tools/api_contract.py --write` and
# commit both artefacts. `--check` fails the commit on drift.

class OverviewDTO(BaseModel):
    """System-wide totals. Every figure spans every tenant."""

    accounts: int
    libraries: int
    memberships: int
    books: int
    copies: int
    shelves: int
    captures: int
    reads: int
    duplicates: int
    lent_out: int
    auto: int = Field(description="Books nobody has approved (§5.1's lowest "
                                  "rung). `manual` outranks `approved`, so "
                                  "this — and only this — is 'awaiting'.")
    approved: int
    manual: int
    authenticated: bool = Field(
        description="False when no BOOKSNAP_STAFF_TOKEN is configured, i.e. "
                    "anyone who can reach this port can read every tenant.",
    )
    orphan_libraries: list[str] = Field(
        description="Libraries with no membership at all — nobody can see or "
                    "administer them. Should always be empty; `new_library` "
                    "mints an admin membership in the same call to keep it so.",
    )


class LibraryDTO(BaseModel):
    id: str
    label: str
    created_at: str | None = None
    members: int
    admins: int
    books: int
    copies: int
    auto: int
    approved: int
    manual: int
    shelves: int
    captures: int
    reads: int
    duplicates: int
    lent_out: int
    last_activity: str | None = None


class MembershipDTO(BaseModel):
    library_id: str
    role: str
    joined_at: str | None = None


class AccountDTO(BaseModel):
    id: str
    display_name: str
    email: str | None = None
    created_at: str | None = None
    memberships: list[MembershipDTO]


class BookDTO(BaseModel):
    id: str
    library_id: str
    title: str
    author: str
    status: str
    copy_count: int
    shelf_count: int
    added_at: str | None = None


class BookPageDTO(BaseModel):
    items: list[BookDTO]
    total: int
    offset: int
    limit: int
    truncated: bool = Field(
        description="A ranked search stopped at the scan cap, so `total` is "
                    "honest but pages past the cap are not reachable. Narrow "
                    "the query.",
    )


class ShelfDTO(BaseModel):
    id: str
    library_id: str
    label: str
    depth_count: int
    virtual: bool
    captures: int
    books: int = Field(description="DISTINCT books with a copy standing here, "
                                   "not copies — two copies of one book is "
                                   "one book on the shelf.")
    last_read: str | None = None


class ReadDTO(BaseModel):
    id: str
    library_id: str
    shelf_id: str
    shelf_label: str
    depth: int
    mode: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    claims: int


# --- the app ----------------------------------------------------------------

def create_app(queries: StaffQueries) -> FastAPI:
    """Build the service around an already-constructed read model.

    Injected rather than read from the environment here, for the same reason
    `app.api.app.create_app` takes its ports: a test binds a temporary
    database without touching the process environment, and there is no
    module-level state for two apps to share.
    """
    app = FastAPI(
        title="booksnap staff API",
        version="0.1.0",
        description="System administration, across every tenant. Read-only.",
    )

    configured = os.environ.get(STAFF_TOKEN_ENV, "").strip()

    def require_staff(
        x_booksnap_staff: Annotated[str | None, Header()] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        """Reject anything without the shared secret, when one is configured.

        ⚠ `secrets.compare_digest`, not `==`: a token compared with `==` leaks
        its prefix through timing, and this one opens every tenant.
        """
        if not configured:
            return
        presented = x_booksnap_staff or ""
        if not presented and authorization:
            scheme, _, rest = authorization.partition(" ")
            if scheme.lower() == "bearer":
                presented = rest.strip()
        if not presented or not secrets.compare_digest(presented, configured):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "a staff token is required; present it as "
                f"{STAFF_HEADER} or Authorization: Bearer …",
            )

    guard = [Depends(require_staff)]

    @app.get("/api/staff/v1/overview", response_model=OverviewDTO,
             dependencies=guard, summary="System-wide totals")
    def overview() -> OverviewDTO:
        return OverviewDTO(
            **queries.overview(),
            authenticated=bool(configured),
            orphan_libraries=list(queries.orphan_libraries()),
        )

    @app.get("/api/staff/v1/libraries", response_model=list[LibraryDTO],
             dependencies=guard, summary="Every library in the system")
    def libraries() -> list[LibraryDTO]:
        return [LibraryDTO(**vars(row)) for row in queries.libraries()]

    @app.get("/api/staff/v1/accounts", response_model=list[AccountDTO],
             dependencies=guard, summary="Every account, with its memberships")
    def accounts() -> list[AccountDTO]:
        """⚠ This is the route that has no equivalent in `/api/v1`, and could
        not have one: the product API answers *"which libraries may I name"*,
        never *"who is in the system"*.

        It reports identity and membership — who exists, and what they may
        reach. It deliberately does not report what any individual has been
        READING or photographing: "statistics about the users" is a fair thing
        for an operator to want, and a per-person activity feed of someone's
        own household is a different and much larger power. Aggregate figures
        live on the library rows instead.
        """
        return [
            AccountDTO(
                id=row.id, display_name=row.display_name, email=row.email,
                created_at=row.created_at,
                memberships=[
                    MembershipDTO(library_id=m.library_id, role=m.role,
                                  joined_at=m.joined_at)
                    for m in row.memberships
                ],
            )
            for row in queries.accounts()
        ]

    @app.get("/api/staff/v1/books", response_model=BookPageDTO,
             dependencies=guard, summary="Books across every tenant")
    def books(
        q: str = "",
        library_id: str | None = None,
        book_status: str | None = Query(default=None, alias="status"),
        sort: str = "title",
        ascending: bool = True,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> BookPageDTO:
        if book_status is not None and book_status not in ("auto", "approved",
                                                           "manual"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "status must be auto, approved or manual")
        items, total = queries.books(
            q=q, library_id=library_id, status=book_status, sort=sort,
            ascending=ascending, limit=limit, offset=offset,
        )
        return BookPageDTO(
            items=[BookDTO(**vars(row)) for row in items],
            total=total, offset=offset, limit=limit,
            truncated=bool(q.strip()) and total > RANKED_SCAN_CAP,
        )

    @app.get("/api/staff/v1/libraries/{library_id}/shelves",
             response_model=list[ShelfDTO], dependencies=guard,
             summary="One library's shelves")
    def shelves(library_id: str) -> list[ShelfDTO]:
        """⚠ Cross-tenant, so it cannot be `/api/v1/shelves`: that resolves the
        caller's membership, and a system administrator is a member of
        nothing. Note the consequence for the console — an EMPTY list and a
        library that does not exist look the same here, deliberately: this
        service has no reason to distinguish them, and the library list it
        came from is the authority on which ids are real."""
        return [ShelfDTO(**vars(row)) for row in queries.shelves(library_id)]

    @app.get("/api/staff/v1/reads", response_model=list[ReadDTO],
             dependencies=guard, summary="Recent reads, across every tenant")
    def reads(
        limit: int = Query(default=30, ge=1, le=200),
        library_id: str | None = None,
    ) -> list[ReadDTO]:
        return [ReadDTO(**vars(row))
                for row in queries.recent_reads(limit, library_id)]

    @app.exception_handler(SchemaMismatch)
    def _schema_moved(_request: object, exc: SchemaMismatch):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))

    @app.exception_handler(sqlite3.OperationalError)
    def _schema_moved_under_us(_request: object, exc: sqlite3.OperationalError):
        """⚠ This is what makes the handler above REACHABLE, and it was dead
        code until a review said so.

        `self_check()` runs once, in `StaffQueries.__init__` — so a schema that
        moves while this service is RUNNING (the product server migrating
        `work/product.db` under it, which is the normal way to deploy) could
        only ever surface as a raw `OperationalError`, i.e. a 500 with a SQL
        fragment in the log and nothing on screen. The 503 this service
        documents could not happen.

        So an operational error re-runs the shape check: if the database really
        has moved, the operator gets the named-columns message and a 503 that
        says *come back after a restart*; if it has not, the original error is
        re-raised untouched rather than dressed up as a schema problem it is
        not.
        """
        try:
            queries.self_check()
        except SchemaMismatch as moved:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, str(moved)) from exc
        raise exc

    return app
