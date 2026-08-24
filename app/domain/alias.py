# -*- coding: utf-8 -*-
"""What a merged shelf leaves behind (P6.4a, MAP_PLAN §3.11).

**[DECIDED 2026-08-21 — owner]** *"Image keeps its own identity. Shelf and
slot can be aliases (in addition to the image)"*, and the alias carries the
old address too.

Three identities, and they are not the same kind of thing:

  - **the image** is durable and is NEVER aliased. A capture already moves
    between shelves keeping its own id, and its earlier reads stay filed
    under the shelf as it was THEN. A merge changes which shelf a photograph
    hangs off; it does not re-identify the photograph;
  - **the shelf** may become an alias: ``alias_id -> shelf_id``;
  - **the slot** may become an alias in the same row — the absorbed shelf's
    former ``(section, col, level)`` resolves to the survivor as well.

The second half is the one worth defending. *"The shelf that was at section
1, column 2, level 3"* is a question the library can still answer after the
wood has been re-identified, and it matters because **the address is what a
person reads off a drawing** — it is the half that survives in someone's
memory when the id does not.

⚠ **The address here is HISTORICAL.** It records where the absorbed shelf
USED to stand, not where anything stands now. §3.10a settled the consequence
so this module does not have to argue it: the cell may since have become a
gap — the owner put a television there — and that is fine. The extent is
untouched by a gap, so the address still exists; it simply holds no shelf. An
alias therefore never needs a live slot at its former address, and a gap must
never be refused because some alias remembers that cell.

Pure (H1). The resolver takes the aliases it is given; :mod:`app.ports.store`
is what fetches them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.domain.book import DomainError
from app.domain.shelf import ShelfAddress


@dataclass(frozen=True)
class ShelfAlias:
    """One absorbed identity, and where it used to stand.

    ``label`` is kept because it is the other half of *"the shelf that was"* —
    a household calls a shelf *"the one with the cookbooks"* long after the
    drawing has been rearranged, and that name is destroyed by the merge
    unless something remembers it.
    """

    alias_id: str
    library_id: str
    shelf_id: str
    merged_at: str
    address: ShelfAddress | None = None
    label: str = ""

    def __post_init__(self) -> None:
        if not self.library_id:
            raise DomainError("an alias must belong to a library (H2)")
        if not self.alias_id or not self.shelf_id:
            raise DomainError("an alias needs both an id and a survivor")
        if self.alias_id == self.shelf_id:
            # Not pedantry: `resolve` would answer with the id it was handed
            # and every caller would believe the shelf was still there.
            raise DomainError(
                f"shelf {self.alias_id} cannot be an alias of itself")


def resolve(shelf_id: str, aliases: Iterable[ShelfAlias]) -> str:
    """Which shelf answers for this id — one hop, never a walk.

    ⚠ **One hop is enforced by ``ShelfStore.save_alias``**, and this
    paragraph used to say it was guaranteed by the schema. It is not, and a
    migration review stored a chain AND a cycle through the public API to
    prove it: the foreign key proves ``shelf_id`` names a live ``shelves``
    row, which is a different claim from "names a shelf that is not itself an
    ``alias_id``". Only the first was ever checked.

    What a chain costs: A absorbed by B, later B absorbed by C, and
    :func:`identities` for C returns ``('C', 'B')`` — A is not in the list, so
    ``books_on_shelf`` never asks for it and every book that arrived on A is
    unreachable from the only shelf that still exists, with
    ``foreign_key_check`` clean throughout. A cycle is worse: neither shelf
    can ever be deleted again.

    So the store refuses both ends — a survivor that is itself absorbed, and
    an id that is already a survivor — and THAT is why there is no cycle guard
    here. The invariant is real; it just lives one layer down.

    An id nothing has absorbed answers itself, which is what makes this safe
    to call on every shelf id rather than only the ones somebody suspects.
    """
    for alias in aliases:
        if alias.alias_id == shelf_id:
            return alias.shelf_id
    return shelf_id


def resolve_address(
    address: ShelfAddress, aliases: Iterable[ShelfAlias],
) -> str | None:
    """Which shelf is *"the one that was at this slot"*, or ``None``.

    The address half of §3.11. Exactly one answer by construction — the
    partial unique index over ``(library_id, section_id, col, level)`` is what
    makes that true, and the owner settled it precisely so this lookup is not
    a query that silently picks the first of several.

    ⚠ Answers only for a slot whose shelf was ABSORBED. A slot with a live
    shelf standing in it is not this function's business — ask
    ``ShelfStore.get_shelf_at``, which is the live question.
    """
    for alias in aliases:
        if alias.address == address:
            return alias.shelf_id
    return None


def absorbed_by(shelf_id: str, aliases: Iterable[ShelfAlias]) -> tuple[ShelfAlias, ...]:
    """Every identity that resolves to this shelf.

    ⚠ A helper of :func:`identities`, and nothing else calls it yet. An
    earlier docstring named three callers — the delete refusal and the
    *formerly …* line — which in fact go through ``ShelfStore.aliases_of``,
    the narrow query, because they start from a shelf id and a store rather
    than from a list. Same family as a docstring asserting a test exists.
    """
    return tuple(a for a in aliases if a.shelf_id == shelf_id)


def identities(shelf_id: str, aliases: Iterable[ShelfAlias]) -> tuple[str, ...]:
    """Every id a query about this shelf must look under, survivor first.

    ⚠ The reason ``books_on_shelf`` exists at all. Six tables name a shelf and
    only two have a foreign key, so a merge that rewrote every reference would
    report a clean ``foreign_key_check`` over a library whose locations had
    quietly moved — §3.11's whole argument. Nothing is rewritten, so every
    question about a shelf has to ask about its absorbed identities too, and
    this is the one place that list is built.
    """
    return (shelf_id,) + tuple(a.alias_id for a in absorbed_by(shelf_id, aliases))
