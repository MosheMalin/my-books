# -*- coding: utf-8 -*-
"""Entities and rules. Pure Python: no I/O, no framework, no driver imports.

Empty at P1.0 by design — the scaffolding item deliberately ships no domain
model (see IMPLEMENTATION_PLAN §4, P1.0 "no behaviour"). Book/Copy arrive in
P1.1, Shelf/Capture in P2.1.

The one thing that already lives here is the vocabulary for tenancy, because
H2 says every persisted record carries a library reference from the first
write — so the type it travels as must exist before the first write does.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LibraryRef:
    """The tenant key. Every store method and every persisted record takes one.

    A separate type rather than a bare ``str`` on purpose: it makes the
    "library-scoped" signature visible at every call site, and it makes the
    day a library gains an owning account (P3.1) a change to one class.
    """

    id: str
    label: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("LibraryRef.id must be non-empty")
