# -*- coding: utf-8 -*-
"""Wire types. Deliberately NOT the domain entities (H3).

Two jobs, and they pull in opposite directions if you let them:

  - a DTO is the API's *contract*, so it changes only when the API means to.
    Serialising ``Book`` directly would make every domain refactor a breaking
    API change and every DTO convenience a domain field;
  - a DTO is also the source of the generated TypeScript
    (``app/web/src/api/schema.d.ts``), so a field renamed here becomes a client
    BUILD failure. ``tools/api_contract.py`` enforces that the committed schema
    stays in step.

Mapping lives here rather than in the domain, because the domain must not know
an HTTP layer exists.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain import Book, Capture, Claim, Copy, Lending, Provenance, Read, Shelf
from app.ports.blobs import Blob


class LibraryRefDTO(BaseModel):
    """The tenant reference the client echoes back on every request.

    Present from the very first endpoint on purpose: the client is
    tenant-aware from P1.0 (§1.3), even though there is exactly one library
    until pillar 3.
    """

    id: str = Field(description="Opaque library identifier.")
    label: str = Field(description="Human-readable library name.")


class MetaResponse(BaseModel):
    """Service identity + the caller's resolved library."""

    app: str = Field(description="Service name.")
    version: str = Field(description="Server package version.")
    api_version: str = Field(description="API major version, e.g. 'v1'.")
    library: LibraryRefDTO = Field(description="Library resolved for this caller.")


# --- books ---------------------------------------------------------------

class SightingDTO(BaseModel):
    """One entry of a copy's append-only provenance (§5.2)."""

    run_id: str
    spine_id: str
    shelf_id: str | None = Field(
        default=None,
        description="Where this sighting happened. Null for the 251 imported "
                    "books, whose recorded evidence is only run+spine.",
    )
    depth: int | None = Field(
        default=None,
        description="Which row front-to-back (§5.7). Travels WITH shelf_id — "
                    "both null or both set.",
    )
    captured_at: str | None = None

    @classmethod
    def of(cls, p: Provenance) -> "SightingDTO":
        return cls(run_id=p.run_id, spine_id=p.spine_id, shelf_id=p.shelf_id,
                   depth=p.depth, captured_at=p.captured_at)


class LendingDTO(BaseModel):
    """Per copy, never per book — you lend an object, not a work."""

    lent_to: str
    lent_at: str
    due_at: str | None = None
    returned_at: str | None = None
    is_out: bool = Field(description="Derived: no returned_at yet.")

    @classmethod
    def of(cls, l: Lending) -> "LendingDTO":
        return cls(lent_to=l.lent_to, lent_at=l.lent_at, due_at=l.due_at,
                   returned_at=l.returned_at, is_out=l.is_out)


class CopyDTO(BaseModel):
    """One physical object. Created only by a human action (§5.1)."""

    id: str
    status: str
    label: str = ""
    shelf_id: str | None = None
    depth: int | None = Field(
        default=None,
        description="Row front-to-back. A located copy always has one; an "
                    "unlocated copy has neither shelf nor depth (§5.7).",
    )
    tags: list[str] = Field(default_factory=list)
    condition: str = ""
    acquired_at: str | None = None
    lending: LendingDTO | None = None
    last_seen: SightingDTO | None = Field(
        default=None, description="Most recent provenance entry, if any."
    )
    sighting_count: int = Field(
        description="Length of the provenance list; the list itself is on the "
                    "book detail, not in every row.",
    )

    @classmethod
    def of(cls, c: Copy) -> "CopyDTO":
        return cls(
            id=c.id,
            status=c.status.value,
            label=c.label,
            shelf_id=c.shelf_id,
            depth=c.depth,
            tags=list(c.fields.tags),
            condition=c.fields.condition,
            acquired_at=c.fields.acquired_at,
            lending=LendingDTO.of(c.lending) if c.lending else None,
            last_seen=SightingDTO.of(c.last_seen) if c.last_seen else None,
            sighting_count=len(c.provenance),
        )


class WorkFieldsDTO(BaseModel):
    """Book-level user fields. You don't rate your second copy differently."""

    rating: int | None = None
    notes: str = ""
    read_status: str | None = None


class BookDTO(BaseModel):
    """A book and its copies.

    Copies are embedded in the LIST response, not fetched per row. With one
    copy per book on the real data that is roughly a 2x payload, and the
    alternative — the book surface firing a request per card (UI_PLAN §5) —
    is far worse. Revisit if a library ever has many multi-copy books.
    """

    id: str
    title: str
    author: str = ""
    author_key: str = Field(
        description="Normalized author, the key the author chip groups on "
                    "(§5.1 — authors are strings, not entities).",
    )
    status: str = Field(description="auto | approved | manual — the strongest "
                                    "claim among this book's copies.")
    copy_count: int
    added_at: str | None = None
    shared_book_id: str | None = None
    work: WorkFieldsDTO
    copies: list[CopyDTO]

    @classmethod
    def of(cls, b: Book) -> "BookDTO":
        return cls(
            id=b.id,
            title=b.title,
            author=b.author,
            author_key=b.normalized_author,
            status=b.status.value,
            copy_count=b.copy_count,
            added_at=b.added_at,
            shared_book_id=b.shared_book_id,
            work=WorkFieldsDTO(rating=b.work.rating, notes=b.work.notes,
                               read_status=b.work.read_status),
            copies=[CopyDTO.of(c) for c in b.copies],
        )


class BookPageDTO(BaseModel):
    """One page plus the total, so the client can render "1-20 of 251"
    without a second round trip."""

    items: list[BookDTO]
    total: int
    offset: int
    limit: int


class BookPatch(BaseModel):
    """Fix a title or an author by hand. Either field, or both.

    Saving marks the book ``manual`` — a human decision outranking an auto one
    (UI_PLAN §5). That is applied by the domain, not here.
    """

    title: str | None = Field(default=None, min_length=1)
    author: str | None = None


class BookCreate(BaseModel):
    """Add a book the reader never found. Lands as ``manual`` with one copy."""

    title: str = Field(min_length=1)
    author: str = ""


class CopyCreate(BaseModel):
    """*"I have another copy"* (§5.1) — the only path that creates a second
    physical object. No ``shelf_id`` here: shelves don't exist until P2.1, so
    every copy today is unlocated regardless of how it was created."""

    label: str = ""
    tags: list[str] = Field(default_factory=list)
    condition: str = ""


class CopyPatch(BaseModel):
    """Fix a copy's own label/tags/condition. Object-level, unlike
    :class:`BookPatch` — describing "paperback, torn cover" is not a claim
    about the book's identity, so unlike a title/author edit this does not
    change the copy's status."""

    label: str | None = None
    tags: list[str] | None = None
    condition: str | None = None


class LendRequest(BaseModel):
    """*"Lend it out"*. ``lent_at`` is server time (the ``Clock``, like
    ``added_at``), never client-supplied — a borrow date is a fact about when
    the server recorded the action, not something the caller should be able
    to backdate."""

    lent_to: str = Field(min_length=1)
    due_at: str | None = None


# --- shelves and captures (P2.1/P2.2) ------------------------------------

class ShelfDTO(BaseModel):
    """A shelf's identity. No address — that is pillar 6 (plan §1.1)."""

    id: str
    label: str = Field(
        default="",
        description="Optional. Empty is normal: identity is free, so a shelf "
                    "is never required to be named. An unnamed one is shown "
                    "by the image it came from.",
    )
    depth_count: int = Field(
        description="Rows front-to-back, declared by the owner — never "
                    "detected (§5.7). 1 unless a row behind was added.",
    )
    virtual: bool = Field(
        description="The wishlist. Excluded from shelf listings by default.",
    )
    created_at: str | None = None
    capture_count: int = Field(
        description="Photos filed against this shelf, across every depth.",
    )

    @classmethod
    def of(cls, shelf: Shelf, *, capture_count: int) -> "ShelfDTO":
        return cls(
            id=shelf.id, label=shelf.label, depth_count=shelf.depth_count,
            virtual=shelf.virtual, created_at=shelf.created_at,
            capture_count=capture_count,
        )


class ShelfCreate(BaseModel):
    """Declare a shelf. Every field optional — see :class:`ShelfDTO.label`."""

    label: str = ""
    virtual: bool = False


class ShelfPatch(BaseModel):
    """Name a shelf, or clear the name. ``depth_count`` is deliberately NOT
    here: adding a row behind is its own endpoint, because §5.7 makes it an
    explicit declaration rather than a number to nudge."""

    label: str | None = None


class CaptureDTO(BaseModel):
    """One photo of part of a shelf, keyed by ``(shelf, depth, order)``."""

    id: str
    shelf_id: str
    depth: int = Field(description="Which row front-to-back. 1-based.")
    order: int = Field(
        description="Position among this shelf+depth's photos, left-to-right "
                    "or right-to-left per the shelf's reading direction.",
    )
    image_id: str | None = Field(
        default=None,
        description="Reference, never bytes — blobs live behind BlobStore "
                    "(P3.5). Also what identifies an unnamed shelf on screen.",
    )
    captured_at: str | None = None

    @classmethod
    def of(cls, c: Capture) -> "CaptureDTO":
        return cls(id=c.id, shelf_id=c.shelf_id, depth=c.depth, order=c.order,
                   image_id=c.image_id, captured_at=c.captured_at)


class CaptureCreate(BaseModel):
    """File a photo.

    ``shelf_id`` is optional and that is the point of P2.2: a photo that names
    no shelf gets a fresh unnamed one, because a capture with no shelf is a
    read with nothing to reconcile against (§5.6). *"Unassigned"* on screen
    means *not yet named*, never *not yet filed*.
    """

    image_id: str | None = None
    shelf_id: str | None = None
    depth: int = Field(default=1, ge=1)
    order: int | None = Field(
        default=None,
        description="Omit to append after the last photo at this shelf+depth.",
    )


class CapturePatch(BaseModel):
    """Re-bind a photo: move it to another shelf, another row, or another
    position. This is the inline assignment the intake UI performs."""

    shelf_id: str | None = None
    depth: int | None = Field(default=None, ge=1)
    order: int | None = Field(default=None, ge=0)


class ImageDTO(BaseModel):
    """A stored photo. Bytes are served from ``/images/{key}/full|thumb``."""

    key: str = Field(
        description="Storage key AND content hash. Re-uploading the same photo "
                    "returns this same key, so a URL built from it can be "
                    "cached forever — different bytes can never reuse it.",
    )
    sha256: str
    size: int = Field(description="Bytes as STORED, after EXIF normalisation.")
    content_type: str
    filename: str = Field(
        default="", description="Original name, for the review screen only.",
    )
    width: int = 0
    height: int = Field(
        default=0,
        description="Dimensions of the stored, upright image — so the grid can "
                    "reserve the right aspect ratio before the bytes arrive.",
    )

    @classmethod
    def of(cls, blob: Blob) -> "ImageDTO":
        return cls(key=blob.key, sha256=blob.sha256, size=blob.size,
                   content_type=blob.content_type, filename=blob.filename,
                   width=blob.width, height=blob.height)


class CaptureBinding(BaseModel):
    """What :meth:`create` produced — the photo AND the shelf it landed on.

    Both, never just the capture: when the shelf was auto-created the client
    has no other way to learn its id, and a second round trip to discover the
    thing you just implicitly made is the sort of gap that gets papered over
    with a client-side guess. Same reasoning as the copy routes returning the
    whole ``BookDTO``.
    """

    capture: CaptureDTO
    shelf: ShelfDTO
    shelf_created: bool = Field(
        description="True when no shelf_id was given and one was made.",
    )


# --- reads and claims (P2.4) -----------------------------------------------

class ClaimDTO(BaseModel):
    """What one read asserts about one spine (`app.domain.read.Claim`)."""

    id: str
    spine_id: str
    capture_id: str
    text: str = Field(description="The raw OCR/read text for this spine.")
    title: str = ""
    author: str = ""
    tier: str = Field(description="auto | review | unmatched.")
    score: float = 0.0
    catalog_id: str | None = None
    crop_key: str | None = Field(
        default=None,
        description="BlobStore key of the spine crop, if the engine produced "
                    "one. Fetch its picture at GET /images/{crop_key}/thumb"
                    "|full — the same endpoint every other photo uses.",
    )
    box: list[int] | None = Field(
        default=None,
        description="[x0,y0,x1,y1] within the source capture image, or null.",
    )

    @classmethod
    def of(cls, c: Claim) -> "ClaimDTO":
        return cls(
            id=c.id, spine_id=c.spine_id, capture_id=c.capture_id, text=c.text,
            title=c.title, author=c.author, tier=c.tier.value, score=c.score,
            catalog_id=c.catalog_id, crop_key=c.crop_key,
            box=list(c.box) if c.box is not None else None,
        )


class ReadSummaryDTO(BaseModel):
    """One row of a shelf's read history — no claims, no config. Listing a
    shelf's reads is a history view (§5.6's "history as diffs" surface, once
    P2.8 builds it); it does not need every claim of every past read to
    render a row."""

    id: str
    shelf_id: str
    depth: int
    mode: str
    status: str
    claim_count: int
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None

    @classmethod
    def of(cls, r: Read) -> "ReadSummaryDTO":
        return cls(
            id=r.id, shelf_id=r.shelf_id, depth=r.depth, mode=r.mode,
            status=r.status.value, claim_count=len(r.claims),
            started_at=r.started_at, finished_at=r.finished_at, error=r.error,
        )


class ReadDTO(BaseModel):
    """One read, in full — returned by start/get/stop, never by the list.

    ``config`` is the full tunable snapshot from `app.domain.read.Read` —
    included for the same audit reason the tuning server exposes its own run
    config, not because a review screen needs to render it.
    """

    id: str
    shelf_id: str
    depth: int
    capture_ids: list[str]
    mode: str
    status: str
    code_version: dict | None = None
    config: dict | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    claims: list[ClaimDTO] = Field(default_factory=list)
    progress: dict | None = Field(
        default=None,
        description="Live progress while running (image N of M, spines "
                    "read) — NOT persisted; comes from the job runner and is "
                    "null once the read has a terminal status.",
    )

    @classmethod
    def of(cls, r: Read, *, progress: dict | None = None) -> "ReadDTO":
        return cls(
            id=r.id, shelf_id=r.shelf_id, depth=r.depth,
            capture_ids=list(r.capture_ids), mode=r.mode, status=r.status.value,
            code_version=r.code_version, config=r.config,
            started_at=r.started_at, finished_at=r.finished_at, error=r.error,
            claims=[ClaimDTO.of(c) for c in r.claims], progress=progress,
        )


class ReadCreate(BaseModel):
    """Start a read of one shelf at one depth."""

    depth: int = Field(default=1, ge=1)
    mode: str = Field(
        default="spines",
        description="Engine mode: 'spines' (Tesseract, free, ~10s/spine), "
                    "'fullpage' (Google Vision) or 'llmpage' (Claude vision, "
                    "the engine's own current default per CLAUDE.md). Passed "
                    "straight through to booksnap.Pipeline.run — modes are "
                    "the engine's own, not redefined here.",
    )
