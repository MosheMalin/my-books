# -*- coding: utf-8 -*-
"""GET /api/v1/meta — service identity and the caller's library.

The scaffolding's single endpoint. It is not a health check: it is the
narrowest possible route that still exercises tenancy (H2) and the DTO ->
OpenAPI -> TypeScript contract (D3), which is what P1.0 exists to prove.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app import API_VERSION, __version__
from app.api.deps import current_library
from app.api.dto import LibraryRefDTO, MetaResponse
from app.domain import LibraryRef

router = APIRouter(tags=["meta"])


@router.get("/meta", response_model=MetaResponse, summary="Service and library identity")
def get_meta(library: LibraryRef = Depends(current_library)) -> MetaResponse:
    return MetaResponse(
        app="booksnap",
        version=__version__,
        api_version=API_VERSION,
        library=LibraryRefDTO(id=library.id, label=library.label),
    )
