# -*- coding: utf-8 -*-
"""/api/v1/images — the bytes behind a capture (P2.3).

THIN by rule (H3): validation, decoding and the storage layout all live in the
``BlobStore`` adapter, and what is here is the HTTP shape.

**Upload and binding are two calls, deliberately.** ``POST /images`` stores
bytes and returns a key; ``POST /captures`` files a photo onto a shelf. The
alternative — one multipart call that uploads and binds — reads tidier and is
worse in the flow that actually happens: the owner drops twelve photos at once,
and the shelf/depth for each is decided while looking at the thumbnails. Two
calls also make upload progress per-photo, and let a re-upload be free (the
key is the content hash, so the second attempt writes nothing).

Serving the bytes back from the product is not a detail either: the tuning
server's `work/runs/` is ITS archive, and the product reads its own store or
nothing. That rule is what keeps P3.5 a re-keying rather than a migration.
"""
from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)

from app.api.deps import get_blob_store
from app.api.dto import ImageDTO
from app.api.policy import require
from app.domain import Capability, LibraryRef
from app.ports.blobs import BlobStore, ImageTooLarge, UnsupportedImage

router = APIRouter(prefix="/images", tags=["images"])

THUMB = "thumb"

# A browser caches an image URL forever safely here: the key IS the content
# hash, so different bytes can never reuse a URL. That is the one real payoff
# of content addressing on the serving side.
_IMMUTABLE = "public, max-age=31536000, immutable"


@router.post("", response_model=ImageDTO, status_code=status.HTTP_201_CREATED)
async def upload_image(
    file: UploadFile = File(description="The photo. Decoded to validate it."),
    filename: str = Form(
        default="",
        description="Original name, for the review screen. Falls back to the "
                    "upload's own name; never used to decide the format.",
    ),
    library: LibraryRef = Depends(require(Capability.CAPTURE)),
    store: BlobStore = Depends(get_blob_store),
) -> ImageDTO:
    """Store a photo. **Idempotent by content** — the same bytes return the
    same key and write nothing the second time, so a re-upload after a browser
    refresh costs a hash rather than a duplicate (§12.3 #13).

    ``201`` either way. A conditional ``200``-if-present would leak whether
    somebody has already uploaded this exact photo, and the client has nothing
    to do differently.
    """
    data = await file.read()
    try:
        blob = store.put(library, data, filename=filename or file.filename or "")
    except UnsupportedImage as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            str(exc)) from exc
    except ImageTooLarge as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            str(exc)) from exc
    return ImageDTO.of(blob)


@router.get("/{key}", response_model=ImageDTO)
def get_image(
    key: str,
    library: LibraryRef = Depends(require(Capability.VIEW_PHOTOS)),
    store: BlobStore = Depends(get_blob_store),
) -> ImageDTO:
    """Metadata without the bytes — size, dimensions, original filename."""
    blob = store.stat(library, key)
    if blob is None:
        # Absent and foreign are the same answer (§4.2).
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such image")
    return ImageDTO.of(blob)


@router.get("/{key}/full")
def get_full(
    key: str,
    library: LibraryRef = Depends(require(Capability.VIEW_PHOTOS)),
    store: BlobStore = Depends(get_blob_store),
) -> Response:
    """The stored photo, EXIF already applied — the same pixels the engine
    reads, which is what makes a review screen trustworthy."""
    return _serve(store, library, key, variant=None)


@router.get("/{key}/thumb")
def get_thumb(
    key: str,
    library: LibraryRef = Depends(require(Capability.VIEW_PHOTOS)),
    store: BlobStore = Depends(get_blob_store),
) -> Response:
    """A JPEG thumbnail for the review grid.

    Whether it was cached at upload or derived just now is the adapter's
    business — this route asks for a variant and gets bytes. Keeping the
    rendering behind the port is also what keeps the API layer out of the
    image-processing business, which the layering test forbids outright.
    """
    return _serve(store, library, key, variant=THUMB)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(
    key: str,
    library: LibraryRef = Depends(require(Capability.DELETE_PHOTOS)),
    store: BlobStore = Depends(get_blob_store),
) -> None:
    """Remove a photo and its renditions.

    ⚠ Does NOT check whether a capture still points at it — the stores cannot
    see each other's aggregates, and reference counting is P3.5's. Until then
    this is for a photo uploaded by mistake, and a capture whose image was
    deleted shows a missing picture rather than disappearing.
    """
    if not store.delete(library, key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such image")


def _serve(store: BlobStore, library: LibraryRef, key: str,
           *, variant: str | None) -> Response:
    data = store.read(library, key, variant=variant)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such image")
    blob = store.stat(library, key, variant=variant)
    return Response(
        content=data,
        media_type=blob.content_type if blob else "application/octet-stream",
        headers={"Cache-Control": _IMMUTABLE, "ETag": f'"{key}-{variant or ""}"'},
    )
