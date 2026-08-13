# -*- coding: utf-8 -*-
"""/api/v1/members — who is in the account, and the invites that grow it.

P4.3, §4.2's MANAGE_MEMBERS row finally consuming routes. USER-SCOPED like
`/libraries` (the closed exemption list in tests/test_api.py): membership
is a fact about an ACCOUNT, addressed by the same "operating as" rule
every user-scoped write uses (`deps.operating_account`). Admin-only across
the board — §4.2 has one row for this whole surface, and even SEEING the
member list stays behind it until someone asks for less (the matrix makes
loosening a one-cell edit).

**An invite is a share-link.** The admin mints one and the raw token is in
the RESPONSE, once — the household's real transport is their own chat, not
our mailer. Stores hold the hash; the open-invites list is metadata that
cannot reproduce the link (`app/ports/invites.py`).

**Accepting joins the ACCOUNT** (§4.1 "invite once"): one membership row,
every library the customer owns, at the role the invite carries. Accepting
while already a member consumes the link and changes NOTHING — a link must
never be a demotion (or promotion) path around an admin's explicit
`set_role`.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api import deps
from app.api.dto import (
    InviteAccept,
    InviteCreate,
    InviteDTO,
    InviteMintedDTO,
    LibraryDTO,
    MemberDTO,
)
from app.domain import Capability, Membership, Role, allowed
from app.domain.auth import hash_token
from app.domain.invites import new_invite
from app.domain.tenancy import (
    NoAdminLeft,
    UnknownMember,
    remove_member,
    set_role,
)
from app.ports import Clock, Principal
from app.ports.invites import InviteStore
from app.ports.tenancy import TenancyStore

router = APIRouter(prefix="/members", tags=["members"])


def _admin_account(request: Request, principal: Principal,
                   tenancy: TenancyStore):
    """The operating account, gated on §4.2's one row for this surface."""
    resolved = deps.operating_account(request, principal, tenancy)
    if resolved is None:
        # A caller with no account has no members to manage; §4.2's answer
        # for "not yours to see" on the user axis.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such library")
    account, membership = resolved
    if not allowed(membership.role, Capability.MANAGE_MEMBERS):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "managing members is an admin action (§4.2)",
        )
    return account, membership


@router.get("", response_model=list[MemberDTO],
            summary="Who is in this account")
def list_members(
    request: Request,
    principal: Principal = Depends(deps.get_principal),
    tenancy: TenancyStore = Depends(deps.get_tenancy_store),
) -> list[MemberDTO]:
    account, _membership = _admin_account(request, principal, tenancy)
    rows = tenancy.list_members(account.id)
    return [
        MemberDTO(
            user_id=m.user_id,
            display_name=(tenancy.get_user(m.user_id).display_name
                          if tenancy.get_user(m.user_id) else ""),
            role=m.role.value,
            joined_at=m.joined_at,
        )
        for m in rows
    ]


@router.patch("/{user_id}", response_model=list[MemberDTO],
              summary="Change a member's role")
def patch_member(
    user_id: str,
    body: InviteCreate,  # {role} — the same one-field shape
    request: Request,
    principal: Principal = Depends(deps.get_principal),
    tenancy: TenancyStore = Depends(deps.get_tenancy_store),
) -> list[MemberDTO]:
    """The whole member list comes back — "is there still an admin?" is a
    fact about the list, and the screen showing one row is showing the
    list."""
    account, _membership = _admin_account(request, principal, tenancy)
    members = tenancy.list_members(account.id)
    try:
        updated = set_role(members, user_id, Role(body.role))
    except UnknownMember as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except NoAdminLeft as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    for m in updated:
        if m.user_id == user_id:
            tenancy.save_membership(m)
    return list_members(request, principal, tenancy)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Remove a member")
def delete_member(
    user_id: str,
    request: Request,
    principal: Principal = Depends(deps.get_principal),
    tenancy: TenancyStore = Depends(deps.get_tenancy_store),
) -> None:
    """The person leaves, the collection stays (UI_PLAN §5, one level up).
    Since P4.1b removal is EFFECTIVE — their next request answers 404."""
    account, _membership = _admin_account(request, principal, tenancy)
    members = tenancy.list_members(account.id)
    try:
        remove_member(members, user_id)
    except UnknownMember as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except NoAdminLeft as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    tenancy.delete_membership(user_id, account.id)


@router.post("/invites", response_model=InviteMintedDTO,
             status_code=status.HTTP_201_CREATED,
             summary="Mint an invite link")
def create_invite(
    body: InviteCreate,
    request: Request,
    principal: Principal = Depends(deps.get_principal),
    tenancy: TenancyStore = Depends(deps.get_tenancy_store),
    invites: InviteStore = Depends(deps.get_invite_store),
    clock: Clock = Depends(deps.get_clock),
) -> InviteMintedDTO:
    """The raw token appears HERE and never again — the list below is
    metadata only, because the store holds the hash. Copy the link now."""
    account, _membership = _admin_account(request, principal, tenancy)
    try:
        role = Role(body.role)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"{body.role!r} is not a role") from exc
    token = secrets.token_urlsafe(32)
    invite = new_invite(token, account.id, role, principal.id,
                        clock.now_iso())
    invites.save_invite(invite)
    return InviteMintedDTO(token=token, role=invite.role.value,
                           expires_at=invite.expires_at)


@router.get("/invites", response_model=list[InviteDTO],
            summary="Open invites of this account")
def list_invites(
    request: Request,
    principal: Principal = Depends(deps.get_principal),
    tenancy: TenancyStore = Depends(deps.get_tenancy_store),
    invites: InviteStore = Depends(deps.get_invite_store),
    clock: Clock = Depends(deps.get_clock),
) -> list[InviteDTO]:
    account, _membership = _admin_account(request, principal, tenancy)
    return [
        InviteDTO(id=i.token_hash, role=i.role.value,
                  created_at=i.created_at, expires_at=i.expires_at)
        for i in invites.list_open_invites(account.id, now=clock.now_iso())
    ]


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Revoke an invite")
def revoke_invite(
    invite_id: str,
    request: Request,
    principal: Principal = Depends(deps.get_principal),
    tenancy: TenancyStore = Depends(deps.get_tenancy_store),
    invites: InviteStore = Depends(deps.get_invite_store),
) -> None:
    """404 for an invite this account does not hold — the store narrows by
    account, so another customer's invite is indistinguishable from none."""
    account, _membership = _admin_account(request, principal, tenancy)
    if not invites.revoke_invite(account.id, invite_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such invite")


@router.post("/invites/accept", response_model=list[LibraryDTO],
             summary="Accept an invite")
def accept_invite(
    body: InviteAccept,
    principal: Principal = Depends(deps.get_principal),
    tenancy: TenancyStore = Depends(deps.get_tenancy_store),
    invites: InviteStore = Depends(deps.get_invite_store),
    clock: Clock = Depends(deps.get_clock),
) -> list[LibraryDTO]:
    """The INVITEE's half — any signed-in user, no admin gate, no header:
    the account comes from the token. Expired, consumed, revoked and
    invented are one 404 (which guess was close is not on the wire).

    Returns the switcher's new rows for the joined account, so the client
    can show what just opened up without a second round trip.
    """
    now = clock.now_iso()
    token_hash = hash_token(body.token)
    invite = invites.consume_invite(token_hash, by=principal.id, now=now)
    if invite is None:
        # One live case hides among the dead ones: MY OWN half-finished
        # accept. Consume-then-grant are two transactions, and a crash
        # between them burned the link with nothing granted (v16's
        # migration review) — so a consumed invite whose consumer is the
        # caller re-enters here and finishes the grant below. Single-use
        # across USERS is untouched: anyone else's token is still 404.
        existing = invites.get_invite(token_hash)
        if existing is None or existing.consumed_by != principal.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "that invite is expired, used, or was revoked")
        invite = existing
    existing = tenancy.membership(principal.id, invite.account_id)
    if existing is None:
        tenancy.save_membership(Membership(
            user_id=principal.id,
            account_id=invite.account_id,
            role=invite.role,
            joined_at=now,
        ))
    # else: already in — the link is spent, the membership is UNTOUCHED.
    # A link is never a role change around an admin's explicit set_role.
    membership = tenancy.membership(principal.id, invite.account_id)
    return [
        LibraryDTO.of(lib, membership)
        for lib in tenancy.list_libraries(invite.account_id)
    ]