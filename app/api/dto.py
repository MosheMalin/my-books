# -*- coding: utf-8 -*-
"""Wire types. Deliberately NOT the domain entities (H3).

These are also the source of the generated TypeScript client types
(``app/web/src/api/schema.d.ts``), so a field rename here becomes a client
BUILD failure rather than a runtime surprise. ``tools/check_contract.py``
enforces that the committed schema is in step with these classes.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class LibraryRefDTO(BaseModel):
    """The tenant reference the client echoes back on every request.

    Present from the very first endpoint on purpose: the client is
    tenant-aware from P1.0 (§1.3), even though there is exactly one library
    until pillar 3.
    """

    id: str = Field(description="Opaque library identifier.")
    label: str = Field(description="Human-readable library name.")


class MetaResponse(BaseModel):
    """Service identity + the caller's resolved library.

    The one endpoint P1.0 ships. It carries no domain data — its job is to
    prove the whole path end to end: principal -> library -> DTO -> OpenAPI
    schema -> generated TS type -> typed fetch in a React component.
    """

    app: str = Field(description="Service name.")
    version: str = Field(description="Server package version.")
    api_version: str = Field(description="API major version, e.g. 'v1'.")
    library: LibraryRefDTO = Field(description="Library resolved for this caller.")
