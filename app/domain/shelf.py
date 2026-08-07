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
nothing to diff against (§5.6) — and that needs an **id**, not a drawing and
not even a name. ``tests/test_domain.py`` asserts the absence structurally,
because the tempting mistake is to add ``bookcase`` here "while we're at it"
and then have two places that own an address.

**Identity here is free** (owner's call, 2026-08-07): a shelf must exist and be
re-findable, and that is all. An unnamed shelf is shown by the image it came
from — the owner recognises a photo of their own bookshelf without a caption.
Naming it, and any other location information, is optional and stays optional;
the real binding waits for pillar 6.

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
    counterpart in the room — and P2.5's reconciliation would then compare
    against it.
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
    """The durable thing a re-read diffs against (§5.3).

    **The label is OPTIONAL** (owner's call, 2026-08-07). A shelf's identity is
    free: it needs to exist and be re-findable, not to be described. Until the
    map arrives a shelf that was never named is shown by the image it came
    from, which the owner already recognises — a photo of a bookshelf is a
    picture of that bookshelf. So *"living room, case 2, third shelf"* is
    something you may type, not a toll you pay before the first photo can be
    filed. Optional location information stays optional; the real binding
    waits for pillar 6.

    That is a real reversal of the earlier reading, where the label WAS the
    interim location and therefore mandatory. It matters because a required
    label makes capture a two-step action forever, to buy an interim answer to
    "where is it?" that pillar 6 replaces anyway.

    ``virtual`` marks the wishlist: a real list of books, kept alongside the
    shelves because that is where the user looks for it, but not a physical
    place. It is excluded from shelf counts — see :func:`counts_toward_library`.
    """

    id: str
    library_id: str
    label: str = ""
    depth_count: int = 1
    virtual: bool = False
    created_at: str | None = None

    def __post_init__(self) -> None:
        if not self.library_id:
            raise DomainError("a shelf must belong to a library (H2)")
        if self.depth_count < 1:
            raise DomainError("a shelf is at least one row deep")
        if self.virtual and self.depth_count != 1:
            raise VirtualShelfHasNoDepth(
                f"shelf {self.id} is virtual; depth is physical (§5.7)"
            )

    @property
    def is_named(self) -> bool:
        """Whether the owner has described this shelf.

        The UI needs the distinction because an unnamed shelf is shown by its
        capture instead — and because "name this shelf" is a prompt worth
        offering once, not a field worth blocking on.
        """
        return bool(self.label.strip())

    @property
    def sort_key(self) -> tuple[str, str, str]:
        """Named shelves alphabetically, then unnamed ones oldest-first.

        Ordering unnamed shelves by ``created_at`` rather than letting them
        clump under one blank label matters more than it looks: early on most
        shelves are unnamed, so "sorted by label" would otherwise mean a block
        of visually identical rows in id order — which is arbitrary to the
        person reading it. Creation order at least matches the sequence they
        photographed them in. ``id`` last, so the order is total.
        """
        return (self.label.strip(), self.created_at or "", self.id)

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
    label: str = "",
    depth_count: int = 1,
    virtual: bool = False,
    created_at: str | None = None,
) -> Shelf:
    """A shelf. The label is optional — see :class:`Shelf`.

    Default one row deep, and §5.7 says the second row must be an explicit
    action rather than a number the user is asked for up front. Same shape of
    decision as the label: nothing is demanded before the first photo.
    """
    return Shelf(
        id=id,
        library_id=library_id,
        label=label,
        depth_count=depth_count,
        virtual=virtual,
        created_at=created_at,
    )


def rename_shelf(shelf: Shelf, label: str) -> Shelf:
    """Name a shelf, or fix the name. Also the path back to unnamed — passing
    ``""`` is legal, because a label the owner no longer wants is not worth
    keeping just to avoid an empty string."""
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


def capture_onto_a_new_shelf(
    *,
    shelf_id: str,
    library_id: str,
    capture_id: str,
    image_id: str | None = None,
    captured_at: str | None = None,
) -> tuple[Shelf, Capture]:
    """A photo that names no shelf still gets one (P2.2).

    This is the binding rule, and it is here rather than in a router because
    it is a decision, not plumbing: **every capture has a shelf identity, from
    the moment it exists.** A photo with no shelf would be a read with nothing
    to reconcile against (§5.6), so "assign it later" is not a state the data
    model offers — the shelf is created unnamed, and *"Unassigned"* in the UI
    means *not yet named*, not *not yet filed*.

    Which is why the shelf comes out unnamed and one row deep: the owner's
    call is that identity is FREE (see :class:`Shelf`). Nothing is asked before
    the first photo can be filed, and both the name and the row behind it are
    added later if they are ever wanted.

    ⚠ One image = one shelf is a **placeholder**, not the target. Without the
    map there is nothing to bind several photos of one physical shelf together;
    pillar 6 provides the exit by merging shelf identities (plan P6.1b). That
    is why nothing may treat a shelf id as a permanent handle on a piece of
    furniture.
    """
    shelf = new_shelf(id=shelf_id, library_id=library_id,
                      created_at=captured_at)
    capture = new_capture(shelf, id=capture_id, image_id=image_id,
                          captured_at=captured_at)
    return shelf, capture


def counts_toward_library(shelf: Shelf) -> bool:
    """Whether a shelf is part of "how many shelves do I have".

    The wishlist is not. It holds books the owner does not own, so counting it
    inflates both the shelf count and — once P2.5 shows books-per-shelf — the
    size of the library itself. Stores default to excluding virtual shelves for
    this reason; ``include_virtual=True`` is the caller opting in.
    """
    return not shelf.virtual
