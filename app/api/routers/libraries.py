# -*- coding: utf-8 -*-
"""/api/v1/libraries — the switcher's data, and the only user-scoped routes.

⚠⚠ **These are the routes exempt from H2's "every route resolves its library
through ``current_library``" meta-test**, and the exemption is a closed list in
``tests/test_api.py``, not a convention. The reason is circularity: these
routes are how a caller LEARNS which libraries it may name, so requiring them
to resolve one first would mean a client with no valid selection — a fresh
browser, a renamed library, a user whose membership was just removed — has
no way to find out. They resolve a **user** instead, through the same
``get_principal`` every other route already depends on, so they are scoped;
just on the other axis.

THIN by rule (H3), like every router here. The two rules worth naming both
live in ``app/domain/tenancy.py``:

  - creating a library grants NOBODY anything
    (:func:`app.domain.tenancy.new_library` returns a Library and nothing
    else). Until P3.7b it minted an admin membership here, because a
    library WAS the boundary; access now comes from the owning account,
    and a second grant per library would be one the resolver never reads;
  - a library is created and kept **named** (§4.3), unlike a shelf, whose
    label is optional because an unnamed shelf is shown by its own photograph.

**Deliberately absent, not disabled:** DELETE. §4.2 lists "delete the library"
as an admin capability, and it means deleting every book, shelf, read and
photo in it — a cascade across six aggregates that do not know about each
other, and the single most destructive act in the product. Its two named
prerequisites now exist — P3.2's policy (`Capability.DELETE_LIBRARY`, admin,
already a row in the matrix so the route cannot ship open) and P3.5's blob
purge (`BlobStore.purge`) — but the cascade itself is still a design owed:
today no store has a "drop everything in this library" operation, and adding
six of them for a route nobody has asked to press is speculation. When it is
built, note the meta-test exemption list is keyed by (method, path), so
`DELETE /libraries/{id}` will NOT inherit the user-scoped exemption
silently. Member management (invite, change role, remove) is P4.3's, for the
same reason: an invite with no login to accept it is not a feature.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api import deps
from app.api.deps import (
    get_clock,
    get_id_gen,
    get_principal,
    get_tenancy_store,
    owner_membership,
)
from app.api.dto import LibraryCreate, LibraryDTO, LibraryPatch
from app.domain import (
    Account,
    Capability,
    Membership,
    allowed,
    new_library,
    rename_library,
)
from app.domain.tenancy import LibraryNeedsAName
from app.ports import Clock, IdGen, Principal
from app.ports.tenancy import TenancyStore

router = APIRouter(prefix="/libraries", tags=["libraries"])


def _account(
    request: Request, principal: Principal, tenancy: TenancyStore,
) -> tuple[Account, Membership]:
    """The account a new library goes under — the one the caller is
    OPERATING AS (P4.1b).

    "Which account?" has one answer per request and it is answered in ONE
    place. The rule: the account owning the library the request itself
    names (the same ``X-Booksnap-Library`` header every other call
    carries — the client's actual selection, which is what "operating as"
    means); with no header, the caller's sole account. A caller in SEVERAL
    accounts with no header is refused with instructions rather than
    guessed at — "the first account we happen to list" was a cross-tenant
    write the moment a second membership existed (P3.7b's review, M6).

    The dev-era branches died with the dev identity: no user row is minted
    here (the session's user exists by construction), and no account is
    minted here (that is sign-up's job, P4.1c) — a user with no account
    cannot create a library, which is §4.1's "creating a library writes
    into a customer" taken at face value.
    """
    requested = (request.headers.get(deps.LIBRARY_HEADER)
                 or request.query_params.get(deps.LIBRARY_PARAM))
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
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "this user has no account yet — sign-up creates one (§4.3)",
        )
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "you belong to several accounts; name a library of the one this "
        "should go under (the X-Booksnap-Library header)",
    )


@router.get("", response_model=list[LibraryDTO],
            summary="Libraries this user can reach")
def list_libraries(
    principal: Principal = Depends(get_principal),
    tenancy: TenancyStore = Depends(get_tenancy_store),
) -> list[LibraryDTO]:
    """Ordered by the domain's own key, so the switcher never reshuffles.

    A user that belongs to nothing gets ``[]``, not an error — a real
    state (P4.3's sign-up, before the first library) the client has to render.

    ⚠ **Store data only, with no special case for the principal's own default
    library** — even though :func:`app.api.deps.current_library` serves that
    one without consulting the store. Patching it in here would put a second
    copy of the resolver's dev-trusted rule in a second module, and the day
    they disagreed the switcher would be missing the very library on screen.
    Guaranteeing the membership row exists is the composition root's job
    (``app.main:_bootstrap_dev_user``), and
    ``test_the_library_meta_resolves_is_always_one_the_switcher_lists`` pins
    the agreement rather than trusting it.
    """
    rows = [
        (lib, membership)
        for account, membership in tenancy.list_accounts(principal.id)
        for lib in tenancy.list_libraries(account.id)
    ]
    # One order across every account the caller belongs to. `list_libraries`
    # already sorts within one, but the switcher renders a single flat list and
    # an order that depends on which account happened to come back first is an
    # order the user experiences as reshuffling.
    rows.sort(key=lambda pair: pair[0].sort_key)
    return [LibraryDTO.of(lib, m) for lib, m in rows]


@router.post("", response_model=LibraryDTO, status_code=status.HTTP_201_CREATED,
             summary="Create a library")
def create_library(
    body: LibraryCreate,
    request: Request,
    principal: Principal = Depends(get_principal),
    tenancy: TenancyStore = Depends(get_tenancy_store),
    clock: Clock = Depends(get_clock),
    ids: IdGen = Depends(get_id_gen),
) -> LibraryDTO:
    """Created under the caller's existing account, granting nothing new.

    ⚠ It inherits the standing the caller already had with that customer.
    Until P3.7b this route wrote a membership too; `new_library` returning
    a Library and nothing else is what P3.7b calls its most load-bearing
    deletion, and `test_creating_a_library_grants_nobody_anything` pins it.

    ⚠ This route is the DELIBERATE escape hatch for §4.1's settled tenancy
    rule (owner, 2026-08-10): a second Library under one account is legal —
    it is the rare genuinely-separate collection (a shop's stock, a
    classroom set) — and the ONLY discouragement is client-side, on purpose:
    the app-bar switcher renders no create action until a second library
    already exists (`LibrarySwitcher.tsx`). A server-side count cap was
    considered and REFUSED: it would block the very cases the decision
    blesses, a quota is a different axis from P3.2's (role × capability)
    policy data, and the structural half of the rule is already enforced
    where it matters — a Library cannot carry a room or a place
    (`test_a_library_is_not_a_place`). Do not "fix" this route in either
    direction without re-reading VISION §4.1.

    ⚠⚠ **Admin-only, and P3.7b is what made that necessary.** Before the
    boundary moved, this route minted a BRAND-NEW tenant with the caller as
    its admin — it touched nobody else, so leaving it open cost nothing. Now
    it writes into an EXISTING customer that other people belong to: every
    member's switcher grows a row, the operator's dashboard counts it, and
    (from P3.7c) it draws on that customer's shared run-rate cap. Without this
    check a VIEWER — §4.2's "friend browsing what you own" — can append
    unlimited libraries to the account paying for it, and nothing in the
    product can remove them (DELETE is deliberately absent). Found by P3.7b's
    data-integrity review, which reproduced exactly that.

    `MANAGE_LIBRARY` rather than a new capability: §4.2 has no "create a
    library" row, and the closest cell it does have — *rename the library*,
    "the library's name is the tenant's own identity" — is the same act one
    step later.
    """
    account, membership = _account(request, principal, tenancy)
    if not allowed(membership.role, Capability.MANAGE_LIBRARY):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "adding a library to this account is an admin action (§4.2)",
        )
    try:
        library = new_library(
            id=ids.new_id(), label=body.label, account=account,
            created_at=clock.now_iso(),
        )
    except LibraryNeedsAName as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    tenancy.save_library(library)
    return LibraryDTO.of(library, membership)


@router.patch("/{library_id}", response_model=LibraryDTO,
              summary="Rename a library")
def patch_library(
    library_id: str,
    body: LibraryPatch,
    principal: Principal = Depends(get_principal),
    tenancy: TenancyStore = Depends(get_tenancy_store),
) -> LibraryDTO:
    """404 for a library this user is not a member of — never 403 (§4.2).

    Resolved through the same :func:`app.api.deps.owner_membership` the door
    uses, so "which account owns this" is answered by one function for the
    whole product. A library that does not exist and one owned by a customer
    the caller has nothing to do with come back from the same branch, which is
    what keeps the two indistinguishable on the wire.
    """
    library, membership = owner_membership(tenancy, principal.id, library_id)
    if library is None or membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such library")
    # P3.2: the one direct `allowed()` call outside app/api/policy.py, because
    # this route is on the USER axis — `require()` resolves a library
    # through `current_library`, which these routes are exempt from (the
    # closed list in tests/test_api.py). Same matrix, same data; only the
    # transport of "which library" differs. 403 (not 404) is honest here: the
    # membership above proves the caller may SEE the library — renaming the
    # household's own name is what §4.2 reserves for its admin.
    if not allowed(membership.role, Capability.MANAGE_LIBRARY):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "renaming a library is an admin action (§4.2)",
        )
    try:
        renamed = rename_library(library, body.label)
    except LibraryNeedsAName as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    tenancy.save_library(renamed)
    return LibraryDTO.of(renamed, membership)
