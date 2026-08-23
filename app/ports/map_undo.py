# -*- coding: utf-8 -*-
"""MapUndoStore — persistence for P6.4b's undo journal (MAP_PLAN §3.15).

A SEPARATE port from :class:`app.ports.map.MapStore`, and the reason is the
one every other split in this package gives: the lifetimes are independent.
An entry outlives the rows it remembers — that is the entire point of it,
since the rows it remembers have been deleted — and it must survive the
deletion of the bookcase it can put back. Folding these methods onto
``MapStore`` would also mean the store that performs a destructive edit is
the store that judges whether it may be undone.

**Two methods and one predicate, deliberately.** There is no cursor and no
"undo entry N": *record all, undo the head* (owner, 2026-08-24). The journal
keeps every destructive edit as the record of what happened, and only the
newest entry is ever offered. :meth:`recent` is the one query — its ``limit``
serves the head with ``limit=1`` and the history with more — so the n-deep
stack this item deliberately is not can arrive later as a behaviour change
rather than a migration.

May import ``app.domain`` only (H1) — same rule as every other port.
"""
from __future__ import annotations

from typing import Protocol

from app.domain import LibraryRef
from app.domain.map_undo import MapUndoEntry


class MapUndoStore(Protocol):
    """All methods library-scoped (H2), same as every store in this package."""

    def record(self, library: LibraryRef, entry: MapUndoEntry) -> None:
        """Insert or replace by ``entry.id``.

        **Replace, not insert-only**, because coalescing rewrites the head in
        place: the two requests behind one bookcase deletion produce one
        entry, which is written twice — see
        :func:`app.domain.map_undo.coalesces_with`.

        Raises :class:`app.ports.store.WrongLibrary` if ``entry.library_id``
        disagrees with ``library``.
        """

    def recent(
        self, library: LibraryRef, *, limit: int = 1,
    ) -> tuple[MapUndoEntry, ...]:
        """The library's newest entries, newest first, at most ``limit``.

        Newest **regardless of** ``undone_at``: an entry that has been
        replayed still occupies the head, and the head is the only entry
        anyone is offered. That is what makes this one-deep rather than a
        stack — undoing does not expose the edit before it, it exhausts the
        offer. A caller asking whether an undo is available reads
        ``entry.is_live``, and the distinction is deliberate, because
        *"nothing to undo"* and *"you already undid it"* are different
        sentences to show somebody.
        """

    def mark_undone(
        self, library: LibraryRef, entry_id: str, at: str,
    ) -> bool:
        """Stamp an entry as replayed. ``False`` if there was no such entry.

        The row is kept, never deleted: the journal is the record of what
        happened, and an undo is one of the things that happened. There is no
        inverse of this call — an entry is replayed once, and there is no
        redo.
        """
