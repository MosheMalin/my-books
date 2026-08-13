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
    """The caller's role in the ACCOUNT that owns an already-resolved library.

    Since P3.7b a role is held per account, so this asks the same question
    ``current_library`` just asked, through the same
    :func:`app.api.deps.owner_membership` — one join, written once. The role
    that comes back governs every library that account owns, which is what
    §4.1's revision means by a library being logical and not a boundary.

    **A role comes from rows, full stop** (P4.1b). The dev-trusted fallback
    that upgraded a missing membership on the principal's own library to
    ADMIN — the landmine P3.7b named so it would be removed on time — died
    with the dev identity: removing someone's membership now removes their
    access, which is the sentence authentication exists to make true.

    ``None`` here is unreachable past ``current_library`` — it just
    resolved a membership for exactly this pair — but unreachable is not a
    reason to serve it as admin, so it answers the same 404 the resolver
    would have.
    """
    _library, membership = deps.owner_membership(
        tenancy, principal.id, library.id
    )
    if membership is not None:
        return membership.role
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
                f"'{capability.value}' needs a role this user's "
                f"'{role.value}' membership does not grant (§4.2)",
            )
        return library

    setattr(check, CAPABILITY_ATTR, capability)
    return check
