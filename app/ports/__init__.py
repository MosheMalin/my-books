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

from app.domain import LibraryRef
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
    """Whoever is making the request.

    Until pillar 4 there is no login, so the adapter is a hardcoded dev
    principal. The important part is that it exists NOW: H2 requires exactly
    one function resolving principal -> library, and a route that reaches for
    "the" library instead is the thing that has to be rewritten later.
    """

    @property
    def id(self) -> str:
        """Stable identifier for the caller."""

    @property
    def library(self) -> LibraryRef:
        """The library this request operates on."""


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
