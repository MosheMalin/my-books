# -*- coding: utf-8 -*-
"""/api/v1/libraries — the switcher's data, and the only account-scoped routes.

⚠⚠ **These are the routes exempt from H2's "every route resolves its library
through ``current_library``" meta-test**, and the exemption is a closed list in
``tests/test_api.py``, not a convention. The reason is circularity: these
routes are how a caller LEARNS which libraries it may name, so requiring them
to resolve one first would mean a client with no valid selection — a fresh
browser, a renamed library, an account whose membership was just removed — has
no way to find out. They resolve an **account** instead, through the same
``get_principal`` every other route already depends on, so they are scoped;
just on the other axis.

THIN by rule (H3), like every router here. The two rules worth naming both
live in ``app/domain/tenancy.py``:

  - creating a library mints its admin membership in the same call
    (:func:`app.domain.tenancy.new_library`) — a library saved without one is
    invisible to the person who made it and administrable by nobody;
  - a library is created and kept **named** (§4.3), unlike a shelf, whose
    label is optional because an unnamed shelf is shown by its own photograph.

**Deliberately absent, not disabled:** DELETE. §4.2 lists "delete the library"
as an admin capability, and it means deleting every book, shelf, read and
photo in it — a cascade across six aggregates that do not know about each
other, and the single most destructive act in the product. It needs P3.2's
policy and P3.5's blob purge to be honest, and neither exists yet. Member
management (invite, change role, remove) is P4.3's, for the same reason: an
invite with no login to accept it is not a feature.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_clock, get_id_gen, get_principal, get_tenancy_store
from app.api.dto import LibraryCreate, LibraryDTO, LibraryPatch
from app.domain import Account, Capability, allowed, new_library, rename_library
from app.domain.tenancy import LibraryNeedsAName
from app.ports import Clock, IdGen, Principal
from app.ports.tenancy import TenancyStore

router = APIRouter(prefix="/libraries", tags=["libraries"])


def _account(principal: Principal, tenancy: TenancyStore) -> Account:
    """The caller's account record, created on first sight if need be.

    A dev-trusted principal exists before any row does (that is what
    "dev-trusted" means), and the composition root already ensures the owner's
    account — but a fresh database reached through some other entry point
    would otherwise 500 the first time someone pressed *new library*. Creating
    it here is idempotent and cheap; P4.1 replaces the whole path with a
    session lookup, where an unknown account is a real error.
    """
    existing = tenancy.get_account(principal.id)
    if existing is not None:
        return existing
    account = Account(id=principal.id)
    tenancy.save_account(account)
    return account


@router.get("", response_model=list[LibraryDTO],
            summary="Libraries this account belongs to")
def list_libraries(
    principal: Principal = Depends(get_principal),
    tenancy: TenancyStore = Depends(get_tenancy_store),
) -> list[LibraryDTO]:
    """Ordered by the domain's own key, so the switcher never reshuffles.

    An account that belongs to nothing gets ``[]``, not an error — a real
    state (P4.3's sign-up, before the first library) the client has to render.

    ⚠ **Store data only, with no special case for the principal's own default
    library** — even though :func:`app.api.deps.current_library` serves that
    one without consulting the store. Patching it in here would put a second
    copy of the resolver's dev-trusted rule in a second module, and the day
    they disagreed the switcher would be missing the very library on screen.
    Guaranteeing the membership row exists is the composition root's job
    (``app.main:_bootstrap_dev_account``), and
    ``test_the_library_meta_resolves_is_always_one_the_switcher_lists`` pins
    the agreement rather than trusting it.
    """
    return [LibraryDTO.of(lib, m) for lib, m in tenancy.list_libraries(principal.id)]


@router.post("", response_model=LibraryDTO, status_code=status.HTTP_201_CREATED,
             summary="Create a library")
def create_library(
    body: LibraryCreate,
    principal: Principal = Depends(get_principal),
    tenancy: TenancyStore = Depends(get_tenancy_store),
    clock: Clock = Depends(get_clock),
    ids: IdGen = Depends(get_id_gen),
) -> LibraryDTO:
    """The creator becomes its admin, in the same domain call and the same
    two writes — see the module note."""
    account = _account(principal, tenancy)
    try:
        library, membership = new_library(
            id=ids.new_id(), label=body.label, owner=account,
            created_at=clock.now_iso(),
        )
    except LibraryNeedsAName as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    tenancy.save_library(library)
    tenancy.save_membership(membership)
    return LibraryDTO.of(library, membership)


@router.patch("/{library_id}", response_model=LibraryDTO,
              summary="Rename a library")
def patch_library(
    library_id: str,
    body: LibraryPatch,
    principal: Principal = Depends(get_principal),
    tenancy: TenancyStore = Depends(get_tenancy_store),
) -> LibraryDTO:
    """404 for a library this account is not a member of — never 403 (§4.2).

    The membership is looked up FIRST and the library second: asking the other
    way round would answer "no such library" for a real library and "not
    found" for a fictional one from two different branches, and only one of
    them stays honest when P3.2 adds roles.
    """
    membership = tenancy.membership(principal.id, library_id)
    library = tenancy.get_library(library_id) if membership else None
    if membership is None or library is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such library")
    # P3.2: the one direct `allowed()` call outside app/api/policy.py, because
    # this route is on the ACCOUNT axis — `require()` resolves a library
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
