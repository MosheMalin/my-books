# -*- coding: utf-8 -*-
"""The tenant key.

Lives in its own module (rather than in ``__init__``) so entity modules can
import it without a circular import through the package re-exports.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LibraryRef:
    """Every store method and every persisted record takes one.

    A separate type rather than a bare ``str`` on purpose: it makes the
    "library-scoped" signature visible at every call site, and it makes the
    day a library gains an owning account (P3.1) a change to one class.
    """

    id: str
    label: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("LibraryRef.id must be non-empty")
