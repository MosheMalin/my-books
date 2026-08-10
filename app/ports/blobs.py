# -*- coding: utf-8 -*-
"""The BlobStore port — image bytes, kept out of the database (D1, P2.3).

Shelf photos are multi-MB JPEGs. In the database file they would bloat it,
route every image read through this process, and make a backup of the catalog
a backup of the photo album. So bytes live behind this port with a **storage
key in a row**, which is the rule D1 states and P3.5 later re-keys per tenant.

Three properties are the port, and each is here because getting it wrong is
expensive later rather than annoying now:

  - **content-addressed.** The key is derived from the bytes' SHA-256, so
    uploading the same photo twice stores it once and returns the same key
    (§12.3 #13). A phone camera roll re-uploaded after a browser refresh is the
    normal case, not an edge one;
  - **library-scoped on every method** (H2), like every other port here. The
    disk adapter already writes under ``libraries/<library_id>/``, which is
    P3.5's own layout — so pillar 3 inherits retention and orphan-collection
    work, not a migration;
  - **variants are a CACHE, not data.** A thumbnail can always be regenerated
    from the original, so losing one costs a re-render and nothing else. The
    ADAPTER owns them end to end — the port asks for ``variant="thumb"`` and
    gets bytes, and whether they were cached, just made, or made twice is not
    the caller's business. That is also what keeps the API layer out of the
    image-processing business, which the layering test forbids outright.

P3.5 added the lifecycle half: :meth:`BlobStore.list_keys` (what is actually
stored, for the orphan reconciler in :mod:`app.blob_lifecycle`) and
:meth:`BlobStore.purge` (everything a library ever stored, gone — the §3
"user-purgeable" primitive, and half of what a future DELETE-library needs).
Retention POLICY stays out: §3's decision is "keep originals + crops,
user-purgeable" — keeping is free, so there is no TTL machinery to own here.

Still deliberately NOT here: any notion of *what* an image depicts, which is
the ``Capture`` aggregate's business — including which keys are REFERENCED.
The store cannot see the other aggregates, so "orphan" is a word only
:mod:`app.blob_lifecycle` may use.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain import LibraryRef


class BlobError(Exception):
    """Base for storage failures that are the caller's problem, not the disk's."""


class UnsupportedImage(BlobError):
    """The bytes are not an image this system will serve.

    Checked by DECODING, never by trusting the filename or the declared
    content type — both are client-supplied, and a store that believes them
    will happily serve whatever was actually uploaded back to a browser under
    an image content type.
    """


class ImageTooLarge(BlobError):
    """Above the accepted upload ceiling.

    A limit exists because the alternative is that one mistaken video fills the
    disk. It is not a cost control — that is pillar 5.
    """


@dataclass(frozen=True)
class Blob:
    """What the store knows about one stored object.

    ``width``/``height`` are here rather than left to the client because the
    review grid needs an aspect ratio before the bytes arrive, and asking the
    browser to discover it means a reflow on every tile.
    """

    key: str
    sha256: str
    size: int
    content_type: str
    filename: str = ""
    width: int = 0
    height: int = 0


class BlobStore(Protocol):
    """Byte storage for images. All methods library-scoped (H2)."""

    def put(
        self,
        library: LibraryRef,
        data: bytes,
        *,
        filename: str = "",
    ) -> Blob:
        """Store ``data`` and return its :class:`Blob`.

        **Idempotent by content**: the same bytes yield the same key and are
        written once. Re-uploading therefore costs a hash, not a duplicate, and
        two captures may legitimately share one blob.

        The content type is determined by DECODING the image, not from
        ``filename`` — see :class:`UnsupportedImage`. Raises that for anything
        that will not decode, and :class:`ImageTooLarge` past the ceiling.
        """

    def stat(
        self,
        library: LibraryRef,
        key: str,
        *,
        variant: str | None = None,
    ) -> Blob | None:
        """Metadata without the bytes, or ``None``. A blob in another library
        reads as absent — the same 404-not-403 reasoning as the other stores
        (§4.2)."""

    def read(
        self,
        library: LibraryRef,
        key: str,
        *,
        variant: str | None = None,
    ) -> bytes | None:
        """The bytes, or ``None`` if absent (or foreign, which is the same).

        ``variant="thumb"`` returns a rendition for a grid. The implementation
        decides whether to cache it and when to make it; a caller must never
        get ``None`` for a variant of a blob that exists, because "the picture
        is missing" and "the thumbnail has not been made yet" look identical on
        screen and only one of them is a real problem.
        """

    def delete(self, library: LibraryRef, key: str) -> bool:
        """Remove a blob and every variant of it. ``False`` if it wasn't there.

        ⚠ Nothing here checks whether a ``Capture`` still points at it — the
        store cannot see the other aggregate. A deleted blob leaves a capture
        whose image will not load; that is a recorded, deliberate gap (the
        admin-gated DELETE route says what it destroys), and the orphan
        reconciler (P3.5) cleans the OTHER direction — bytes no row names.
        """

    def list_keys(self, library: LibraryRef) -> tuple["StoredBlob", ...]:
        """Every ORIGINAL stored for this library — never variants or
        metadata sidecars, which are derived from an original and travel with
        it (P3.5).

        ``age_seconds`` is measured at call time, because the one thing the
        reconciler must know besides the key is "was this uploaded a moment
        ago" — upload and capture-binding are two calls (P2.3), so a blob is
        legitimately unreferenced in the gap between them, and a collector
        without an age floor would eat uploads mid-flow.
        """

    def purge(self, library: LibraryRef) -> int:
        """Delete EVERYTHING this library ever stored — originals, variants,
        sidecars. Returns how many originals went.

        §3's "user-purgeable", as a primitive: the API exposes per-photo
        deletion (admin, `DELETE /images/{key}`); this whole-library form has
        no route yet — it is half of what DELETE-library needs (the other
        half is the six-aggregate cascade that item still owes), and a
        destructive bulk route with no UI asking for it would be speculative.
        Idempotent: purging an empty or unknown library is 0, not an error.
        """


@dataclass(frozen=True)
class StoredBlob:
    """One stored original, as the reconciler sees it (P3.5)."""

    key: str
    age_seconds: float
