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
  - the not-seen streak is a badge, never a removal .... §5.6  history.not_seen_streak
  - a diff summary is a snapshot, never recomputed ..... §5.5  read.DiffSummary
  - a retracted finding never deletes a vouched-for book  UI §5 retract.plan_retraction
  - a deleted book is not re-added by the next read . §5.6  retract.deletion_sites
  - a library is created with a name .................. §4.3  tenancy.new_library
  - a library keeps at least one admin ................ §4.2  tenancy.NoAdminLeft
  - a role says who you are, never what you may do .... §4.2  tenancy.Role
  - what a role MAY do is one table, never an if ...... §4.2  policy.POLICY
  - an undeclared capability raises, never defaults ... §4.2  policy.allowed
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
from app.domain.history import DepthStatus, depth_staleness, not_seen_streak
from app.domain.library import LibraryRef
from app.domain.policy import POLICY, Capability, PolicyUndeclared, allowed
from app.domain.reconcile import (
    ClaimOutcome,
    Decision,
    DecisionKind,
    Diff,
    NotSeenEntry,
    OutcomeKind,
    reconcile,
    summarize,
)
from app.domain.read import (
    Alternative,
    Claim,
    ClaimTier,
    DiffSummary,
    Read,
    ReadAlreadyFinished,
    ReadStatus,
    add_manual_claim,
    append_claim,
    fail_read,
    finish_read,
    new_read,
    stop_read,
    with_diff_summary,
)
from app.domain.retract import (
    RetractAction,
    Retraction,
    deletion_sites,
    plan_retraction,
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
from app.domain.tenancy import (
    Account,
    Library,
    LibraryNeedsAName,
    Membership,
    NoAdminLeft,
    Role,
    UnknownMember,
    User,
    new_account,
    new_library,
    remove_member,
    rename_library,
    set_role,
)
from app.domain.text import author_sort_key, book_key, normalize

__all__ = [
    "Account",
    "Alternative",
    "AmbiguousCopy",
    "Book",
    "Capability",
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
    "DepthStatus",
    "Diff",
    "DiffSummary",
    "DomainError",
    "DuplicateQuestion",
    "FIRE_TABLE",
    "FireDecision",
    "FireRule",
    "Lending",
    "Library",
    "LibraryNeedsAName",
    "LibraryRef",
    "Membership",
    "NoAdminLeft",
    "NotSeenEntry",
    "OutcomeKind",
    "POLICY",
    "PolicyUndeclared",
    "PromptKind",
    "Provenance",
    "Read",
    "ReadAlreadyFinished",
    "ReadStatus",
    "RetractAction",
    "Retraction",
    "Role",
    "Shelf",
    "Status",
    "UnknownCopy",
    "UnknownDepth",
    "UnknownMember",
    "User",
    "VirtualShelfHasNoDepth",
    "WorkFields",
    "add_copy",
    "add_depth",
    "add_manual_claim",
    "allowed",
    "append_claim",
    "approve",
    "author_sort_key",
    "book_key",
    "build_prompt",
    "capture_onto_a_new_shelf",
    "counts_toward_library",
    "deletion_sites",
    "depth_staleness",
    "edit",
    "edit_copy",
    "fail_read",
    "finish_read",
    "fires",
    "lend",
    "new_account",
    "new_book",
    "new_capture",
    "new_library",
    "new_read",
    "new_shelf",
    "normalize",
    "not_seen_streak",
    "observe",
    "open_or_refresh",
    "pick_default_copy",
    "plan_retraction",
    "reconcile",
    "relink_copy",
    "remove_from_shelf",
    "remove_member",
    "rename_library",
    "rename_shelf",
    "return_copy",
    "set_role",
    "set_work_fields",
    "stop_read",
    "summarize",
    "with_diff_summary",
]
