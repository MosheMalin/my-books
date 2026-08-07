# -*- coding: utf-8 -*-
"""DuplicateQueue — persistence for P2.6's durable "duplicates to resolve"
queue (§5.4).

A FIFTH, independent port, same reasoning as every other split in
``app.ports.store``/``app.ports.decisions``: a :class:`~app.domain.copy_resolution.DuplicateQuestion`'s
lifetime is independent of a book's, a shelf's, a read's or a `Decision`'s —
it is opened when §5.4's prompt fires and nobody answers it THIS call, and it
is closed the moment a `Decision` exists at the same key, whether that
`Decision` came from a fresh human answer or from the queue's own "use the
safe default" action. Keeping it separate is also what lets a Postgres move
port one aggregate at a time (D1).

``app.domain.reconcile`` needs no port for reconciliation itself (it is a
pure function over plain values); what needs one is making an UNANSWERED
question survive past the read that raised it, so a human can come back to
the Books tab later and resolve it without re-running anything. That is what
this file is for — the queue's sibling of `app.ports.decisions.DecisionStore`.

May import ``app.domain`` only (H1) — same rule as every other port.
"""
from __future__ import annotations

from typing import Protocol

from app.domain import DuplicateQuestion, LibraryRef


class DuplicateQueue(Protocol):
    """All methods library-scoped (H2), same as every store in this package."""

    def save_question(self, library: LibraryRef, question: DuplicateQuestion) -> None:
        """Insert or replace the OPEN question for
        ``(question.shelf_id, question.depth, question.book_key)`` — the
        same composite key `DecisionStore` uses, because a question and its
        eventual answer are two states of the same fact. Raises
        :class:`app.ports.store.WrongLibrary` if ``question.library_id``
        disagrees with ``library``.
        """

    def get_question(
        self, library: LibraryRef, shelf_id: str, depth: int, book_key: str,
    ) -> DuplicateQuestion | None:
        """By its natural key, or ``None`` if nothing is open there. A
        question in another library reads as ``None`` — the same
        404-not-403 reasoning as every other aggregate (§4.2)."""

    def list_open_questions(
        self, library: LibraryRef, *, shelf_id: str | None = None,
    ) -> tuple[DuplicateQuestion, ...]:
        """Every OPEN question, optionally narrowed to one shelf.

        ``shelf_id=None`` lists across the WHOLE library — the shape the
        Books tab's "duplicates to resolve" filter needs, since a queue
        entry is about a BOOK, not about which shelf you happen to be
        looking at. Narrowed listing exists for the same reason
        `ReadStore.list_reads`'s ``depth`` parameter does: a caller that
        could only ever ask "every open question in the library" would have
        to re-derive the narrowing itself.
        """

    def delete_question(
        self, library: LibraryRef, shelf_id: str, depth: int, book_key: str,
    ) -> bool:
        """Close a question — called the moment a `Decision` exists at this
        exact key, whether from a fresh human answer or the queue's own
        default-resolve action. Returns ``False`` if nothing was open there
        (answering a question nobody skipped is a normal, common case, not
        an error).
        """
