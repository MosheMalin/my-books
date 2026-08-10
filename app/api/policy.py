# -*- coding: utf-8 -*-
"""The ONE policy enforcement point (P3.2).

Every library-scoped route declares its capability by depending on
:func:`require` instead of ``deps.current_library`` directly::

    library: LibraryRef = Depends(require(Capability.EDIT_BOOKS))

The checker itself depends on ``deps.current_library``, so H2's meta-test
("every route resolves its library through the one resolver") keeps holding
unchanged — this module never decides WHICH library a request is about, only
whether the caller's role in it clears the declared capability. The AST test
guarding ``deps.py`` is exactly why the role logic lives in a separate file:
H2 is about library resolution, and mixing a second concern into that module
would make its structural test meaningless.

**Denial inside a library you belong to is 403, and that is not a §4.2
violation.** The 404-not-403 rule protects the EXISTENCE of other households'
libraries; it is answered by ``current_library``, one dependency earlier. By
the time this check runs the caller is a member — they already know the
library exists, and telling a Viewer "your role does not upload photos" is
the honest, actionable answer where a 404 would gaslight them about a
library they are looking at.

The meta-test in ``tests/test_api.py``
(``test_every_api_route_declares_exactly_one_policy_capability``) is the other
half of the design: a route with no declaration FAILS the suite rather than
defaulting to open, which is what "one enforcement point" buys — there is no
second door to forget to lock.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.api import deps
from app.domain import Capability, LibraryRef, Role, allowed
from app.ports import Principal
from app.ports.tenancy import TenancyStore

#: Attribute stamped on every checker so the meta-test can find the
#: declaration in a route's dependency tree without executing anything.
CAPABILITY_ATTR = "__policy_capability__"


def _role(
    principal: Principal, tenancy: TenancyStore, library: LibraryRef,
) -> Role:
    """The caller's role in an already-resolved library.

    The membership row is the answer, and it is consulted FIRST — a stored
    VIEWER role on the caller's own library outranks the fallback below
    (pinned by ``test_a_membership_row_on_your_own_library_outranks_the_
    dev_trusted_fallback``). The one fallback mirrors ``current_library``'s
    own dev-trusted case, for the same reason it has one: a ``Principal`` is
    built by the server, never by a request, so the principal's OWN library
    is legitimately theirs even before any row exists (``app/main.py``'s
    bootstrap writes the ADMIN row; a test that skipped it is exercising the
    same trust).

    ⚠ P4-era landmine, named now so it is removed on time (P3.2's review):
    this fallback means REMOVING someone's membership from their own default
    library is ineffective — the resolver still serves it and this line
    upgrades them to ADMIN. Dormant while the principal is the dev adapter
    (there is no removal), and it MUST be deleted when P4.1 makes principals
    real — a logged-in user's role comes from rows, full stop.

    ``None`` for any OTHER library is unreachable past ``current_library`` —
    it just resolved a membership for exactly this pair — but unreachable is
    not a reason to serve it as admin, so it answers the same 404 the
    resolver would have.
    """
    membership = tenancy.membership(principal.id, library.id)
    if membership is not None:
        return membership.role
    if library.id == principal.library.id:
        return Role.ADMIN
    raise HTTPException(status.HTTP_404_NOT_FOUND, "no such library")


def require(capability: Capability):
    """A dependency that resolves the library AND checks the caller may act.

    Returns the :class:`LibraryRef` on success, so a route swaps
    ``Depends(deps.current_library)`` for ``Depends(require(...))`` without
    touching anything else in its signature.
    """

    def check(
        request: Request,
        principal: Principal = Depends(deps.get_principal),
        tenancy: TenancyStore = Depends(deps.get_tenancy_store),
        library: LibraryRef = Depends(deps.current_library),
    ) -> LibraryRef:
        role = _role(principal, tenancy, library)
        if not allowed(role, capability):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"'{capability.value}' needs a role this account's "
                f"'{role.value}' membership does not grant (§4.2)",
            )
        return library

    setattr(check, CAPABILITY_ATTR, capability)
    return check
