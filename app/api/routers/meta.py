# -*- coding: utf-8 -*-
"""GET /api/v1/meta — service identity and the caller's library.

The scaffolding's single endpoint. It is not a health check: it is the
narrowest possible route that still exercises tenancy (H2) and the DTO ->
OpenAPI -> TypeScript contract (D3), which is what P1.0 exists to prove.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app import API_VERSION, __version__
from app.api.deps import get_principal, get_tenancy_store
from app.api.dto import LibraryRefDTO, MetaResponse, UserDTO
from app.api.policy import require
from app.domain import Capability, LibraryRef
from app.ports import Principal
from app.ports.tenancy import TenancyStore

router = APIRouter(tags=["meta"])


@router.get("/meta", response_model=MetaResponse, summary="Service and library identity")
def get_meta(
    library: LibraryRef = Depends(require(Capability.BROWSE)),
    principal: Principal = Depends(get_principal),
    tenancy: TenancyStore = Depends(get_tenancy_store),
) -> MetaResponse:
    """The library here is the RESOLVED one — what the request's own header
    asked for (P3.1), not a server-side constant. A client that sends a
    library it may not have gets 404 from the resolver rather than a
    misleading 200 naming a different one."""
    user = tenancy.get_user(principal.id)
    return MetaResponse(
        app="booksnap",
        version=__version__,
        api_version=API_VERSION,
        library=LibraryRefDTO(id=library.id, label=library.label),
        # The user row may not exist yet on a fresh database (it is created
        # by the composition root, or on the first `POST /libraries`). Falling
        # back to the principal's own id keeps `meta` a route that always
        # answers — it is the one the client calls to find out whether the
        # server is there at all.
        user=UserDTO(
            id=principal.id,
            display_name=user.display_name if user else "",
        ),
    )
