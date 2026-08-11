# -*- coding: utf-8 -*-
"""How much disk each tenant's photographs occupy.

⚠ **Nothing in the database knows how large a photograph is.**
:mod:`app.ports.blobs` keeps bytes out of it on purpose (D1: the database must
not become a backup of the photo album), so size lives on disk — in the file
itself and in the JSON sidecar :class:`app.adapters.disk_blobs.DiskBlobStore`
writes beside it. A console that wants to answer *"how much space does this
account occupy"* has to look at the tree.

⚠ **And it may not import the adapter that owns that tree.**
``tests/test_layering.py:test_the_staff_service_binds_no_adapter_and_so_needs_
no_exemption`` keeps this service free of ``app.adapters`` — that is the
recorded argument for why ``app/staff_api/main.py`` is not in
``COMPOSITION_ROOTS``, and importing ``DiskBlobStore`` here to borrow eight
lines of path-joining would spend it.

So this module knows the LAYOUT on purpose, exactly the way
:mod:`app.staff_api.queries` knows the schema on purpose, and it is guarded the
same way: ``tests/test_staff_api.py`` writes a blob through the real
``DiskBlobStore`` and asserts this reader finds it with the same size and the
same digest. A layout change fails a test rather than quietly reporting 0 MB.

**What is counted, and why it is not the sum of the originals.** Every file
under a library's blob directory: originals, the ``~thumb`` renditions the
store generates, and the sidecars. That is what the disk holds, and "space this
account occupies" is the question an operator is asking when they look at a
storage column. The alternative — summing the sidecars' ``size`` fields — would
report a number smaller than the disk by however many renditions exist, which
is the sort of plausible-but-wrong figure this service exists not to produce.

**No caching.** One walk per request, `os.scandir`, O(files). At the scale this
product has (hundreds of photographs per household) that is a handful of
milliseconds, and a TTL cache would trade a real number for a stale one plus a
clock. When it stops being cheap, measure it and say so here.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Usage:
    """What one library's blob directory holds."""

    files: int = 0
    bytes: int = 0


@dataclass(frozen=True)
class BlobFacts:
    """One image, from its sidecar. ``present`` is about the FILE.

    A capture whose bytes are gone is not a rounding error — it is a photograph
    the household can no longer see, and the console is the only place anyone
    would notice. So a missing blob reports ``present=False`` with zeroes,
    rather than being skipped or crashing the page it appears on.
    """

    key: str
    present: bool = False
    bytes: int = 0
    width: int = 0
    height: int = 0
    content_type: str = ""
    filename: str = ""
    sha256: str = ""


class BlobTree:
    """Read-only sight of the blob root. ``None`` means "not configured".

    A console pointed at a database but not at a blob root is a normal state —
    it happens the moment the two live on different machines — and it must
    report zero storage rather than 500 on the dashboard. Same posture as the
    staff token: degrade, and say what is missing.
    """

    def __init__(self, root: str | Path | None) -> None:
        self.root = Path(root) if root else None

    # --- layout (mirrors app/adapters/disk_blobs.py — see the module note) ---

    def _dir(self, library_id: str) -> Path | None:
        if self.root is None or not library_id:
            return None
        return self.root / "libraries" / library_id / "blobs"

    def _path(self, library_id: str, key: str) -> Path | None:
        """Resolve a key to a file, or ``None`` if it is not a well-formed one.

        ⚠ The key is VALIDATED, never trusted, for the same reason the store
        validates it: it arrives from a database column that a capture row
        could hold anything in, and ``../`` in a path segment is how a reader
        that just joins strings walks out of the blob root. A key here is
        always ``<64 hex>.<alnum ext>``.
        """
        base = self._dir(library_id)
        if base is None:
            return None
        stem, _, ext = key.partition(".")
        if len(stem) != 64 or not all(c in "0123456789abcdef" for c in stem):
            return None
        if not ext.isalnum():
            return None
        return base / stem[:2] / f"{stem}.{ext}"

    # --- questions ----------------------------------------------------------

    def usage(self) -> dict[str, Usage]:
        """Every library's footprint, from ONE walk of the tree.

        Keyed by library id — including ids the database no longer has, which
        is deliberate: bytes belonging to a deleted library still occupy the
        disk, and a total that quietly omitted them would be wrong in the one
        direction an operator cares about.
        """
        out: dict[str, Usage] = {}
        if self.root is None:
            return out
        libraries = self.root / "libraries"
        try:
            entries = list(os.scandir(libraries))
        except OSError:
            # Not configured yet, or on another machine. Zero, not a failure.
            return out
        for entry in entries:
            if entry.is_dir():
                out[entry.name] = _walk(Path(entry.path) / "blobs")
        return out

    def facts(self, library_id: str, key: str | None) -> BlobFacts:
        """One image's metadata, from its sidecar plus the file itself.

        ⚠ ``bytes`` comes from ``stat()``, not from the sidecar's ``size``
        field. The two agree when nothing has gone wrong, and when they do not,
        the disk is the one telling the truth about disk usage.
        """
        if not key:
            return BlobFacts(key="")
        path = self._path(library_id, key)
        if path is None or not path.exists():
            return BlobFacts(key=key)
        meta: dict[str, object] = {}
        sidecar = path.with_suffix(".json")
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A sidecar can be absent (an older blob) or corrupt. The FILE is
            # still there and its size is still true, so the row degrades to
            # "we know how big it is" rather than vanishing.
            meta = {}
        return BlobFacts(
            key=key, present=True, bytes=path.stat().st_size,
            width=_int(meta.get("width")), height=_int(meta.get("height")),
            content_type=str(meta.get("content_type") or ""),
            filename=str(meta.get("filename") or ""),
            sha256=str(meta.get("sha256") or ""),
        )


def _walk(directory: Path) -> Usage:
    """Files and bytes under one directory, recursively.

    ⚠ Symlinks are not followed (`follow_symlinks=False` on the type check and
    the default for `DirEntry.stat`): a link into the rest of the filesystem
    would otherwise make a household's storage figure the size of the machine.
    """
    files = total = 0
    stack = [directory]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    files += 1
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                # A file removed between the listing and the stat. Skipping it
                # is the honest answer; raising would blank a dashboard because
                # the GC ran at the wrong moment.
                continue
    return Usage(files=files, bytes=total)


def _int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
