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
import re
from dataclasses import dataclass
from pathlib import Path

#: What a library id may look like before it is joined into a path.
#:
#: ⚠ The KEY was validated from the first commit and the LIBRARY ID was not —
#: an asymmetry two reviewers found independently, three lines below a
#: docstring explaining why a key must never be trusted. Measured on Windows:
#: ``".."`` climbs out of the root, ``"C:/Windows"`` replaces it outright, and
#: a UNC segment turns a database column into an outbound SMB fetch.
#: Not reachable today (ids are `uuid4().hex`) — but `tools/import_legacy.py`
#: writes an operator-supplied `--library` verbatim, and the owner's own tree
#: already holds a non-uuid `dev-library`, so "ids are always hex" is a
#: convention, not an invariant.
_SAFE_LIBRARY_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

#: Longest filename this service will republish.
#:
#: ⚠ `filename` is the upload's form field, verbatim, and NOTHING on the write
#: path caps it. A review measured 20 captures with 200,000-character names
#: turning one `GET /images` into 4 MB, i.e. ~40 MB at `limit=200` — from an
#: unauthenticated LAN upload. The real fix belongs at the port where the name
#: enters; this is the console refusing to be the amplifier in the meantime,
#: and it is lossless for every name a camera or a human produces.
MAX_FILENAME = 200


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
        """⚠ The id is VALIDATED before it becomes a path segment — see
        :data:`_SAFE_LIBRARY_ID`. `pathlib` does not normalise `..`, and a
        drive-qualified segment replaces the root rather than extending it."""
        if self.root is None or not _SAFE_LIBRARY_ID.fullmatch(library_id):
            return None
        return self.root / "libraries" / library_id / "blobs"

    # --- is the disk even visible from here? --------------------------------

    @property
    def visible(self) -> bool:
        """Whether this process can see the blob tree at all.

        ⚠⚠ The distinction a review caught, and it is the difference between a
        dashboard and a false alarm. With no blob root configured — a state
        `main.py:blob_root` deliberately tolerates, because the database and
        the photographs can live on different machines — every capture reports
        `present=False`, which `ImageDTO` documents as *"a photograph the
        household can no longer see"*. So the console would announce that every
        photograph in every tenant is lost, and, worse, a GENUINE loss would be
        invisible among them. Three states, not two: present, lost, and
        can't-tell.
        """
        return self.root is not None and (self.root / "libraries").is_dir()

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
        if path is None:
            return BlobFacts(key=key)
        meta: dict[str, object] = {}
        sidecar = path.with_suffix(".json")
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A sidecar can be absent (an older blob) or corrupt. The FILE may
            # still be there and its size still true, so the row degrades to
            # "we know how big it is" rather than vanishing.
            meta = {}
        try:
            size = path.stat().st_size
        except OSError:
            # ⚠ Not merely "the file is gone": `exists()`-then-`stat()` is a
            # RACE, and `tools/blob_gc.py` is the other runner. Before a review
            # measured it, a GC unlinking one orphan mid-render 500'd the whole
            # cross-tenant page — instead of one row reading `present=False`,
            # which is the posture this dataclass promises. `_walk` guarded the
            # same race and this did not.
            return BlobFacts(key=key)
        return BlobFacts(
            key=key, present=True, bytes=size,
            width=_int(meta.get("width")), height=_int(meta.get("height")),
            content_type=str(meta.get("content_type") or ""),
            filename=str(meta.get("filename") or "")[:MAX_FILENAME],
            sha256=str(meta.get("sha256") or ""),
        )


def _walk(directory: Path) -> Usage:
    """Files and bytes under one directory, recursively.

    ⚠ Symlinks are not followed (`follow_symlinks=False` on the type check and
    on the `stat`): a link into the rest of the filesystem would otherwise make
    a household's storage figure the size of the machine.

    ⚠ **Windows DIRECTORY JUNCTIONS are followed, and that is not covered by
    the line above.** A review measured it: `mklink /J` inside a blob directory
    reports `is_symlink() == False` and `is_dir(follow_symlinks=False) == True`,
    so the junction is walked — a 1-file tree reported 42 files. It needs no
    administrator rights. Accepted rather than fixed, with the reason stated:
    creating one requires write access to the blob tree, i.e. the attacker is
    already inside the data this figure describes, and containment-checking
    every directory would cost a `resolve()` per node on the walk this service
    runs twice per dashboard load. Say it plainly rather than let the symlink
    sentence read as a guarantee it is not.
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
