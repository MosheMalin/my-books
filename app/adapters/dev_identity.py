# -*- coding: utf-8 -*-
"""Dev-trusted identity: one hardcoded principal, one hardcoded library.

This is the stub H2 calls for. There is no login until pillar 4 and no second
library until pillar 3, but the SHAPE is the real one — a principal carrying a
library reference — so P3.1 replaces this adapter and touches no route.

The ids are overridable by env so a second library can be exercised by hand
before the real resolver exists.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from app.domain import LibraryRef

DEV_LIBRARY_ID = "dev-library"
DEV_LIBRARY_LABEL = "My library"
DEV_PRINCIPAL_ID = "dev-owner"


class DevPrincipal:
    """Implements ``app.ports.Principal``."""

    def __init__(
        self,
        principal_id: str | None = None,
        library: LibraryRef | None = None,
    ) -> None:
        self._id = principal_id or os.environ.get(
            "BOOKSNAP_DEV_PRINCIPAL", DEV_PRINCIPAL_ID
        )
        self._library = library or LibraryRef(
            id=os.environ.get("BOOKSNAP_DEV_LIBRARY", DEV_LIBRARY_ID),
            label=os.environ.get("BOOKSNAP_DEV_LIBRARY_LABEL", DEV_LIBRARY_LABEL),
        )

    @property
    def id(self) -> str:
        return self._id

    @property
    def library(self) -> LibraryRef:
        return self._library


class SystemClock:
    """Implements ``app.ports.Clock``."""

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


class UuidIdGen:
    """Implements ``app.ports.IdGen``."""

    def new_id(self) -> str:
        return uuid.uuid4().hex
