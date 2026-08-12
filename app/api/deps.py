# -*- coding: utf-8 -*-
"""Request-scoped dependencies.

H2, verbatim: *there is exactly one function resolving principal -> library*.
That function is :func:`current_library`, and ``tests/test_api.py`` asserts
that every ``/api/v1`` route has it somewhere in its dependency chain — a new
route that reaches for "the" library instead fails the suite rather than
quietly working until pillar 3.

There is also **no module-level mutable state** here (H2, §1.3). The provider
is bound per-application via ``dependency_overrides`` in ``create_app``, not
stashed in a module global the way ``booksnap/server.py``'s job dict is.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.domain import Library, LibraryRef, Membership
from app.ports import Clock, IdGen, Principal
from app.ports.blobs import BlobStore
from app.ports.decisions import DecisionStore
from app.ports.duplicates import DuplicateQueue
from app.ports.jobs import JobRunner
from app.ports.reader import Reader
from app.ports.store import BookStore, ReadStore, ShelfStore
from app.ports.tenancy import TenancyStore

#: The header the client puts a library reference in, on every request (§1.3).
#: Chosen over a path prefix (``/api/v1/libraries/{id}/books``) at P1.0 and
#: kept here: a prefix would make the library part of every resource's own
#: address, so switching would rewrite every URL the client holds — including
#: the deep links (`#/book/<id>`) the hash router already stores.
#:
#: ⚠ The consequence, recorded rather than discovered later: a shared URL does
#: NOT carry the library. Opening someone else's deep link resolves it against
#: whichever library the receiving client has selected, and a book id from
#: another library reads as 404 (§4.2). Acceptable while a household has one
#: or two libraries; if links ever have to travel, the fix is a query
#: parameter the router honours, not a change of transport.
LIBRARY_HEADER = "X-Booksnap-Library"

#: The same reference, as a query parameter, for requests the BROWSER issues
#: rather than the client's own ``fetch()``.
#:
#: ⚠ This is not a convenience — without it the header transport is simply
#: WRONG for part of the product, and it shipped that way for an afternoon.
#: An ``<img src>`` and a download ``<a href>`` cannot carry a custom header:
#: the browser builds those requests itself. So every photo, every spine crop
#: and both export links resolved against the caller's DEFAULT library, and in
#: a second library they 404'd — a shelf photo that had just been read
#: correctly rendered as an empty box.
#:
#: The header stays the transport for everything else (the reasoning below
#: still holds); this is the escape hatch for the requests that cannot use it.
LIBRARY_PARAM = "library"


def get_principal() -> Principal:
    """Placeholder provider, replaced per-app by ``create_app``.

    Raising here rather than returning a default is deliberate: an app that
    forgot to bind an identity adapter must fail loudly on the first request,
    not silently serve someone else's library.
    """
    raise RuntimeError(
        "no Principal provider bound; build the app via app.api.app.create_app"
    )


def get_tenancy_store() -> TenancyStore:
    """Placeholder, same shape as every other port below.

    Declared before :func:`current_library` because the resolver depends on
    it: from P3.1 on, an app that serves the product needs to know which
    libraries exist, so an unbound one is a wiring gap and not a mode.
    """
    raise RuntimeError("no TenancyStore bound; build the app via create_app")


def current_library(
    request: Request,
    principal: Principal = Depends(get_principal),
    tenancy: TenancyStore = Depends(get_tenancy_store),
) -> LibraryRef:
    """The single principal -> library resolution point (H2).

    Until P3.1 this returned ``principal.library`` and nothing else — correct
    for one hardcoded library, and the reason every route was written to ask
    THIS function rather than reach for "the" library. Nothing above it
    changes now that it does real work; that was the whole point of the stub.

    The reference is read from the header, or — for requests the browser
    issues itself, where a header is not available — from the ``library``
    query parameter (see :data:`LIBRARY_PARAM`). The header WINS: the client's
    own ``fetch()`` always sets it, so a URL that also carries a stale
    parameter must not override what the app currently has selected.

    Three cases, in order:

    1. **neither given** — the principal's own default library. Kept, rather
       than made an error, because it is what every ``curl``, every API test
       and the OpenAPI examples do, and refusing them buys no safety: a caller
       with no reference still only reaches their own library;
    2. **it names the principal's default** — served without a store
       lookup. This is both the common path and the *dev-trusted* half of the
       item the plan asks for: a `Principal` is built by the server, never by
       a request, so its own library needs no membership row to be legitimate.
       P4.1 replaces the adapter, not this line;
    3. **it names anything else** — resolved through the
       :class:`TenancyStore`: the library names its OWNING ACCOUNT, the
       caller's membership of that account decides, and the library's own row
       supplies the label.

    ⚠ Case 3 is where P3.7b moved the boundary, and it is two lookups rather
    than one on purpose. Before, a membership named a library and this asked
    about that pair directly. Now a membership names an ACCOUNT, so the
    question is *who owns this library, and do you belong to them* — which is
    the whole of §4.1's revision, in one place, on every request. Nothing
    else in the product asks it.

    A library that does not exist, one owned by an account the caller does not
    belong to, and one whose owner does not exist are the SAME answer —
    **404, never 403** (§4.2). P3.3 makes that a meta-test over every route;
    here it is the door, and getting it wrong here would leak the existence of
    other customers' libraries from the one place that can see all of them.
    """
    requested = (request.headers.get(LIBRARY_HEADER)
                 or request.query_params.get(LIBRARY_PARAM))
    if not requested or requested == principal.library.id:
        return principal.library
    library, membership = owner_membership(tenancy, principal.id, requested)
    if library is None or membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such library")
    return library.ref


def owner_membership(
    tenancy: TenancyStore, user_id: str, library_id: str,
) -> tuple[Library | None, Membership | None]:
    """This user's membership of the account that OWNS ``library_id``.

    Not a FastAPI dependency — a plain function, called by
    :func:`current_library` above and by ``app.api.policy._role``. Both need
    the same two facts (does this library exist, and what is your standing
    with its owner), and writing the join twice is how the resolver and the
    capability check would eventually disagree about who owns what.

    ``(None, None)`` covers three different miss reasons — no such library, no
    such owner, no membership — and collapses them deliberately: §4.2's
    404-never-403 rule is exactly the instruction not to tell them apart on
    the wire. They stay distinguishable INSIDE the server through the store's
    own methods, which is where the operator console reads them.
    """
    library = tenancy.get_library(library_id)
    if library is None:
        return None, None
    return library, tenancy.membership(user_id, library.account_id)


# The remaining ports, same pattern as get_principal: placeholders that FAIL
# rather than defaulting, replaced per-application in create_app. The api
# layer names the PORT; app/main.py decides which adapter satisfies it (H1).

def get_book_store() -> BookStore:
    raise RuntimeError("no BookStore bound; build the app via create_app")


def get_shelf_store() -> ShelfStore:
    raise RuntimeError("no ShelfStore bound; build the app via create_app")


def get_blob_store() -> BlobStore:
    raise RuntimeError("no BlobStore bound; build the app via create_app")


def get_read_store() -> ReadStore:
    raise RuntimeError("no ReadStore bound; build the app via create_app")


def get_decision_store() -> DecisionStore:
    raise RuntimeError("no DecisionStore bound; build the app via create_app")


def get_duplicate_queue() -> DuplicateQueue:
    raise RuntimeError("no DuplicateQueue bound; build the app via create_app")


def get_reader() -> Reader:
    raise RuntimeError("no Reader bound; build the app via create_app")


def get_job_runner() -> JobRunner:
    raise RuntimeError("no JobRunner bound; build the app via create_app")


def get_clock() -> Clock:
    raise RuntimeError("no Clock bound; build the app via create_app")


def get_id_gen() -> IdGen:
    raise RuntimeError("no IdGen bound; build the app via create_app")
