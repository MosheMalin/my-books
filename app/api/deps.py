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

from app.domain import Account, Library, LibraryRef, Membership
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

#: The session cookie (P4.1a). Lives here with the other transport constants
#: (`LIBRARY_HEADER`, `LIBRARY_PARAM`): the auth router SETS it and P4.1b's
#: resolver READS it, and neither may import the other. The cookie's value is
#: the raw token; the database only ever holds its hash.
SESSION_COOKIE = "booksnap_session"

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


def requested_library_id(request: Request) -> str | None:
    """The library reference this request carries, header winning over the
    query parameter — ONE copy of the precedence (a second, unpinned copy
    in `operating_account` survived a reversal at review)."""
    return (request.headers.get(LIBRARY_HEADER)
            or request.query_params.get(LIBRARY_PARAM))


def current_library(
    request: Request,
    principal: Principal = Depends(get_principal),
    tenancy: TenancyStore = Depends(get_tenancy_store),
) -> LibraryRef:
    """The single principal -> library resolution point (H2).

    Until P3.1 this returned the principal's own library and nothing else;
    until P4.1b it also trusted that library without a store lookup — the
    dev-trusted branch, deleted together with the dev identity. Since P4.1b
    EVERY resolution goes through :func:`owner_membership`: the library
    names its owning account, the caller's membership of that account
    decides, the library's own row supplies the label. There is no library
    a session reaches without a row saying so.

    The reference is read from the header, or — for requests the browser
    issues itself, where a header is not available — from the ``library``
    query parameter (see :data:`LIBRARY_PARAM`). The header WINS: the
    client's own ``fetch()`` always sets it, so a URL that also carries a
    stale parameter must not override what the app currently has selected.

    **No reference at all** resolves to the caller's first library — first
    account by id, first library by its own sort key, the same total order
    the switcher renders — kept rather than made an error because it is
    what every ``curl``, every API test and the OpenAPI examples do, and
    refusing them buys no safety. A caller with no library anywhere (a
    bare user before P4.1c's sign-up) gets the same 404 as any other
    unresolvable reference.

    A library that does not exist, one owned by an account the caller does
    not belong to, and one whose owner does not exist are the SAME answer —
    **404, never 403** (§4.2). P3.3 makes that a meta-test over every
    route; here it is the door, and getting it wrong here would leak the
    existence of other customers' libraries from the one place that can see
    all of them.
    """
    requested = requested_library_id(request)
    if not requested:
        rows = [lib
                for account, _m in tenancy.list_accounts(principal.id)
                for lib in tenancy.list_libraries(account.id)]
        if not rows:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such library")
        # The SAME flat order the switcher renders — first-account-first
        # measurably diverged from it the moment a second account existed
        # (P4.1b's quality review, with invites one item away).
        rows.sort(key=lambda lib: lib.sort_key)
        return rows[0].ref
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

    ⚠⚠ **Both lookups run on every path, and the wasted query is the point.**
    The obvious shape — return early when the library is missing — costs ONE
    store call for a library that does not exist and TWO for one that belongs
    to a customer you are not in, and the sqlite adapter opens a connection
    per operation. That is a clean 2× on the whole resolution, and P3.7b's
    security review turned it into an oracle: 20 real ids of another customer
    and 20 invented ones, interleaved, 200 samples each — **40/40 classified
    correctly by response time alone**, with no overlap between the two
    distributions, while every reply was byte-identical `404 {"detail":"no
    such library"}`. Sweeping ids then enumerates another account's libraries
    through a door that answers the same thing to all of them.

    The early return was not there before P3.7b — the old join asked about
    (user, library) directly and cost one query either way — so this is a
    regression the boundary move introduced, not an inherited condition. It
    matters most after P4.1, when any logged-in user of any account can
    address this endpoint; it is written down now because the fix is one
    wasted lookup and the diagnosis is not.
    """
    library = tenancy.get_library(library_id)
    # A real account id when the library exists; the caller's own string when
    # it does not — either way one membership lookup, of the same shape, that
    # cannot match anything it should not.
    account_id = library.account_id if library is not None else library_id
    membership = tenancy.membership(user_id, account_id)
    if library is None:
        return None, None
    return library, membership


def operating_account(
    request: Request, principal: Principal, tenancy: TenancyStore,
) -> tuple[Account, Membership] | None:
    """The ACCOUNT a user-scoped write acts on — the one the caller is
    OPERATING AS — or ``None`` for a caller who belongs to none (the
    sign-up case, which only `create_library` may answer by minting).

    One copy of the rule, since P4.3 needs it for member management too:
    the account owning the library the request itself names (the header
    every call carries — the client's actual selection); with no header,
    the caller's sole account. Several accounts and no header is refused
    with instructions rather than guessed at — "the first account we list"
    was a cross-tenant write the moment a second membership existed
    (P3.7b's review, M6).

    Not a FastAPI dependency, like `owner_membership` beside it: the
    routers that need it also need its ``None`` case to mean different
    things, which a Depends cannot express.
    """
    requested = requested_library_id(request)
    if requested:
        library, membership = owner_membership(tenancy, principal.id, requested)
        if library is None or membership is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such library")
        account = tenancy.get_account(library.account_id)
        if account is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such library")
        return account, membership
    mine = tenancy.list_accounts(principal.id)
    if len(mine) == 1:
        return mine[0]
    if not mine:
        return None
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "you belong to several accounts; name a library of the one this "
        "should go under (the X-Booksnap-Library header)",
    )


def owning_account(tenancy: TenancyStore, library: LibraryRef) -> str:
    """Which customer this already-resolved library belongs to.

    The same question :func:`owner_membership` asks, for the callers that
    do not need a membership back — the rate cap and the job queue's
    fairness key, both of which only want to know whose budget and whose
    turn this is. It lives beside its sibling for the reason that one's
    docstring already gives: writing the join twice is how two parts of
    the product come to disagree about who owns what, and P3.7c had it
    written four times before this existed.

    ⚠ Unreachable-for-a-missing-row since P4.1b: every ``LibraryRef`` a
    route holds came out of :func:`current_library`, which resolved a real
    row moments ago. The old dev-trusted fallback (the library's own id as
    the account key) died with the dev identity; a miss here now RAISES,
    because inventing an account key is how one customer's read bills
    another's budget, silently.
    """
    owner = tenancy.get_library(library.id)
    if owner is None:
        raise LookupError(
            f"library {library.id!r} vanished between resolution and use"
        )
    return owner.account_id


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


def get_invite_store() -> InviteStore:
    raise RuntimeError("no InviteStore bound; build the app via create_app")


def get_auth_store() -> AuthStore:
    raise RuntimeError("no AuthStore bound; build the app via create_app")


def get_mailer() -> Mailer:
    raise RuntimeError("no Mailer bound; build the app via create_app")


def get_clock() -> Clock:
    raise RuntimeError("no Clock bound; build the app via create_app")


def get_id_gen() -> IdGen:
    raise RuntimeError("no IdGen bound; build the app via create_app")
