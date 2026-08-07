# -*- coding: utf-8 -*-
"""DecisionStore — persistence for P2.5's standing reconciliation answers.

A SEPARATE port from :class:`app.ports.store.BookStore`/``ShelfStore``, same
reasoning as every other split in ``app.ports.store``: a `Decision`'s lifetime
is independent of a book's or a shelf's — it can exist before the book it
concerns is ever created (a REJECTED decision for a claim that never became a
book) and it outlives any one read. Keeping it separate is also what lets a
Postgres move port one aggregate at a time instead of three.

``app.ports.store`` says reconciliation itself "needs no port" — true of the
PURE function (`app.domain.reconcile.reconcile`), which takes decisions as a
plain argument. What DOES need a port is making a decision survive past the
read that produced it, so a LATER read of the same (shelf, depth) honours it
(§5.6: "a human decision must not be overridden by re-running"). That is what
this file is for.

May import ``app.domain`` only (H1) — same rule as every other port.
"""
from __future__ import annotations

from typing import Protocol

from app.domain import Decision, LibraryRef


class DecisionStore(Protocol):
    """All methods library-scoped (H2), same as every store in this package."""

    def save_decision(self, library: LibraryRef, decision: Decision) -> None:
        """Insert or replace the decision for
        ``(decision.shelf_id, decision.depth, decision.book_key)`` — a human
        who changes their mind (rare, but §5.4's queue makes it possible)
        overwrites rather than accumulating a history nobody reads. Raises
        :class:`app.ports.store.WrongLibrary` if ``decision.library_id``
        disagrees with ``library``.
        """

    def get_decision(
        self, library: LibraryRef, shelf_id: str, depth: int, book_key: str,
    ) -> Decision | None:
        """By its natural key, or ``None``. A decision in another library
        reads as ``None`` — the same 404-not-403 reasoning as every other
        aggregate (§4.2)."""

    def list_decisions(
        self, library: LibraryRef, shelf_id: str, depth: int,
    ) -> tuple[Decision, ...]:
        """Every decision at this ONE (shelf, depth) — exactly the shape
        `reconcile()` takes, so the caller builds its ``decisions`` argument
        with one call per read rather than filtering a library-wide list.
        """

    def delete_decision(
        self, library: LibraryRef, shelf_id: str, depth: int, book_key: str,
    ) -> bool:
        """The 'undo' of a mis-click — mirrors
        ``booksnap.library.clear_decision``. Returns ``False`` if there was
        nothing to remove. Deliberately does NOT touch any `Book`: a decision
        answers a QUESTION, and clearing the answer does not itself add,
        remove or relink anything — the next read asks again.
        """
