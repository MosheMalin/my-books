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
  - lending is per copy, never per book ................ §5.2  Lending, lend
"""
from __future__ import annotations

from app.domain.book import (
    AmbiguousCopy,
    Book,
    Copy,
    CopyAlreadyLentOut,
    CopyFields,
    CopyNotLentOut,
    DomainError,
    Lending,
    Provenance,
    Status,
    UnknownCopy,
    WorkFields,
    add_copy,
    approve,
    edit,
    edit_copy,
    lend,
    new_book,
    observe,
    remove_from_shelf,
    return_copy,
    set_work_fields,
)
from app.domain.library import LibraryRef
from app.domain.text import author_sort_key, book_key, normalize

__all__ = [
    "AmbiguousCopy",
    "Book",
    "Copy",
    "CopyAlreadyLentOut",
    "CopyFields",
    "CopyNotLentOut",
    "DomainError",
    "Lending",
    "LibraryRef",
    "Provenance",
    "Status",
    "UnknownCopy",
    "WorkFields",
    "add_copy",
    "approve",
    "author_sort_key",
    "book_key",
    "edit",
    "edit_copy",
    "lend",
    "new_book",
    "normalize",
    "observe",
    "remove_from_shelf",
    "return_copy",
    "set_work_fields",
]
