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

from app.domain import Book, Copy, Lending, Provenance


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
        description="Null until the map exists (§1.1) — the UI hides it.",
    )
    captured_at: str | None = None

    @classmethod
    def of(cls, p: Provenance) -> "SightingDTO":
        return cls(run_id=p.run_id, spine_id=p.spine_id, shelf_id=p.shelf_id,
                   captured_at=p.captured_at)


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
