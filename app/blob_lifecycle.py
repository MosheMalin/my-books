# -*- coding: utf-8 -*-
"""The orphan reconciler (P3.5) — the one module allowed to say "orphan".

A blob is bytes with a key; whether anything NAMES that key lives in two
other aggregates the blob store cannot see: ``Capture.image_id`` (a shelf
photo) and ``Claim.crop_key`` (a spine crop a read saved). So the question
"which stored bytes does no row point at?" is a composition question, and it
lives here — a sibling of :mod:`app.reconcile_apply`, needing ``app.domain``
and ``app.ports`` and nothing else (never ``app/api``, never an adapter).

Direction matters. The API's ``DELETE /images`` handles the row→bytes
direction (an admin deletes a photo; a capture pointing at it shows a missing
picture — recorded, deliberate). This module handles bytes→rows: uploads
whose capture never got made, crops of retracted experiments, anything a
crash stranded. Photos are the evidence the whole product runs on, so the
collector is built to under-delete:

  - **referenced wins, always.** The referenced set is collected from every
    capture of every shelf (wishlist included) AND every claim of every read
    — via :meth:`ReadStore.list_all_reads`, not a shelf walk, because a
    deleted shelf's reads still exist and their crops are still evidence;
  - **young blobs are never touched.** Upload and capture-binding are two
    calls (P2.3, deliberately), so a blob is legitimately unreferenced in
    the gap between them — and "the gap" can be an afternoon of dropping
    photos before any get filed. The default floor is a day;
  - **the plan is data, the deletion is a second, explicit step** — the same
    split as ``reconcile()``/``apply_diff``: `find_orphans` computes and
    touches nothing, `collect_orphans` executes a plan you could have
    printed first. ``tools/blob_gc.py`` defaults to the printout.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain import LibraryRef
from app.ports.blobs import BlobStore
from app.ports.store import ReadStore, ShelfStore

#: A day. Not tunable per call site lightly: the number exists to survive the
#: longest plausible "uploaded, not yet filed" gap — a phone's camera roll
#: dropped in the morning and bound to shelves in the evening.
DEFAULT_MIN_AGE_S = 24 * 60 * 60.0


@dataclass(frozen=True)
class OrphanPlan:
    """What a collection run WOULD do — data, so a dry run is the same code
    path as the real one minus the deletes."""

    orphans: tuple[str, ...]        # old enough and unreferenced: collectable
    too_young: tuple[str, ...]      # unreferenced but under the age floor
    referenced: int                 # stored keys a row still names
    stored: int                     # everything list_keys saw


def referenced_keys(
    library: LibraryRef, shelves: ShelfStore, reads: ReadStore,
) -> frozenset[str]:
    """Every blob key a durable row still names.

    Both sources, deliberately: captures alone would collect every spine
    crop; reads alone would collect every unread photo. And reads come from
    ``list_all_reads``, never a walk of current shelves — a shelf whose
    captures were removed can itself be deleted while its reads (and their
    crops) remain, and evidence a DB row points at must not be collectable
    just because its shelf retired (mutation-checked).
    """
    keys: set[str] = set()
    for shelf in shelves.list_shelves(library, include_virtual=True):
        for capture in shelves.list_captures(library, shelf.id):
            if capture.image_id:
                keys.add(capture.image_id)
    for read in reads.list_all_reads(library):
        for claim in read.claims:
            if claim.crop_key:
                keys.add(claim.crop_key)
    return frozenset(keys)


def find_orphans(
    library: LibraryRef,
    blobs: BlobStore,
    shelves: ShelfStore,
    reads: ReadStore,
    *,
    min_age_s: float = DEFAULT_MIN_AGE_S,
) -> OrphanPlan:
    """Compute the plan. Touches nothing."""
    referenced = referenced_keys(library, shelves, reads)
    orphans: list[str] = []
    too_young: list[str] = []
    stored = blobs.list_keys(library)
    for blob in stored:
        if blob.key in referenced:
            continue
        (orphans if blob.age_seconds >= min_age_s else too_young).append(blob.key)
    return OrphanPlan(
        orphans=tuple(orphans),
        too_young=tuple(too_young),
        referenced=sum(1 for b in stored if b.key in referenced),
        stored=len(stored),
    )


def collect_orphans(
    library: LibraryRef,
    blobs: BlobStore,
    shelves: ShelfStore,
    reads: ReadStore,
    *,
    min_age_s: float = DEFAULT_MIN_AGE_S,
) -> OrphanPlan:
    """Compute the plan, then execute exactly it.

    The referenced set is re-collected here (inside `find_orphans`) in the
    same call that deletes — a plan carried over from an earlier process
    would race an upload that got referenced in between. The age floor
    covers the remaining window (a reference written between OUR listing and
    the delete), which is why `min_age_s=0` is for tests, not operations.
    """
    plan = find_orphans(library, blobs, shelves, reads, min_age_s=min_age_s)
    for key in plan.orphans:
        blobs.delete(library, key)
    return plan
