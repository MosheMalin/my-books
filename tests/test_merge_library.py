# -*- coding: utf-8 -*-
"""The library merge (§4.1's cleanup, P6.1's exit arriving early).

This tool rewrites the owner's REAL database exactly once per mis-modelled
library, which is the profile that justifies the heaviest testing style in
the repo: real temp SQLite files built through the real stores, a real
DiskBlobStore, and assertions that read everything back through the same
adapters the product uses — never through the SQL the tool itself wrote.
"""
from __future__ import annotations

import io
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.adapters.disk_blobs import DiskBlobStore
from app.adapters.merge_library import MergeRefused, merge_library
from app.adapters.sqlite_store import (
    SqliteBookStore,
    SqliteReadStore,
    SqliteShelfStore,
    SqliteTenancyStore,
)
from app.domain import (
    Claim,
    ClaimTier,
    LibraryRef,
    Membership,
    Provenance,
    Role,
    Status,
    User,
    add_copy,
    append_claim,
    finish_read,
    new_account,
    new_book,
    new_capture,
    new_library,
    new_read,
    new_shelf,
)

SRC = LibraryRef(id="lib-parents", label="")
DST = LibraryRef(id="lib-main", label="")


def _png(colour=(120, 40, 40)) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (24, 24), colour).save(out, format="PNG")
    return out.getvalue()


class _World:
    """Two real libraries in one real SQLite file, plus real blobs."""

    def __init__(self, root: Path) -> None:
        self.db = root / "merge.db"
        self.blob_root = root / "blobs"
        self.blobs = DiskBlobStore(self.blob_root)
        self.books = SqliteBookStore(self.db)
        self.shelves = SqliteShelfStore(self.db)
        self.reads = SqliteReadStore(self.db)
        self.tenancy = SqliteTenancyStore(self.db)
        owner = User(id="usr-owner")
        self.tenancy.save_user(owner)
        # Both libraries under ONE account: a merge across customers is
        # refused outright (§4.1), so the only shape this tool has to handle
        # is two collections of the same owner.
        account, membership = new_account(id="acc-owner", owner=owner)
        self.account = account
        self.tenancy.save_account(account)
        self.tenancy.save_membership(membership)
        for ref, label in ((DST, "משפחת מלין"), (SRC, "lib2")):
            self.tenancy.save_library(
                new_library(id=ref.id, label=label, account=account))

    def seed_source_scan(self):
        """One scan's worth in the source: a shelf, a photographed capture,
        a settled read with a cropped claim, and two books — one unique, one
        colliding with the target by key."""
        self.photo = self.blobs.put(SRC, _png((10, 10, 10))).key
        self.crop = self.blobs.put(SRC, _png((20, 20, 20))).key
        shelf = new_shelf(id="sh-par", library_id=SRC.id)
        self.shelves.save_shelf(SRC, shelf)
        capture = new_capture(shelf, id="cap-par", image_id=self.photo)
        self.shelves.save_capture(SRC, capture)
        read = new_read(shelf, [capture], id="rd-par", depth=1, mode="llmpage",
                        started_at="2026-08-09T22:00:00+00:00")
        read = append_claim(read, Claim(
            id="cl-par", spine_id="sp1", capture_id="cap-par",
            title="לימודי רעל", author="מריה וי. סניידר",
            tier=ClaimTier.AUTO, crop_key=self.crop,
        ))
        read = finish_read(read, finished_at="2026-08-09T22:01:00+00:00")
        self.reads.save_read(SRC, read)

        # The colliding work: same title/author as a target book, its copy
        # standing at the source's shelf with real provenance and a status a
        # human granted.
        self.books.save(SRC, new_book(
            id="b-src-poison", library_id=SRC.id, title="לימודי רעל",
            author="מריה וי. סניידר", copy_id="c-src-poison",
            status=Status.APPROVED, shelf_id="sh-par", depth=1,
            provenance=(Provenance(run_id="rd-par", spine_id="sp1",
                                   shelf_id="sh-par", depth=1,
                                   captured_at="2026-08-09T22:01:00+00:00"),),
            added_at="2026-08-09T22:01:00+00:00",
        ))
        # The unique one.
        self.books.save(SRC, new_book(
            id="b-src-unique", library_id=SRC.id, title="ספר שאין בבית",
            author="סופר אלמוני", copy_id="c-src-unique",
            added_at="2026-08-09T22:01:00+00:00",
        ))

    def seed_target(self):
        self.books.save(DST, new_book(
            id="b-dst-poison", library_id=DST.id, title="לימודי רעל",
            author="מריה וי. סניידר", copy_id="c-dst-poison",
            status=Status.MANUAL, added_at="2026-01-01T00:00:00+00:00",
        ))
        self.books.save(DST, new_book(
            id="b-dst-other", library_id=DST.id, title="היער השיכור",
            author="ג'ראלד דארל", copy_id="c-dst-other",
            added_at="2026-01-01T00:00:00+00:00",
        ))


def _world():
    tmp = Path(tempfile.mkdtemp(prefix="booksnap-merge-"))
    w = _World(tmp)
    w.seed_target()
    w.seed_source_scan()
    return w, tmp


def _merge(w: _World, **kw):
    return merge_library(w.db, SRC.id, DST.id, w.blobs, **kw)


def test_a_unique_book_moves_whole_and_disappears_from_the_source():
    w, tmp = _world()
    try:
        report = _merge(w)
        assert report.books_moved == 1
        moved = w.books.get(DST, "b-src-unique")
        assert moved is not None and moved.title == "ספר שאין בבית"
        assert moved.library_id == DST.id
        assert w.books.get(SRC, "b-src-unique") is None
        assert w.books.count(DST) == 3          # 2 seeded + 1 moved
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_colliding_work_becomes_another_copy_of_the_book_already_owned():
    """The physical truth: the camera saw a real copy standing at the
    source's shelf. It re-parents — id, status, provenance and location
    intact — onto the book the target already has; no second book row."""
    w, tmp = _world()
    try:
        report = _merge(w)
        assert report.copies_reparented == 1
        assert any("לימודי רעל" in c for c in report.collisions)
        book = w.books.get(DST, "b-dst-poison")
        assert len(book.copies) == 2
        moved = next(c for c in book.copies if c.id == "c-src-poison")
        assert moved.status is Status.APPROVED, "the copy's own status lost"
        assert moved.shelf_id == "sh-par" and moved.depth == 1
        assert [p.sighting for p in moved.provenance] == [("rd-par", "sp1")], \
            "provenance did not follow its copy"
        # `position` is a storage column, not a domain field — read it back
        # through SQL, because two copies sharing one position would order
        # ambiguously forever.
        with sqlite3.connect(str(w.db)) as conn:
            positions = [r[0] for r in conn.execute(
                "SELECT position FROM copies WHERE book_id = 'b-dst-poison'")]
        assert len(set(positions)) == len(positions), "positions collided"
        assert w.books.get(SRC, "b-src-poison") is None
        assert w.books.get(DST, "b-src-poison") is None, \
            "the redundant book row survived"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_scan_moves_with_its_identity_and_its_photos():
    """Shelf, capture, read and claim keep their ids — a merge re-homes, it
    never re-mints — and both the shelf photo and the spine crop are
    readable in the TARGET afterwards while the source tree is gone."""
    w, tmp = _world()
    try:
        _merge(w)
        shelf = w.shelves.get_shelf(DST, "sh-par")
        assert shelf is not None
        captures = w.shelves.list_captures(DST, "sh-par")
        assert [c.id for c in captures] == ["cap-par"]
        assert captures[0].image_id == w.photo
        read = w.reads.get_read(DST, "rd-par")
        assert read is not None and read.shelf_id == "sh-par"
        assert [cl.id for cl in read.claims] == ["cl-par"]
        assert read.claims[0].crop_key == w.crop

        assert w.blobs.read(DST, w.photo) is not None
        assert w.blobs.read(DST, w.crop) is not None
        assert w.blobs.list_keys(SRC) == (), "the source tree survived"
        assert w.shelves.get_shelf(SRC, "sh-par") is None
        assert w.reads.get_read(SRC, "rd-par") is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_an_unnamed_shelf_gains_the_location_label_and_a_named_one_keeps_its_own():
    """Until P6.1 gives locations their Place, the label is where "these
    shelves stand at the parents'" survives the merge. Only BLANK labels —
    a name the owner typed is theirs."""
    w, tmp = _world()
    try:
        named = new_shelf(id="sh-named", library_id=SRC.id, label="ספרים ישנים")
        w.shelves.save_shelf(SRC, named)
        report = _merge(w, label_unnamed_shelves="אצל ההורים")
        assert report.shelves_labelled == 1
        assert w.shelves.get_shelf(DST, "sh-par").label == "אצל ההורים"
        assert w.shelves.get_shelf(DST, "sh-named").label == "ספרים ישנים"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)



def test_the_source_drawing_moves_and_stands_beside_the_targets():
    """P6.1's five map tables joined `_LIBRARY_TABLES`, so the merge has to
    move them — the leftover check aborts the whole transaction otherwise, and
    a table moved but missing from that tuple commits an orphan instead.

    Nothing is merged GEOMETRICALLY: both houses start at 0,0, so laying one
    out beside the other would move furniture the owner placed. The parents'
    site simply arrives next to this one, which is one visible rename away
    from being right and zero taps away from being honest.
    """
    from dataclasses import replace

    from app.adapters.sqlite_store import SqliteMapStore
    from app.domain import (Rect, ShelfAddress, new_bookcase, new_floor,
                            new_place, new_section, new_site)

    w, tmp = _world()
    try:
        maps = SqliteMapStore(w.db)
        maps.save_site(DST, new_site(id="st-home", library_id=DST.id,
                                     name="הבית"))
        maps.save_site(SRC, new_site(id="st-par", library_id=SRC.id,
                                     name="אצל ההורים"))
        maps.save_floor(SRC, new_floor(id="fl-par", library_id=SRC.id,
                                       site_id="st-par", name="קרקע"))
        maps.save_place(SRC, new_place(id="pl-par", library_id=SRC.id,
                                       floor_id="fl-par",
                                       rect=Rect(0, 0, 11, 9), name="סלון"))
        maps.save_bookcase(SRC, new_bookcase(id="bc-par", library_id=SRC.id,
                                             floor_id="fl-par",
                                             rect=Rect(1, 0, 4, 1),
                                             place_id="pl-par"))
        maps.save_section(SRC, new_section(id="se-par", library_id=SRC.id,
                                           bookcase_id="bc-par", columns=1,
                                           default_levels=2))
        # …with the source's real shelf standing in one of its slots, so the
        # address has to survive the move as well as the row does.
        moved_in = w.shelves.get_shelf(SRC, "sh-par")
        w.shelves.save_shelf(SRC, replace(
            moved_in, address=ShelfAddress("se-par", 1, 1)))

        _merge(w)

        after = maps.load_map(DST)
        assert {s.name for s in after.sites} == {"הבית", "אצל ההורים"}
        assert [p.rect for p in after.places] == [Rect(0, 0, 11, 9)], (
            "the parents' room was relocated by the merge"
        )
        assert after.bookcases[0].place_id == "pl-par"
        assert after.sections[0].column_levels == (2,)
        assert maps.load_map(SRC).is_empty, "the source kept its drawing"
        carried = w.shelves.get_shelf(DST, "sh-par")
        assert carried.address == ShelfAddress("se-par", 1, 1)
        assert w.shelves.get_shelf_at(
            DST, ShelfAddress("se-par", 1, 1)).id == "sh-par"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_source_shelf_aliases_move_with_their_shelves():
    """P6.4a. The opposite call from the undo journal below, and the reason is
    the merge's own guarantee: shelves and sections re-home with their **ids
    intact**, so *"A resolves to B, and A used to be at section X"* is as true
    after the move as before — and it is still the only answer to where A
    went. Dropping them would lose that with nothing able to notice, since
    four of the six tables naming a shelf have no foreign key.
    """
    from app.adapters.sqlite_store import SqliteShelfStore
    from app.domain.alias import ShelfAlias, resolve

    w, tmp = _world()
    try:
        shelves = SqliteShelfStore(w.db)
        shelves.save_shelf(SRC, new_shelf(id="sh-gone", library_id=SRC.id))
        shelves.save_alias(SRC, ShelfAlias(
            alias_id="sh-gone", library_id=SRC.id, shelf_id="sh-par",
            address=None, label="מהתמונה",
            merged_at="2026-08-25T10:00:00+00:00"))

        _merge(w)

        assert shelves.list_aliases(SRC) == (), "an alias stayed behind"
        moved = shelves.list_aliases(DST)
        assert [a.alias_id for a in moved] == ["sh-gone"]
        assert moved[0].label == "מהתמונה"
        assert resolve("sh-gone", moved) == "sh-par", (
            "the alias moved but no longer resolves")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_source_undo_journal_is_dropped_rather_than_re_homed():
    """P6.4b, and the one library-scoped table the merge DELETES.

    Two independent reasons, either fatal alone: an entry's ``inverse`` holds
    whole rows with the SOURCE ``library_id`` baked into each, so replaying a
    re-homed entry writes rows the stores refuse outright; and its fingerprint
    was taken in a world the merge has since rearranged, which is the state
    §3.15 says an undo must refuse rather than guess its way through.

    So: the source's entries are GONE, not moved — and the target's own undo
    is untouched, because a merge is something that happened to the source,
    not to the collection absorbing it.
    """
    from app.adapters.sqlite_store import SqliteMapUndoStore
    from app.domain.map_undo import MapRestore, MapUndoEntry

    w, tmp = _world()
    try:
        journal = SqliteMapUndoStore(w.db)
        source_shelf = w.shelves.get_shelf(SRC, "sh-par")
        assert source_shelf is not None, "fixture has no sh-par"
        for lib, entry_id in ((SRC, "u-src"), (DST, "u-dst")):
            # Both entries remember the SAME shelf row, which is the point:
            # what decides their fate is whose journal they are in, not what
            # they happen to name.
            journal.record(lib, MapUndoEntry(
                id=entry_id, library_id=lib.id, kind="clear_bookcase",
                tag="bookcase:bc", recorded_at="2026-08-24T09:00:00Z",
                restore=MapRestore(shelves=(source_shelf,)), fingerprint={},
            ))

        _merge(w)

        assert journal.recent(SRC, limit=9) == (), (
            "the source's undo entries survived the merge")
        assert [e.id for e in journal.recent(DST, limit=9)] == ["u-dst"], (
            "the merge re-homed the source's journal into the target, where "
            "replaying it would write rows naming a library that is gone")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_every_library_scoped_table_is_in_the_leftover_check():
    """The tuple and the move loop must not drift apart, and only ONE
    direction was loud.

    Dropping a table from the MOVE aborts the merge — that half works. But
    dropping it from `_LIBRARY_TABLES` while still moving it is silent, and
    that is the direction that matters next time somebody adds a table:
    the leftover check is the thing that catches a move nobody wrote.

    So compare the tuple against the schema itself. Every table with a
    `library_id` column has to be in it, and a new one fails here rather than
    in six months as an orphan on the owner's own file.
    """
    from app.adapters.merge_library import _LIBRARY_TABLES

    w, tmp = _world()
    try:
        conn = sqlite3.connect(str(w.db))
        try:
            scoped = set()
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ):
                columns = {r[1] for r in conn.execute(
                    f"PRAGMA table_info({name})")}
                if "library_id" in columns:
                    scoped.add(name)
        finally:
            conn.close()
        assert scoped == set(_LIBRARY_TABLES), (
            f"_LIBRARY_TABLES disagrees with the schema — missing "
            f"{sorted(scoped - set(_LIBRARY_TABLES))}, stale "
            f"{sorted(set(_LIBRARY_TABLES) - scoped)}"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_two_libraries_of_different_customers_are_never_merged():
    """§4.1's boundary, over the most destructive tool in the product.

    This tool exists to undo a location that was modelled as a tenant before
    Place existed — and a location does not change owner. Merging across
    accounts would hand every book, photo and read in one collection to people
    who were never invited, performed by an operator with a --confirm flag.
    The guard was enforced by comment only until P3.7b's data-integrity review
    deleted it and watched the whole ring stay green.
    """
    w, tmp = _world()
    try:
        # A third library, under a SECOND customer.
        other, membership = new_account(id="acc-other",
                                        owner=User(id="usr-other"))
        w.tenancy.save_user(User(id="usr-other"))
        w.tenancy.save_account(other)
        w.tenancy.save_membership(membership)
        w.tenancy.save_library(
            new_library(id="lib-theirs", label="שלהם", account=other))
        w.seed_source_scan()
        before = w.books.count(SRC)

        try:
            merge_library(w.db, src_id=SRC.id, dst_id="lib-theirs",
                          blobs=w.blobs)
        except MergeRefused as exc:
            assert "different accounts" in str(exc), exc
        else:
            raise AssertionError("a merge across customers was allowed")

        # Untouched on both sides: a refusal writes nothing.
        assert w.books.count(SRC) == before
        assert w.tenancy.get_library(SRC.id) is not None
        assert w.tenancy.get_library("lib-theirs") is not None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def test_the_source_tenant_is_retired_and_the_target_untouched():
    w, tmp = _world()
    try:
        _merge(w)
        assert w.tenancy.get_library(SRC.id) is None
        assert w.tenancy.get_library(DST.id) is not None
        # ⚠ The MEMBERSHIP survives, and that is the P3.7b change: it names
        # the account, which still owns the target. Deleting it here would
        # remove a person from a customer because one of its libraries was
        # tidied away — the merge retires a collection, never a grant.
        assert w.tenancy.membership("usr-owner", "acc-owner") is not None
        listed = [lib.id for lib in w.tenancy.list_libraries("acc-owner")]
        assert listed == [DST.id], "the switcher would still offer the ghost"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_source_with_recorded_human_answers_is_refused_untouched():
    """A standing decision or an open question is a HUMAN's answer scoped to
    its library; re-scoping it silently is refused, and refusal means
    nothing moved — not a half-merge."""
    w, tmp = _world()
    try:
        with sqlite3.connect(str(w.db)) as conn:
            conn.execute(
                "INSERT INTO decisions "
                "(library_id, shelf_id, depth, book_key, kind, decided_at) "
                "VALUES (?, 'sh-par', 1, 'k', 'rejected', '2026-08-09')",
                (SRC.id,))
        try:
            _merge(w)
            raise AssertionError("a source with decisions merged anyway")
        except MergeRefused:
            pass
        assert w.books.get(SRC, "b-src-unique") is not None, "a refusal wrote"
        assert w.tenancy.get_library(SRC.id) is not None
        assert w.blobs.read(SRC, w.photo) is not None, \
            "a refusal purged the source's photos"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_an_abort_after_the_blob_copy_leaves_the_source_photos_alive():
    """The file's central safety claim, exercised end to end (review F1): a
    transaction that aborts AFTER the photos were copied must leave the
    source tree intact — every key a source row names still resolves. The
    concurrent writer is simulated by a blob store whose listing plants a
    decision row mid-copy, exactly what a live server's DELETE /books does;
    the IN-TRANSACTION re-check must catch it (review F2). Mutations this
    kills: purging the source before the commit, and dropping the
    re-check (the widened leftover list then aborts on the orphan)."""
    w, tmp = _world()
    try:
        class WriterDuringCopy:
            """Delegates to the real store; the listing is the copy loop's
            first call, so it is the moment 'during the copy' starts."""

            def __init__(self, inner, db):
                self._inner, self._db, self._planted = inner, db, False

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def list_keys(self, library):
                if not self._planted:
                    self._planted = True
                    with sqlite3.connect(str(self._db)) as conn:
                        conn.execute(
                            "INSERT INTO decisions (library_id, shelf_id, "
                            "depth, book_key, kind, decided_at) VALUES "
                            "(?, 'sh-par', 1, 'k', 'rejected', '2026-08-10')",
                            (SRC.id,))
                return self._inner.list_keys(library)

        try:
            merge_library(w.db, SRC.id, DST.id,
                          WriterDuringCopy(w.blobs, w.db))
            raise AssertionError("a decision written mid-copy was orphaned")
        except MergeRefused:
            pass
        assert w.blobs.read(SRC, w.photo) is not None, \
            "an aborted merge lost the source's photos"
        assert w.blobs.read(SRC, w.crop) is not None
        assert w.books.get(SRC, "b-src-unique") is not None, "rows half-moved"
        assert w.tenancy.get_library(SRC.id) is not None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_torn_destination_photo_refuses_the_merge_before_any_row_moves():
    """`put` trusts an existing path (dedup) — so a torn file already at the
    destination would be 'copied', committed over, and the only good copy
    purged (review F5). The hash-back verification refuses instead."""
    w, tmp = _world()
    try:
        stem, _, ext = w.crop.partition(".")
        torn = (w.blob_root / "libraries" / DST.id / "blobs" / stem[:2]
                / f"{stem}.{ext}")
        torn.parent.mkdir(parents=True, exist_ok=True)
        torn.write_bytes(b"\xff\xd8\x00")   # 3 bytes of a JPEG that is not one
        try:
            _merge(w)
            raise AssertionError("a torn destination photo was trusted")
        except MergeRefused as exc:
            assert w.crop in str(exc)
        assert w.blobs.read(SRC, w.crop) is not None, "the good copy was lost"
        assert w.books.get(SRC, "b-src-unique") is not None, "rows moved anyway"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_colliding_book_carrying_a_rating_or_note_is_refused():
    """The colliding source ROW is deleted after its copies re-parent — a
    rating or note on it would vanish silently (review F6). Which side wins
    is a human question, so the tool refuses to answer it."""
    w, tmp = _world()
    try:
        with sqlite3.connect(str(w.db)) as conn:
            conn.execute("UPDATE books SET rating = 5 WHERE id = ?",
                         ("b-src-poison",))
        try:
            _merge(w)
            raise AssertionError("a rated colliding book was discarded")
        except MergeRefused as exc:
            assert "לימודי רעל" in str(exc)
        assert w.books.get(SRC, "b-src-poison") is not None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_nonsense_inputs_are_refused_before_anything_happens():
    w, tmp = _world()
    try:
        for src, dst in ((SRC.id, SRC.id), ("lib-ghost", DST.id),
                         (SRC.id, "lib-ghost")):
            try:
                merge_library(w.db, src, dst, w.blobs)
                raise AssertionError(f"merged {src} -> {dst}")
            except MergeRefused:
                pass
        assert w.books.count(SRC) == 2 and w.books.count(DST) == 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_lending_rides_with_a_reparented_copy():
    """The colliding copy might be LENT OUT — the lending state and the
    materialized lent_out flag both belong to the copy and must survive the
    re-parenting, or "who has my books" forgets an outstanding loan."""
    from app.domain import lend

    w, tmp = _world()
    try:
        book = w.books.get(SRC, "b-src-poison")
        book = lend(book, "c-src-poison", lent_to="דנה",
                    lent_at="2026-08-09T23:00:00+00:00")
        w.books.save(SRC, book)
        _merge(w)
        merged = w.books.get(DST, "b-dst-poison")
        moved = next(c for c in merged.copies if c.id == "c-src-poison")
        assert moved.lending and moved.lending.is_out
        assert moved.lending.lent_to == "דנה"
        page = w.books.list(DST, lent_out=True)
        assert [b.id for b in page.items] == ["b-dst-poison"], \
            "the lent_out flag was lost in the move"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))
