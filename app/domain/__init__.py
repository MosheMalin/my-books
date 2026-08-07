# -*- coding: utf-8 -*-
"""Entities and rules. Pure Python: no I/O, no framework, no driver imports.

The one import that leaves this package is ``normalize()`` from the
recognition core — see ``app/domain/text.py`` for why duplicating it would be
the worse choice.

Rules that live here because they must be testable in milliseconds and must
never be silently reversed (plan H5):

  - the matcher never auto-creates a copy .............. §5.1  book.observe
  - an approved book is never demoted by a worse re-read  §5.6  Status.merge
  - *remove from shelf* != *delete from library* ....... UI §5  remove_from_shelf
  - lending is per copy, never per book ................ §5.2  Lending, lend
  - depth is declared, never detected ................. §5.7  shelf.new_capture
  - a different row is a different location ........... §5.7  book._resolve_copy
  - the wishlist is not furniture ..................... §5.7  counts_toward_library
  - a shelf's list is reconciled, never replaced ....... §5.6  reconcile.reconcile
  - a rejected/wrong-book claim is never re-added ...... §5.6  reconcile.reconcile
  - "not seen" never auto-removes a book ............... §5.6  reconcile._not_seen_here
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
    relink_copy,
    remove_from_shelf,
    return_copy,
    set_work_fields,
)
from app.domain.copy_resolution import (
    DEFAULT_RESOLUTION,
    FIRE_TABLE,
    CopyResolutionPrompt,
    DuplicateQuestion,
    FireDecision,
    FireRule,
    PromptKind,
    build_prompt,
    fires,
    open_or_refresh,
    pick_default_copy,
)
from app.domain.library import LibraryRef
from app.domain.reconcile import (
    ClaimOutcome,
    Decision,
    DecisionKind,
    Diff,
    NotSeenEntry,
    OutcomeKind,
    reconcile,
)
from app.domain.read import (
    Alternative,
    Claim,
    ClaimTier,
    Read,
    ReadAlreadyFinished,
    ReadStatus,
    append_claim,
    fail_read,
    finish_read,
    new_read,
    stop_read,
)
from app.domain.shelf import (
    Capture,
    Shelf,
    UnknownDepth,
    VirtualShelfHasNoDepth,
    add_depth,
    capture_onto_a_new_shelf,
    counts_toward_library,
    new_capture,
    new_shelf,
    rename_shelf,
)
from app.domain.text import author_sort_key, book_key, normalize

__all__ = [
    "Alternative",
    "AmbiguousCopy",
    "Book",
    "Capture",
    "Claim",
    "ClaimOutcome",
    "ClaimTier",
    "Copy",
    "CopyAlreadyLentOut",
    "CopyFields",
    "CopyNotLentOut",
    "CopyResolutionPrompt",
    "DEFAULT_RESOLUTION",
    "Decision",
    "DecisionKind",
    "Diff",
    "DomainError",
    "DuplicateQuestion",
    "FIRE_TABLE",
    "FireDecision",
    "FireRule",
    "Lending",
    "LibraryRef",
    "NotSeenEntry",
    "OutcomeKind",
    "PromptKind",
    "Provenance",
    "Read",
    "ReadAlreadyFinished",
    "ReadStatus",
    "Shelf",
    "Status",
    "UnknownCopy",
    "UnknownDepth",
    "VirtualShelfHasNoDepth",
    "WorkFields",
    "add_copy",
    "add_depth",
    "append_claim",
    "approve",
    "author_sort_key",
    "book_key",
    "build_prompt",
    "capture_onto_a_new_shelf",
    "counts_toward_library",
    "edit",
    "edit_copy",
    "fail_read",
    "finish_read",
    "fires",
    "lend",
    "new_book",
    "new_capture",
    "new_read",
    "new_shelf",
    "normalize",
    "observe",
    "open_or_refresh",
    "pick_default_copy",
    "reconcile",
    "relink_copy",
    "remove_from_shelf",
    "rename_shelf",
    "return_copy",
    "set_work_fields",
    "stop_read",
]
