# -*- coding: utf-8 -*-
"""Wire types. Deliberately NOT the domain entities (H3).

Two jobs, and they pull in opposite directions if you let them:

  - a DTO is the API's *contract*, so it changes only when the API means to.
    Serialising ``Book`` directly would make every domain refactor a breaking
    API change and every DTO convenience a domain field;
  - a DTO is also the source of the generated TypeScript
    (``app/ui/src/api/schema.d.ts``), so a field renamed here becomes a client
    BUILD failure. ``tools/api_contract.py`` enforces that the committed schema
    stays in step.

Mapping lives here rather than in the domain, because the domain must not know
an HTTP layer exists.
"""
from __future__ import annotations

from typing import Mapping

from pydantic import BaseModel, Field

from app.domain.alias import ShelfAlias
from app.domain import (
    AddressParts,
    MergePlan,
    DEFAULT_COLUMNS,
    DEFAULT_DEPTH,
    DEFAULT_LEVELS,
    MAX_DEPTH,
    MAX_SLOTS_PER_BOOKCASE,
    Alternative,
    Book,
    Bookcase,
    Capture,
    Claim,
    Copy,
    DepthStatus,
    DiffSummary,
    Lending,
    Library,
    Membership,
    Provenance,
    Floor,
    Place,
    Read,
    Rect,
    Section,
    Shelf,
    ShelfAddress,
    Site,
    SlotRemoval,
)
from app.ports.map import MapSnapshot
from app.ports.blobs import Blob


class LibraryRefDTO(BaseModel):
    """The tenant reference the client echoes back on every request.

    Present from the very first endpoint on purpose: the client is
    tenant-aware from P1.0 (§1.3), even though there is exactly one library
    until pillar 3.
    """

    id: str = Field(description="Opaque library identifier.")
    label: str = Field(description="Human-readable library name.")


class UserDTO(BaseModel):
    """Who the server thinks is asking (§4.1).

    The session's user (P4.1b). On the wire because the switcher's list
    is *this user's* libraries, and a client that cannot name the user
    cannot explain an empty list.

    ⚠ Called ``AccountDTO`` until P3.7a. The word "account" now belongs to the
    CUSTOMER (VISION §4.1, 2026-08-11) and arrives on the wire at P3.7b —
    reading this field as a tenant is the mistake the rename exists to stop.
    """

    id: str = Field(description="Opaque user identifier (the session's "
                                "user since P4.1b).")
    display_name: str = Field(default="", description="Shown in the UI, if set.")


class LibraryDTO(BaseModel):
    """One library the caller is a member of, with the role they hold.

    A superset of :class:`LibraryRefDTO` rather than a replacement: the REF is
    what travels on every request, and the switcher needs the role too. See
    ``app/domain/tenancy.py`` for why the two types exist.
    """

    id: str
    account_id: str = Field(description="The customer that owns it (§4.1). On "
                                        "the wire because the role below is "
                                        "held per ACCOUNT, so two libraries "
                                        "sharing one always agree.")
    label: str = Field(description="Human-readable name; blank only for a "
                                   "library backfilled by schema v12.")
    role: str = Field(description="viewer | editor | admin (§4.2) — the "
                                  "caller's role in the OWNING ACCOUNT, so it "
                                  "is the same for every library of one.")
    created_at: str | None = None

    @classmethod
    def of(cls, library: Library, membership: Membership) -> "LibraryDTO":
        return cls(id=library.id, account_id=library.account_id,
                   label=library.label, role=membership.role.value,
                   created_at=library.created_at)


class LibraryCreate(BaseModel):
    """A library is created with a name (§4.3) — see `new_library`.

    ⚠ No ``min_length`` here on purpose, tempting though it is. Pydantic would
    then answer 422 for ``""`` while ``"   "`` reached the domain and came
    back 400 — two status codes for one mistake, decided by whitespace. The
    rule lives in :func:`app.domain.tenancy.new_library`, which strips first,
    so the API stays thin (H3) and the answer stays one thing.
    """

    label: str = Field(description="What the household calls it.")


class LibraryPatch(BaseModel):
    """Rename. The only mutable field a library has today."""

    label: str


class LoginLinkRequest(BaseModel):
    """Ask for a sign-in link (§3's magic link, P4.1a).

    ⚠ Minimal shape-checking only, and no `EmailStr` on purpose: that
    validator drags in a dependency to reject addresses a mail provider
    would accept, and the honest test of an address is whether mail
    arrives. A wrong address costs its owner a link that never comes —
    the same answer as a right address, which is also the anti-enumeration
    property the route needs.
    """

    email: str = Field(max_length=254,
                       description="Where the link goes. 254 is RFC 5321's cap.")


class ProvidersDTO(BaseModel):
    """Which provider sign-ins this DEPLOYMENT configured (P4.2).

    A fact about configuration, not about any caller — so it is safe
    before anyone is signed in, and it is what lets the login screen
    offer exactly the buttons that work (absent, not disabled).
    """

    providers: list[str] = Field(
        description="Subset of ['google', 'apple'] — empty is normal.")


class SessionCreate(BaseModel):
    """Redeem an emailed token for a session cookie."""

    token: str = Field(max_length=128,
                       description="The token from the sign-in link, verbatim.")


class MemberDTO(BaseModel):
    """One person in the account, with the role covering every library it
    owns (§4.1 — a role is held per account)."""

    user_id: str
    display_name: str = ""
    role: str = Field(description="viewer | editor | admin")
    joined_at: str | None = None


class InviteCreate(BaseModel):
    """Mint an invite (or set a member's role — the same one field)."""

    role: str = Field(description="viewer | editor | admin")


class InviteMintedDTO(BaseModel):
    """The freshly minted invite, RAW TOKEN INCLUDED — shown exactly once.

    The store holds only the hash, so no later call can reproduce this.
    The client's job is to put the link where the admin can copy it NOW.
    """

    token: str
    role: str
    expires_at: str


class InviteDTO(BaseModel):
    """An open invite's metadata. ``id`` is the token's hash — enough to
    revoke, useless to redeem."""

    id: str
    role: str
    created_at: str
    expires_at: str


class InviteAccept(BaseModel):
    """Redeem an invite link."""

    token: str = Field(max_length=128)


class MetaResponse(BaseModel):
    """Service identity + who is asking + the library resolved for them."""

    app: str = Field(description="Service name.")
    version: str = Field(description="Server package version.")
    api_version: str = Field(description="API major version, e.g. 'v1'.")
    library: LibraryRefDTO = Field(description="Library resolved for this caller.")
    user: UserDTO = Field(description="The caller, from the session.")


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
    not_seen_streak: int | None = Field(
        default=None,
        description="Consecutive most-recent reads of this copy's OWN "
                    "(shelf, depth) that did not reconfirm it (§5.6's soft "
                    "badge, never a removal — app.domain.history.not_seen_"
                    "streak). Populated only by GET /shelves/{id}/books, "
                    "which has that shelf's read archive in hand; null "
                    "everywhere else, including an unlocated copy.",
    )

    @classmethod
    def of(cls, c: Copy, *, not_seen_streak: int | None = None) -> "CopyDTO":
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
            not_seen_streak=not_seen_streak,
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
    def of(cls, b: Book, *, streaks: Mapping[str, int] | None = None) -> "BookDTO":
        """``streaks`` maps a copy id to its ``not_seen_streak`` (P2.8) — a
        book-list caller never passes it (no shelf/depth in view), so every
        copy's badge is simply absent there, exactly as intended."""
        streaks = streaks or {}
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
            copies=[CopyDTO.of(c, not_seen_streak=streaks.get(c.id))
                    for c in b.copies],
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

class ShelfAddressDTO(BaseModel):
    """Where a shelf stands, once somebody has drawn it (pillar 6).

    ``section -> column -> level`` and nothing above it: the room, the case,
    the storey and the site are all reachable FROM the section, and copying
    them here would be four fields that disagree with the drawing the moment
    a bookcase moves. Both indices are **1-based**.
    """

    section_id: str
    col: int = Field(ge=1)
    level: int = Field(ge=1, description="Counts from the TOP of the column.")

    @classmethod
    def of(cls, address: ShelfAddress) -> "ShelfAddressDTO":
        return cls(section_id=address.section_id, col=address.col,
                   level=address.level)


class FormerIdentityDTO(BaseModel):
    """One identity this shelf answers for, and where it used to stand.

    §3.11's own sentence, made visible: *"the shelf that was at section 1,
    column 2, level 3"* is a question the library can still answer after the
    wood has been re-identified — and the address is the half that survives in
    someone's memory when the id does not.

    ⚠ ``label`` is the household's name for the absorbed shelf, which the
    merge would otherwise destroy. A shelf is *"the one with the cookbooks"*
    long after the drawing has been rearranged.
    """

    id: str
    label: str = ""
    merged_at: str = ""
    address: ShelfAddressDTO | None = Field(
        default=None,
        description="Where it USED to stand. Historical: §3.10a leaves the "
                    "extent untouched, so the cell may since have become a "
                    "gap and that is fine — this answers *the shelf that "
                    "was*, not *the shelf that is*.",
    )


class ShelfDTO(BaseModel):
    """A shelf's identity, and — since P6.1 — where it stands, if anywhere."""

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
    book_count: int = Field(
        default=0,
        description="Copies standing on this shelf, across every depth. What "
                    "a destructive gesture has to be able to say out loud "
                    "before it happens — and, when it is zero along with "
                    "`capture_count`, the reason not to ask at all.",
    )
    address: ShelfAddressDTO | None = Field(
        default=None,
        description="Null for every shelf born from a photograph — which is "
                    "most of them, and stays legal forever: the drawn and the "
                    "photographed are ONE population, and binding them is "
                    "P6.4's job rather than a precondition.",
    )

    formerly: list[FormerIdentityDTO] = Field(
        default_factory=list,
        description="Identities absorbed into this shelf (§3.11). Empty for "
                    "almost every shelf, and never null: a screen that has to "
                    "ask whether the list exists before asking whether it is "
                    "empty gets it wrong once.",
    )

    @classmethod
    def of(cls, shelf: Shelf, *, capture_count: int,
           book_count: int = 0,
           formerly: tuple[ShelfAlias, ...] = ()) -> "ShelfDTO":
        return cls(
            formerly=[FormerIdentityDTO(
                id=a.alias_id, label=a.label, merged_at=a.merged_at,
                address=(ShelfAddressDTO(section_id=a.address.section_id,
                                         col=a.address.col,
                                         level=a.address.level)
                         if a.address else None))
                for a in formerly],
            id=shelf.id, label=shelf.label, depth_count=shelf.depth_count,
            virtual=shelf.virtual, created_at=shelf.created_at,
            capture_count=capture_count,
            book_count=book_count,
            address=(ShelfAddressDTO.of(shelf.address)
                     if shelf.address else None),
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


class DepthStatusDTO(BaseModel):
    """One row's last-read date, for the shelf-detail screen's soft
    staleness line (UI_PLAN §3: *"rows 2, 3 not read since 11.3.2026"*) —
    see ``app.domain.history.depth_staleness``."""

    depth: int
    last_read_at: str | None = Field(
        default=None, description="Null if this row has never been read.",
    )
    is_stale: bool = Field(
        description="Read less recently than this SHELF's own freshest row "
                    "— never against a clock, and never automatic beyond "
                    "this soft line (§5.7's own closing note).",
    )

    @classmethod
    def of(cls, s: DepthStatus) -> "DepthStatusDTO":
        return cls(depth=s.depth, last_read_at=s.last_read_at, is_stale=s.is_stale)


class ShelfOverviewDTO(BaseModel):
    """The shelf-detail screen's header data (UI_PLAN §3, level 3): declared
    depth, per-row last-read dates and the staleness line they imply. Books
    themselves are a separate call (``GET /shelves/{id}/books``) — this is
    the shelf's own state, not its contents, the same split ``BookDetail``
    keeps from the list."""

    shelf: ShelfDTO
    depths: list[DepthStatusDTO]
    last_read_at: str | None = Field(
        default=None,
        description="The freshest read across EVERY depth, or null if this "
                    "shelf has never been read at all.",
    )

    @classmethod
    def of(cls, shelf: Shelf, *, capture_count: int,
           depths: list[DepthStatusDTO], book_count: int = 0,
           formerly: tuple[ShelfAlias, ...] = ()) -> "ShelfOverviewDTO":
        """⚠ `formerly` and `book_count` are here because THIS is the route
        the shelf screen reads. `ShelfDTO.of` has four construction sites and
        only `_dto` carried them, so *the shelf says what it was* — the
        headline of P6.4e — shipped inert: the field was populated on
        `GET /shelves` and `GET /shelves/{id}`, which that screen does not
        call. A review caught it; the client ring was green because the
        harness built the overview body by hand and injected the field the
        server never sent.
        """
        freshest = max((d.last_read_at for d in depths if d.last_read_at),
                       default=None)
        return cls(shelf=ShelfDTO.of(shelf, capture_count=capture_count,
                                     book_count=book_count,
                                     formerly=formerly),
                   depths=depths, last_read_at=freshest)


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

class AlternativeDTO(BaseModel):
    """One ranked runner-up `booksnap.match.explain()` considered for a
    claim's OCR text (P2.7) — what the review UI's "why?" panel renders.
    ``reason`` is empty for a candidate that passed the matcher's own gates
    (a real runner-up) and names the gate that refused one that didn't."""

    title: str
    author: str = ""
    score: float = 0.0
    reason: str = ""

    @classmethod
    def of(cls, a: Alternative) -> "AlternativeDTO":
        return cls(title=a.title, author=a.author, score=a.score,
                   reason=a.reason)


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
    alternatives: list[AlternativeDTO] = Field(
        default_factory=list,
        description="Ranked runners-up from explain(), for the review UI's "
                    "'why?' — never the accepted match itself. Empty when the "
                    "engine had no OCR text or no explain() to ask (a "
                    "structured fallback provider).",
    )

    @classmethod
    def of(cls, c: Claim) -> "ClaimDTO":
        return cls(
            id=c.id, spine_id=c.spine_id, capture_id=c.capture_id, text=c.text,
            title=c.title, author=c.author, tier=c.tier.value, score=c.score,
            catalog_id=c.catalog_id, crop_key=c.crop_key,
            box=list(c.box) if c.box is not None else None,
            alternatives=[AlternativeDTO.of(a) for a in c.alternatives],
        )


class DiffSummaryDTO(BaseModel):
    """Headline diff counts, captured once when a read settles — see
    ``app.domain.read.DiffSummary`` for why this is a SNAPSHOT and must never
    be recomputed to "freshen" it. This is the plan's own example rendered
    literally: ``+3 added · 1 corrected · 12 unchanged · 1 not seen``."""

    added: int = 0
    corrected: int = 0
    unchanged: int = 0
    needs_decision: int = 0
    not_seen: int = 0
    rejected: int = 0
    ignored: int = 0

    @classmethod
    def of(cls, s: DiffSummary) -> "DiffSummaryDTO":
        return cls(added=s.added, corrected=s.corrected, unchanged=s.unchanged,
                   needs_decision=s.needs_decision, not_seen=s.not_seen,
                   rejected=s.rejected, ignored=s.ignored)


class ReadSummaryDTO(BaseModel):
    """One row of a shelf's read history — no claims, no config. Listing a
    shelf's reads is a history view (§5.6's "history as diffs" surface,
    P2.8); it does not need every claim of every past read to render a row.
    """

    id: str
    shelf_id: str
    depth: int
    mode: str
    status: str
    claim_count: int
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    diff_summary: DiffSummaryDTO | None = Field(
        default=None,
        description="Null while running, for a failed read, or for a read "
                    "that finished before this column existed (v10 and "
                    "earlier) — the history row shows it without one rather "
                    "than inventing a number nobody measured.",
    )

    @classmethod
    def of(cls, r: Read) -> "ReadSummaryDTO":
        return cls(
            id=r.id, shelf_id=r.shelf_id, depth=r.depth, mode=r.mode,
            status=r.status.value, claim_count=len(r.claims),
            started_at=r.started_at, finished_at=r.finished_at, error=r.error,
            diff_summary=DiffSummaryDTO.of(r.diff_summary)
            if r.diff_summary is not None else None,
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
    diff_summary: DiffSummaryDTO | None = Field(
        default=None,
        description="Same snapshot as ReadSummaryDTO's — see there. Carried "
                    "here too so a single read fetched on its own (e.g. from "
                    "a history row) does not need a second call.",
    )

    @classmethod
    def of(cls, r: Read, *, progress: dict | None = None) -> "ReadDTO":
        return cls(
            id=r.id, shelf_id=r.shelf_id, depth=r.depth,
            capture_ids=list(r.capture_ids), mode=r.mode, status=r.status.value,
            code_version=r.code_version, config=r.config,
            started_at=r.started_at, finished_at=r.finished_at, error=r.error,
            claims=[ClaimDTO.of(c) for c in r.claims], progress=progress,
            diff_summary=DiffSummaryDTO.of(r.diff_summary)
            if r.diff_summary is not None else None,
        )


class ReadCreate(BaseModel):
    """Start a read of one shelf at one depth."""

    depth: int = Field(default=1, ge=1)
    mode: str = Field(
        default="llmpage",
        description="Engine mode: 'llmpage' (Claude vision — the DEFAULT, and "
                    "the engine's own current default per CLAUDE.md), "
                    "'fullpage' (Google Vision) or 'spines' (Tesseract, free, "
                    "~10s/spine). Passed straight through to "
                    "booksnap.Pipeline.run — modes are the engine's own, not "
                    "redefined here. A mode whose credential is missing is "
                    "refused at the door with 409 rather than failing inside "
                    "the worker thread.",
    )


# --- reconciliation (P2.5) --------------------------------------------------
#
# Deliberately plain `str` fields for every classification (`kind`, `reason`),
# not the domain's `OutcomeKind`/`AnswerKind` enums — same convention as
# `ClaimDTO.tier` and `BookDTO.status` above (H3): a DTO is the API's own
# contract, so it must not change shape just because a domain enum grows a
# value the client has no use for yet.

class NotSeenEntryDTO(BaseModel):
    """A copy that stood here before this read and was not reconfirmed by it.
    NEVER a removal — see `app.domain.reconcile.NotSeenEntry`."""

    book: BookDTO
    copy_id: str

    @classmethod
    def of(cls, entry) -> "NotSeenEntryDTO":
        return cls(book=BookDTO.of(entry.book), copy_id=entry.copy_id)


class ClaimOutcomeDTO(BaseModel):
    """One claim, classified by `app.domain.reconcile.reconcile`."""

    claim: ClaimDTO
    kind: str = Field(
        description="added | unchanged | corrected | needs_decision | "
                    "rejected | ignored",
    )
    book_key: str = ""
    existing_book: BookDTO | None = Field(
        default=None,
        description="The book this claim resolves against, unmodified — "
                    "present for unchanged/corrected/needs_decision, null "
                    "for added (no book exists yet).",
    )
    existing_copy_id: str | None = None
    reason: str = Field(
        default="",
        description="Machine reason: same_location | new_book_unconfirmed | "
                    "manual_add | ambiguous_location | "
                    "relinked_by_decision | new_copy_by_decision | "
                    "duplicate_within_depth | no_identity | rejected | "
                    "wrong_book.",
    )

    @classmethod
    def of(cls, outcome) -> "ClaimOutcomeDTO":
        return cls(
            claim=ClaimDTO.of(outcome.claim), kind=outcome.kind.value,
            book_key=outcome.book_key,
            existing_book=BookDTO.of(outcome.existing_book)
                if outcome.existing_book is not None else None,
            existing_copy_id=outcome.existing_copy_id, reason=outcome.reason,
        )


class DiffDTO(BaseModel):
    """A read reconciled against the shelf's durable state (§5.6) — what the
    owner sees after re-photographing a shelf: a DIFF, never a new result set.
    """

    shelf_id: str
    depth: int
    read_id: str
    added: list[ClaimOutcomeDTO]
    corrected: list[ClaimOutcomeDTO]
    unchanged: list[ClaimOutcomeDTO]
    needs_decision: list[ClaimOutcomeDTO] = Field(
        description="Still open — §5.4's ask, or a REVIEW-tier new-book "
                    "claim awaiting confirm/reject. POST .../apply with an "
                    "answer for each claim_id to resolve one.",
    )
    not_seen: list[NotSeenEntryDTO]
    rejected: list[ClaimOutcomeDTO] = Field(
        description="Excluded on purpose — a standing decision said so. Not "
                    "one of the plan's four headline counts; kept for "
                    "transparency so a suppressed book has a visible reason.",
    )
    ignored: list[ClaimOutcomeDTO] = Field(
        description="No book identity, or a within-read duplicate of "
                    "another claim (§5.7 #2 overlap dedup).",
    )

    @classmethod
    def of(cls, diff) -> "DiffDTO":
        return cls(
            shelf_id=diff.shelf_id, depth=diff.depth, read_id=diff.read_id,
            added=[ClaimOutcomeDTO.of(o) for o in diff.added],
            corrected=[ClaimOutcomeDTO.of(o) for o in diff.corrected],
            unchanged=[ClaimOutcomeDTO.of(o) for o in diff.unchanged],
            needs_decision=[ClaimOutcomeDTO.of(o) for o in diff.needs_decision],
            not_seen=[NotSeenEntryDTO.of(n) for n in diff.not_seen],
            rejected=[ClaimOutcomeDTO.of(o) for o in diff.rejected],
            ignored=[ClaimOutcomeDTO.of(o) for o in diff.ignored],
        )


class AnswerIn(BaseModel):
    """One human response to one still-open (``needs_decision``) claim."""

    claim_id: str = Field(min_length=1)
    kind: str = Field(
        description="confirm | reject | already_listed | another_copy | "
                    "wrong_book — see app.reconcile_apply.AnswerKind for "
                    "which claims each fits.",
    )
    copy_id: str | None = Field(
        default=None,
        description="Which existing copy, for 'already_listed' when the "
                    "book has more than one (§5.4).",
    )
    title: str | None = Field(
        default=None,
        description="With 'confirm' only: approve this finding AS CORRECTED. "
                    "The claim keeps the engine's own text (it is evidence); "
                    "the correction lands on the book that gets created.",
    )
    author: str | None = None


class ApplyDiffRequest(BaseModel):
    """Apply a read's diff: everything `reconcile()` already decided persists
    unconditionally; ``answers`` resolves whichever ``needs_decision`` claims
    the caller is answering right now. Omitted ones simply stay open.

    "Approve all" is this route with one ``confirm`` per pending finding —
    deliberately not its own endpoint: a bulk approval is N ordinary
    approvals, and giving it a separate door would be a second place for the
    rule "an already-answered finding never rides along with approve-all" to
    be got wrong."""

    answers: list[AnswerIn] = Field(default_factory=list)


class FindingMatchDTO(BaseModel):
    """One finding of THIS read that matches what the owner is typing into
    *"add a book the engine missed"* (P2.10, owner 2026-08-09).

    Deliberately thin — an id and the two strings. The client already holds
    the whole diff, so it looks the state up by ``claim_id`` rather than
    having it repeated here; what it cannot do for itself is the MATCHING,
    which is why that stays on the server (see
    ``app.domain.search.TextEntry``)."""

    claim_id: str
    title: str
    author: str = ""
    tier: str


class ManualFindingIn(BaseModel):
    """*"The engine missed this book"* — a book the owner adds to a photo by
    hand (P2.10, owner 2026-08-09).

    It becomes a MANUAL-tier `Claim` on that read, which is what keeps the
    photo's findings a complete account of what is in the picture rather than
    only what a reader managed to see. Entering the library needs no approval
    step: typing the title IS the approval (§5.1's ladder)."""

    title: str = Field(min_length=1)
    author: str = ""
    after_spine_id: str | None = Field(
        default=None,
        description="File this finding immediately after that one, rather "
                    "than at the end. Used when one spine turns out to be "
                    "several volumes: the parts belong next to the part they "
                    "were split from, not at the bottom of the photo.",
    )


# --- the durable duplicates queue (P2.6, §5.4) ------------------------------

class DuplicateQuestionDTO(BaseModel):
    """One open §5.4 ask, as the "duplicates to resolve" queue shows it.

    ``existing_book`` and the two cheap-win fields are all computed FRESH
    against the book's CURRENT state on every read of this DTO — never
    cached on the stored question — same reasoning as `DiffDTO` being
    recomputed on every call: the book may have gained a copy, been edited,
    or had its loan returned since the question was opened.
    """

    id: str
    shelf_id: str
    depth: int
    book_key: str
    claim_title: str
    claim_author: str
    existing_book: BookDTO
    opened_at: str
    prompt_kind: str = Field(
        description="three_way | lent_out_return — the sharper question "
                    "('you lent this to X — is it back?') when the "
                    "preselected candidate copy is currently lent out "
                    "(§5.4's first cheap win).",
    )
    default_copy_id: str | None = Field(
        default=None,
        description="The preselected candidate for 'already listed' — no "
                    "shelf assigned, else least-recently-seen (§5.4's "
                    "second cheap win). A PRESELECTION only; never applied "
                    "without a human choosing it, except via POST .../skip.",
    )
    lent_to: str | None = Field(
        default=None,
        description="Populated only when prompt_kind is lent_out_return.",
    )

    @classmethod
    def of(cls, q, *, book: Book, prompt) -> "DuplicateQuestionDTO":
        return cls(
            id=q.id, shelf_id=q.shelf_id, depth=q.depth, book_key=q.book_key,
            claim_title=q.claim_title, claim_author=q.claim_author,
            existing_book=BookDTO.of(book), opened_at=q.opened_at,
            prompt_kind=prompt.kind.value,
            default_copy_id=prompt.candidate_copy_id, lent_to=prompt.lent_to,
        )


class DuplicateAnswerIn(BaseModel):
    """A human's answer to one queued question — the SAME three-way
    vocabulary as §5.4's inline prompt (`app.reconcile_apply.AnswerKind`),
    minus ``confirm``/``reject``: a queued question is always
    ``ambiguous_location`` (the review-tier "is this a real book?" question
    has no standing queue — P2.6 is scoped to copy resolution only)."""

    kind: str = Field(
        description="already_listed | another_copy | wrong_book.",
    )
    copy_id: str | None = Field(
        default=None,
        description="Which existing copy, for 'already_listed' when the "
                    "book has more than one (§5.4). Omit to use the "
                    "preselected default_copy_id.",
    )


# --- the physical map (P6.2, MAP_PLAN §3) --------------------------------
#
# The whole drawing is READ in one call and WRITTEN one object at a time —
# `app/ports/map.py` argues both halves. The DTOs follow that shape: one
# `MapDTO` out, a small Create/Patch per object in.
#
# ⚠ Geometry is `x/y/w/h` INTEGERS in abstract units, and the API says so in
# every description it can. §3.4 forbids the system deriving a capacity, a
# centimetre or a book count from a length — a plausible number nobody
# measured is exactly what a later reader adds because it looks like free
# value, and this is the layer where such a field would be added.

#: Plans are bounded because houses are. A review stored a rectangle
#: 4.6e18 units wide (accepted, echoed on every GET) and crashed the adapter
#: with 2**64 — `OverflowError: Python int too large to convert to SQLite
#: INTEGER`, a 500 on a write. The memory store took all of it happily, so
#: the API ring could never have seen either.
_PLAN_LIMIT = 100_000


class RectDTO(BaseModel):
    """A rectangle in **abstract units** — never pixels, never centimetres."""

    x: int = Field(ge=-_PLAN_LIMIT, le=_PLAN_LIMIT)
    y: int = Field(ge=-_PLAN_LIMIT, le=_PLAN_LIMIT)
    w: int = Field(gt=0, le=_PLAN_LIMIT)
    h: int = Field(gt=0, le=_PLAN_LIMIT)

    @classmethod
    def of(cls, rect: Rect) -> "RectDTO":
        return cls(x=rect.x, y=rect.y, w=rect.w, h=rect.h)

    def to_domain(self) -> Rect:
        return Rect(x=self.x, y=self.y, w=self.w, h=self.h)


class SiteDTO(BaseModel):
    """A whole property: home, the office, the parents' place."""

    id: str
    name: str
    order: int = Field(default=0, ge=-_PLAN_LIMIT, le=_PLAN_LIMIT)

    @classmethod
    def of(cls, site: Site) -> "SiteDTO":
        return cls(id=site.id, name=site.name, order=site.order)


class FloorDTO(BaseModel):
    """A storey **of one site**. Never part of a shelf's address (§3.7)."""

    id: str
    site_id: str
    name: str
    order: int = Field(default=0, ge=-_PLAN_LIMIT, le=_PLAN_LIMIT)

    @classmethod
    def of(cls, floor: Floor) -> "FloorDTO":
        return cls(id=floor.id, site_id=floor.site_id, name=floor.name,
                   order=floor.order)


class PlaceDTO(BaseModel):
    """A room, drawn as a rectangle on its floor's plan."""

    id: str
    floor_id: str
    name: str = ""
    rect: RectDTO
    order: int = Field(
        default=0, ge=-_PLAN_LIMIT, le=_PLAN_LIMIT,
        description="Drawing order, and therefore z-order: the last one drawn "
                    "is on top, which is what decides an overlapping tap.",
    )

    @classmethod
    def of(cls, place: Place) -> "PlaceDTO":
        return cls(id=place.id, floor_id=place.floor_id, name=place.name,
                   rect=RectDTO.of(place.rect), order=place.order)


class BookcaseDTO(BaseModel):
    """One piece of furniture: one footprint, one name, one room it moves
    with."""

    id: str
    floor_id: str
    place_id: str | None = Field(
        default=None,
        description="The room it stands in. Null is legal — a case drawn "
                    "before its room is somewhere rather than nowhere, and it "
                    "carries its own floor for that reason (§3.7).",
    )
    name: str = ""
    front: str = Field(
        default="S",
        description="N/E/S/W — which face the books look out of, and "
                    "therefore whose LEFT END is column 1. A fact about the "
                    "furniture, so the UI's reading direction never moves it.",
    )
    rect: RectDTO
    order: int = Field(default=0, ge=-_PLAN_LIMIT, le=_PLAN_LIMIT)

    @classmethod
    def of(cls, case: Bookcase) -> "BookcaseDTO":
        return cls(id=case.id, floor_id=case.floor_id, place_id=case.place_id,
                   name=case.name, front=case.front,
                   rect=RectDTO.of(case.rect), order=case.order)


class CellRef(BaseModel):
    """One cell of a section's face, 1-based — named, not a bare pair.

    `[2, 3]` is two numbers whose order the reader has to remember, and this
    project has been bitten by exactly that class of confusion before
    (depth ≠ row ≠ band). One shape in both directions: it is what a request
    names and what a section reports back.
    """

    column: int = Field(ge=1, le=40)
    level: int = Field(ge=1, le=40)


class SectionDTO(BaseModel):
    """One built unit of a bookcase — a low base, or the case standing on it.

    ``column_levels`` holds one entry per column, being that column's level
    count; the column count is that list's length and there is no second
    field that could disagree with it.
    """

    id: str
    bookcase_id: str
    ordinal: int = Field(
        description="1-based, BOTTOM first: section 1 stands on the floor. "
                    "Unique per bookcase, because it is what an address "
                    "prints.",
    )
    column_levels: list[int]
    gaps: list[CellRef] = Field(
        default=[],
        description="Cells that are switched OFF — the space a television "
                    "stands in, a desk niche. A MASK over the extent and "
                    "never a change to it: the shelves below a gap keep the "
                    "level numbers their addresses print. No shelf stands in "
                    "one, so a gapped cell is simply absent from the slots "
                    "this section describes.",
    )
    default_levels: int = Field(
        description="Applied when a COLUMN is created. Editing it does not "
                    "reach back into existing columns (§3.3).",
    )
    default_depth: int = Field(
        description="Applied when a SHELF is created. Editing it does not "
                    "reach back into existing shelves — read live, dropping "
                    "it from 2 to 1 would delete the location of every book "
                    "in the back row.",
    )

    @classmethod
    def of(cls, section: Section) -> "SectionDTO":
        return cls(id=section.id, bookcase_id=section.bookcase_id,
                   ordinal=section.ordinal,
                   column_levels=list(section.column_levels),
                   gaps=[CellRef(column=col, level=level)
                         for col, level in section.gaps],
                   default_levels=section.default_levels,
                   default_depth=section.default_depth)


class BookcaseDrawnDTO(BookcaseDTO):
    """What drawing a bookcase answers: the case **and the section it minted
    alongside it**.

    ⚠ The section id is not a convenience. A create mints its ids on the
    server while the document holds locally minted ones, and the client
    translates rather than rewrites (`app/web/src/map/push.ts`) — so an id it
    is never told stays local for the rest of the session. The elevation
    addresses that first section in the very next gesture: draw a case, press
    ``+ column``, and without this field the request goes to
    ``/map/sections/c3:s1`` and answers *404 no such section*. A previous fix
    claimed to close that by reading ``section`` off this response, which did
    not carry one.
    """

    section: SectionDTO

    @classmethod
    def of_drawn(cls, case: Bookcase, section: Section) -> "BookcaseDrawnDTO":
        return cls(id=case.id, floor_id=case.floor_id, place_id=case.place_id,
                   name=case.name, front=case.front,
                   rect=RectDTO.of(case.rect), order=case.order,
                   section=SectionDTO.of(section))


class MapDTO(BaseModel):
    """One library's whole drawing, in one response.

    Read whole because that is what an editor needs — the canvas cannot draw
    a room without knowing which storey is showing, nor a bookcase without
    its columns — and because a house is tens of rows, not thousands.
    """

    sites: list[SiteDTO] = []
    floors: list[FloorDTO] = []
    places: list[PlaceDTO] = []
    bookcases: list[BookcaseDTO] = []
    sections: list[SectionDTO] = []

    @classmethod
    def of(cls, snapshot: MapSnapshot) -> "MapDTO":
        return cls(
            sites=[SiteDTO.of(s) for s in snapshot.sites],
            floors=[FloorDTO.of(f) for f in snapshot.floors],
            places=[PlaceDTO.of(p) for p in snapshot.places],
            bookcases=[BookcaseDTO.of(b) for b in snapshot.bookcases],
            sections=[SectionDTO.of(s) for s in snapshot.sections],
        )


class SiteCreate(BaseModel):
    """A site is NAMED — it exists only because there are two of them, and an
    unnamed one in a picker is unusable."""

    name: str = Field(min_length=1, max_length=120)
    order: int = Field(default=0, ge=-_PLAN_LIMIT, le=_PLAN_LIMIT)


class SitePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1,
                             max_length=120)
    order: int | None = Field(default=None, ge=-_PLAN_LIMIT,
                              le=_PLAN_LIMIT)


class FloorCreate(BaseModel):
    site_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=120)
    order: int = Field(default=0, ge=-_PLAN_LIMIT, le=_PLAN_LIMIT)


class FloorPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1,
                             max_length=120)
    order: int | None = Field(default=None, ge=-_PLAN_LIMIT,
                              le=_PLAN_LIMIT)


class PlaceCreate(BaseModel):
    """A room's NAME is optional, deliberately: a plan that demands eight
    names before it shows you anything is a toll."""

    floor_id: str = Field(min_length=1)
    rect: RectDTO
    name: str = Field(default="", max_length=120)
    order: int = Field(default=0, ge=-_PLAN_LIMIT, le=_PLAN_LIMIT)


class PlacePatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    rect: RectDTO | None = None
    floor_id: str | None = None
    order: int | None = Field(default=None, ge=-_PLAN_LIMIT,
                              le=_PLAN_LIMIT)


class BookcaseCreate(BaseModel):
    """Draw a bookcase — and, with it, every shelf its first section
    describes (§3.1: a drawn slot IS a Shelf)."""

    floor_id: str = Field(min_length=1)
    rect: RectDTO
    name: str = ""
    front: str = Field(default="S", pattern="^[NESW]$")
    place_id: str | None = None
    order: int = Field(default=0, ge=-_PLAN_LIMIT, le=_PLAN_LIMIT)
    columns: int = Field(default=DEFAULT_COLUMNS, ge=1, le=40)
    levels: int = Field(default=DEFAULT_LEVELS, ge=1, le=40)
    depth: int = Field(default=DEFAULT_DEPTH, ge=1, le=MAX_DEPTH)


class BookcasePatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    rect: RectDTO | None = None
    front: str | None = Field(default=None, pattern="^[NESW]$")
    order: int | None = Field(default=None, ge=-_PLAN_LIMIT,
                              le=_PLAN_LIMIT)
    place_id: str | None = Field(
        default=None,
        description="Point the case at a room; it moves onto that room's "
                    "storey with it. Use `detach` to let go — null here means "
                    "'unchanged', because a JSON null cannot mean both.",
    )
    floor_id: str | None = Field(
        default=None,
        description="Move a DETACHED case to another storey. A case attached "
                    "to a room moves with the room instead (PATCH the room), "
                    "because furniture and its room are on one storey by "
                    "construction.",
    )
    detach: bool = Field(
        default=False,
        description="Let go of the room, keeping the storey. Explicit, "
                    "because containment may only ever REASSIGN a case, never "
                    "orphan one (§4).",
    )


class SectionCreate(BaseModel):
    """Add a section to a bookcase. It copies the shape of the one it stands
    against — a hutch usually has about as many columns as its base."""

    bookcase_id: str = Field(min_length=1)
    where: str | None = Field(
        default=None, pattern="^(top|bottom)$",
        description="At the top of the stack, or under it. Omit both fields "
                    "for the top.",
    )
    above_id: str | None = Field(
        default=None,
        description="Put it directly above THIS section, and shape it like "
                    "that one. The general form of `where`, and the only way "
                    "to express a section going back into the MIDDLE of a "
                    "stack — which is what undoing a middle removal is. "
                    "Without it the client had to say `top`, the server "
                    "appended, and the drawing and the library silently "
                    "disagreed about which unit stands on which.",
    )


class SectionPatch(BaseModel):
    """Change the grid, or the defaults. Both halves report what happened to
    the shelves, because a column removed is real shelves removed."""

    columns: int | None = Field(default=None, ge=1, le=40)
    column: int | None = Field(
        default=None, ge=1,
        description="With `levels`, changes ONE column's level count.",
    )
    levels: int | None = Field(default=None, ge=1, le=40)
    default_levels: int | None = Field(default=None, ge=1, le=40)
    default_depth: int | None = Field(default=None, ge=1, le=MAX_DEPTH)


class SectionMove(BaseModel):
    """Swap a section with the neighbour above or below it (P6.7a)."""

    direction: str = Field(
        pattern="^(up|down)$",
        description="In FURNITURE terms, never screen terms: `up` means "
                    "towards the ceiling, a higher ordinal. The elevation "
                    "draws top-down, so the arrow pointing up on screen "
                    "sends `up`.",
    )


class SectionOrderDTO(BaseModel):
    """A bookcase's sections after a reorder, bottom-first.

    The WHOLE stack, not the one section that moved: `ordinal` is unique per
    bookcase and a swap renumbers two of them, so answering with one would
    leave the client holding a stack that has two sections claiming the same
    number until it reloaded.
    """

    sections: list[SectionDTO]


class SectionGapPatch(BaseModel):
    """Switch cells off, or back on. One instruction, with its sign.

    ``gap`` is required and has no default: *make this a hole* and *make this
    a shelf again* are opposite instructions, and a defaulted boolean would
    mean an ABSENT one silently performs the destructive half.

    ⚠ That covers absence, and only absence — an earlier draft of this
    docstring said "malformed request", which a security review measured to be
    wider than the truth: pydantic's lax mode coerces ``"yes"``, ``"on"``,
    ``1`` and ``1.0`` to True, so a wrong-TYPED value still lands on the
    destructive side (``"maybe"``, ``2``, ``[]`` are 422). Left lax on
    purpose, because ``BookcasePatch.detach`` and every other boolean on this
    API behave the same way and one rule everywhere beats a stricter rule
    here — but the claim now says what it does.

    The list is capped at a bookcase's whole slot budget — a request may
    reasonably name every cell of a section, and nothing beyond that is a
    request anybody makes.
    """

    cells: list[CellRef] = Field(min_length=1, max_length=MAX_SLOTS_PER_BOOKCASE)
    gap: bool = Field(
        description="True switches the cells off (no shelf stands there); "
                    "false switches them back on, minting an empty shelf at "
                    "the section's CURRENT default depth.",
    )


class SlotDepthPatch(BaseModel):
    """One shelf's OWN depth — the per-shelf override §3.3 promises.

    Not clamped to the section's default in either direction: the whole point
    is that a shelf may differ from the case it stands in.
    """

    depth_count: int = Field(ge=1, le=MAX_DEPTH)


class SlotRemovalDTO(BaseModel):
    """What a structural edit did to the shelves standing in the slots.

    Two outcomes, never one — and the API returns both because the owner is
    entitled to know that a shelf survived rather than vanished.
    """

    deleted: list[str] = Field(
        default=[],
        description="Empty shelves that went with their slot. Scaffolding.",
    )
    detached: list[str] = Field(
        default=[],
        description="Shelves holding photos or books. They SURVIVE, without "
                    "an address — their books keep their shelf; what they "
                    "lose is a location the drawing no longer has.",
    )

    @classmethod
    def of(cls, removal: SlotRemoval) -> "SlotRemovalDTO":
        return cls(deleted=list(removal.deleted),
                   detached=list(removal.detached))


class MergeRequest(BaseModel):
    """*Absorb this shelf into that one.*

    ⚠ ``strip`` has **no default**, and that is §3.12 rather than strictness:
    appending the absorbed shelf's photographs after the survivor's encodes a
    claim — *its half is to the right* — that nothing measured. §5.7's rule is
    *declared, never detected*, and a default here would be the system
    detecting it on the owner's behalf, silently, every time.
    """

    into: str = Field(description="The surviving shelf's id.")
    strip: str = Field(
        description="Which shelf's photographs come first on the merged "
                    "strip: `absorbed_first` or `survivor_first`. One radio "
                    "button; no default.",
    )


class DepthCountDTO(BaseModel):
    """``{depth, count}`` — a per-depth tally.

    A list rather than an object keyed by depth, because JSON has only string
    keys and a client would then be parsing `"2"` back into a number to
    compare it with a shelf's own depth.
    """

    depth: int
    count: int


class DecisionClashDTO(BaseModel):
    """One `(depth, book_key)` a human answered on BOTH shelves.

    §3.13 settles it by the newer ``decided_at`` — the rule the table's own
    upsert already applies to a person changing their mind — but what is being
    overwritten here is a different answer given at a different place, so
    every one is NAMED rather than chosen in silence.
    """

    depth: int
    book_key: str
    winner: str = Field(description="`absorbed` or `survivor`.")
    absorbed_kind: str
    survivor_kind: str


class MergeRefusalDTO(BaseModel):
    """Why not, in a form a client can act on.

    ⚠ ``reason`` is a STABLE CODE beside the sentence, and it exists because
    P6.4c ended with the opposite mistake filed against it: the 409 that
    offers the merge carries its occupant as prose inside `detail`, so the
    client throws the whole string away and prints one Hebrew sentence of its
    own. A screen that must say something different for *a read is running*
    than for *the wishlist stands nowhere* cannot get there by parsing
    English.
    """

    reason: str
    say: str


class BandDTO(BaseModel):
    """One horizontal shelf surface a photograph shows, as fractions of its
    height. Fractions because the client draws them over an image it has
    scaled to fit a phone."""

    top: float = Field(ge=0, le=1)
    bottom: float = Field(ge=0, le=1)


class LevelProposalDTO(BaseModel):
    """What one photograph of a bookcase suggests its level count is (P6.6).

    ⚠ A PROPOSAL, and the word is load-bearing. §3.14: *the map may propose;
    only a ✓ binds*. This route writes nothing — no shelf, no section, no
    image, not even the photograph, which is never stored. Applying the number
    is a separate, explicit call to the section's own levels route.

    ⚠ ``levels`` is a count of BANDS in a picture, which is not the same
    statement as *this bookcase has N shelves*. A photo that shows part of a
    case answers about that part; a photo of a single shelf answers **1**,
    which is what all eleven of the owner's photographs measured on the day
    this shipped. The client says which of the two it is showing.
    """

    levels: int = Field(
        ge=1, description="How many bands the photo shows — `len(bands)`, "
                          "restated so a caller that only wants the number "
                          "does not have to count a list.",
    )
    bands: list[BandDTO]


class AddressPartsDTO(BaseModel):
    """A shelf's address as PARTS, never as a sentence.

    The sentence is Hebrew in the product and English in the console, so
    assembling it here would be a second i18n table nobody maintains. What is
    NOT the client's is which parts appear at all — that rule has one copy, in
    ``app.domain.place.address_parts``, and this DTO is its wire shape.

    ``section``, ``column`` and ``depth`` are null when naming them would
    imply a choice that does not exist: a one-section case never says
    *section 1*, a one-column case never says *column 1*, and the front row
    is never called a row (§3.6, UI_PLAN §1.1, §5.7).
    """

    place: str = Field(
        description="The ROOM. Empty when the bookcase stands on no room — "
                    "legal, and not the same as unknown (§3.7).",
    )
    bookcase: str = Field(
        description="The furniture's name. May be empty: naming a case is "
                    "optional, exactly as naming a shelf is.",
    )
    section: int | None = None
    column: int | None = None
    level: int = Field(description="1-based, counted from the TOP.")
    depth: int | None = Field(
        default=None,
        description="Row front-to-back, and only when it is not the front "
                    "one. Asked for by query, because the shelf has a depth "
                    "COUNT and a copy has a depth.",
    )

    @classmethod
    def of(cls, parts: AddressParts) -> "AddressPartsDTO":
        return cls(place=parts.place, bookcase=parts.bookcase,
                   section=parts.section, column=parts.column,
                   level=parts.level, depth=parts.depth)


class ShelfWhereDTO(BaseModel):
    """Where one shelf stands — VISION §7's *"given a book, answer where is
    it"*, which is the sentence P6.5 exists to make answerable.

    ⚠ ``site`` is beside the address and never inside it. §3.7 settles that a
    Site and a Floor are groupings and *"never part of an address"*, because
    putting either in would re-address every shelf in the house the day
    somebody renames a building. But two sites may each have a *living room*,
    so the site is carried as CONTEXT — and only when there is more than one
    of them, which is §3.9's rule for the map's own site segment, applied
    where the same ambiguity turns up.
    """

    shelf_id: str = Field(
        description="RESOLVED through the alias (§3.11), so a bookmarked or "
                    "queued id from before a merge answers with the shelf "
                    "that stands there now rather than 404.",
    )
    label: str = ""
    depth_count: int = Field(
        description="Rows front-to-back the owner declared. 1 for almost "
                    "every shelf; what makes *row 2 of 3* sayable.",
    )
    site: str | None = Field(
        default=None,
        description="Null when this library has one site — naming it would "
                    "be chrome for a household that has never met the "
                    "concept.",
    )
    address: AddressPartsDTO | None = Field(
        default=None,
        description="Null for a shelf that stands nowhere, which is MOST of "
                    "them and stays legal forever: the drawn and the "
                    "photographed are one population (§3.1). A screen must "
                    "read this as *not on the map yet*, never as an error.",
    )


class MergePreviewDTO(BaseModel):
    """What the merge would move. §3.15's other half of the same courtesy.

    Answers **200 for a refusal too**, carrying it in ``refused`` — a preview
    that 409s cannot show the owner why, which is the only thing it is for.
    """

    absorbed_id: str
    survivor_id: str
    refused: MergeRefusalDTO | None = None
    already: bool = Field(
        default=False,
        description="The two identities already answer as one. A no-op, so a "
                    "retry after a dropped response cannot half-merge.",
    )
    depth: int = Field(
        default=1,
        description="The survivor's depth AFTER (§3.12's ladder). Never "
                    "smaller than it is now; depth NUMBERS are never remapped.",
    )
    books: int = Field(default=0, description="Distinct books that move.")
    copies: list[DepthCountDTO] = Field(default_factory=list)
    photos: list[DepthCountDTO] = Field(default_factory=list)
    clashes: list[DecisionClashDTO] = Field(default_factory=list)
    answers_moved: int = Field(
        default=0,
        description="Standing §5.6 answers that move with the wood — the "
                    "load-bearing table (§3.13). Left behind, the next read "
                    "re-adds every phantom the owner ever rejected there.",
    )
    identities_moved: int = Field(
        default=0,
        description="Identities that already answered to the absorbed shelf "
                    "and are re-pointed at the survivor, to keep the resolver "
                    "one hop.",
    )

    @classmethod
    def of(cls, absorbed_id: str, survivor_id: str,
           plan: MergePlan) -> "MergePreviewDTO":
        return cls(
            absorbed_id=absorbed_id, survivor_id=survivor_id,
            depth=plan.depth, books=plan.books,
            copies=[DepthCountDTO(depth=d, count=n)
                    for d, n in plan.copies_per_depth.items()],
            photos=[DepthCountDTO(depth=d, count=n)
                    for d, n in plan.photos_per_depth.items()],
            clashes=[DecisionClashDTO(depth=c.depth, book_key=c.book_key,
                                      winner=c.winner,
                                      absorbed_kind=c.absorbed_kind,
                                      survivor_kind=c.survivor_kind)
                     for c in plan.clashes],
            answers_moved=len(plan.decisions),
            identities_moved=len(plan.was_aliases),
        )


class MergeResultDTO(BaseModel):
    """The survivor as it now stands, and what the merge actually moved."""

    survivor: ShelfDTO
    moved: MergePreviewDTO


class UndoOfferDTO(BaseModel):
    """Whether the last destructive map edit can be taken back (P6.4b, §3.15).

    ⚠ ``reason`` is a machine-readable token and not a sentence, on purpose:
    the client is Hebrew-first, so the words belong in
    ``app/web/src/map/text.ts``, where they have a Hebrew form and a plural
    that agrees. A server that shipped the sentence would ship it in one
    language.
    """

    available: bool = Field(
        description="Whether a press of undo would succeed right now. False "
                    "for all three of: nothing recorded, already taken back, "
                    "and the world moved — `reason` says which.",
    )
    kind: str = Field(
        default="",
        description="Which edit is at the head — `remove_column`, `gaps`, "
                    "`clear_bookcase`, `delete_site` and so on. Empty when "
                    "nothing was ever recorded.",
    )
    recorded_at: str = Field(default="", description="When that edit happened.")
    restores: dict[str, int] = Field(
        default={},
        description="What the undo would put back, counted per kind of row "
                    "(plus `removed`, for shelves the edit created that the "
                    "undo would take away again). Empty unless available.",
    )
    restored: dict[str, int] = Field(
        default={},
        description="What THIS call actually put back. `POST` only — and it "
                    "exists because `restores` cannot serve: that one answers "
                    "*what WOULD an undo do*, so after a successful undo it "
                    "is correctly empty. A client announcing from it said "
                    "*0 books came back* with 22 measured on the shelf.",
    )
    reason: str = Field(
        default="",
        description="`nothing_recorded`, `already_undone` or `world_moved`. "
                    "Empty exactly when `available` is true.",
    )
    changed: list[str] = Field(
        default=[],
        description="For `world_moved`: which targets moved, as `table:id`. "
                    "§3.15 requires the refusal to say WHY, and this is it.",
    )

    @classmethod
    def of(cls, offer) -> "UndoOfferDTO":
        return cls(
            available=offer.available,
            kind=offer.kind,
            recorded_at=offer.recorded_at,
            restores=dict(offer.restores or {}),
            reason=offer.reason,
            changed=list(offer.changed),
        )


class SectionEditDTO(BaseModel):
    """A section after an edit, with what it cost the shelves."""

    section: SectionDTO
    created: int = Field(
        default=0, description="New empty shelves, one per new slot.")
    removal: SlotRemovalDTO = SlotRemovalDTO()


class DepthApplyDTO(BaseModel):
    """The explicit application of a section's depth default.

    ``kept`` names the shelves that could NOT be shallowed because books
    stand behind — reported rather than silently skipped, so the screen says
    what it did instead of claiming it did everything.
    """

    kept: list[str] = []
