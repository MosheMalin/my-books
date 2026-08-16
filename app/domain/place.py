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
from app.domain.shelf import Shelf, ShelfAddress

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
        """Every slot this section describes, column-major and 1-based."""
        return tuple(
            ShelfAddress(self.id, col, level)
            for col in range(1, self.column_count + 1)
            for level in range(1, self.levels_in(col) + 1)
        )


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
        after = replace(section, column_levels=section.column_levels[:n])
    else:
        after = replace(
            section,
            column_levels=section.column_levels
            + tuple([section.default_levels] * (n - section.column_count)),
        )
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
    return _change(section, replace(section, column_levels=tuple(levels_now)))


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
    """Close the gaps: 1, 2, 3 bottom-first, in the order given.

    Needed after adding at the bottom or removing from the middle, because
    ``ordinal`` is unique per bookcase AND is what the address prints. Ids are
    untouched — they are the durable handle a shelf's address holds.
    """
    return tuple(
        replace(section, ordinal=i)
        for i, section in enumerate(
            sorted(sections, key=lambda s: s.ordinal), start=1)
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
    """The explicit, opt-in application of the level default to every column."""
    after = replace(
        section,
        column_levels=tuple([section.default_levels] * section.column_count),
    )
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
