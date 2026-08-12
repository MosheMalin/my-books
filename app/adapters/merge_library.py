# -*- coding: utf-8 -*-
"""Merge one library's contents into another, and retire the source (§4.1).

The tool for the settled tenancy rule's cleanup: a location that was modelled
as a TENANT before Place existed (owner, 2026-08-10 — "ספריית ההורים... It's
a place / location") moves back into the collection it always belonged to.
This is P6.1's "retire a library into a Place" exit arriving early, minus the
Place record itself — which is why shelves can carry a LABEL across the move:
until pillar 6, the label is where the location knowledge survives.

A sibling of :mod:`app.adapters.migrations`, and like it, deliberately
SQL-shaped: this is data surgery on one SQLite file, done in one transaction,
tested against real temp databases built through the real stores — not a
port-generic algorithm, because the ports deliberately have no "move between
libraries" verbs and growing them for a one-way cleanup would put a
cross-tenant door in every adapter forever.

What it preserves, and how:

  - **identity.** Shelf, capture, read, claim and copy ids are unchanged —
    a merge re-homes rows, it never re-mints them. Provenance (the evidence)
    is keyed by copy and never touched at all;
  - **collisions become copies, because that is the physical truth.** A
    source book whose ``book_key`` already exists in the target is the same
    WORK; the copy the camera saw standing at the source's shelf is a real,
    additional physical copy. Its copies (with their provenance, status,
    lending) re-parent onto the target book and the redundant book row is
    deleted. Positions renumber after the target's own, so the order stays
    total;
  - **photos move first, disappear last.** Blob bytes are COPIED into the
    target before the transaction and the source tree is purged only after
    the commit — at every failure point the keys a row names resolve
    somewhere. Content addressing makes the copy idempotent and makes
    already-shared bytes free.

What it refuses (loudly, before touching anything): a source with OPEN
decisions or duplicate questions. Both are scoped to (library, shelf, depth,
book_key); the shelves move with their ids intact so a mechanical move would
usually be right — but a standing "no" is a human's recorded answer, and
silently re-scoping human answers is exactly the kind of quiet write this
codebase refuses everywhere else. Resolve them, or extend this tool WITH
tests, before merging such a library.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.domain import LibraryRef
from app.ports.blobs import BlobStore

#: Every table carrying a ``library_id`` column, and what the merge does with
#: it. ONE list, so the leftover check below cannot drift from the moves —
#: F2 of the pre-run review was exactly that drift: `decisions` and
#: `duplicate_questions` were neither moved nor leftover-checked, so a row a
#: concurrent writer slipped in during the blob copy committed as an orphan
#: of a deleted library, and a human's recorded "no" stopped suppressing the
#: book it was about.
# Every table carrying a `library_id`. ⚠ `memberships` LEFT this list at
# P3.7b: a membership names an account now, so it has no library_id to move
# and no orphan to leave behind. Keeping it here would have made the
# leftover check below raise `no such column` on every merge.
_LIBRARY_TABLES = ("books", "copies", "shelves", "captures", "reads",
                   "decisions", "duplicate_questions")


class MergeRefused(Exception):
    """The merge would be wrong or ambiguous; nothing was touched."""


@dataclass(frozen=True)
class MergeReport:
    books_moved: int = 0
    copies_reparented: int = 0          # collision copies, onto existing books
    collisions: tuple[str, ...] = ()    # "title / author" per merged work
    shelves_moved: int = 0
    shelves_labelled: int = 0
    captures_moved: int = 0
    reads_moved: int = 0
    blobs_copied: int = 0
    blobs_purged: int = 0

    def summary(self) -> str:
        lines = [
            f"books moved: {self.books_moved}",
            f"copies re-parented onto existing books: {self.copies_reparented}",
        ]
        for c in self.collisions:
            lines.append(f"  = now another copy of: {c}")
        lines += [
            f"shelves moved: {self.shelves_moved} "
            f"(labelled: {self.shelves_labelled})",
            f"captures moved: {self.captures_moved}",
            f"reads moved: {self.reads_moved}",
            f"photos copied: {self.blobs_copied}, source tree purged: "
            f"{self.blobs_purged}",
        ]
        return "\n".join(lines)


def _refuse_if_collisions_discard_book_fields(
    conn: sqlite3.Connection, src: str, dst: str,
) -> None:
    """A colliding source BOOK row is deleted after its copies re-parent —
    so a rating, a note, a read-status or a shared-book link on it would
    vanish silently (review F6). Refused rather than merged: which side's
    rating wins is a human question, and this tool answers no human
    questions."""
    rows = conn.execute(
        """SELECT s.title, s.author FROM books s JOIN books d
             ON d.library_id = ? AND d.book_key = s.book_key
           WHERE s.library_id = ?
             AND (s.rating IS NOT NULL OR s.notes != ''
                  OR s.read_status IS NOT NULL
                  OR s.shared_book_id IS NOT NULL)""",
        (dst, src),
    ).fetchall()
    if rows:
        names = "; ".join(f"{r['title']} / {r['author']}" for r in rows)
        raise MergeRefused(
            f"colliding book(s) carry a rating, note, read-status or shared "
            f"link that the merge would silently discard: {names}. Move or "
            "clear those by hand first — which side wins is a human "
            "question."
        )


def _refuse_if_answered_questions(conn: sqlite3.Connection, src: str) -> None:
    for table, what in (("decisions", "standing decisions"),
                        ("duplicate_questions", "open duplicate questions")):
        n = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE library_id = ?", (src,)
        ).fetchone()[0]
        if n:
            raise MergeRefused(
                f"source library has {n} {what} — a human's recorded answers "
                "are scoped to their library, and re-scoping them silently is "
                "refused. Resolve them first, or extend merge_library WITH "
                "tests."
            )


def merge_library(
    db_path: str | Path,
    src_id: str,
    dst_id: str,
    blobs: BlobStore,
    *,
    label_unnamed_shelves: str = "",
) -> MergeReport:
    """Move everything in ``src`` into ``dst`` and delete ``src``'s tenancy
    rows. See the module docstring for the rules; raises :class:`MergeRefused`
    without writing when they cannot hold."""
    if src_id == dst_id:
        raise MergeRefused("source and target are the same library")
    src_ref = LibraryRef(id=src_id, label="")
    dst_ref = LibraryRef(id=dst_id, label="")

    # A generous timeout so a live server's brief write lock waits instead of
    # aborting; a raw OperationalError past it is re-raised as a refusal
    # below, so the operator can tell "locked, nothing happened" apart from
    # a crash after the commit (review F8).
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        owners = {}
        for lib, name in ((src_id, "source"), (dst_id, "target")):
            row = conn.execute(
                "SELECT account_id FROM libraries WHERE id = ?", (lib,)
            ).fetchone()
            if row is None:
                raise MergeRefused(f"no such {name} library: {lib!r}")
            owners[name] = str(row["account_id"])
        # ⚠ REFUSED across customers, and not because it is hard. Moving a
        # library into another account's hands would hand every book, photo
        # and read in it to people who were never invited — the one thing
        # §4.1's boundary exists to make impossible, performed by an
        # operator tool with a --confirm flag. This tool exists to undo a
        # location that was modelled as a tenant; a location does not change
        # owner. If a customer genuinely has to hand over a collection, that
        # is a transfer with its own consent story, not a merge.
        if owners["source"] != owners["target"]:
            raise MergeRefused(
                f"{src_id!r} and {dst_id!r} belong to different accounts "
                f"({owners['source']!r} and {owners['target']!r}); merging "
                "them would move a collection between customers (§4.1)"
            )
        _refuse_if_answered_questions(conn, src_id)
        _refuse_if_collisions_discard_book_fields(conn, src_id, dst_id)

        # --- photos first (outside the transaction, idempotent) -----------
        # Copied, not moved: until the commit below succeeds, every key a
        # source row names must still resolve under the source.
        blobs_copied = 0
        copied_keys: list[str] = []
        for stored in blobs.list_keys(src_ref):
            data = blobs.read(src_ref, stored.key)
            if data is None:            # a variantless race; nothing to copy
                continue
            meta = blobs.stat(src_ref, stored.key)
            blobs.put(dst_ref, data,
                      filename=meta.filename if meta else "")
            copied_keys.append(stored.key)
            blobs_copied += 1
        # Existence is not proof of content (review F5): `put` skips a path
        # that already exists, so a torn destination file — a crash between
        # rename and flush, a pre-existing corrupt copy — would be trusted,
        # committed over, and then the only GOOD copy purged. Content
        # addressing makes the verification exact: the bytes must hash back
        # to their own key.
        for key in copied_keys:
            data = blobs.read(dst_ref, key)
            if (data is None
                    or hashlib.sha256(data).hexdigest() != key.split(".")[0]):
                raise MergeRefused(
                    f"photo {key} did not verify in the target after the "
                    "copy — refusing to touch any row while a byte is in "
                    "doubt. Inspect the target's copy, delete it, and re-run."
                )

        # --- one transaction for every row ---------------------------------
        with conn:
            # Re-checked INSIDE the transaction (review F2): the first check
            # ran before the multi-second blob copy, and a decision recorded
            # by a live server in that window would otherwise commit as an
            # orphan of a deleted library — a human's standing "no" that
            # nothing would ever read again.
            #
            # ⚠ Deliberately REDUNDANT with the leftover check at the bottom
            # (decisions/questions are in _LIBRARY_TABLES): deleting either
            # alone survives the suite because the other still aborts —
            # verified, the P2.1 "what else enforces this?" pattern — and
            # deleting both fails the named mid-copy-writer test. The
            # difference is the MESSAGE: this one says what to resolve; the
            # leftover check says only that a half-move was refused.
            _refuse_if_answered_questions(conn, src_id)
            # Collisions: same work, another physical copy. Re-parent the
            # source book's copies onto the target book, positions appended
            # after the target's own; provenance follows its copy untouched.
            collisions: list[str] = []
            copies_reparented = 0
            rows = conn.execute(
                """SELECT s.id AS src_book, s.title, s.author, d.id AS dst_book
                   FROM books s JOIN books d
                     ON d.library_id = ? AND d.book_key = s.book_key
                   WHERE s.library_id = ?""",
                (dst_id, src_id),
            ).fetchall()
            for r in rows:
                base = conn.execute(
                    "SELECT COALESCE(MAX(position), -1) FROM copies "
                    "WHERE book_id = ?", (r["dst_book"],),
                ).fetchone()[0] + 1
                src_copies = conn.execute(
                    "SELECT id FROM copies WHERE book_id = ? "
                    "ORDER BY position, id", (r["src_book"],),
                ).fetchall()
                for offset, copy in enumerate(src_copies):
                    conn.execute(
                        "UPDATE copies SET book_id = ?, library_id = ?, "
                        "position = ? WHERE id = ?",
                        (r["dst_book"], dst_id, base + offset, copy["id"]),
                    )
                    copies_reparented += 1
                conn.execute("DELETE FROM books WHERE id = ?", (r["src_book"],))
                collisions.append(f"{r['title']} / {r['author']}")

            # Everything else re-homes with its id intact.
            books_moved = conn.execute(
                "UPDATE books SET library_id = ? WHERE library_id = ?",
                (dst_id, src_id)).rowcount
            conn.execute(
                "UPDATE copies SET library_id = ? WHERE library_id = ?",
                (dst_id, src_id))
            shelves_labelled = 0
            if label_unnamed_shelves:
                # The location knowledge, surviving as a label until P6.1
                # gives it a Place. Only BLANK labels — a name the owner
                # typed is theirs.
                shelves_labelled = conn.execute(
                    "UPDATE shelves SET label = ? "
                    "WHERE library_id = ? AND label = ''",
                    (label_unnamed_shelves, src_id)).rowcount
            shelves_moved = conn.execute(
                "UPDATE shelves SET library_id = ? WHERE library_id = ?",
                (dst_id, src_id)).rowcount
            captures_moved = conn.execute(
                "UPDATE captures SET library_id = ? WHERE library_id = ?",
                (dst_id, src_id)).rowcount
            reads_moved = conn.execute(
                "UPDATE reads SET library_id = ? WHERE library_id = ?",
                (dst_id, src_id)).rowcount

            # Retire the emptied library. Memberships are untouched on
            # purpose since P3.7b: they belong to the ACCOUNT, which still
            # owns the target — deleting them here would remove people from
            # a customer because one of its libraries was tidied away.
            conn.execute("DELETE FROM libraries WHERE id = ?", (src_id,))

            # The invariant the whole move exists for: nothing left behind —
            # over EVERY library_id table (_LIBRARY_TABLES), so a table the
            # moves above forgot aborts the transaction instead of committing
            # an orphan (review F2's other half).
            for table in _LIBRARY_TABLES:
                left = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE library_id = ?",
                    (src_id,)).fetchone()[0]
                if left:
                    raise MergeRefused(
                        f"{left} {table} rows still name the source — "
                        "aborting the transaction rather than committing a "
                        "half-move"
                    )

        # Only after the commit: the source's bytes are no longer named by
        # any row, so the tree goes. (A crash between commit and here leaves
        # orphaned bytes, which is the blob GC's job — never broken images.)
        blobs_purged = blobs.purge(src_ref)

        return MergeReport(
            books_moved=books_moved,
            copies_reparented=copies_reparented,
            collisions=tuple(collisions),
            shelves_moved=shelves_moved,
            shelves_labelled=shelves_labelled,
            captures_moved=captures_moved,
            reads_moved=reads_moved,
            blobs_copied=blobs_copied,
            blobs_purged=blobs_purged,
        )
    except sqlite3.OperationalError as exc:
        # Almost always "database is locked" past the timeout — a live
        # server writing. The transaction rolled back; nothing moved. Named
        # so the operator can tell it from a crash AFTER the commit, which
        # is the opposite situation (review F8).
        raise MergeRefused(
            f"the database refused the write ({exc}) — a running server is "
            "probably holding it. Nothing was merged; stop the server or "
            "retry in a quiet moment."
        ) from exc
    finally:
        conn.close()
