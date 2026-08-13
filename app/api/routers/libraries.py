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
    operating_account,
    owner_membership,
)
from app.api.dto import LibraryCreate, LibraryDTO, LibraryPatch
from app.domain import (
    Account,
    Capability,
    Membership,
    allowed,
    new_account,
    new_library,
    rename_library,
)
from app.domain.tenancy import LIBRARIES_PER_ACCOUNT, LibraryNeedsAName
from app.ports import Clock, IdGen, Principal
from app.ports.tenancy import TenancyStore

router = APIRouter(prefix="/libraries", tags=["libraries"])


@router.get("", response_model=list[LibraryDTO],
            summary="Libraries this user can reach")
def list_libraries(
    principal: Principal = Depends(get_principal),
    tenancy: TenancyStore = Depends(get_tenancy_store),
) -> list[LibraryDTO]:
    """Ordered by the domain's own key, so the switcher never reshuffles.

    A user that belongs to nothing gets ``[]``, not an error — a real
    state (P4.3's sign-up, before the first library) the client has to render.

    Store data only. Since P4.1b the resolver reads the SAME rows this
    lists — the dev-trusted special case died with the dev identity — so
    the switcher and the resolver cannot disagree by construction;
    ``test_the_library_meta_resolves_is_always_one_the_switcher_lists``
    keeps them pinned anyway.
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
    classroom set) — and the everyday discouragement is client-side, on
    purpose: the app-bar switcher renders no create action until a second
    library already exists (`LibrarySwitcher.tsx`). The [OPEN] count cap
    CLOSED at P4.1c (owner, 2026-08-13: 5 per account) — a retry-loop and
    abuse guard like §1.2's run-rate cap, set high enough to never block a
    legitimate separate collection, which is why 5 and not 1. The
    structural half of the rule stays where it was — a Library cannot
    carry a room or a place (`test_a_library_is_not_a_place`). Do not
    change either half without re-reading VISION §4.1.

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

    **The sign-up act lives here too (P4.1c, §4.3 step 2).** A caller with
    NO account minting their first library mints the account WITH it: an
    account with no library is a customer with nowhere to put a book, so
    the two are created together — domain objects first (a blank name
    refuses before anything is written), rows after. The new account's
    membership is ADMIN by construction (`new_account`), so the §4.2 check
    is cleared the honest way, and `LIBRARIES_PER_ACCOUNT` never binds a
    first library.
    """
    resolved = operating_account(request, principal, tenancy)
    now = clock.now_iso()
    if resolved is None:
        user = tenancy.get_user(principal.id)
        if user is None:  # a session names a user; its absence is a 401
            raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                                "this session's user no longer exists")
        try:
            minted, first = new_account(
                id=ids.new_id(), owner=user, created_at=now,
            )
            library = new_library(id=ids.new_id(), label=body.label,
                                  account=minted, created_at=now)
        except LibraryNeedsAName as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        # ONE atomic, idempotent write: a raced double sign-up (two tabs,
        # a pull-to-refresh mid-flight) adopts the winner's account
        # instead of minting a permanent twin, and no crash window can
        # leave an account without its membership (P4.1c's data-integrity
        # review measured both).
        account, membership = tenancy.mint_first_account(
            minted, first, library)
        if account.id == minted.id:
            return LibraryDTO.of(library, membership)
        # Lost the race: fall through to the existing-account path with
        # the winner's account — the same request now creates a SECOND
        # library there only if it clears the same gates as anyone else.
        resolved = (account, membership)

    account, membership = resolved
    if not allowed(membership.role, Capability.MANAGE_LIBRARY):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "adding a library to this account is an admin action (§4.2)",
        )
    # The cap is a number on the ACCOUNT, checked at create — never a
    # second scope on the data (VISION §4.1; the constant argues for its
    # own value). 403, not 429: this is not a window that reopens.
    # ⚠ ADVISORY under concurrency, stated plainly (P4.1c's review
    # measured 14 at n=10): the count and the insert are two operations,
    # and racing past a loop-guard by the width of a burst harms nothing
    # it protects against. If it ever must BIND, count and insert become
    # one transaction — do not trust this check for that.
    if len(tenancy.list_libraries(account.id)) >= LIBRARIES_PER_ACCOUNT:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"this account already holds {LIBRARIES_PER_ACCOUNT} libraries "
            f"— the cap guards against runaway creation, and merging or "
            f"removing one is not offered yet",
        )
    try:
        library = new_library(
            id=ids.new_id(), label=body.label, account=account,
            created_at=now,
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
