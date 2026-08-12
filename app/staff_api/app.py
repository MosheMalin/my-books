# -*- coding: utf-8 -*-
"""The system-admin API: ``/api/staff/v1``.

Read-only and cross-tenant. See the package docstring for why this is a
separate application rather than a role inside the product API.

⚠ **The credential is the whole security model here, and it is not the same
one the product uses.** `/api/v1` has no authentication at all — a deliberate
single-household trade until pillar 4 — and that trade does NOT carry over: a
route that returns every user and every household's book list is a
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
    RANK_NAMES, RANKED_SCAN_CAP, SchemaMismatch, StaffQueries, WORK_SORTS,
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

    #: CUSTOMERS. Distinct from `users` (people) and `libraries`
    #: (collections) — three counts the console drew as two until P3.7b.
    accounts: int
    #: Accounts with members but no admin: nobody can invite, re-role or
    #: rename. Should always be zero; a number here already happened.
    accounts_without_admin: int = 0
    users: int
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
    image_files: int = Field(
        description="Files under the blob root, renditions and sidecars "
                    "included — what the disk actually holds. Zero when no "
                    "blob root is configured (the database and the photographs "
                    "can live on different machines).",
    )
    image_bytes: int
    blobs_visible: bool = Field(
        description="This process can see the blob tree. When false the two "
                    "figures above are zero because nobody looked, not "
                    "because nothing is there — and every image reports "
                    "`present: false` for the same reason.",
    )
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
    account_id: str
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
    image_files: int = 0
    image_bytes: int = 0


class AccountDTO(BaseModel):
    """One customer, with every figure summed over the libraries it owns."""

    id: str
    label: str
    created_at: str | None = None
    libraries: int
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
    image_files: int = 0
    image_bytes: int = 0


class MembershipDTO(BaseModel):
    account_id: str
    role: str
    joined_at: str | None = None


class UserDTO(BaseModel):
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
        description="A ranked search stopped at the scan cap: `total` is "
                    "honest, but the rows were ranked over an arbitrary "
                    "capped slice, so the best match may not be on any page "
                    "you can reach. Narrow the query.",
    )


class WorkDTO(BaseModel):
    """One book across every tenant — the console's unit since revision 4.

    ⚠ There is no `library_id` here, and that is the point of the type. A
    system console's question about a book is *how widespread is it*, not
    *whose is it*; the per-household instances are a second call
    (`/works/instances`), because acting on one is a different, narrower job.
    """

    key: str = Field(description="`app.domain.text.book_key` — "
                                 "`normalize(title)|normalize(author)`. Opaque "
                                 "to the client; pass it back verbatim.")
    title: str
    author: str
    status: str = Field(description="The STRONGEST §5.1 claim any household "
                                    "makes about this work.")
    mixed: bool = Field(description="Instances disagree about status. A work "
                                    "manual in one house and auto in another "
                                    "has no single status, and hiding that "
                                    "would answer 'anything unapproved?' "
                                    "wrongly.")
    libraries: int = Field(description="How many libraries hold it. Unaffected "
                                       "by the filters — see the query's note "
                                       "on HAVING vs WHERE.")
    copies: int
    first_added: str | None = None
    last_added: str | None = None


class WorkPageDTO(BaseModel):
    items: list[WorkDTO]
    total: int
    offset: int
    limit: int
    truncated: bool = Field(
        description="A ranked search stopped at the scan cap: `total` is "
                    "honest, but the rows were ranked over an arbitrary "
                    "capped slice, so the best match may not be on any page "
                    "you can reach. Narrow the query.",
    )


class ImageDTO(BaseModel):
    """One photograph — the console's unit since revision 4.

    ⚠ **This replaced `ShelfDTO`, and the replacement is the point.** VISION
    §4.1a records that "one image = one shelf" is a PLACEHOLDER with a recorded
    exit (P2.1): intake mints a shelf identity per photograph until pillar 6's
    map can say two photographs are the same piece of wood. A console listing
    shelves was therefore listing photographs under a noun they had not earned.
    So the image leads, and `shelf_id`/`depth`/`order` are reported as the SLOT
    it is currently filed at — the pair pillar 6 replaces with a real address.

    ⚠ **No bytes are served by this service, only facts about them.** An
    operator looking at a household's actual photographs is a larger power than
    counting them; the console renders a thumbnail only for a library the
    operator is a member of, through the product API, exactly as the household
    client does.
    """

    id: str = Field(description="The capture id. There is no separate image "
                                "entity yet — a capture IS a photograph filed "
                                "somewhere, and `image_key` is its content "
                                "address.")
    library_id: str
    image_key: str | None = None
    captured_at: str | None = None
    shelf_id: str
    shelf_label: str
    depth: int
    order: int
    present: bool = Field(description="The bytes are on disk. False is a real "
                                      "finding — a photograph the household "
                                      "can no longer see — not a blank cell. "
                                      "⚠ Only when `blobs_visible`; otherwise "
                                      "it means nobody looked.")
    bytes: int
    width: int
    height: int
    content_type: str
    filename: str
    reads: int = Field(description="Runs that CONSUMED this photograph "
                                   "(`reads.capture_ids`), which is not the "
                                   "same as runs that found something in it — "
                                   "a run that found nothing is exactly what "
                                   "an operator is looking for.")
    findings: int
    auto: int
    review: int
    unmatched: int
    last_read: str | None = None


class ImagePageDTO(BaseModel):
    items: list[ImageDTO]
    total: int
    offset: int
    limit: int
    blobs_visible: bool = Field(
        description="⚠ Read this BEFORE `present`. When false, the service "
                    "cannot see the blob tree at all (the database and the "
                    "photographs may live on different machines), so every "
                    "row reports `present: false` and zero bytes — which is "
                    "'we did not look', not 'they are gone'. A console that "
                    "conflated the two would announce that every photograph "
                    "in every tenant was lost, and hide a real loss among "
                    "the noise.",
    )


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
             dependencies=guard, summary="Every customer in the system")
    def accounts() -> list[AccountDTO]:
        """The operator's own word for a tenant, finally naming one.

        Until P3.7b the console rendered a LIBRARY row here and labelled
        it "account", because a library was the tenant; the id was shown
        underneath so the mapping stayed visible rather than hidden. This
        route retires that. A customer owning two collections is one row
        now, and its numbers are the sum of theirs.
        """
        return [AccountDTO(**vars(row)) for row in queries.accounts()]

    @app.get("/api/staff/v1/users", response_model=list[UserDTO],
             dependencies=guard, summary="Every user, with their memberships")
    def users() -> list[UserDTO]:
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
            UserDTO(
                id=row.id, display_name=row.display_name, email=row.email,
                created_at=row.created_at,
                memberships=[
                    MembershipDTO(account_id=m.account_id, role=m.role,
                                  joined_at=m.joined_at)
                    for m in row.memberships
                ],
            )
            for row in queries.users()
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
        if book_status is not None and book_status not in RANK_NAMES:
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

    @app.get("/api/staff/v1/works", response_model=WorkPageDTO,
             dependencies=guard, summary="Books aggregated across every tenant")
    def works(
        q: str = "",
        library_id: str | None = None,
        book_status: str | None = Query(default=None, alias="status"),
        sort: str = "title",
        ascending: bool = True,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> WorkPageDTO:
        """⚠ `library_id` and `status` SELECT works; they never narrow what a
        work reports. "In 3 libraries" means three whatever the filter says —
        see `StaffQueries.works` for why that had to be a `HAVING`."""
        if book_status is not None and book_status not in RANK_NAMES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "status must be auto, approved or manual")
        if sort not in WORK_SORTS:
            # ⚠ A 400, not a silent fall back to title order. `/books` sorts by
            # `recently_added` and a work's date key is `first_added`; a caller
            # carrying the wrong spelling would otherwise be served a plausible
            # wrong ordering with nothing on screen to say so.
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"sort must be one of {', '.join(WORK_SORTS)}")
        items, total = queries.works(
            q=q, library_id=library_id, status=book_status, sort=sort,
            ascending=ascending, limit=limit, offset=offset,
        )
        return WorkPageDTO(
            items=[WorkDTO(**vars(row)) for row in items],
            total=total, offset=offset, limit=limit,
            truncated=bool(q.strip()) and total > RANKED_SCAN_CAP,
        )

    @app.get("/api/staff/v1/works/instances", response_model=list[BookDTO],
             dependencies=guard, summary="Every household's copy of one work")
    def work_instances(key: str) -> list[BookDTO]:
        """The key travels as a QUERY parameter, not a path segment.

        It is `normalize(title)|normalize(author)` — Hebrew, spaces, a pipe,
        and whatever else a title contains. A path segment would need encoding
        the console cannot get wrong only by being careful, and `/works/<key>`
        would additionally collide with this very route the day a work is
        called "instances".
        """
        return [BookDTO(**vars(row)) for row in queries.work_instances(key)]

    @app.get("/api/staff/v1/images", response_model=ImagePageDTO,
             dependencies=guard, summary="Photographs across every tenant")
    def images(
        library_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> ImagePageDTO:
        """⚠ This REPLACED `/libraries/{id}/shelves`, and the replacement is
        the item, not a rename. See `ImageDTO`: a shelf is a placeholder minted
        per photograph until pillar 6, so a console shelf list was a photograph
        list wearing the wrong noun.

        Cross-tenant, so it could not be `/api/v1/...`: that resolves the
        caller's membership, and a system administrator is a member of nothing.
        An empty page and a library that does not exist look the same here,
        deliberately — the library list is the authority on which ids are real.
        """
        items, total = queries.images(library_id=library_id, limit=limit,
                                      offset=offset)
        return ImagePageDTO(items=[ImageDTO(**vars(row)) for row in items],
                            total=total, offset=offset, limit=limit,
                            blobs_visible=queries.blobs.visible)

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
