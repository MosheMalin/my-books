# -*- coding: utf-8 -*-
"""Local-disk BlobStore (P2.3). Images on a filesystem, keys in the database.

D1 keeps blobs out of SQLite; this is the other half of that decision. The
layout is **already P3.5's**::

    <root>/libraries/<library_id>/blobs/<ab>/<sha256>.<ext>
                                            <sha256>.json      sidecar
                                            <sha256>~thumb.jpg variant

so pillar 3 inherits retention, purge and orphan collection rather than a path
migration. The two-character fan-out exists because a few thousand files in one
directory is where filesystems and `ls` both start to hurt.

**Content-addressed**: the key is the digest, so re-uploading a photo after a
browser refresh writes nothing and returns the same key. That also means two
captures may legitimately share one blob, which is why :meth:`delete` cannot be
called from capture deletion — see the port's warning.

⚠ **EXIF orientation is applied when the bytes are stored, not when they are
shown.** Phone photos carry a rotation flag; `cv2.imread` honours it, PIL does
not unless asked, and browsers honour it only for some `img` cases. Left alone,
the engine would read an upright shelf while the review grid showed it on its
side — and the person reviewing would reasonably conclude the reader was
broken. So the stored bytes are normalised once, up front, and everything
downstream sees the same pixels.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
from pathlib import Path

from app.domain import LibraryRef
from app.ports.blobs import Blob, ImageTooLarge, UnsupportedImage

# 40MB. A 48MP phone JPEG is ~15MB and a HEIC well under that, so this is
# "somebody dropped a video in", not a quality ceiling.
MAX_UPLOAD_BYTES = 40 * 1024 * 1024

THUMB = "thumb"
THUMB_MAX_PX = 480
THUMB_QUALITY = 82
# Every rendition is a JPEG whatever the original was: one format means the
# review grid has one code path.
_VARIANT_EXT = "jpg"
VARIANT_CONTENT_TYPE = "image/jpeg"

# What we will decode AND serve back, keyed by what PIL reports as the format.
#
# ⚠ **MPO is here because it is what phones actually produce.** A "JPEG" out of
# a modern iPhone or Samsung is usually a Multi-Picture Object: a JPEG
# container carrying a second embedded frame (HDR, depth, or the second lens).
# PIL reports `format='MPO'`, not `'JPEG'`, so a whitelist of the obvious three
# rejects EVERY REAL PHOTO while passing every synthetic test image — PIL's own
# `Image.new(...).save(format='JPEG')` produces plain JPEG. That is exactly how
# this shipped broken: the tests were green and every upload from the owner's
# phone 415'd. Frame 0 of an MPO is an ordinary JPEG, which is what browsers
# and cv2 both read, so it is served as `image/jpeg`.
_FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "MPO": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}

# What to RE-ENCODE as when orientation has to be corrected. The second frame
# is not wanted — the product needs the picture, not the depth map.
#
# ⚠ Honest note: this line is NOT load-bearing, and removing it survives the
# test suite. PIL writing a single transposed frame with `format='MPO'`
# produces output byte-identical to `format='JPEG'` (measured: 678 bytes
# either way, read back as JPEG). It stays because it states the intent
# explicitly rather than leaning on that undocumented equivalence — but it is
# belt-and-braces, not a rule, and it is written down that way so nobody
# mistakes a passing suite for coverage of it.
_REENCODE_AS = {"MPO": "JPEG"}

# Formats PIL cannot open at all but whose container is recognisable, so the
# refusal can say what to do instead of "not a decodable image". HEIC is the
# iPhone default whenever the camera is NOT set to "Most Compatible", so this
# is the single most likely upload failure after MPO.
_MAGIC_HINTS = (
    (b"ftypheic", "HEIC"), (b"ftypheix", "HEIC"), (b"ftyphevc", "HEIC"),
    (b"ftypmif1", "HEIF"), (b"ftypavif", "AVIF"),
)


class DiskBlobStore:
    """Implements ``app.ports.blobs.BlobStore``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # --- layout ----------------------------------------------------------

    def _dir(self, library: LibraryRef) -> Path:
        return self.root / "libraries" / library.id / "blobs"

    def _path(self, library: LibraryRef, key: str,
              variant: str | None = None) -> Path | None:
        """Resolve a key (and optional variant) to a path, or ``None``.

        The key is validated rather than trusted: it arrives in a URL, and
        ``../`` in a path segment is how a store that just joins strings serves
        somebody's private key file. A key here is always ``<64 hex>.<ext>``.

        ⚠ **A variant carries its OWN extension, not the original's.** Every
        rendition is a JPEG whatever the source was, so deriving the path from
        the key's extension writes JPEG bytes into a ``~thumb.png`` — which
        then gets served as ``image/png`` and renders as a broken image. Caught
        by a test rather than by review.
        """
        stem, _, ext = key.partition(".")
        if len(stem) != 64 or not all(c in "0123456789abcdef" for c in stem):
            return None
        if not ext.isalnum():
            return None
        if variant is not None:
            if not variant.isalnum():
                return None
            return self._dir(library) / stem[:2] / f"{stem}~{variant}.{_VARIANT_EXT}"
        return self._dir(library) / stem[:2] / f"{stem}.{ext}"

    def _sidecar(self, library: LibraryRef, key: str) -> Path | None:
        path = self._path(library, key)
        return path.with_suffix(".json") if path else None

    # --- BlobStore -------------------------------------------------------

    def put(self, library: LibraryRef, data: bytes, *, filename: str = "") -> Blob:
        if len(data) > MAX_UPLOAD_BYTES:
            raise ImageTooLarge(
                f"{len(data)} bytes is over the {MAX_UPLOAD_BYTES} limit"
            )
        normalised, content_type, ext, size_px = _normalise(data)

        # The digest is of the STORED bytes, not the uploaded ones. Otherwise
        # the same photo uploaded twice — once already upright, once with an
        # EXIF flag — would hash differently and store twice, while being
        # pixel-identical on disk.
        sha = hashlib.sha256(normalised).hexdigest()
        key = f"{sha}.{ext}"
        path = self._path(library, key)
        assert path is not None  # our own key, always well-formed
        path.parent.mkdir(parents=True, exist_ok=True)

        blob = Blob(key=key, sha256=sha, size=len(normalised),
                    content_type=content_type, filename=filename,
                    width=size_px[0], height=size_px[1])
        if not path.exists():
            _write_atomic(path, normalised)
        # The sidecar is rewritten even on a repeat upload: the bytes are the
        # same photo, but the filename may be the better one this time (a
        # re-upload from the camera roll rather than "download (3).jpg").
        _write_atomic(self._sidecar(library, key),
                      json.dumps(_meta(blob), ensure_ascii=False).encode())
        self._render(library, key, THUMB, normalised)
        return blob

    def stat(self, library: LibraryRef, key: str, *,
             variant: str | None = None) -> Blob | None:
        path = self._path(library, key, variant)
        if path is None:
            return None
        if variant is None:
            return self._read_meta(library, key) if path.exists() else None
        # A variant is a rendition of the same image: it keeps the original's
        # key (that is how it is addressed) and reports its OWN content type,
        # which is JPEG regardless of what the original was.
        if not path.exists() and self.read(library, key, variant=variant) is None:
            return None
        stored = self._read_meta(library, key)
        return Blob(key=key, sha256=stored.sha256 if stored else "",
                    size=path.stat().st_size if path.exists() else 0,
                    content_type=VARIANT_CONTENT_TYPE,
                    filename=stored.filename if stored else "")

    def read(self, library: LibraryRef, key: str, *,
             variant: str | None = None) -> bytes | None:
        path = self._path(library, key, variant)
        if path is None:
            return None
        if path.exists():
            return path.read_bytes()
        if variant is None:
            return None
        # The rendition is a CACHE: a missing one is re-derived rather than
        # reported absent, because on screen "no thumbnail yet" and "this photo
        # is gone" look identical and only one of them is a real problem.
        original = self.read(library, key)
        if original is None:
            return None
        return self._render(library, key, variant, original)

    def delete(self, library: LibraryRef, key: str) -> bool:
        path = self._path(library, key)
        if path is None or not path.exists():
            return False
        path.unlink()
        sidecar = self._sidecar(library, key)
        if sidecar and sidecar.exists():
            sidecar.unlink()
        # Variants are a cache of this original, so they go with it. Globbing
        # rather than tracking them: the cost of a stale rendition surviving is
        # a wrong picture on a screen, which is worse than a directory scan.
        for extra in path.parent.glob(f"{path.stem}~*"):
            extra.unlink()
        return True

    # --- internals -------------------------------------------------------

    def _render(self, library: LibraryRef, key: str, variant: str,
                original: bytes) -> bytes | None:
        """Make a rendition and cache it. Never raises.

        A thumbnail that will not render must not fail the upload it came from:
        the photo is the asset and the rendition is a convenience, so losing an
        upload because a grid tile could not be made would be the wrong trade
        by a wide margin. Nor may it fail a read — the caller gets the bytes it
        managed to produce, or ``None`` and a missing tile.
        """
        if variant != THUMB:
            return None
        try:
            thumb = _thumbnail(original)
        except Exception:
            return None
        path = self._path(library, key, variant)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(path, thumb)
        return thumb

    def _read_meta(self, library: LibraryRef, key: str) -> Blob | None:
        sidecar = self._sidecar(library, key)
        if sidecar is None or not sidecar.exists():
            return None
        raw = json.loads(sidecar.read_text(encoding="utf-8"))
        return Blob(**raw)


def _meta(blob: Blob) -> dict:
    return {"key": blob.key, "sha256": blob.sha256, "size": blob.size,
            "content_type": blob.content_type, "filename": blob.filename,
            "width": blob.width, "height": blob.height}


def _write_atomic(path: Path, data: bytes) -> None:
    """Write via a temp file in the same directory, then rename.

    A half-written JPEG is indistinguishable from a corrupt upload, and it
    would be served forever because the key says the content is already there.
    """
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    shutil.move(str(tmp), str(path))


def _normalise(data: bytes) -> tuple[bytes, str, str, tuple[int, int]]:
    """Decode, apply EXIF orientation, and re-encode. Returns the stored form.

    Decoding is also the VALIDATION: a client's filename and content type are
    both its own claim, and a store that trusts them serves back whatever was
    really uploaded under an image content type. If PIL cannot open it, it is
    not an image as far as this system is concerned.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").upper()
            if fmt not in _FORMATS:
                raise UnsupportedImage(
                    f"{fmt or 'unknown'} is not a format this system serves; "
                    f"use JPEG, PNG or WEBP"
                )
            content_type, ext = _FORMATS[fmt]
            upright = ImageOps.exif_transpose(img)
            if upright is img or _orientation(img) in (None, 1):
                # Nothing to correct — keep the ORIGINAL bytes rather than
                # re-encoding. A JPEG round-tripped through PIL loses quality
                # for no reason, and the engine's accuracy is measured on the
                # pixels it is given. An MPO kept whole is a little larger than
                # it needs to be (it still carries its second frame), which is
                # a cheap price for not touching the pixels the reader sees.
                return data, content_type, ext, img.size
            out = io.BytesIO()
            upright.save(out, format=_REENCODE_AS.get(fmt, fmt), quality=95)
            return out.getvalue(), content_type, ext, upright.size
    except UnidentifiedImageError as exc:
        raise UnsupportedImage(_undecodable_reason(data)) from exc


def _undecodable_reason(data: bytes) -> str:
    """Name the format when the container is recognisable.

    "not a decodable image" is true and useless: the owner is holding a photo
    that plainly IS one. HEIC in particular is the iPhone default whenever the
    camera is not set to "Most Compatible", so the message has to say what to
    change rather than leaving them to conclude the app is broken.
    """
    head = data[:32]
    for magic, name in _MAGIC_HINTS:
        if magic in head:
            return (
                f"{name} images are not supported yet. On iPhone: Settings → "
                "Camera → Formats → Most Compatible, then re-take or "
                "re-export the photo as JPEG."
            )
    return "not a decodable image"


def _orientation(img) -> int | None:
    try:
        exif = img.getexif()
    except Exception:
        return None
    return exif.get(0x0112) if exif else None


def _thumbnail(data: bytes, max_px: int = THUMB_MAX_PX) -> bytes:
    """A JPEG thumbnail of ``data``.

    Always JPEG regardless of the source format: a thumbnail is a rendition for
    a grid, and one format means the review screen has one code path. The
    original is untouched and is what the engine reads.
    """
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as img:
        # Already normalised on the way in, but harmless and correct if this is
        # ever called on bytes from elsewhere.
        upright = ImageOps.exif_transpose(img) or img
        upright.thumbnail((max_px, max_px))
        out = io.BytesIO()
        upright.convert("RGB").save(out, format="JPEG", quality=THUMB_QUALITY)
    return out.getvalue()
