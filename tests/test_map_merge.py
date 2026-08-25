# -*- coding: utf-8 -*-
"""The merge (P6.4d, MAP_PLAN §3.11-§3.13).

One test per reversible sentence, in the shape ``test_domain.py`` uses — not
coverage of the module. The sentences this file holds in place:

  - **a row that governs a future write moves; a row that records a past
    event stays** (§3.13). Six tables, one sentence, and ``decisions`` is the
    load-bearing one;
  - **depth numbers are never remapped** and the survivor only ever DEEPENS
    (§3.12);
  - **the strip order is declared, never inferred** (§3.12);
  - **the absorbed identity survives as an alias, of its id AND its address**
    (§3.11), and nothing is rewritten;
  - **a merge is undoable** (§3.15) — the inverse is the rows as they stood,
    and the census proves it lost nothing.

Each is mutation-checked: reverse the rule, watch the named test fail.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.memory_store import (  # noqa: E402
    MemoryBookStore,
    MemoryDecisionStore,
    MemoryDuplicateQueue,
    MemoryMapStore,
    MemoryMapUndoStore,
    MemoryReadStore,
    MemoryShelfStore,
)
from app.domain import (  # noqa: E402
    Decision,
    DecisionKind,
    DuplicateQuestion,
    LibraryRef,
    MergeRefused,
    Rect,
    ShelfAddress,
    StripOrder,
    add_copy,
    new_book,
    new_bookcase,
    new_capture,
    new_floor,
    new_place,
    new_read,
    new_shelf,
    new_site,
)
from app.domain.alias import identities, resolve, resolve_address  # noqa: E402
from app.map_edit import draw_bookcase  # noqa: E402
from app.map_merge import Shelves, merge, preview  # noqa: E402
from app.map_undo import Journal, offer, undo  # noqa: E402

LIB = LibraryRef("lib-1", "הבית")


class StubClock:
    def __init__(self, start: int = 0) -> None:
        self._n = start

    def now_iso(self) -> str:
        self._n += 1
        return f"2026-08-26T10:{self._n:02d}:00+00:00"


class SeqIdGen:
    def __init__(self, prefix: str = "id") -> None:
        self._n = 0
        self._prefix = prefix

    def new_id(self) -> str:
        self._n += 1
        return f"{self._prefix}-{self._n}"


def _world():
    shelves = MemoryShelfStore()
    maps = MemoryMapStore()
    books = MemoryBookStore()
    maps.bind_shelves(shelves)
    shelves.bind_map(maps)
    shelves.bind_books(books)
    maps.save_site(LIB, new_site(id="st", library_id=LIB.id, name="הבית"))
    maps.save_floor(LIB, new_floor(id="fl", library_id=LIB.id, site_id="st",
                                   name="קרקע"))
    maps.save_place(LIB, new_place(id="pl", library_id=LIB.id, floor_id="fl",
                                   rect=Rect(0, 0, 12, 9), name="סלון"))
    ports = Shelves(map_store=maps, shelves=shelves, books=books,
                    reads=MemoryReadStore(), decisions=MemoryDecisionStore(),
                    duplicates=MemoryDuplicateQueue())
    journal = Journal(store=MemoryMapUndoStore(), ids=SeqIdGen("u"),
                      clock=StubClock(), books=books,
                      decisions=ports.decisions, duplicates=ports.duplicates)
    return ports, journal


def _drawn(ports, *, columns=1, levels=1, depth=1):
    """A bookcase, and the addressed shelves it was born with (§3.1).

    ``DrawnCase.shelves`` is a COUNT, not a list — ten new empty shelves are
    one bookcase, not ten things a screen lists — so the rows come back from
    the section they were addressed to.
    """
    case = new_bookcase(id="bc", library_id=LIB.id, floor_id="fl",
                        rect=Rect(0, 0, 4, 1), place_id="pl")
    drawn = draw_bookcase(ports.map_store, ports.shelves, LIB, case,
                          ids=SeqIdGen("d"), clock=StubClock(),
                          columns=columns, levels=levels, depth=depth)
    made = ports.shelves.list_shelves_in_section(LIB, drawn.sections[0].id)
    return _Drawn(sections=drawn.sections,
                  shelves=tuple(sorted(made, key=lambda s: (
                      s.address.col, s.address.level))))


class _Drawn:
    def __init__(self, sections, shelves):
        self.sections = sections
        self.shelves = shelves


def _photo_born(ports, *, id="ph", label="ספרי בישול", depth_count=1,
                address=None):
    shelf = new_shelf(id=id, library_id=LIB.id, label=label,
                      depth_count=depth_count, created_at="2026-01-01T00:00:00Z",
                      address=address)
    ports.shelves.save_shelf(LIB, shelf)
    return shelf


def _book(ports, *, id, title, shelf_id, depth=1, copy_id=None):
    book = new_book(id=id, library_id=LIB.id, title=title, author="עגנון",
                    copy_id=copy_id or f"c-{id}", shelf_id=shelf_id,
                    depth=depth)
    ports.books.save(LIB, book)
    return book


def _photo(ports, shelf, *, id, depth=1, order=0):
    capture = new_capture(shelf, id=id, depth=depth, order=order,
                          image_id=f"img-{id}")
    ports.shelves.save_capture(LIB, capture)
    return capture


def _merge(ports, journal, absorbed, survivor,
           strip=StripOrder.SURVIVOR_FIRST):
    return merge(ports, LIB, absorbed, survivor, strip=strip,
                 journal=journal, clock=StubClock(40))


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"expected {exc.__name__}, nothing raised")


# --- the census, which is what proves a merge lost nothing ----------------

def census(ports):
    """Digest the whole library, for comparison across a merge.

    §3.11's argument in executable form. Four of the six tables that name a
    shelf have no foreign key, so ``PRAGMA foreign_key_check`` reports a clean
    file over a library whose locations have silently moved — this is the
    check no constraint can perform, and the one that catches the real bug.

    ⚠ **The last line is the point.** *Zero rows naming a shelf id that is
    neither a live shelf nor an alias.* Everything above it can be true of a
    library that has quietly lost half its locations.
    """
    live = {s.id for s in ports.shelves.list_shelves(LIB, include_virtual=True)}
    aliases = ports.shelves.list_aliases(LIB)
    known = live | {a.alias_id for a in aliases}
    books = ports.books.list(LIB, limit=999).items
    copies = [(b.id, c) for b in books for c in b.copies]
    photos = [c for shelf_id in known
              for c in ports.shelves.list_captures(LIB, shelf_id)]
    named = [c.shelf_id for _, c in copies if c.shelf_id] + \
            [c.shelf_id for c in photos] + \
            [a.shelf_id for a in aliases]
    return {
        "books": len(books),
        "copies": len(copies),
        "located": len([c for _, c in copies if c.shelf_id]),
        "at": sorted((resolve(c.shelf_id, aliases), c.depth)
                     for _, c in copies if c.shelf_id),
        "photos": sorted((resolve(c.shelf_id, aliases), c.depth, c.image_id)
                         for c in photos),
        "photo_slots": sorted(c.slot for c in photos),
        "provenance": sorted(
            (b.id, c.id, p.sighting) for b in books for c in b.copies
            for p in c.provenance),
        "orphans": sorted(s for s in named if s not in known),
    }


# --- §3.13: what moves with the wood --------------------------------------

def test_the_books_move_with_the_wood_and_keep_their_depth():
    """`copies` moves — it is where the book IS — and §3.12 forbids
    renumbering: depth 2 of the absorbed shelf is depth 2 of the survivor,
    because renumbering would move books without moving books."""
    ports, journal = _world()
    drawn = _drawn(ports, levels=1, depth=2)
    survivor = drawn.shelves[0]
    absorbed = _photo_born(ports, depth_count=2)
    _book(ports, id="b1", title="תמול שלשום", shelf_id=absorbed.id, depth=2)
    _book(ports, id="b2", title="סיפור פשוט", shelf_id=absorbed.id, depth=1)

    _merge(ports, journal, absorbed, survivor)

    moved = {b.id: b.copies[0] for b in
             ports.books.books_on_shelf(LIB, (survivor.id,))}
    assert set(moved) == {"b1", "b2"}
    assert moved["b1"].shelf_id == survivor.id and moved["b1"].depth == 2, (
        "depth 2 of the absorbed shelf must be depth 2 of the survivor")
    assert moved["b2"].depth == 1


def test_a_merge_records_no_sighting():
    """§3.16 from the other side: a merge may not manufacture evidence.

    The wood was re-identified; the book did not move, was not seen, and
    nothing new is known about it. `provenance` is append-only evidence (§5.2)
    and the not-seen streak, the staleness badge and every §5.6 answer are
    computed from exactly that evidence — so one row added here is a lie every
    one of them repeats.
    """
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    _book(ports, id="b1", title="תמול שלשום", shelf_id=absorbed.id)
    before = census(ports)["provenance"]

    _merge(ports, journal, absorbed, survivor)

    assert census(ports)["provenance"] == before, (
        "the merge wrote provenance — a run id and a spine id on a row no run "
        "produced")


def test_the_photographs_move_and_the_strip_order_is_declared():
    """§3.12: appending the absorbed shelf's photographs after the survivor's
    encodes a claim — *its half is to the right* — that nothing measured. So
    the caller says which, and both answers are honoured."""
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    _photo(ports, survivor, id="s0", order=0)
    _photo(ports, survivor, id="s1", order=1)
    _photo(ports, absorbed, id="a0", order=0)

    _merge(ports, journal, absorbed, survivor, StripOrder.ABSORBED_FIRST)

    strip = sorted(ports.shelves.list_captures(LIB, survivor.id),
                   key=lambda c: c.order)
    assert [c.id for c in strip] == ["a0", "s0", "s1"], (
        "ABSORBED_FIRST put the absorbed shelf's half second")
    assert [c.order for c in strip] == [0, 1, 2], (
        "the merged strip is not densely ordered, so a re-read's dedup has "
        "two photographs claiming one position")


def test_the_survivors_strip_stays_put_when_it_comes_first():
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    _photo(ports, survivor, id="s0", order=0)
    _photo(ports, absorbed, id="a0", order=0)
    _photo(ports, absorbed, id="a1", order=1)

    _merge(ports, journal, absorbed, survivor, StripOrder.SURVIVOR_FIRST)

    strip = sorted(ports.shelves.list_captures(LIB, survivor.id),
                   key=lambda c: c.order)
    assert [c.id for c in strip] == ["s0", "a0", "a1"]


def test_the_rejections_move_or_the_next_read_re_adds_every_phantom():
    """§3.13's load-bearing row.

    §5.6's rule is *"a book the user previously rejected here is not
    re-added"*, and *here* is `(library, shelf, depth, book_key)`. Leave the
    absorbed shelf's rejections behind and the next read of the merged shelf
    re-adds every phantom the owner ever rejected on that wood — no row
    deleted, no key violated, nothing looking wrong.
    """
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    ports.decisions.save_decision(LIB, Decision(
        library_id=LIB.id, shelf_id=absorbed.id, depth=1,
        book_key="עגנון|רוח רפאים", kind=DecisionKind.REJECTED,
        decided_at="2026-02-01T00:00:00Z"))

    _merge(ports, journal, absorbed, survivor)

    standing = ports.decisions.list_decisions(LIB, survivor.id, 1)
    assert [d.book_key for d in standing] == ["עגנון|רוח רפאים"], (
        "the rejection stayed on wood that no longer exists")
    assert ports.decisions.list_decisions(LIB, absorbed.id, 1) == ()


def test_a_clash_of_answers_is_won_by_the_newer_and_named_in_the_preview():
    """The collision `merge_library.py` met and REFUSED rather than choose.

    Here it is chosen — by the rule the table's own upsert already applies to
    a person changing their mind — and every one is NAMED, because what is
    being overwritten is a different answer given at a different place.
    """
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    for shelf_id, kind, when in (
        (survivor.id, DecisionKind.ALREADY_LISTED, "2026-01-01T00:00:00Z"),
        (absorbed.id, DecisionKind.WRONG_BOOK, "2026-03-01T00:00:00Z"),
    ):
        ports.decisions.save_decision(LIB, Decision(
            library_id=LIB.id, shelf_id=shelf_id, depth=1,
            book_key="עגנון|תמול שלשום", kind=kind, decided_at=when))

    seen = preview(ports, LIB, absorbed, survivor,
                   strip=StripOrder.SURVIVOR_FIRST)
    assert [(c.book_key, c.winner) for c in seen.clashes] == [
        ("עגנון|תמול שלשום", "absorbed")]
    assert seen.clashes[0].survivor_kind == "already_listed"

    _merge(ports, journal, absorbed, survivor)
    won = ports.decisions.get_decision(LIB, survivor.id, 1, "עגנון|תמול שלשום")
    assert won.kind is DecisionKind.WRONG_BOOK, "the older answer won"


def test_a_question_whose_key_becomes_answered_is_closed_not_carried():
    """A question is open UNTIL a decision exists at the same key.

    ⚠ Move the absorbed shelf's decision onto a key where the survivor has an
    open question and the pair would coexist — a state nothing else in the
    system produces, and one the Books tab renders as an unanswered ask that
    can never be answered again.
    """
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    ports.duplicates.save_question(LIB, DuplicateQuestion(
        id="q1", library_id=LIB.id, shelf_id=survivor.id, depth=1,
        book_key="עגנון|תמול שלשום", read_id="r", spine_id="s",
        claim_title="תמול שלשום", claim_author="עגנון",
        existing_book_id="b1", opened_at="2026-01-01T00:00:00Z"))
    ports.decisions.save_decision(LIB, Decision(
        library_id=LIB.id, shelf_id=absorbed.id, depth=1,
        book_key="עגנון|תמול שלשום", kind=DecisionKind.ANOTHER_COPY,
        decided_at="2026-03-01T00:00:00Z"))

    _merge(ports, journal, absorbed, survivor)

    assert ports.duplicates.list_open_questions(LIB, shelf_id=survivor.id) == (
        ()), "a question stands open at a key that is now answered"


# --- §3.11: the alias, and nothing rewritten ------------------------------

def test_the_absorbed_identity_survives_as_an_alias_of_id_and_address():
    """§3.11: *"the shelf that was at section 1, column 2, level 3"* is a
    question the library can still answer after the wood has been
    re-identified — because the address is what a person reads off a
    drawing, and it is the half that survives in someone's memory when the id
    does not."""
    ports, journal = _world()
    drawn = _drawn(ports, columns=2)
    survivor, other = drawn.shelves[0], drawn.shelves[1]
    where = other.address
    # A slot holds one shelf (§3.1), so the drawn one steps aside first: what
    # this test is about is a shelf that STOOD somewhere being absorbed.
    ports.shelves.delete_shelf(LIB, other.id)
    absorbed = _photo_born(ports, label="ספרי בישול", address=where)

    _merge(ports, journal, absorbed, survivor)

    aliases = ports.shelves.list_aliases(LIB)
    assert resolve(absorbed.id, aliases) == survivor.id
    assert resolve_address(where, aliases) == survivor.id, (
        "the former SLOT no longer resolves — the half §3.11 records rather "
        "than derives")
    assert aliases[0].label == "ספרי בישול", (
        "the household's name for the shelf was destroyed by the merge")
    assert ports.shelves.get_shelf(LIB, absorbed.id) is None


def test_an_identity_that_already_answered_is_re_pointed_in_the_same_step():
    """P6.4a's named trap: merging a shelf that has itself absorbed one is
    refused by the one-hop rule, so the re-point must happen inside the same
    transaction — otherwise every book that arrived with that identity is
    unreachable the moment the shelf it names is deleted."""
    ports, journal = _world()
    drawn = _drawn(ports, columns=2)
    first, second = drawn.shelves[0], drawn.shelves[1]
    oldest = _photo_born(ports, id="ph-0", label="הראשון")
    middle = _photo_born(ports, id="ph-1", label="האמצעי")
    _book(ports, id="b1", title="בית", shelf_id=oldest.id)

    _merge(ports, journal, oldest, middle)
    ports2 = ports
    middle = ports2.shelves.get_shelf(LIB, middle.id)
    _merge(ports, journal, middle, first)

    aliases = ports.shelves.list_aliases(LIB)
    assert set(identities(first.id, aliases)) == {first.id, oldest.id,
                                                  middle.id}, (
        "an identity fell out of the closure, so every book that arrived "
        "with it is unreachable from the only shelf still standing")
    assert [b.id for b in ports.books.books_on_shelf(
        LIB, identities(first.id, aliases))] == ["b1"]
    assert census(ports)["orphans"] == [], census(ports)["orphans"]
    assert second is not None


# --- §3.12: the ladder ----------------------------------------------------

def test_the_survivor_deepens_and_never_shallows():
    """§3.12's ladder. The survivor's `depth_count` is often a creation-time
    default copied from its section (§3.3) that nobody looked at; the absorbed
    shelf's is a human answer to *"add a row behind this one"* — the one thing
    §5.7 says cannot be detected."""
    ports, journal = _world()
    survivor = _drawn(ports, depth=1).shelves[0]
    absorbed = _photo_born(ports, depth_count=3)

    out = _merge(ports, journal, absorbed, survivor)

    assert out.survivor.depth_count == 3, (
        "the survivor kept a default nobody looked at, un-declaring a row of "
        "books the owner declared by hand")


def test_a_deeper_survivor_is_not_shallowed_by_a_flat_absorbed_shelf():
    ports, journal = _world()
    survivor = _drawn(ports, depth=4).shelves[0]
    absorbed = _photo_born(ports, depth_count=1)
    out = _merge(ports, journal, absorbed, survivor)
    assert out.survivor.depth_count == 4


# --- the refusals ---------------------------------------------------------

def test_a_shelf_cannot_be_merged_into_itself():
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    exc = _raises(MergeRefused, _merge, ports, journal, survivor, survivor)
    assert exc.reason == "same_shelf"


def test_the_wishlist_is_not_a_shelf_and_is_refused_either_way():
    """§5.7: it stands nowhere. Merging into or out of it would give unowned
    books a location that exists."""
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    wishlist = new_shelf(id="wish", library_id=LIB.id, virtual=True)
    ports.shelves.save_shelf(LIB, wishlist)
    assert _raises(MergeRefused, _merge, ports, journal,
                   wishlist, survivor).reason == "wishlist"
    assert _raises(MergeRefused, _merge, ports, journal,
                   survivor, wishlist).reason == "wishlist"


def test_a_merge_is_refused_while_a_read_of_either_identity_is_running():
    """§3.11, and the reason is not tidiness: a running read's diff will be
    applied against a shelf that is about to stop existing."""
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    shot = _photo(ports, absorbed, id="a0", order=0)
    ports.reads.save_read(LIB, new_read(
        absorbed, (shot,), id="r1", depth=1, mode="llmpage",
        started_at="2026-08-26T09:00:00Z"))

    exc = _raises(MergeRefused, _merge, ports, journal, absorbed, survivor)
    assert exc.reason == "read_running"
    assert ports.shelves.get_shelf(LIB, absorbed.id) is not None, (
        "a refused merge deleted the shelf anyway")


def test_merging_into_a_shelf_that_has_itself_been_absorbed_is_refused():
    """Following it would silently merge into a third identity nobody chose."""
    ports, journal = _world()
    drawn = _drawn(ports, columns=2)
    first, second = drawn.shelves[0], drawn.shelves[1]
    absorbed = _photo_born(ports)
    _merge(ports, journal, second, first)

    exc = _raises(MergeRefused, _merge, ports, journal, absorbed, second)
    assert exc.reason == "survivor_absorbed"


def test_a_retry_is_a_no_op_rather_than_a_second_merge():
    """§3.15: *A already resolves to B* answers 200 as a no-op, so a retry
    provoked by a dropped response cannot half-merge."""
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    _book(ports, id="b1", title="בית", shelf_id=absorbed.id)

    _merge(ports, journal, absorbed, survivor)
    after = census(ports)
    again = _merge(ports, journal, absorbed, survivor)

    assert again.already is True
    assert census(ports) == after, "the retry moved something a second time"
    assert len(journal.store.recent(LIB, limit=9)) == 1, (
        "the retry wrote a second journal entry, which would push the real "
        "one off the head")


# --- §3.15: the undo ------------------------------------------------------

def test_a_merge_can_be_taken_back_and_the_census_proves_it():
    """The whole item, in one assertion.

    ⚠ Compared with a CENSUS rather than a handful of fields, because four of
    the six tables that name a shelf have no foreign key: a library that has
    lost half its locations passes `foreign_key_check` and every spot check
    somebody thinks to write.
    """
    ports, journal = _world()
    drawn = _drawn(ports, columns=2, levels=2, depth=2)
    survivor = drawn.shelves[0]
    absorbed = _photo_born(ports, depth_count=2, label="ספרי בישול")
    _book(ports, id="b1", title="תמול שלשום", shelf_id=absorbed.id, depth=2)
    _book(ports, id="b2", title="סיפור פשוט", shelf_id=survivor.id, depth=1)
    _photo(ports, absorbed, id="a0", order=0)
    _photo(ports, survivor, id="s0", order=0)
    ports.decisions.save_decision(LIB, Decision(
        library_id=LIB.id, shelf_id=absorbed.id, depth=1,
        book_key="עגנון|רוח רפאים", kind=DecisionKind.REJECTED,
        decided_at="2026-02-01T00:00:00Z"))
    before = census(ports)

    _merge(ports, journal, absorbed, survivor, StripOrder.ABSORBED_FIRST)
    assert offer(journal, ports.map_store, ports.shelves, LIB).available

    undo(journal, ports.map_store, ports.shelves, ports.books, LIB)

    assert census(ports) == before, "the undo did not restore the library"
    assert ports.shelves.get_shelf(LIB, absorbed.id).label == "ספרי בישול"
    assert ports.shelves.list_aliases(LIB) == (), (
        "the alias outlived the merge it records")
    assert ports.decisions.list_decisions(LIB, absorbed.id, 1)[0].kind is \
        DecisionKind.REJECTED
    assert ports.decisions.list_decisions(LIB, survivor.id, 1) == (), (
        "the rejection was left standing at the survivor too, so the next "
        "read suppresses a book on the strength of a merge that was undone")
    assert ports.shelves.get_shelf(LIB, survivor.id).depth_count == 2


def test_an_undo_refuses_once_a_moved_book_has_been_moved_again():
    """§3.15: an undo that cannot prove the world is still as it left it
    refuses, and says why."""
    ports, journal = _world()
    drawn = _drawn(ports, columns=2)
    survivor, elsewhere = drawn.shelves[0], drawn.shelves[1]
    absorbed = _photo_born(ports)
    _book(ports, id="b1", title="בית", shelf_id=absorbed.id)

    _merge(ports, journal, absorbed, survivor)
    from app.domain import refile_copy
    moved = ports.books.get(LIB, "b1")
    ports.books.save(LIB, refile_copy(moved, "c-b1", shelf_id=elsewhere.id,
                                      depth=1))

    said = offer(journal, ports.map_store, ports.shelves, LIB)
    assert said.available is False and said.reason == "world_moved"
    assert "copies:c-b1" in said.changed, said.changed


def test_an_undo_refuses_once_the_alias_it_wrote_has_been_re_pointed():
    ports, journal = _world()
    drawn = _drawn(ports, columns=2)
    survivor, third = drawn.shelves[0], drawn.shelves[1]
    absorbed = _photo_born(ports)

    _merge(ports, journal, absorbed, survivor)
    ports.shelves.rewrite_aliases(
        LIB, remove=(absorbed.id,),
        put=(_alias(absorbed.id, third.id),))

    said = offer(journal, ports.map_store, ports.shelves, LIB)
    assert said.available is False
    assert f"aliases:{absorbed.id}" in said.changed, said.changed


def _alias(alias_id, shelf_id):
    from app.domain.alias import ShelfAlias

    return ShelfAlias(alias_id=alias_id, library_id=LIB.id, shelf_id=shelf_id,
                      merged_at="2026-08-26T11:00:00+00:00")
