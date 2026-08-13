# -*- coding: utf-8 -*-
"""Ports: the Protocols the api layer is allowed to depend on.

May import ``app.domain``. May NOT import adapters, the api layer, a web
framework or a driver — that is what keeps the datastore/queue/storage
decisions swappable (IMPLEMENTATION_PLAN D1, H4 ring 2).

Defined here: the three request-scoped ports. ``BookStore``/``ShelfStore`` live
in ``app.ports.store`` and ``BlobStore`` in ``app.ports.blobs``, each with
enough of its own vocabulary (sorts, pages, blobs) to be worth a file. JobQueue
arrives with P2.4.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.ports.blobs import Blob, BlobError, BlobStore, ImageTooLarge, UnsupportedImage

__all__ = [
    "Blob",
    "BlobError",
    "BlobStore",
    "Clock",
    "IdGen",
    "ImageTooLarge",
    "Principal",
    "UnsupportedImage",
]


@runtime_checkable
class Principal(Protocol):
    """Whoever is making the request — identity, and NOTHING else (P4.1b).

    Until P4.1b this also carried a default ``library``, because the
    dev-trusted principal was configuration and configuration had to say
    which library it meant. A session says only WHO: which libraries that
    person may reach is the tenancy store's answer, resolved per request in
    exactly one place (``app.api.deps.current_library`` — H2), and a
    principal that carried a library would be a second copy of that answer
    going stale in every session row.
    """

    @property
    def id(self) -> str:
        """Stable identifier for the caller."""


@runtime_checkable
class Clock(Protocol):
    """Time, injected so rules and stores are testable without waiting."""

    def now_iso(self) -> str:
        """Current UTC instant as an ISO-8601 string."""


@runtime_checkable
class IdGen(Protocol):
    """Identifier minting, injected so records are reproducible in tests."""

    def new_id(self) -> str:
        ...
