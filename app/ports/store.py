# -*- coding: utf-8 -*-
"""BookStore, ShelfStore and ReadStore — the seam that makes the datastore
decision reversible.

Plan D1 picks SQLite *now*, Postgres later, and says plainly that "the
contract tests are what keep this revisitable". So this file is the contract,
and `tests/test_store_contract.py` runs it against every implementation.

Two rules shape every signature here:

  - **every method is library-scoped** (H2). Not "most"; every one. A method
    without a ``library`` parameter is a method that has to be rewritten at
    pillar 3, and by then it has call sites;
  - **every aggregate is saved whole.** Copies and provenance travel with
    their book, claims travel with their read, rather than having stores of
    their own. That keeps the rules in ``app/domain`` — a store that could
    write a Copy or a Claim independently would be a second path to creating
    one, and §5.1 says there is exactly one (for a Copy) and P2.4 makes the
    same call for a Claim.

Deliberately NOT here: reconciliation itself (P2.5 — a pure function over a
shelf's state and a read's claims, so it belongs in the domain and needs no
port) and blob storage (P2.3's ``BlobStore``, in its own file — a capture's
``image_id`` is a reference, and multi-MB JPEGs are exactly what D1 keeps out
of the database file). What DOES need a port is making one of P2.5's
decisions survive past the read that produced it — see
``app.ports.decisions.DecisionStore``, a fourth, independent aggregate for the
same reasons as the three below.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from app.domain import Book, Capture, LibraryRef, Read, Shelf, Status


class StoreError(Exception):
    """Base for storage-contract violations, as opposed to domain rules."""


class DuplicateBookKey(StoreError):
    """Two different books would share one ``normalize(t)|normalize(a)`` key.

    §5.1: a Book is identified by ``{title, author}`` *within a library*. This
    fires when an edit renames a book onto another one — a real case (fixing a
    misread title to one you already own), and one whose resolution is a merge,
    not a silent overwrite. The store refuses; P1.4 decides.
    """


class WrongLibrary(StoreError):
    """A record's ``library_id`` disagrees with the scope it is written to.

    Never a user error — always a wiring bug, and the kind that writes one
    tenant's data into another's. It raises loudly rather than being coerced.
    """


class UnknownShelf(StoreError):
    """A capture names a shelf that does not exist in this library.

    A foreign-key violation in relational terms, but raised by name because the
    likely cause is a client passing a shelf id from another library — which
    §4.2 says must look like absence, not like a permission error.
    """


class DuplicateCaptureSlot(StoreError):
    """Two captures claiming one ``(shelf, depth, order)`` (§5.3).

    That triple IS a capture's identity, so allowing two would make a shelf's
    book order ambiguous — and the ambiguity would surface much later, as a
    reconciliation diff that reorders itself between reads.
    """


class ShelfNotEmpty(StoreError):
    """Deleting a shelf that still holds evidence.

    §5.6's whole direction is that nothing is destroyed automatically, and a
    shelf's captures are the record a re-read diffs against. So deletion is for
    the shelf typed by mistake, not for clearing one out — and emptying it
    first is a deliberate, separately-confirmed action.
    """


class BookSort(str, Enum):
    """Sort orders §6 lists as "Must". ``TITLE``/``AUTHOR`` sort by NORMALIZED
    forms, so Hebrew orders sensibly regardless of nikud, geresh or a leading
    particle in the stored string.

    ``AUTHOR`` orders by SURNAME (``app.domain.text.author_sort_key``), the way
    a shelf is filed — not by the stored string, which would put every author
    under their given name. Every implementation must agree; the contract
    suite asserts it against each one.
    """

    TITLE = "title"
    AUTHOR = "author"
    RECENTLY_ADDED = "recently_added"


@dataclass(frozen=True)
class BookPage:
    """One page of results plus the total, so the client can render "1-20 of
    251" without a second round trip."""

    items: tuple[Book, ...]
    total: int
    offset: int
    limit: int


class BookStore(Protocol):
    """Persistence for the Book aggregate. All methods library-scoped (H2)."""

    def save(self, library: LibraryRef, book: Book) -> None:
        """Insert or replace a book and everything under it.

        Raises :class:`WrongLibrary` if ``book.library_id`` disagrees with
        ``library``, and :class:`DuplicateBookKey` if a *different* book in
        this library already holds the same key.
        """

    def get(self, library: LibraryRef, book_id: str) -> Book | None:
        """By id, or ``None``. A book in another library reads as ``None`` —
        indistinguishable from absent, which is what lets the API answer 404
        rather than 403 and avoid leaking existence (§4.2, P3.3)."""

    def get_by_key(self, library: LibraryRef, key: str) -> Book | None:
        """By ``normalize(title)|normalize(author)`` — the identity a read
        uses to ask "do I already own this?" (§5.4, §5.6)."""

    def delete(self, library: LibraryRef, book_id: str) -> bool:
        """*Delete from the library*: the book and every copy under it.

        The other, non-destructive action lives in the domain
        (``remove_from_shelf``). Returns False if it wasn't there.
        """

    def list(
        self,
        library: LibraryRef,
        *,
        sort: BookSort = BookSort.TITLE,
        ascending: bool = True,
        status: Status | None = None,
        author_key: str | None = None,
        lent_out: bool | None = None,
        book_ids: tuple[str, ...] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> BookPage:
        """The Books tab's query (§6): sort, page, filter by status or author.

        ``author_key`` is a NORMALIZED author string — the author chip is a
        grouping over normalized strings, not an entity (§5.1).

        ``lent_out`` matches a book with AT LEAST ONE copy currently lent out
        (``Lending.is_out``) — the "who has my books" view (§5.2). It is a
        book-level filter over a copy-level fact, same shape as ``status``.

        ``book_ids`` restricts the result to an explicit id set — sort and
        paging still apply on top of it. Generic on purpose (P2.6): this
        store has no idea what a "duplicate question" is (that is
        ``app.ports.duplicates.DuplicateQueue``'s aggregate, a separate
        port), so the Books tab's "duplicates to resolve" filter is composed
        at the API layer — list the open questions' book ids, then narrow
        here — rather than teaching this port about another aggregate. An
        explicit EMPTY tuple means "match nothing" (an empty queue pages as
        zero books), which is different from ``None`` ("no id filter").
        """

    def search(
        self,
        library: LibraryRef,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> BookPage:
        """Hebrew search over title + author, ranked by relevance (P1.5).

        A separate method from :meth:`list` because the result ORDER is the
        answer here — relevance, not an axis the caller picks. Passing a
        ``sort`` alongside a query would be a lie.

        **What an implementation may and may not choose.** The semantics are
        fixed by ``app.domain.search``: :func:`~app.domain.search.parse` says
        what a query means and :func:`~app.domain.search.score` says what comes
        first, and both are pure. An adapter chooses only how it NARROWS —
        SQLite uses ``LIKE`` over a stored haystack column, Postgres could use
        ``pg_trgm`` or a tsvector — and then ranks with the shared function.
        The contract suite runs the same cases against every implementation,
        so a clever retrieval strategy that changes the answers gets caught.

        An empty or whitespace-only query returns an EMPTY page, never the
        whole library: an empty search box is the caller's business.
        """

    def count(self, library: LibraryRef) -> int:
        """Books in this library. Cheap enough to call on every page."""


class ShelfStore(Protocol):
    """Persistence for Shelf and Capture. All methods library-scoped (H2).

    A **separate port from** :class:`BookStore`, not extra methods on it. The
    two aggregates have independent lifetimes: a shelf exists before any book
    is on it, and a copy leaving a shelf (``remove_from_shelf``) changes the
    book and not the shelf. Merging them would also mean a Postgres adapter had
    to port both at once, which is precisely the coupling D1 is avoiding.

    Captures live here rather than in a store of their own because a capture
    is meaningless without its shelf — its identity IS ``(shelf, depth, order)``
    (§5.3) — and because "the captures of this shelf at this depth" is the
    query P2.5's reconciliation runs.
    """

    # --- shelves ---------------------------------------------------------

    def save_shelf(self, library: LibraryRef, shelf: Shelf) -> None:
        """Insert or replace. Raises :class:`WrongLibrary` on a mismatch."""

    def get_shelf(self, library: LibraryRef, shelf_id: str) -> Shelf | None:
        """By id, or ``None``. A shelf in another library reads as ``None`` —
        same 404-not-403 reasoning as :meth:`BookStore.get` (§4.2)."""

    def list_shelves(
        self,
        library: LibraryRef,
        *,
        include_virtual: bool = False,
    ) -> tuple[Shelf, ...]:
        """Every shelf, ordered by label.

        **Virtual shelves are excluded by default** — the wishlist holds books
        the owner does not own, so counting it among the shelves inflates both
        the shelf list and the apparent size of the library (§6). The caller
        that wants it says so; nobody gets it by forgetting a filter.

        Not paged: a personal library has tens of shelves, not thousands, and
        the shelves screen shows them all. If that ever stops being true the
        change is additive.
        """

    def count_shelves(self, library: LibraryRef, *, include_virtual: bool = False) -> int:
        """How many shelves. Excludes the wishlist by default, as above."""

    def delete_shelf(self, library: LibraryRef, shelf_id: str) -> bool:
        """Remove a shelf that holds no captures. Returns False if absent.

        Raises :class:`ShelfNotEmpty` when captures exist. Deliberately *not* a
        cascade: cascading would delete the photographic record a re-read diffs
        against, and §5.6 says a shelf's book list is durable state.

        ⚠ Copies still pointing at this shelf are NOT cleared here — they live
        in the other aggregate, and a store may not reach across. The caller
        clears them with ``remove_from_shelf`` first; P2.2 owns that sequence
        in the API, where both stores are in hand.
        """

    # --- captures --------------------------------------------------------

    def save_capture(self, library: LibraryRef, capture: Capture) -> None:
        """Insert or replace one photo of one shelf at one depth.

        Raises :class:`WrongLibrary` on a mismatch, :class:`UnknownShelf` if
        the shelf does not exist in this library — a capture whose shelf is
        absent is a read with nothing to reconcile against — and
        :class:`DuplicateCaptureSlot` if another capture already holds this
        ``(shelf, depth, order)``.
        """

    def get_capture(self, library: LibraryRef, capture_id: str) -> Capture | None:
        """By id, or ``None``."""

    def list_captures(
        self,
        library: LibraryRef,
        shelf_id: str,
        *,
        depth: int | None = None,
    ) -> tuple[Capture, ...]:
        """A shelf's captures in ``(depth, order)`` order.

        ``depth`` narrows to one row front-to-back. That parameter is the whole
        reason this method exists in this shape: §5.6's not-seen rule and the
        diff view are **per depth**, and §5.7 #2 forbids overlap-dedup across
        depths — a caller that could only fetch "all captures of this shelf"
        would have to re-derive the scoping every time, and P2.3 is where
        getting it wrong is expensive.
        """

    def delete_capture(self, library: LibraryRef, capture_id: str) -> bool:
        """Remove one capture. Returns False if it wasn't there."""


class ReadStore(Protocol):
    """Persistence for Read + its Claims (P2.4). All methods library-scoped
    (H2), same as every other store here.

    A SEPARATE port from :class:`ShelfStore`, not extra methods on it — same
    reasoning as the ``BookStore``/``ShelfStore`` split: a Read's lifetime is
    independent (created, runs, settles into a terminal status; a shelf just
    accumulates them over time), and keeping the port separate is what stops
    a Postgres move from having to port three aggregates in one commit.

    Claims travel WITH their Read, whole — exactly like Copy/Provenance
    travel with their Book. A store that could write a Claim on its own would
    be a second path to producing evidence about a spine, and the whole point
    of routing every read through the Reader/JobRunner ports is that there is
    exactly one.

    ⚠ Unlike :meth:`ShelfStore.save_capture`, ``save_read`` does NOT validate
    that ``shelf_id`` names a real shelf in this library. A capture's
    ``shelf_id`` is client-supplied and must be policed (§4.2); a Read's is
    not — it is only ever constructed by ``app.domain.read.new_read`` from an
    already-loaded ``Shelf``, so by the time a caller has a ``Read`` to save,
    the shelf is known-good. Adding the check here would duplicate a
    guarantee the domain already gives, for a class of bug (a forged
    ``shelf_id``) that cannot occur through the one constructor.

    Deliberately no ``delete_read``: reads are an audit trail, the same
    "archived, never overwritten" stance the tuning server takes with its own
    runs (CLAUDE.md, "Run history") — nothing in P2.4 needs one removed, and
    adding it before something needs it is a guess at a requirement rather
    than a measured one.
    """

    def save_read(self, library: LibraryRef, read: Read) -> None:
        """Insert or replace, whole (claims included). Raises
        :class:`WrongLibrary` if ``read.library_id`` disagrees with
        ``library`` — never a user error, always a wiring bug (same as every
        other aggregate's ``save``)."""

    def get_read(self, library: LibraryRef, read_id: str) -> Read | None:
        """By id, or ``None``. A read in another library reads as ``None`` —
        the same 404-not-403 reasoning as everywhere else (§4.2)."""

    def list_reads(
        self,
        library: LibraryRef,
        shelf_id: str,
        *,
        depth: int | None = None,
    ) -> tuple[Read, ...]:
        """A shelf's reads, most recent first. ``depth`` narrows to one row —
        the same shape as :meth:`ShelfStore.list_captures`, for the same
        reason: §5.7 #1 scopes a read's history to the row it actually
        covered, and a caller that could only ask "every read of this shelf"
        would have to re-derive that scoping every time.
        """

    def list_reads_for_capture(
        self, library: LibraryRef, capture_id: str,
    ) -> tuple[Read, ...]:
        """Every read that included this ONE photo, most recent first (P2.10).

        The image workspace's *"clicking a photo opens its runs"* (§12.2 #10),
        and the reason it is a store method rather than a filter over
        :meth:`list_reads`: a capture can be RE-BOUND to another shelf or row
        after it was read (P2.2's intake correction), and its earlier reads
        stay filed — correctly — under the shelf as it was THEN. Deriving a
        photo's runs from its CURRENT shelf would silently lose exactly the
        history a workspace exists to show, and it would lose it only for
        photos someone had to correct.

        Matching is on ``Read.capture_ids``, so a read of a whole row lists
        under every photo of that row — which is honest: it read them all
        (§5.7 #1 forbids a partial read of one row).
        """
