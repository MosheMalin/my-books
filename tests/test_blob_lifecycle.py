# -*- coding: utf-8 -*-
"""P3.5 — the orphan reconciler, retention and purge.

The property under test is DIRECTIONAL: photos are the evidence the whole
product runs on, so the collector must under-delete. Every test here pins a
way it could come to over-delete — a reference source dropped, the age floor
dropped, a deleted shelf's reads forgotten — plus the purge primitive's
scope (one library, whole library, nothing else).

The blob store is the REAL DiskBlobStore on a temp dir, same reasoning as
the API ring's `_blobs()`: the reconciler's one external fact is what is
actually on disk, and a fake that returns what it was handed asserts nothing
about the part that can be wrong (variants, sidecars, the fan-out layout).
"""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.disk_blobs import DiskBlobStore
from app.adapters.memory_store import MemoryReadStore, MemoryShelfStore
from app.blob_lifecycle import collect_orphans, find_orphans, referenced_keys
from app.domain import (
    Claim,
    ClaimTier,
    LibraryRef,
    append_claim,
    finish_read,
    new_capture,
    new_read,
    new_shelf,
)

LIB = LibraryRef(id="lib-1", label="ראשית")
OTHER = LibraryRef(id="lib-2", label="אחרת")


def _png(colour=(200, 30, 30)) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (24, 24), colour).save(out, format="PNG")
    return out.getvalue()


class _World:
    """One library's worth of stores, plus shortcuts to seed them."""

    def __init__(self, root: Path) -> None:
        self.blobs = DiskBlobStore(root)
        self.shelves = MemoryShelfStore()
        self.reads = MemoryReadStore()
        self._n = 0

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}-{self._n}"

    def upload(self, colour, library: LibraryRef = LIB) -> str:
        return self.blobs.put(library, _png(colour)).key

    def shelf_with_capture(self, image_key: str | None,
                           library: LibraryRef = LIB):
        shelf = new_shelf(id=self._id("sh"), library_id=library.id)
        self.shelves.save_shelf(library, shelf)
        capture = new_capture(shelf, id=self._id("cap"), image_id=image_key)
        self.shelves.save_capture(library, capture)
        return shelf, capture

    def read_with_crop(self, shelf, capture, crop_key: str | None,
                       library: LibraryRef = LIB):
        read = new_read(shelf, [capture], id=self._id("rd"), depth=1,
                        mode="spines", started_at="2026-08-10T00:00:00+00:00")
        read = append_claim(read, Claim(
            id=self._id("cl"), spine_id="sp1", capture_id=capture.id,
            title="ספר", tier=ClaimTier.AUTO, crop_key=crop_key,
        ))
        read = finish_read(read, finished_at="2026-08-10T00:01:00+00:00")
        self.reads.save_read(library, read)
        return read


def _world():
    tmp = Path(tempfile.mkdtemp(prefix="booksnap-gc-"))
    return _World(tmp), tmp


def test_references_come_from_captures_and_claims_both():
    """Dropping either source over-deletes: captures alone would collect
    every spine crop, reads alone every unread photo."""
    w, tmp = _world()
    try:
        photo = w.upload((10, 10, 10))
        crop = w.upload((20, 20, 20))
        shelf, capture = w.shelf_with_capture(photo)
        w.read_with_crop(shelf, capture, crop)
        keys = referenced_keys(LIB, w.shelves, w.reads)
        assert photo in keys, "a capture's photo is referenced"
        assert crop in keys, "a claim's spine crop is referenced"
        plan = find_orphans(LIB, w.blobs, w.shelves, w.reads, min_age_s=0)
        assert plan.orphans == ()
        assert plan.referenced == 2 and plan.stored == 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_an_unreferenced_blob_is_collected_and_its_variants_go_with_it():
    w, tmp = _world()
    try:
        photo = w.upload((10, 10, 10))
        stray = w.upload((99, 99, 99))
        shelf, capture = w.shelf_with_capture(photo)
        plan = collect_orphans(LIB, w.blobs, w.shelves, w.reads, min_age_s=0)
        assert plan.orphans == (stray,)
        assert w.blobs.read(LIB, stray) is None
        assert w.blobs.stat(LIB, stray) is None, "the sidecar survived"
        stem = stray.partition(".")[0]
        leftovers = list((tmp / "libraries" / LIB.id / "blobs").rglob(f"{stem}*"))
        assert leftovers == [], f"derived files survived the original: {leftovers}"
        assert w.blobs.read(LIB, photo) is not None, "a referenced blob was taken"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_fresh_upload_is_never_collected():
    """Upload and capture-binding are two calls (P2.3) — a blob is
    legitimately unreferenced for the whole gap between them, so the age
    floor is what stands between the reconciler and eating an upload
    mid-flow. THE over-delete guard; reversing it must fail here."""
    w, tmp = _world()
    try:
        fresh = w.upload((50, 50, 50))   # just written: age ~0
        plan = collect_orphans(LIB, w.blobs, w.shelves, w.reads)  # default floor
        assert plan.orphans == ()
        assert plan.too_young == (fresh,)
        assert w.blobs.read(LIB, fresh) is not None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_repeat_upload_makes_an_old_blob_young_again():
    """The dedup path (`put` of bytes already stored) must refresh mtime —
    age is the reconciler's whole safety floor, and a re-dropped photo is
    ABOUT to be bound to a capture. Without the refresh, a GC that listed
    before the new binding and deleted after it takes a blob a capture now
    points at (found by review, reproduced end to end)."""
    import os as _os
    import time as _time

    w, tmp = _world()
    try:
        data = _png((60, 60, 60))
        key = w.blobs.put(LIB, data).key
        path = next(p for p in (tmp / "libraries" / LIB.id / "blobs").rglob("*")
                    if p.name == key)
        old = _time.time() - 3 * 24 * 3600
        _os.utime(path, (old, old))
        assert w.blobs.list_keys(LIB)[0].age_seconds > 24 * 3600
        assert w.blobs.put(LIB, data).key == key   # the dedup path
        assert w.blobs.list_keys(LIB)[0].age_seconds < 3600, (
            "a repeat upload left the blob 'old' — the age floor no longer "
            "protects the upload-then-bind gap it exists for"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_deleted_shelfs_reads_still_protect_their_crops():
    """The reason `ReadStore.list_all_reads` exists: a shelf whose captures
    were removed can itself be deleted while its reads remain, and their
    crops are evidence a DB row still points at. A shelf-walk reconciler
    would collect them — mutation: swap `list_all_reads` for a walk of
    current shelves and this fails."""
    w, tmp = _world()
    try:
        photo = w.upload((10, 10, 10))
        crop = w.upload((20, 20, 20))
        shelf, capture = w.shelf_with_capture(photo)
        w.read_with_crop(shelf, capture, crop)
        assert w.shelves.delete_capture(LIB, capture.id)
        assert w.shelves.delete_shelf(LIB, shelf.id)
        plan = collect_orphans(LIB, w.blobs, w.shelves, w.reads, min_age_s=0)
        assert crop not in plan.orphans, (
            "a retired shelf's read lost its crop — evidence a DB row points at"
        )
        assert w.blobs.read(LIB, crop) is not None
        # The capture's photo genuinely IS unreferenced now — the capture row
        # is gone — but the READ still names the capture id, not the photo
        # key; only the crop is the read's own reference. The photo goes.
        assert photo in plan.orphans
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_wishlists_captures_count_as_references_too():
    """`list_shelves` defaults to excluding virtual shelves — the one
    default that is WRONG here, because a wishlist photo is still a photo."""
    w, tmp = _world()
    try:
        photo = w.upload((10, 10, 10))
        shelf = new_shelf(id="sh-wish", library_id=LIB.id, label="משאלות",
                          virtual=True)
        w.shelves.save_shelf(LIB, shelf)
        w.shelves.save_capture(LIB, new_capture(shelf, id="cap-w",
                                                image_id=photo))
        plan = find_orphans(LIB, w.blobs, w.shelves, w.reads, min_age_s=0)
        assert plan.orphans == (), "a wishlist photo was declared orphaned"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_collection_is_scoped_to_one_library():
    w, tmp = _world()
    try:
        stray_here = w.upload((99, 99, 99))
        stray_there = w.upload((99, 99, 99), library=OTHER)
        plan = collect_orphans(LIB, w.blobs, w.shelves, w.reads, min_age_s=0)
        assert plan.orphans == (stray_here,)
        assert w.blobs.read(OTHER, stray_there) is not None, (
            "collecting one library touched another's bytes"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_purge_removes_one_librarys_everything_and_nothing_else():
    """§3's "user-purgeable", the primitive: originals, variants, sidecars,
    the whole tree — for ONE library. Idempotent on an empty one."""
    w, tmp = _world()
    try:
        w.upload((10, 10, 10))
        w.upload((20, 20, 20))
        kept = w.upload((30, 30, 30), library=OTHER)
        assert w.blobs.purge(LIB) == 2
        assert not (tmp / "libraries" / LIB.id).exists()
        assert w.blobs.list_keys(LIB) == ()
        assert w.blobs.read(OTHER, kept) is not None
        assert w.blobs.purge(LIB) == 0, "purging nothing must be 0, not an error"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_list_keys_reports_originals_only():
    """Variants and sidecars are DERIVED — listing them would double-count
    what one delete removes, and the reconciler would report phantom
    orphans that `delete` already took."""
    w, tmp = _world()
    try:
        key = w.upload((10, 10, 10))
        assert w.blobs.read(LIB, key, variant="thumb") is not None  # force render
        listed = w.blobs.list_keys(LIB)
        assert [b.key for b in listed] == [key]
        assert listed[0].age_seconds >= 0.0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))
