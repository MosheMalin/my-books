# -*- coding: utf-8 -*-
"""The physical map — Site, Floor, Place, Bookcase, Section (pillar 6, P6.1).

``shelf.py`` split one word in two and left the second half to this module:

  | | what it is | where |
  |---|---|---|
  | **shelf identity** | id, a free-text label, ``depth_count`` | ``shelf.py`` |
  | **shelf address**  | place → bookcase → section → column → level | here |

The address is what a drawing produces, and ``planning/MAP_PLAN.md`` is the
decomposition every rule below cites. Nine passes of a standalone lab settled
the shape; this module is that shape in Python, with the clamps the lab could
not have (it had no books).

**The five levels, and the two that are only groupings**::

    Site    "home", "the parents' place"      grouping
      Floor "ground floor", "upstairs"        grouping
        Place        the ROOM                 <- the address starts here
          Bookcase   one piece of furniture
            Section  one built unit, bottom-first
              column x level                  <- one Shelf

⚠ **A Site and a Floor are never part of an address** (MAP_PLAN §3.7, §3.9).
They exist because two storeys both start at 0,0 on a plan, so drawing them on
one canvas puts the bedroom on top of the kitchen. Putting either into the
address would re-address every shelf in the house the day somebody renames a
building.

⚠ **`Place` is the ROOM.** VISION's older gloss said *"a room, or a whole
site"* — one noun over two levels — and it was amended on 2026-08-16 when the
owner asked for a real Site. The editor's word for a ``Place`` is *room*; that
is the only alias, and it is written down here so it stays one.

⚠ **Never say "row" or "band" for depth**, here or anywhere: ``segment.py``
uses *band* for the horizontal shelf rows found within one photo, which is a
vertical concept where this one is front-to-back. A test enforces the word
choice in this module, as it already does in ``shelf.py``.

No I/O, no framework, no geometry engine — same rule as the rest of
``app/domain``. In particular this module does **no** hit-testing and **no**
snapping: those need pixels and a pointer and are the client's, and §3.4
forbids the server deriving anything (least of all a capacity) from a length.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Mapping

from app.domain.book import DomainError
from app.domain.shelf import Shelf, ShelfAddress, bind_shelf

# --- constants ------------------------------------------------------------

#: What a fresh column gets. Five, because most bookcases are.
DEFAULT_LEVELS = 5
#: One row front-to-back — the same default ``new_shelf`` already uses, and
#: for the same reason (§5.7: the second row is an explicit declaration, never
#: a number the owner is asked for up front).
DEFAULT_DEPTH = 1
#: Two, because most bookcases are (owner, 2026-08-16). One was a modelling
#: minimum masquerading as a default.
DEFAULT_COLUMNS = 2
#: The most slots one bookcase may hold, across every section.
#:
#: ⚠ A resource limit, not a modelling opinion, and it exists because a
#: security review measured what its absence costs: a 110-byte request asking
#: for 40 columns of 40 wrote 1600 shelf rows in 16.5 seconds, and a 40-BYTE
#: *add a section* request — which states no size at all, because it copies
#: its neighbour — added 1600 more. Thirty of those took 47 seconds and 3000
#: rows.
#:
#: 400 is far above any real bookcase (a large one is 6 columns of 8) and far
#: below the number that hurts. A refusal names the number, so the owner of a
#: genuinely enormous case knows what to argue with.
MAX_SLOTS_PER_BOOKCASE = 400
#: Sections stack bottom to top; more than a handful is not furniture.
MAX_SECTIONS_PER_BOOKCASE = 8
#: The ceiling on a section's DEFAULT depth only. An existing shelf is not
#: clamped by it: ``Shelf.depth_count`` has never had a maximum, and inventing
#: one here would refuse data the owner already declared.
MAX_DEPTH = 4

#: Which edge of a rectangle. ``N`` is the smaller y — the plan is pinned LTR
#: and drawn top-down (§3.5), so these name directions on the DRAWING, not
#: compass bearings in the world.
SIDES = ("N", "E", "S", "W")


# --- errors ---------------------------------------------------------------


class NotEmpty(DomainError):
    """A grouping still holds something, so removing it is refused.

    MAP_PLAN §3.7: *"removing a storey with anything on it is refused, and
    says what is in the way. Nothing here auto-removes"* — the same instinct
    as §5.6's rule that a not-seen book stays. The message names the counts,
    because "cannot delete" without a reason is what makes the next reader
    delete the guard.
    """


class TooManySlots(DomainError):
    """A bookcase would hold more shelves than :data:`MAX_SLOTS_PER_BOOKCASE`.

    A resource limit with a real reason (see the constant): every slot is a
    row, and a request that states no size — *add a section*, which copies its
    neighbour — can otherwise multiply a large case indefinitely. The message
    names the count and the ceiling, because a refusal the owner cannot
    interpret is one they retry.
    """


class SlotsOccupied(DomainError):
    """Cells were asked to become gaps while something still stands on them.

    **Refusing is the owner's decision** (2026-08-22): a column shrink
    DETACHES an occupied shelf (:func:`plan_slot_removal`), which costs a book
    its location, while a gap refuses and says so. *"The TV goes where the
    books are not"* is a sentence the owner can act on.

    ⚠ The first draft of this docstring claimed the gesture was therefore
    **loss-proof** — *"there was nothing there to lose"* — and a review
    measured that to be false: an empty shelf can still carry a label, a depth
    override and an id that standing decisions name. What the refusal actually
    covers, and what it deliberately does not, is written once, in
    :func:`app.map_edit.apply_gaps`, beside the code that enforces it.

    ``shelves`` are the ones in the way. Today only their COUNT reaches the
    owner — the route renders ``str(exc)`` — so this is the affordance
    P6.3.2b needs to mark the offending cells in the elevation, and it is
    carried rather than recomputed because by then the world may have moved.
    A count with a remedy already beats "cannot" (CLAUDE.md, working style: a
    wrong stated reason is worse than none, and no reason is what gets a
    guard deleted).
    """

    def __init__(self, message: str, shelves: tuple[Shelf, ...] = ()) -> None:
        super().__init__(message)
        self.shelves = shelves


class SlotTaken(DomainError):
    """A shelf was offered a slot another shelf already stands in (P6.4c).

    **The refusal that offers a next step.** MAP_PLAN §3.11 splits binding in
    two: the safe half is an unaddressed shelf gaining an address, and the
    dangerous half is two identities becoming ONE — which moves a population
    of copies and merges two capture strips. §3.14 is why they are never one
    button: *"a wrong binding looks like success, because the map gets
    fuller."* So a taken slot is not something bind quietly resolves; it is
    where bind stops and says who is there.

    ``occupant`` is carried rather than looked up again by whoever renders the
    refusal, for the reason :class:`SlotsOccupied` gives one line up: by then
    the world may have moved, and a second read can answer differently from
    the one the decision was made on.

    ⚠ It is NOT the same event as :class:`DuplicateShelfSlot`, which is the
    store's unique index catching two binds that raced. This one is the check;
    that one is the backstop, and the caller translates it into this so the
    owner reads one sentence either way.
    """

    def __init__(self, message: str, occupant: Shelf) -> None:
        super().__init__(message)
        self.occupant = occupant


class CellIsGap(DomainError):
    """The cell is switched off, so it is not a slot (§3.10a).

    Refused rather than un-gapped on the way past. Switching a cell back on is
    a decision about the FURNITURE — *"the television is gone"* — and the
    owner has one control for it that says so. A bind that silently restored
    the cell would make *put this shelf here* mean two things, one of which
    the owner never asked for.
    """


class AlreadyOnTheMap(DomainError):
    """The shelf being bound already stands somewhere (P6.4c).

    So this would be a MOVE, and a move is refused here on purpose. Two
    reasons, and the second is the load-bearing one:

    - the plan's sentence for this item is *"an unaddressed shelf gains an
      address, and loses one"*. A move is those two gestures, and each is
      worth its own ✓ (§3.14);
    - **it would make bind destructive.** Binding into a free slot loses
      nothing, which is why it records no undo — the same argument
      ``set_gaps`` makes for un-gapping a cell. A move vacates the old slot,
      and that address is a thing somebody could want back, so it would need
      a journal entry. Refusing keeps one gesture purely additive instead of
      making it conditionally destructive, which is the kind of rule nobody
      remembers at the call site.
    """


class NotOnThisFloor(DomainError):
    """A room and the bookcase attaching to it are on different storeys.

    §3.7: *a room is found only on its own storey.* Without it a bookcase
    drawn upstairs attaches to the kitchen underneath it — and then moves
    with it.
    """


# --- geometry -------------------------------------------------------------


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle in **abstract units**, always whole ones.

    §3.4, twice over:

      - *free measurements, not real centimetres.* A unit is relative to the
        other units in the same plan and to nothing else. Nothing in this
        codebase may turn one into a capacity, a centimetre or a book count;
      - **integers**, enforced rather than hoped for. The lab shipped a room
        that rendered as ``11.000000000000004x9`` because snapping moves a
        rectangle by ADDING a correction, and ``x + (round(x) - x)`` is not
        ``round(x)`` in floating point — the dust then seeded the magnet for
        the next rectangle, which inherited it. The client sweeps it at both
        constructors; this refuses it at the door, because a canvas resize, a
        phone rotation or a zoom must never be able to corrupt a stored plan.
    """

    x: int
    y: int
    w: int
    h: int

    def __post_init__(self) -> None:
        for name in ("x", "y", "w", "h"):
            value = getattr(self, name)
            # bool is an int in Python, and `Rect(x=True, …)` is a wiring bug
            # that would otherwise be stored as 1, silently.
            if not isinstance(value, int) or isinstance(value, bool):
                raise DomainError(
                    f"plan geometry is whole abstract units; {name}={value!r} "
                    f"is not an int (MAP_PLAN §3.4)"
                )
        if self.w <= 0 or self.h <= 0:
            raise DomainError(
                f"a rectangle needs a positive size, got {self.w}x{self.h}"
            )


# --- the two groupings ----------------------------------------------------


@dataclass(frozen=True)
class Site:
    """A whole property: home, the office, the parents' place.

    Added 2026-08-16 at the owner's call, overruling the plan's own
    recommendation of a flat list — *"the parents' place, upstairs"* needs two
    groupings rather than one longer label.

    ``order`` is the owner's ordering, not a creation timestamp: a site is a
    thing you list, and the list you want is rarely the order you happened to
    add them in.
    """

    id: str
    library_id: str
    name: str
    order: int = 0

    def __post_init__(self) -> None:
        _needs_library(self, "a site")
        # MANDATORY, unlike a shelf label — the same call as "library name
        # mandatory, shelf label optional": a site exists only because there
        # are two of them, and an unnamed one in a picker is unusable.
        if not self.name.strip():
            raise DomainError("a site is named (it exists to be told apart)")


@dataclass(frozen=True)
class Floor:
    """A storey **of one site**.

    Each site has its own: the ground floor of the parents' place is not the
    ground floor of this one, which is exactly why floors could not stay a
    flat list once sites arrived.
    """

    id: str
    library_id: str
    site_id: str
    name: str
    order: int = 0

    def __post_init__(self) -> None:
        _needs_library(self, "a floor")
        if not self.site_id:
            raise DomainError("a floor belongs to a site (MAP_PLAN §3.9)")
        if not self.name.strip():
            raise DomainError("a floor is named")


# --- the address levels ---------------------------------------------------


@dataclass(frozen=True)
class Place:
    """A room, drawn as a rectangle on its floor's plan.

    The first level of a shelf's address, and the only one of the three
    location nouns that enters it.

    The name is **optional**, deliberately, and for the reason a shelf label
    is: a plan that demands eight names before it shows you anything is a
    toll. An unnamed room is recognisable by its shape and its neighbours,
    which is what a drawing is for.
    """

    id: str
    library_id: str
    floor_id: str
    rect: Rect
    name: str = ""
    #: Drawing order, and therefore **z-order**: the last one drawn is on top,
    #: which is the rule the lab's hit test already used (`roomAt` walks the
    #: array backwards, so the newest room wins an overlap). The lab got it
    #: from array position; a table has no array, so the client assigns it.
    #: Ties break by id, which is arbitrary but total — never by insertion,
    #: which a store is not obliged to preserve.
    order: int = 0

    def __post_init__(self) -> None:
        _needs_library(self, "a place")
        if not self.floor_id:
            raise DomainError("a place stands on a floor (MAP_PLAN §3.9)")


@dataclass(frozen=True)
class Bookcase:
    """One piece of furniture: one footprint, one name, one room it moves with.

    ``place_id`` may be ``None`` — a case can stand on the plan attached to no
    room, which is what makes drawing one *before* its room possible.

    ⚠ ``floor_id`` is carried **here as well as on the room**, on purpose
    (§3.7): an unattached case has to be *somewhere* rather than everywhere. It
    takes its room's floor whenever it attaches to one, and
    :func:`attach_bookcase` is the only thing that may change either.

    ``front`` is the face the books look out of — and therefore the face whose
    left end is column 1 (§7.3, closed 2026-08-16). It is a fact about the
    furniture, so the UI's reading direction never moves it.

    **Sections are not held here.** They are rows of their own: a bookcase
    with three sections and forty shelves would otherwise be an aggregate that
    has to be written whole to rename it.
    """

    id: str
    library_id: str
    floor_id: str
    rect: Rect
    name: str = ""
    front: str = "S"
    place_id: str | None = None
    #: Drawing order / z-order — see :class:`Place.order`. Furniture wins a
    #: tap over a room in every tool (§3.8), so a case's order competes only
    #: with other cases.
    order: int = 0

    def __post_init__(self) -> None:
        _needs_library(self, "a bookcase")
        if not self.floor_id:
            raise DomainError(
                "a bookcase carries its own floor, so an unattached one is "
                "somewhere rather than everywhere (MAP_PLAN §3.7)"
            )
        if self.front not in SIDES:
            raise DomainError(f"front is one of {SIDES}, not {self.front!r}")


@dataclass(frozen=True)
class Section:
    """One built unit of a bookcase — a low base, or the case standing on it.

    ⚠ **Called a SECTION deliberately** (§3.6). Not a *unit*: the plan's
    measurements are already units. Not a *tier*: too close to ``level``, the
    shelf row inside a column. This project has been bitten by exactly this
    before, which is why the name is part of the design and not a preference.

    ``ordinal`` is **1-based and bottom-first**: section 1 stands on the floor.
    A plain bookcase has exactly one, and then the address never mentions it —
    see :func:`address_parts`. It is UNIQUE per bookcase, declared as an index:
    two sections both at 1 would make the address print "section 1" for two
    different shelves.

    ⚠ **The id is durable now, and it was not in the lab.** ``persist.ts``
    rebuilds section ids from array position on every import, on the stated
    grounds that *"nothing outside the document refers to one"*. That sentence
    stopped being true the moment ``shelves.section_id`` existed: an importer
    that renumbers by position orphans every addressed shelf in the library,
    and inserting a section at the BOTTOM renumbers all of them. P6.3 must
    carry ids across, not regenerate them.

    ``column_levels`` holds one entry per column, being that column's level
    count. The **column count is that tuple's length**; there is no second
    field that could disagree with it.

    ``gaps`` holds the cells that are switched OFF — a television standing in
    the middle of the wall unit, a desk niche, the notch an L leaves. It is
    the cheap half of the free-form elevation §3.6 deliberately deferred, and
    it is a MASK over the extent rather than a change to it: the wood is still
    that tall, so the shelves BELOW a gap keep the level numbers printed on
    the addresses of books somebody has already been told to go and find.
    That is the whole reason it is not "shrink the column" — the owner's
    words, 2026-08-22: *"the lower shelves should not get up now"*.

    Consequences, each pinned by a test:

      - a gapped cell is **not** a slot, so ``addresses`` skips it and no
        ``Shelf`` stands there. §3.1 says a drawn slot IS a shelf; a shelf row
        marked *unavailable* would be a shelf that is not a shelf, and every
        query about "the books on this shelf" would have to learn about it;
      - a gap outside the extent is **refused**, not ignored. The geometry
        functions prune first (see :func:`_pruned`), so shrinking a column
        past a gap takes the gap with it and growing back yields a real shelf
        rather than a resurrected hole;
      - a section that is **entirely** gaps is legal. That is what makes
        *"deleting cells never deletes the bookcase"* structural: the extent,
        which is what the case IS, is untouched by any number of gaps.

    ``default_levels`` and ``default_depth`` are **creation-time defaults**
    (§3.3), copied into a shelf when the shelf is created and never read
    through to afterwards. That is the whole rule, and the reason it is one:
    if the case's depth were read live, editing it from 2 to 1 would silently
    delete the location of every book standing in the back row.
    """

    id: str
    library_id: str
    bookcase_id: str
    ordinal: int = 1
    column_levels: tuple[int, ...] = ()
    #: ``(column, level)`` pairs, 1-based, that are switched off. Sorted and
    #: deduplicated in ``__post_init__``, so two sections describing the same
    #: face compare equal however the cells were named.
    gaps: tuple[tuple[int, int], ...] = ()
    default_levels: int = DEFAULT_LEVELS
    default_depth: int = DEFAULT_DEPTH

    def __post_init__(self) -> None:
        _needs_library(self, "a section")
        if not self.bookcase_id:
            raise DomainError("a section belongs to a bookcase")
        if self.ordinal < 1:
            raise DomainError("sections are numbered from 1, bottom first")
        if any(n < 1 for n in self.column_levels):
            raise DomainError("a column has at least one level")
        # Normalised at construction, with the idiom and for the reason
        # `app.domain.book._settle_location` states: freezing means operations
        # return new objects, so ordering the mask here is not a mutation any
        # caller can observe. Two sections describing the same face must
        # compare equal — `_change` diffs address SETS, but the editor sends
        # whatever order the owner tapped in, and a section that differs from
        # itself only by that order is a write nobody asked for.
        object.__setattr__(
            self, "gaps",
            tuple(sorted({(int(c), int(v)) for c, v in self.gaps})),
        )
        for col, level in self.gaps:
            if not 1 <= col <= len(self.column_levels) or not (
                1 <= level <= self.levels_in(col)
            ):
                raise DomainError(
                    f"a gap stands in the case, and column {col} level "
                    f"{level} is outside a section of "
                    f"{len(self.column_levels)} column(s) with levels "
                    f"{list(self.column_levels)}"
                )
        if self.default_levels < 1:
            raise DomainError("a column has at least one level")
        if not 1 <= self.default_depth <= MAX_DEPTH:
            raise DomainError(
                f"a section's default depth is 1..{MAX_DEPTH}, got "
                f"{self.default_depth}"
            )

    @property
    def column_count(self) -> int:
        """The number of columns — derived, never stored twice."""
        return len(self.column_levels)

    def levels_in(self, col: int) -> int:
        """How many levels column ``col`` (1-based) has; 0 if there is no such
        column."""
        if 1 <= col <= len(self.column_levels):
            return self.column_levels[col - 1]
        return 0

    @property
    def addresses(self) -> tuple[ShelfAddress, ...]:
        """Every slot this section describes, column-major and 1-based.

        **Gapped cells are not slots.** Everything destructive and everything
        creative already goes through this property — ``_change`` diffs it,
        ``check_bookcase_size`` counts it, ``map_edit._fill`` fills it — so
        switching a cell off here is what makes the rest of the pipeline
        correct without knowing the word.
        """
        gapped = set(self.gaps)
        return tuple(
            ShelfAddress(self.id, col, level)
            for col in range(1, self.column_count + 1)
            for level in range(1, self.levels_in(col) + 1)
            if (col, level) not in gapped
        )

    # ⚠ There is deliberately no `is_gap(col, level)` helper yet. The first
    # cut had one, described as "asked by the screen" — and the screen is
    # P6.3.2b, which does not exist, so its stated performance argument
    # reasoned about a caller nobody could read. `gaps` is a small sorted
    # tuple; the editor will want a set hoisted out of its render loop, not a
    # per-cell method, and it can add exactly what it needs.


# --- constructors ---------------------------------------------------------


def new_site(*, id: str, library_id: str, name: str, order: int = 0) -> Site:
    return Site(id=id, library_id=library_id, name=name, order=order)


def new_floor(
    *, id: str, library_id: str, site_id: str, name: str, order: int = 0
) -> Floor:
    return Floor(id=id, library_id=library_id, site_id=site_id, name=name,
                 order=order)


def new_place(
    *,
    id: str,
    library_id: str,
    floor_id: str,
    rect: Rect,
    name: str = "",
    order: int = 0,
) -> Place:
    return Place(id=id, library_id=library_id, floor_id=floor_id, rect=rect,
                 name=name, order=order)


def new_bookcase(
    *,
    id: str,
    library_id: str,
    floor_id: str,
    rect: Rect,
    name: str = "",
    front: str = "S",
    place_id: str | None = None,
    order: int = 0,
) -> Bookcase:
    return Bookcase(id=id, library_id=library_id, floor_id=floor_id, rect=rect,
                    name=name, front=front, place_id=place_id, order=order)


def new_section(
    *,
    id: str,
    library_id: str,
    bookcase_id: str,
    ordinal: int = 1,
    columns: int = DEFAULT_COLUMNS,
    default_levels: int = DEFAULT_LEVELS,
    default_depth: int = DEFAULT_DEPTH,
) -> Section:
    """A section with ``columns`` columns, each at the section's own default.

    The columns are built from ``default_levels`` HERE, at creation, so the
    tuple is a snapshot and not a live view of the default — which is §3.3
    one level up from the shelves.
    """
    return Section(
        id=id,
        library_id=library_id,
        bookcase_id=bookcase_id,
        ordinal=ordinal,
        column_levels=tuple([default_levels] * max(1, columns)),
        default_levels=default_levels,
        default_depth=default_depth,
    )


# --- attachment -----------------------------------------------------------


def attach_bookcase(bookcase: Bookcase, place: Place) -> Bookcase:
    """Point a case at a room, and move it onto that room's storey.

    §3.7: a bookcase takes its room's floor whenever it attaches to one. The
    two fields cannot be set independently — a case attached to the kitchen
    but recorded upstairs is a record no screen can render honestly.
    """
    if place.library_id != bookcase.library_id:
        raise DomainError(
            f"bookcase {bookcase.id} and place {place.id} are in different "
            f"libraries"
        )
    return replace(bookcase, place_id=place.id, floor_id=place.floor_id)


def detach_bookcase(bookcase: Bookcase) -> Bookcase:
    """Let go of the room, keeping the storey.

    Detaching is **explicit** and it is the ONLY way a case loses its room —
    see :func:`reattach_bookcase` for the half of that rule which cost the lab
    two bugs to find.
    """
    return replace(bookcase, place_id=None)


def reattach_bookcase(bookcase: Bookcase, place: Place | None) -> Bookcase:
    """Re-derive the room from geometry — **reassign only, never orphan**.

    ⚠ Both halves of this were found the hard way in the lab (MAP_PLAN §4,
    third pass), and MAP_PLAN promotes it to a domain rule rather than an
    editor behaviour, which is why it lives here:

      - a case dragged out of every room **keeps the room it had**. Without
        that, nudging a case half a unit past its own wall silently loses its
        room — and a bookcase belongs to a room the way furniture does, not
        the way a rectangle overlaps another rectangle;
      - a case that moved only *because its room did* must not be handed to
        whatever it now overlaps. The caller enforces that by simply not
        calling this — an explicit attachment survived exactly one move
        before that was understood.

    ``place`` is the room the CLIENT says now contains the case: containment
    is pixels and a pointer, and §3.4 keeps that out of here.
    """
    if place is None:
        return bookcase
    return attach_bookcase(bookcase, place)


# --- slots: what a drawing creates and destroys ---------------------------


@dataclass(frozen=True)
class SlotChange:
    """A section edit, split into the section and the shelves it implies.

    §3.1 is why this type exists at all: *a drawn slot IS a Shelf*. Adding a
    column does not merely change a number — ten real, empty, addressed
    ``Shelf`` rows come into being, and shrinking one takes them away again.
    Returning both halves together stops a caller updating the grid and
    forgetting the shelves.

    ``added`` are slots that now exist and need a ``Shelf``; ``dropped`` are
    slots that no longer do. A dropped slot never *deletes* by itself — see
    :func:`plan_slot_removal`, which is where "never auto-remove" is enforced.
    """

    section: Section
    added: tuple[ShelfAddress, ...] = ()
    dropped: tuple[ShelfAddress, ...] = ()


def _change(before: Section, after: Section) -> SlotChange:
    was = set(before.addresses)
    now = set(after.addresses)
    return SlotChange(
        section=after,
        added=tuple(a for a in after.addresses if a not in was),
        dropped=tuple(a for a in before.addresses if a not in now),
    )


def _pruned(gaps: Iterable[tuple[int, int]],
            column_levels: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
    """Drop the gaps a resized extent no longer contains.

    Called by every function that changes ``column_levels``, and it has to be:
    :meth:`Section.__post_init__` REFUSES a gap outside the case, so a shrink
    that carried its mask along unchanged would raise instead of resizing.

    The behaviour it chooses — and the alternative is real — is that the hole
    goes with the wood. Shrinking a column past a gap and growing it back
    yields a **shelf**, not a resurrected hole: a level count is what the
    owner is editing at that moment, and the case coming back taller with an
    invisible cell missing from the middle of it is the kind of surprise that
    gets explained as a bug.
    """
    return tuple(
        (col, level)
        for col, level in gaps
        if 1 <= col <= len(column_levels) and 1 <= level <= column_levels[col - 1]
    )


def with_column_count(section: Section, count: int) -> SlotChange:
    """Add or remove **trailing** columns.

    Trailing rather than "wherever", because a column is identified by its
    position across the face: inserting one in the middle would renumber every
    shelf to its right, and those numbers are printed on the addresses of
    books somebody has already been told to go and find.

    New columns get the section's CURRENT ``default_levels`` — the
    creation-time copy of §3.3, one level up.

    ⚠ An out-of-range count RAISES rather than clamping. Clamping put the
    lenient answer on the DESTRUCTIVE path: ``count=0`` from a confused client
    silently meant *shrink to one column*, dropping every other column's
    slots. It also disagreed with ``Section.__post_init__``, which raises for
    the same value — one invalid input, two answers, and the quiet one doing
    the damage.
    """
    n = _positive(count, "a section has at least one column")
    if n <= section.column_count:
        levels = section.column_levels[:n]
    else:
        levels = section.column_levels + tuple(
            [section.default_levels] * (n - section.column_count))
    after = replace(section, column_levels=levels,
                    gaps=_pruned(section.gaps, levels))
    return _change(section, after)


def with_column_levels(section: Section, col: int, levels: int) -> SlotChange:
    """Change ONE column's level count.

    Levels are numbered **1 at the top**, and a column therefore shrinks from
    the bottom — the lab's behaviour, kept deliberately so the ported editor
    behaves identically. Growing creates slots at the section's current
    default depth.
    """
    if not 1 <= col <= section.column_count:
        raise DomainError(
            f"section {section.id} has {section.column_count} column(s); "
            f"there is no column {col}"
        )
    n = _positive(levels, "a column has at least one level")
    levels_now = list(section.column_levels)
    levels_now[col - 1] = n
    settled = tuple(levels_now)
    return _change(section, replace(section, column_levels=settled,
                                    gaps=_pruned(section.gaps, settled)))


def with_gaps(
    section: Section, cells: Iterable[tuple[int, int]], *, gap: bool
) -> SlotChange:
    """Switch cells off (``gap=True``) or back on — a TV niche, and its undo.

    One function with a boolean rather than two, because they are one
    instruction with opposite signs and the pair would drift: the pruning, the
    range check and the address diff are identical, and only the set operation
    differs. The route carries the sign explicitly for the same reason
    ``patch_section`` refuses two grid instructions in one request.

    ⚠ **The extent is not touched, and that is the feature** (owner,
    2026-08-22). Switching off the cell at level 3 leaves levels 4 and 5 where
    they are, addressed as they were; shrinking the column to 2 is a different
    request with a different meaning, and both remain available.

    An out-of-range cell RAISES, for the reason :func:`with_column_count`
    gives about clamping on a destructive path: the lenient answer would
    silently gap *some other* cell, or none, and answer 200 either way.
    Restoring a cell that is not gapped, and gapping one already gapped, are
    both no-ops — the request and the world already agree.
    """
    asked = tuple((int(col), int(level)) for col, level in cells)
    if not asked:
        raise DomainError("no cells were named")
    for col, level in asked:
        if not 1 <= col <= section.column_count:
            raise DomainError(
                f"section {section.id} has {section.column_count} column(s); "
                f"there is no column {col}"
            )
        if not 1 <= level <= section.levels_in(col):
            raise DomainError(
                f"column {col} of section {section.id} has "
                f"{section.levels_in(col)} level(s); there is no level {level}"
            )
    standing = set(section.gaps)
    settled = standing | set(asked) if gap else standing - set(asked)
    return _change(section, replace(section, gaps=tuple(sorted(settled))))


def with_default_levels(section: Section, levels: int) -> Section:
    """Set the default. **Existing columns are untouched** — that is the point
    of a default (§3.3); applying it is :func:`apply_default_levels`."""
    return replace(
        section,
        default_levels=_positive(levels, "a column has at least one level"),
    )


def with_default_depth(section: Section, depth: int) -> Section:
    """Set the default depth. **Existing shelves are untouched.**

    The rule, and the reason it is one: reading the parent live would delete
    the location of every book standing at depth 2 the moment somebody edits
    the section to 1. Applying it is :func:`apply_default_depth`, which is
    explicit, reports what it touched, and cannot go below an occupied row.

    Out of range RAISES rather than clamping, for the reason
    :func:`with_column_count` states: ``Section.__post_init__`` already raises
    for the same value, and one invalid input must not have two answers.
    """
    if not 1 <= int(depth) <= MAX_DEPTH:
        raise DomainError(
            f"a section's default depth is 1..{MAX_DEPTH}, got {depth}"
        )
    return replace(section, default_depth=int(depth))


def next_section(bookcase_id: str, siblings: Iterable[Section],
                 *, id: str, where: str = "top") -> Section:
    """A new section for a bookcase, shaped like the one it stands against.

    The lab's rule (``model.ts:addSection``) and the reason for it: *"a hutch
    usually has about as many columns as the base it stands on"*, so starting
    from a blank 1×5 would mean re-entering what is already on screen.

    ``where='bottom'`` is the awkward case and is why this returns the whole
    set's renumbering rather than one object — every section above the new one
    moves up an ordinal, and ``ordinal`` is unique per bookcase. Use
    :func:`renumber_sections` on the result.

    **The neighbour's gaps are not copied.** What is copied is the SHAPE — how
    wide, how tall — because that is what saves re-entering. A hole is where
    something else stands (§3.6's television), and the hutch above the base
    does not inherit the television.
    """
    ordered = sorted(siblings, key=lambda s: s.ordinal)
    neighbour = (ordered[-1] if where == "top" else ordered[0]) if ordered else None
    return Section(
        id=id,
        library_id=neighbour.library_id if neighbour else "",
        bookcase_id=bookcase_id,
        ordinal=(ordered[-1].ordinal + 1) if (ordered and where == "top") else 1,
        column_levels=tuple(
            [neighbour.default_levels if neighbour else DEFAULT_LEVELS]
            * (neighbour.column_count if neighbour else 1)
        ),
        default_levels=neighbour.default_levels if neighbour else DEFAULT_LEVELS,
        default_depth=neighbour.default_depth if neighbour else DEFAULT_DEPTH,
    )


def renumber_sections(sections: Iterable[Section]) -> tuple[Section, ...]:
    """Renumber 1, 2, 3 bottom-first, in the order given, leaving no hole.

    ⚠ Nothing to do with :func:`with_gaps`. This closes holes in the ORDINALS
    of a stack of sections; a gap is a cell of one section's face that is not
    a shelf. The word was reused here in prose before the feature existed, and
    is spelled out rather than left to collide.

    Needed after adding at the bottom or removing from the middle, because
    ``ordinal`` is unique per bookcase AND is what the address prints. Ids are
    untouched — they are the durable handle a shelf's address holds.
    """
    return tuple(
        replace(section, ordinal=i)
        for i, section in enumerate(
            sorted(sections, key=lambda s: s.ordinal), start=1)
    )


def check_bookcase_size(sections: Iterable[Section]) -> None:
    """Refuse a bookcase that would hold more slots than anyone builds.

    Called with the sections a write would LEAVE behind, so it catches the
    request that states no size at all — *add a section* copies its
    neighbour's shape, so the client never says what it is asking for.
    """
    listed = list(sections)
    if len(listed) > MAX_SECTIONS_PER_BOOKCASE:
        raise TooManySlots(
            f"a bookcase holds at most {MAX_SECTIONS_PER_BOOKCASE} sections; "
            f"this would have {len(listed)}"
        )
    slots = sum(len(s.addresses) for s in listed)
    if slots > MAX_SLOTS_PER_BOOKCASE:
        raise TooManySlots(
            f"a bookcase holds at most {MAX_SLOTS_PER_BOOKCASE} shelves; "
            f"this would have {slots}"
        )


def shelves_differing_from_default_depth(
    section: Section, shelves: Iterable[Shelf]
) -> int:
    """How many shelves the depth default would CHANGE.

    §3.3 requires the confirmation to be *"an explicit action, showing the
    count affected"*, so the count has to exist before the action does. The
    lab had this (``shelvesDifferingFromDefaultDepth``) and the first cut of
    this module did not — :class:`DepthApplication` reports what it could not
    move, which is a different (and later) question.
    """
    return sum(1 for s in shelves if s.depth_count != section.default_depth)


def apply_default_levels(section: Section) -> SlotChange:
    """The explicit, opt-in application of the level default to every column.

    It levels the extent and takes the gaps below the new height with it
    (:func:`_pruned`) — a gap that survives is one still standing in the case.
    """
    levels = tuple([section.default_levels] * section.column_count)
    after = replace(section, column_levels=levels,
                    gaps=_pruned(section.gaps, levels))
    return _change(section, after)


# --- depth ----------------------------------------------------------------


@dataclass(frozen=True)
class DepthApplication:
    """The result of applying a section's depth default to its shelves.

    ``kept`` are the shelves that were NOT taken all the way down, because
    books stand behind. It is a list rather than a count so the screen can
    name them: "3 shelves kept their depth" is an alarm; naming them is an
    explanation.
    """

    shelves: tuple[Shelf, ...]
    kept: tuple[Shelf, ...] = ()


def apply_default_depth(
    section: Section,
    shelves: Iterable[Shelf],
    *,
    deepest_occupied: Mapping[str, int],
) -> DepthApplication:
    """Copy the section's default onto its shelves — but never below a book.

    §3.3's last clause, and the one the lab could not implement because it had
    no books: *"can never take a shelf below its deepest occupied row"*. A
    shelf holding a copy at depth 2 stays at least 2 deep, and says so.
    Deepening is never refused — there is nothing behind a shelf to protect.

    ``deepest_occupied`` maps a shelf id to the deepest depth a copy or a
    capture actually stands at; a shelf missing from it is empty.

    ⚠ It has **no default**, and that is the second review finding of this
    shape. An empty mapping means "nothing stands behind anything", which
    means "shallow every shelf" — and the measured consequence is a copy
    recorded at depth 2 of a shelf that now declares one row, which
    ``Shelf.check_depth`` then refuses and no foreign key can see.
    ``map_edit.deepest_occupied_depths`` is the one way to compute it.
    """
    occupied = deepest_occupied
    out: list[Shelf] = []
    kept: list[Shelf] = []
    for shelf in shelves:
        floor_ = max(1, int(occupied.get(shelf.id, 1)))
        target = max(section.default_depth, floor_)
        moved = replace(shelf, depth_count=target)
        out.append(moved)
        if target != section.default_depth:
            kept.append(moved)
    return DepthApplication(shelves=tuple(out), kept=tuple(kept))


def _positive(value: int, why: str) -> int:
    n = int(value)
    if n < 1:
        raise DomainError(f"{why}, got {value}")
    return n


# --- removal: nothing here auto-removes -----------------------------------


@dataclass(frozen=True)
class SlotRemoval:
    """What removing a set of slots would do to the shelves standing in them.

    Two outcomes, never one:

      - ``deleted`` — the slot was empty, so the ``Shelf`` row goes with it.
        A drawn-but-never-used shelf is scaffolding; keeping it would leave
        the library full of addresses to furniture that no longer exists;
      - ``detached`` — the shelf holds captures or copies, so it **survives**
        with its address cleared, exactly like every photo-born shelf
        (§3.1: one population, not two). Its books keep their shelf; what
        they lose is a location the owner has just erased from the drawing.

    ⚠ Deleting is never the answer for an occupied shelf. "Never auto-remove"
    is §5.6's rule about books, and a shelf carrying books is the same
    argument with more at stake — ``ShelfStore.delete_shelf`` already refuses
    a shelf with captures, and this planner exists so a caller finds that out
    BEFORE it starts writing.
    """

    deleted: tuple[str, ...] = ()
    detached: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return len(self.deleted) + len(self.detached)


def plan_slot_removal(
    shelves: Iterable[Shelf], *, occupied_ids: Iterable[str]
) -> SlotRemoval:
    """Split the shelves losing their slot into "goes" and "stays, unaddressed".

    ⚠ ``occupied_ids`` has **no default**, deliberately. It used to default to
    the empty set, and a review measured what that means: a caller who has not
    answered *"which of these hold books?"* gets "none of them", which is
    "delete all of them" — and the shelf a book stands on vanishes while
    ``copies.shelf_id`` still names it, invisible to `foreign_key_check` and
    to every screen. A required argument is the smallest thing that makes not
    answering impossible.
    """
    occupied = set(occupied_ids)
    deleted: list[str] = []
    detached: list[str] = []
    for shelf in shelves:
        (detached if shelf.id in occupied else deleted).append(shelf.id)
    return SlotRemoval(deleted=tuple(deleted), detached=tuple(detached))


def plan_bind(
    shelf: Shelf,
    section: Section,
    address: ShelfAddress,
    occupant: Shelf | None,
) -> Shelf:
    """The shelf as it will stand, or the reason it may not (P6.4c, §3.14).

    Every refusal in one place, so the route and the client cannot disagree
    about which of them applies — and so the ORDER is a decision rather than
    an accident of how the code was typed:

    1. **the cell must exist** — outside the extent is a `DomainError` (400),
       because a client asking for column 9 of a 4-column section is working
       from a drawing that is not this one;
    2. **the cell must not be a gap** (409) — it exists, it is switched off;
    3. **the shelf must be unaddressed** (409) — see :class:`AlreadyOnTheMap`;
    4. **the slot must be free** (409, naming the occupant).

    Three and four are in that order because only the last one offers a next
    step. *This shelf is already on the map* is answerable by picking a
    different shelf; *something already stands here* is answerable by merging,
    which is P6.4d — and offering a merge to somebody whose request was
    impossible for a simpler reason is how a dangerous button gets pressed by
    accident.

    ⚠ It does not check that ``shelf`` is not the wishlist. ``Shelf`` itself
    refuses to hold an address while ``virtual`` is set (§5.7: unowned books
    may not stand at a location that exists), so :func:`bind_shelf` raises on
    the last line — one rule, in the constructor, where every other path gets
    it too.
    """
    if address.section_id != section.id:
        raise DomainError(
            f"address names section {address.section_id}, not {section.id}")
    if address.level > section.levels_in(address.col):
        raise DomainError(
            f"section {section.id} has no cell at column {address.col}, "
            f"level {address.level}")
    if (address.col, address.level) in section.gaps:
        raise CellIsGap(
            f"column {address.col}, level {address.level} is switched off; "
            "switch the cell back on before putting a shelf in it")
    if shelf.address is not None:
        raise AlreadyOnTheMap(
            f"shelf {shelf.id} already stands at column {shelf.address.col}, "
            f"level {shelf.address.level}; take it off the map first")
    if occupant is not None:
        raise slot_taken(address, occupant)
    return bind_shelf(shelf, address)


def slot_taken(address: ShelfAddress, occupant: Shelf) -> SlotTaken:
    """The refusal, built once.

    Two places discover a taken slot — this module's check, and the store's
    unique index catching a bind that raced another one — and the owner must
    read the same sentence either way, or the race looks like a different bug.

    It names the LABEL when there is one, because that is what the owner
    called the shelf; the id follows for whoever is reading a log. An unnamed
    shelf is named by its id alone rather than by an empty pair of quotes.
    """
    named = f' "{occupant.label}"' if occupant.label else ""
    return SlotTaken(
        f"column {address.col}, level {address.level} already holds shelf "
        f"{occupant.id}{named}", occupant)


@dataclass(frozen=True)
class GroupingContents:
    """What stands on a storey (or in a site) — what a refusal has to say."""

    places: int = 0
    bookcases: int = 0
    floors: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.places or self.bookcases or self.floors)

    def describe(self) -> str:
        parts = []
        if self.floors:
            parts.append(f"{self.floors} floor(s)")
        if self.places:
            parts.append(f"{self.places} room(s)")
        if self.bookcases:
            parts.append(f"{self.bookcases} bookcase(s)")
        return ", ".join(parts) or "nothing"


def check_removable(what: str, contents: GroupingContents) -> None:
    """Refuse to remove a grouping that still holds something, and say what.

    §3.7 for floors, §3.9 for sites — the same rule, because they are the same
    kind of thing. Emptying it first is the owner's decision to make, one
    object at a time, seeing each one; a cascade would take a bookcase's
    shelves (and therefore a shelf's books' only location) with a single tap
    on a storey nobody was looking at.
    """
    if not contents.is_empty:
        raise NotEmpty(
            f"{what} still holds {contents.describe()}; move or remove them "
            f"first (MAP_PLAN §3.7 — nothing here auto-removes)"
        )


# --- how an address reads -------------------------------------------------


@dataclass(frozen=True)
class AddressParts:
    """A shelf's address, as PARTS rather than a sentence.

    Parts, because the sentence is Hebrew in the product and English in the
    console, and a translated string assembled in Python is a second i18n
    table nobody maintains. The RULE — which parts appear — is the thing that
    must have one copy, and it lives here.

    ``section`` and ``column`` are ``None`` when there is only one of them
    (§3.6): *"the address prints only what discriminates. A one-section case
    never says 'section 1', because saying it would imply there is a section
    2."* The same argument applies to a single-column case, so it is applied.

    ⚠ The elevation EDITOR still numbers every cell it draws, single column or
    not: there the number is a coordinate on a grid you are editing, not an
    address you are being sent to. Different surface, different question.
    """

    place: str
    bookcase: str
    column: int | None
    level: int
    section: int | None = None
    depth: int | None = None


def address_parts(
    *,
    place: Place | None,
    bookcase: Bookcase,
    section: Section,
    section_count: int,
    address: ShelfAddress,
    depth: int | None = None,
) -> AddressParts:
    """Build the parts of "where is it", omitting whatever does not narrow it.

    ``depth`` is the row front-to-back and is included only when it is not the
    front one — §5.7's rule that the back row is a real location, stated only
    when it is not the obvious one.
    """
    return AddressParts(
        place=place.name if place else "",
        bookcase=bookcase.name,
        section=section.ordinal if section_count > 1 else None,
        column=address.col if section.column_count > 1 else None,
        level=address.level,
        depth=depth if depth and depth > 1 else None,
    )


# --- shared checks --------------------------------------------------------


def _needs_library(record: object, what: str) -> None:
    if not getattr(record, "library_id", ""):
        raise DomainError(f"{what} must belong to a library (H2)")
