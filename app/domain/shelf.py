# -*- coding: utf-8 -*-
"""Shelf and Capture — physical identity, without the map (P2.1).

Plan §1.1 splits one word in two, and pillar 2 collapses if the split is left
implicit:

  | | what it is | when |
  |---|---|---|
  | **shelf identity** | id, a free-text label the owner types, ``depth_count`` | here |
  | **shelf address**  | place → bookcase → col → level, geometry, the highlight | pillar 6 |

So there is deliberately **no place, no bookcase, no col, no level** in this
module. A capture has to record *which shelf it is a photo of* or a re-read has
nothing to diff against (§5.6) — that needs an id and a label, not a drawing.
Until the map exists, a shelf's label *is* its location, and §1.1 calls that
"honest and enough". ``tests/test_domain.py`` asserts the absence structurally,
because the tempting mistake is to add ``bookcase`` here "while we're at it"
and then have two places that own an address.

**Depth stays with identity.** §5.7 is explicit that depth cannot be detected —
nothing in a photo says "this is the row behind", the front books are simply
absent — so it must be *declared*, which makes it a property of the shelf and
not of its position in a drawing.

⚠️ **Never say "row" or "band" for this.** ``segment.py`` already uses *band*
for the horizontal shelf rows found *within one photo*, and ``Spine.band`` is
in the stored record format — that is a vertical concept, this one is
front-to-back. §5.7 flags the collision by name, and a test enforces the word
choice in this module, because the confusion is invisible until someone reads
``spine_id = IMG_1234_b0_s07`` and reasonably guesses wrong.

No I/O, no framework, no store — same rule as the rest of ``app/domain``.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from app.domain.book import DomainError


class UnknownDepth(DomainError):
    """A capture or a copy claims a depth the shelf has not declared.

    §5.7: depth is declared, never detected. Accepting a capture at depth 3 of
    a shelf the owner said is one row deep would invent a location that has no
    counterpart in the room — and P2.3 would then reconcile against it.
    """


class VirtualShelfHasNoDepth(DomainError):
    """The wishlist is not a piece of furniture.

    A virtual shelf (§6, the wishlist) is a list of books the owner does not
    own yet. "The row behind" is a physical fact about wood, so it cannot
    apply, and allowing it would put books at a location that does not exist.
    """


# --- entities -------------------------------------------------------------

@dataclass(frozen=True)
class Shelf:
    """The durable thing users think about — *"living room, case 2, third
    shelf"* (§5.3). Free text, typed by the owner; the map gives it structure
    later without changing what it is.

    ``virtual`` marks the wishlist: a real list of books, kept alongside the
    shelves because that is where the user looks for it, but not a physical
    place. It is excluded from shelf counts — see :func:`counts_toward_library`.
    """

    id: str
    library_id: str
    label: str
    depth_count: int = 1
    virtual: bool = False
    created_at: str | None = None

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise DomainError("a shelf must have a label")
        if not self.library_id:
            raise DomainError("a shelf must belong to a library (H2)")
        if self.depth_count < 1:
            raise DomainError("a shelf is at least one row deep")
        if self.virtual and self.depth_count != 1:
            raise VirtualShelfHasNoDepth(
                f"shelf {self.id} is virtual; depth is physical (§5.7)"
            )

    @property
    def depths(self) -> tuple[int, ...]:
        """``(1, 2, ...)`` — 1-based, because the owner declaring "two rows
        deep" means rows one and two, and an off-by-one here would silently
        mis-scope §5.6's not-seen rule."""
        return tuple(range(1, self.depth_count + 1))

    @property
    def is_stacked(self) -> bool:
        """Whether the shelf holds more than one row front-to-back.

        The UI surfaces *"add a row behind this one"* even when this is False —
        §5.7 says most users will not know the feature exists, so hiding it
        behind "this shelf is already stacked" would mean nobody ever stacks
        one.
        """
        return self.depth_count > 1

    def check_depth(self, depth: int) -> int:
        """Return ``depth`` if this shelf has it; raise otherwise."""
        if depth not in self.depths:
            raise UnknownDepth(
                f"shelf {self.id} is {self.depth_count} row(s) deep; "
                f"depth {depth} has not been declared (§5.7)"
            )
        return depth


@dataclass(frozen=True)
class Capture:
    """One photo of part of a shelf (§5.3).

    Keyed by ``(shelf, depth, order)``, all three:

      - **shelf**, or a re-read has nothing to diff against (§5.6);
      - **depth**, because two captures of one shelf at different depths are
        not two views of one scene — the scene physically changed between them,
        which is why §5.7 #2 forbids overlap-dedup across depths;
      - **order**, left-to-right or right-to-left per the shelf's reading
        direction, so a shelf's book list has a sensible order (§5.3).

    ``image_id`` is a reference, never bytes: blobs live on disk behind the
    ``BlobStore`` port (D1, P3.5). It is optional here only because P2.2 owns
    the upload path.
    """

    id: str
    shelf_id: str
    library_id: str
    depth: int = 1
    order: int = 0
    image_id: str | None = None
    captured_at: str | None = None

    def __post_init__(self) -> None:
        if not self.shelf_id:
            raise DomainError("a capture must name the shelf it is a photo of")
        if not self.library_id:
            raise DomainError("a capture must belong to a library (H2)")
        if self.depth < 1:
            raise DomainError("depth is 1-based")
        if self.order < 0:
            raise DomainError("capture order is 0-based and never negative")

    @property
    def slot(self) -> tuple[str, int, int]:
        """``(shelf_id, depth, order)`` — the identity §5.3 gives a capture."""
        return (self.shelf_id, self.depth, self.order)


# --- operations -----------------------------------------------------------

def new_shelf(
    *,
    id: str,
    library_id: str,
    label: str,
    depth_count: int = 1,
    virtual: bool = False,
    created_at: str | None = None,
) -> Shelf:
    """A shelf the owner declared. Default one row deep — the common case, and
    §5.7 says the second row must be an explicit action rather than a number
    the user is asked for up front."""
    return Shelf(
        id=id,
        library_id=library_id,
        label=label,
        depth_count=depth_count,
        virtual=virtual,
        created_at=created_at,
    )


def rename_shelf(shelf: Shelf, label: str) -> Shelf:
    """Fix the label. Until pillar 6 this is the whole of a book's location, so
    it is edited far more often than a structured address would be."""
    return replace(shelf, label=label)


def add_depth(shelf: Shelf) -> Shelf:
    """*"Add a row behind this one"* (§5.7) — the declaration that cannot be
    detected.

    Returns a shelf one row deeper; the new depth is ``result.depth_count``.
    Refused on a virtual shelf, which has no behind.
    """
    if shelf.virtual:
        raise VirtualShelfHasNoDepth(
            f"shelf {shelf.id} is the wishlist, not furniture (§5.7)"
        )
    return replace(shelf, depth_count=shelf.depth_count + 1)


def new_capture(
    shelf: Shelf,
    *,
    id: str,
    depth: int = 1,
    order: int = 0,
    image_id: str | None = None,
    captured_at: str | None = None,
) -> Capture:
    """A photo, bound to a shelf and a declared depth.

    Takes the whole :class:`Shelf` rather than a ``shelf_id`` precisely so the
    depth can be checked against what the owner declared — a capture is the one
    place an undeclared depth can enter the system.
    """
    return Capture(
        id=id,
        shelf_id=shelf.id,
        library_id=shelf.library_id,
        depth=shelf.check_depth(depth),
        order=order,
        image_id=image_id,
        captured_at=captured_at,
    )


def counts_toward_library(shelf: Shelf) -> bool:
    """Whether a shelf is part of "how many shelves do I have".

    The wishlist is not. It holds books the owner does not own, so counting it
    inflates both the shelf count and — once P2.5 shows books-per-shelf — the
    size of the library itself. Stores default to excluding virtual shelves for
    this reason; ``include_virtual=True`` is the caller opting in.
    """
    return not shelf.virtual
