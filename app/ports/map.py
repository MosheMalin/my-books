# -*- coding: utf-8 -*-
"""MapStore — the drawing, as a fifth aggregate (P6.1, MAP_PLAN §3).

A sixth port rather than more methods on ``ShelfStore``, for the reason the
decision store got its own: these are different records with a different
lifetime. A shelf is created by a photograph and outlives every redrawing of
the room it stands in; a room, a floor and a bookcase are created by a person
with a pointer and are edited constantly.

**The map is read whole and written one object at a time**, and both halves
are deliberate:

  - :meth:`MapStore.load_map` returns the entire drawing for a library in one
    call, because that is what an editor needs — the canvas cannot render a
    room without knowing which floor is showing, and it cannot draw a bookcase
    without its columns. It is small by nature (a house is tens of rows, not
    thousands) and it is the one query a plan screen makes;
  - every write names one object. A "save the whole plan" call would make the
    last browser tab to press a key the winner of every disagreement, and the
    lab already showed that a plan is edited in bursts of tiny changes.

**Shelves are not here.** A slot's shelf is a ``Shelf``, in ``ShelfStore``,
carrying a ``ShelfAddress`` (MAP_PLAN §3.1 — one population, not two). Keeping
them apart is what stops this port from growing a second, prettier way to
create a shelf. The orchestration that creates a section's shelves along with
the section lives in ``app/map_edit.py``, over both ports.

Every method is library-scoped (H2), like every other port here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain import Bookcase, Floor, LibraryRef, Place, Section, Site

#: Re-exported, not redefined: ``ShelfStore`` raises it too (a shelf's address
#: names a section), so it lives in ``app.ports.store`` and is imported here.
#: Two classes with this name would mean a caller catching the wrong one.
from app.ports.store import UnknownParent  # noqa: F401


@dataclass(frozen=True)
class MapSnapshot:
    """One library's whole drawing.

    A read model, not an aggregate: nothing is saved through it. The tuples
    arrive in the order the screens want them — sites and floors by the
    owner's ``order`` then name, places and bookcases by floor, sections
    bottom-first — so no caller re-sorts and then disagrees with another
    caller that re-sorted differently.
    """

    sites: tuple[Site, ...] = ()
    floors: tuple[Floor, ...] = ()
    places: tuple[Place, ...] = ()
    bookcases: tuple[Bookcase, ...] = ()
    sections: tuple[Section, ...] = ()

    @property
    def is_empty(self) -> bool:
        """A library nobody has drawn yet — the state every library starts in
        and most stay in. Screens ask this rather than counting sites,
        because "one site, no rooms" is still nothing to show."""
        return not (self.places or self.bookcases)


class MapStore(Protocol):
    """Sites, floors, places, bookcases and sections."""

    def load_map(self, library: LibraryRef) -> MapSnapshot:
        """The whole drawing, in one call."""

    # --- sites ------------------------------------------------------------

    def save_site(self, library: LibraryRef, site: Site) -> None: ...

    def get_site(self, library: LibraryRef, site_id: str) -> Site | None: ...

    def delete_site(self, library: LibraryRef, site_id: str) -> bool:
        """Remove an EMPTY site. Returns False if there was none.

        Raises ``app.domain.NotEmpty`` when floors still belong to it, naming
        them (MAP_PLAN §3.7 — nothing here auto-removes), and when it is the
        last one: a library that has been drawn at all has somewhere for the
        drawing to be.
        """

    # --- floors -----------------------------------------------------------

    def save_floor(self, library: LibraryRef, floor: Floor) -> None: ...

    def get_floor(self, library: LibraryRef, floor_id: str) -> Floor | None: ...

    def delete_floor(self, library: LibraryRef, floor_id: str) -> bool:
        """Remove an EMPTY storey; ``NotEmpty`` names the rooms and cases on it
        and the last floor of a site is refused, exactly as the lab did."""

    # --- places (rooms) ---------------------------------------------------

    def save_place(self, library: LibraryRef, place: Place) -> None: ...

    def get_place(self, library: LibraryRef, place_id: str) -> Place | None: ...

    def delete_place(self, library: LibraryRef, place_id: str) -> bool:
        """Remove a room. **Its bookcases stay** where they stand, attached to
        no room — the lab's rule, and the same one the product already holds
        for shelves: deleting a container never destroys what it held."""

    # --- bookcases --------------------------------------------------------

    def save_bookcase(self, library: LibraryRef, bookcase: Bookcase) -> None: ...

    def get_bookcase(
        self, library: LibraryRef, bookcase_id: str
    ) -> Bookcase | None: ...

    def delete_bookcase(self, library: LibraryRef, bookcase_id: str) -> bool:
        """Remove a case and its sections.

        Raises ``app.domain.NotEmpty`` while any shelf still stands in one of
        its slots. Emptying those slots is ``app/map_edit.py``'s job and is
        never implicit here — an occupied shelf is DETACHED, never deleted,
        and a store method that quietly did either would be the silent
        data-loss bug MAP_PLAN §2 predicted for exactly this item.
        """

    # --- sections ---------------------------------------------------------

    def save_section(self, library: LibraryRef, section: Section) -> None: ...

    def save_sections(
        self, library: LibraryRef, sections: tuple[Section, ...]
    ) -> None:
        """Write a bookcase's sections as ONE unit.

        ⚠ Required, not a convenience. Inserting a section at the BOTTOM
        pushes every other one up an ordinal, and ``ordinal`` is unique per
        bookcase AND is what an address prints. A review measured the
        one-at-a-time version failing part-way: sections renumbered, the new
        one never created, a gap at 3, and the request answering an error
        while having permanently changed the drawing. Every retry widened it.

        All-or-nothing, and the implementation must order its writes so no
        intermediate state collides with the unique index.
        """

    def move_place(
        self, library: LibraryRef, place: Place, floor_id: str
    ) -> Place:
        """Move a room to another storey, **taking its furniture with it**.

        ⚠ One call, one transaction, because the two halves cannot be set
        independently — a review moved a room upstairs and left its bookcase
        on the ground floor, which is precisely the state
        ``NotOnThisFloor`` exists to make unreachable. The case was then
        un-renamable, un-movable and un-resizable forever: every write
        re-checked the invariant and answered 409 about a mismatch the owner
        never created.

        A bookcase belongs to a room the way furniture does (§3.7), so it goes
        where the room goes. That is the same argument ``attach_bookcase``
        already makes in the other direction.
        """

    def get_section(
        self, library: LibraryRef, section_id: str
    ) -> Section | None: ...

    def delete_section(self, library: LibraryRef, section_id: str) -> bool:
        """Remove one section. Refused for the last one of a bookcase (a case
        with no sections is not a simpler case, it is an unaddressable one)
        and while any of its slots is filled."""
