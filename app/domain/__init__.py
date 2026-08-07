# -*- coding: utf-8 -*-
"""Entities and rules. Pure Python: no I/O, no framework, no driver imports.

The one import that leaves this package is ``normalize()`` from the
recognition core — see ``app/domain/text.py`` for why duplicating it would be
the worse choice. Shelf/Capture arrive in P2.1, reconciliation in P2.3.

Rules that live here because they must be testable in milliseconds and must
never be silently reversed (plan H5):

  - the matcher never auto-creates a copy .............. §5.1  book.observe
  - an approved book is never demoted by a worse re-read  §5.6  Status.merge
  - *remove from shelf* != *delete from library* ....... UI §5  remove_from_shelf
"""
from __future__ import annotations

from app.domain.book import (
    AmbiguousCopy,
    Book,
    Copy,
    CopyFields,
    DomainError,
    Lending,
    Provenance,
    Status,
    UnknownCopy,
    WorkFields,
    add_copy,
    approve,
    edit,
    new_book,
    observe,
    remove_from_shelf,
    set_work_fields,
)
from app.domain.library import LibraryRef
from app.domain.text import book_key, normalize

__all__ = [
    "AmbiguousCopy",
    "Book",
    "Copy",
    "CopyFields",
    "DomainError",
    "Lending",
    "LibraryRef",
    "Provenance",
    "Status",
    "UnknownCopy",
    "WorkFields",
    "add_copy",
    "approve",
    "book_key",
    "edit",
    "new_book",
    "normalize",
    "observe",
    "remove_from_shelf",
    "set_work_fields",
]
