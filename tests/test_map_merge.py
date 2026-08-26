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
    Capture,
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

    ⚠⚠ **It digested two of those four.** `decisions` and
    `duplicate_questions` were absent, which made the one test that meets the
    JSON codec through a real merge blind to a lost human answer — measured by
    breaking the undo's decision restore, which only the memory test noticed,
    and only through its own separate assertion. And the orphan line, which
    the docstring calls *the point*, was structurally inert: photographs were
    gathered by iterating the shelves already known, so a capture naming an
    unknown one could never appear in the set it was checked against.

    Every location folds through ``resolve``, so this is comparable
    before-merge to after-merge as well as across an undo — which is what
    MAP_PLAN asks of it and what it could not do while ``photo_slots`` carried
    raw, unresolved shelf ids.
    """
    live = {s.id for s in ports.shelves.list_shelves(LIB, include_virtual=True)}
    aliases = ports.shelves.list_aliases(LIB)
    known = live | {a.alias_id for a in aliases}
    books = ports.books.list(LIB, limit=999).items
    copies = [(b.id, c) for b in books for c in b.copies]
    # ⚠ Over `known` AND over every shelf a row actually names, so a
    # photograph filed under an id nothing answers for is FOUND rather than
    # skipped. The old version iterated `known` alone, which made the orphan
    # check unable to see the one thing it exists for.
    named_shelves = ({c.shelf_id for _, c in copies if c.shelf_id}
                     | {a.shelf_id for a in aliases})
    photos = [c for shelf_id in known | named_shelves
              for c in ports.shelves.list_captures(LIB, shelf_id)]
    decisions = [d for shelf_id in known | named_shelves
                 for d in ports.decisions.decisions_at_shelf(LIB, shelf_id)]
    questions = [q for shelf_id in known | named_shelves
                 for q in ports.duplicates.list_open_questions(
                     LIB, shelf_id=shelf_id)]
    named = ([c.shelf_id for _, c in copies if c.shelf_id]
             + [c.shelf_id for c in photos]
             + [d.shelf_id for d in decisions]
             + [q.shelf_id for q in questions]
             + [a.shelf_id for a in aliases])
    at = lambda shelf_id: resolve(shelf_id, aliases)
    return {
        "books": len(books),
        "copies": len(copies),
        "located": len([c for _, c in copies if c.shelf_id]),
        "at": sorted((at(c.shelf_id), c.depth)
                     for _, c in copies if c.shelf_id),
        "photos": sorted((at(c.shelf_id), c.depth, c.image_id)
                         for c in photos),
        # Resolved, so this compares before-merge to after-merge too.
        "photo_slots": sorted((at(c.shelf_id), c.depth, c.order)
                              for c in photos),
        # §3.13's load-bearing table, and §5.4's queue beside it. Every
        # `(depth, book_key)` decided at either side must still be decided at
        # the survivor — which is what folding the shelf through `resolve`
        # says, in the one place both sides can be compared.
        "decided": sorted((at(d.shelf_id), d.depth, d.book_key, d.kind.value)
                          for d in decisions),
        "asked": sorted((at(q.shelf_id), q.depth, q.book_key)
                        for q in questions),
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


def test_renaming_a_book_after_a_merge_does_not_refuse_the_undo():
    """The other half of the sentence above, and the reason the copy digest is
    NARROW.

    ⚠ A merge writes `shelf_id` and `depth` on a copy and touches nothing
    else, so that is what the fingerprint may hold it to. Digesting the whole
    book instead makes an undo refuse because somebody fixed a title on the
    books tab — a screen with nothing to do with the map — and the refusal
    would name a copy that has not moved an inch.
    """
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    _book(ports, id="b1", title="תמול שלשם", shelf_id=absorbed.id)

    _merge(ports, journal, absorbed, survivor)
    from app.domain import edit
    ports.books.save(LIB, edit(ports.books.get(LIB, "b1"),
                               title="תמול שלשום"))

    said = offer(journal, ports.map_store, ports.shelves, LIB)
    assert said.available is True, said.changed


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


def test_a_merge_and_its_undo_survive_a_real_database_file():
    """The same census, over SQLite rather than dictionaries.

    ⚠ Every other test in this module builds `_world()` from memory stores, so
    the journal's JSON codec — the one component that has silently dropped a
    field twice — meets a merge's inverse ONLY in `test_store_contract.py`.
    That contract is a strong gate and it is not this: it round-trips a
    hand-built entry, while this writes one through `merge()` and reads it
    back through `undo()`, on a file with foreign keys switched on.

    It is one case rather than a second parameterised suite because what it
    adds is the FILE, not more rules: everything it asserts is asserted above
    against the memory stores, and a divergence is exactly what it exists to
    catch.
    """
    import shutil
    import sqlite3
    import tempfile
    from pathlib import Path

    from app.adapters.sqlite_store import (
        SqliteBookStore, SqliteDecisionStore, SqliteDuplicateQueue,
        SqliteMapStore, SqliteMapUndoStore, SqliteReadStore, SqliteShelfStore,
    )
    tmp = tempfile.mkdtemp(prefix="booksnap-merge-")
    try:
        path = Path(tmp) / "books.db"
        # Constructing any store migrates the file — the same path the real
        # app takes, rather than a setup step this test could get wrong.
        ports = Shelves(
            map_store=SqliteMapStore(path), shelves=SqliteShelfStore(path),
            books=SqliteBookStore(path), reads=SqliteReadStore(path),
            decisions=SqliteDecisionStore(path),
            duplicates=SqliteDuplicateQueue(path))
        journal = Journal(store=SqliteMapUndoStore(path), ids=SeqIdGen("u"),
                          clock=StubClock(), books=ports.books,
                          decisions=ports.decisions,
                          duplicates=ports.duplicates)
        ports.map_store.save_site(LIB, new_site(id="st", library_id=LIB.id,
                                                name="הבית"))
        ports.map_store.save_floor(LIB, new_floor(
            id="fl", library_id=LIB.id, site_id="st", name="קרקע"))
        ports.map_store.save_place(LIB, new_place(
            id="pl", library_id=LIB.id, floor_id="fl",
            rect=Rect(0, 0, 12, 9), name="סלון"))

        drawn = _drawn(ports, columns=2, levels=2, depth=2)
        survivor = drawn.shelves[0]
        absorbed = _photo_born(ports, depth_count=2, label="ספרי בישול")
        _book(ports, id="b1", title="תמול שלשום", shelf_id=absorbed.id,
              depth=2)
        _photo(ports, absorbed, id="a0", order=0)
        _photo(ports, survivor, id="s0", order=0)
        ports.decisions.save_decision(LIB, Decision(
            library_id=LIB.id, shelf_id=absorbed.id, depth=1,
            book_key="עגנון|רוח רפאים", kind=DecisionKind.REJECTED,
            decided_at="2026-02-01T00:00:00Z"))
        before = census(ports)

        _merge(ports, journal, absorbed, survivor, StripOrder.ABSORBED_FIRST)
        assert ports.shelves.get_shelf(LIB, absorbed.id) is None
        # ⚠ Read back through the store, so the assertion is about the BLOB
        # and not about an object still in memory.
        assert offer(journal, ports.map_store, ports.shelves, LIB).available, (
            "the entry could not match itself after a round trip through the "
            "codec — which is what a dropped field looks like from here")

        undo(journal, ports.map_store, ports.shelves, ports.books, LIB)

        assert census(ports) == before
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- what a data-integrity review measured --------------------------------

def test_the_identity_is_written_before_a_single_book_moves():
    """⚠ **The CRITICAL, and the whole ordering argument.**

    With the books moved first, a concurrent `DELETE /api/v1/shelves/{id}` on
    the survivor left copies naming a shelf that was neither live nor an alias
    — the census's headline invariant, `foreign_key_check` clean, and no
    journal entry to take it back. And the survivor is the LIKELY one to be
    deletable: §3.11's own example is a photo-born shelf absorbed into a DRAWN
    slot, and a drawn slot is empty by construction.

    Once `A -> B` exists, every row still naming A is reachable through
    `identities()`, so nothing below can orphan anything.
    """
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    for n in range(3):
        _book(ports, id=f"b{n}", title=f"ספר {n}", shelf_id=absorbed.id)

    seen: list[tuple[str, ...]] = []
    real = ports.books.save

    def watched(library, book):
        seen.append(tuple(a.alias_id for a in
                          ports.shelves.list_aliases(library)))
        real(library, book)

    ports.books.save = watched  # type: ignore[method-assign]
    try:
        _merge(ports, journal, absorbed, survivor)
    finally:
        ports.books.save = real  # type: ignore[method-assign]

    assert seen and all(absorbed.id in s for s in seen), (
        "a book moved before the identity was written, so an interruption "
        "there leaves it naming a shelf nothing answers for")
    assert census(ports)["orphans"] == []


def test_a_stray_photograph_arriving_mid_merge_does_not_wedge_the_library():
    """MAJOR: `delete_shelf` raising AFTER the alias was committed left a LIVE
    shelf and an alias for the same id, permanently, with no journal entry and
    a retry that re-raised forever.

    Now the identity is already merged when the delete runs, so a refusal is
    the smaller loss: the row survives, every query folds it into the
    survivor, and the merge is still takeable back.
    """
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    real = ports.shelves.save_capture

    def arrive(library, capture):
        # One photograph lands on the absorbed shelf while the merge runs.
        real(library, capture)
        ports.shelves.save_capture = real  # type: ignore[method-assign]
        real(library, new_capture(absorbed, id="late", depth=1, order=9))

    _photo(ports, absorbed, id="a0", order=0)
    ports.shelves.save_capture = arrive  # type: ignore[method-assign]
    try:
        out = _merge(ports, journal, absorbed, survivor)
    finally:
        ports.shelves.save_capture = real  # type: ignore[method-assign]

    assert ports.shelves.get_shelf(LIB, absorbed.id) is not None, (
        "the shelf was deleted with a photograph still on it")
    assert resolve(absorbed.id, ports.shelves.list_aliases(LIB)) == survivor.id
    assert out.undoable is True, (
        "the merge became un-takeable-back because its last step refused")
    assert offer(journal, ports.map_store, ports.shelves, LIB).available


def test_a_rename_during_a_merge_is_not_reverted_by_it():
    """MAJOR: the survivor was written back WHOLE from a row read before the
    merge began, so a label typed in another tab vanished — and invisibly,
    because `wrote` reports the stale row as this edit's own work. That is the
    silently-wrong undo `wrote` exists to abolish, reappearing because the
    merge was itself the destroyer."""
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports, depth_count=2)
    from app.domain import rename_shelf
    real = ports.shelves.list_captures

    def meanwhile(library, shelf_id, **kw):
        ports.shelves.list_captures = real  # type: ignore[method-assign]
        ports.shelves.save_shelf(library, rename_shelf(
            ports.shelves.get_shelf(library, survivor.id), "מדף הסלון"))
        return real(library, shelf_id, **kw)

    ports.shelves.list_captures = meanwhile  # type: ignore[method-assign]
    try:
        _merge(ports, journal, absorbed, survivor)
    finally:
        ports.shelves.list_captures = real  # type: ignore[method-assign]

    after = ports.shelves.get_shelf(LIB, survivor.id)
    assert after.label == "מדף הסלון", "the merge reverted a rename"
    assert after.depth_count == 2, "and it forgot to deepen"


def test_a_second_merge_never_shallows_the_survivor_under_its_books():
    """§3.12: *"shallowing never happens here"*. It did — two merges
    interleaved, and the outer one wrote back a `depth_count` read before the
    inner one deepened it, leaving books at depth 3 on a shelf declaring one
    row. `check_depth(3)` then raised for every screen that asked."""
    ports, journal = _world()
    survivor = _drawn(ports, depth=1).shelves[0]
    first = _photo_born(ports, id="ph-1", depth_count=1)
    second = _photo_born(ports, id="ph-2", depth_count=3)

    real = ports.books.books_on_shelf
    done = []

    def interleave(library, ids):
        if not done:
            done.append(True)
            _merge(ports, journal, second, survivor)
        return real(library, ids)

    ports.books.books_on_shelf = interleave  # type: ignore[method-assign]
    try:
        _merge(ports, journal, first, survivor)
    finally:
        ports.books.books_on_shelf = real  # type: ignore[method-assign]

    assert ports.shelves.get_shelf(LIB, survivor.id).depth_count == 3, (
        "the outer merge shallowed the survivor under the inner one's rows")


def test_a_rejection_at_a_depth_the_shelf_no_longer_declares_still_moves():
    """§3.13's load-bearing table, at a depth nobody could enumerate.

    A REJECTED decision leaves nothing standing, and the depth patch floors at
    `deepest_occupied_depths` — which counts copies and photographs, not
    answers. So a shelf shallowed after a rejection held a row the merge's
    gather could not see, and it was left behind at an id about to stop
    existing. Deepen the survivor later and the next read re-adds the phantom.
    """
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports, depth_count=1)
    ports.decisions.save_decision(LIB, Decision(
        library_id=LIB.id, shelf_id=absorbed.id, depth=3,
        book_key="עגנון|רוח רפאים", kind=DecisionKind.REJECTED,
        decided_at="2026-02-01T00:00:00Z"))

    _merge(ports, journal, absorbed, survivor)

    assert [d.book_key for d in
            ports.decisions.decisions_at_shelf(LIB, survivor.id)] == [
        "עגנון|רוח רפאים"]
    assert ports.decisions.decisions_at_shelf(LIB, absorbed.id) == ()


def test_an_absorbed_question_does_not_land_on_a_key_already_answered():
    """The forbidden pair, from the direction the first test did not walk: the
    SURVIVOR's own standing answer, rather than one this merge is moving."""
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    ports.decisions.save_decision(LIB, Decision(
        library_id=LIB.id, shelf_id=survivor.id, depth=1,
        book_key="עגנון|תמול שלשום", kind=DecisionKind.REJECTED,
        decided_at="2026-01-01T00:00:00Z"))
    ports.duplicates.save_question(LIB, DuplicateQuestion(
        id="q1", library_id=LIB.id, shelf_id=absorbed.id, depth=1,
        book_key="עגנון|תמול שלשום", read_id="r", spine_id="s",
        claim_title="תמול שלשום", claim_author="עגנון",
        existing_book_id="b1", opened_at="2026-05-01T00:00:00Z"))

    _merge(ports, journal, absorbed, survivor)

    assert ports.duplicates.list_open_questions(
        LIB, shelf_id=survivor.id) == (), (
        "a question stands open at a key the survivor decided long ago")


def test_an_untouched_photograph_does_not_refuse_a_later_undo():
    """The fingerprint's other failure mode: a key that changes for an
    innocent reason. `ABSORBED_FIRST` wrote — and REMEMBERED — the survivor's
    rows at depths the absorbed shelf never had, a shift of zero, so
    re-photographing an untouched depth refused a legitimate undo."""
    ports, journal = _world()
    survivor = _drawn(ports, depth=2).shelves[0]
    absorbed = _photo_born(ports, depth_count=2)
    _photo(ports, absorbed, id="a0", depth=1, order=0)
    _photo(ports, survivor, id="s1", depth=1, order=0)
    _photo(ports, survivor, id="s2", depth=2, order=0)

    _merge(ports, journal, absorbed, survivor, StripOrder.ABSORBED_FIRST)
    entry = journal.store.recent(LIB, limit=1)[0]
    assert "captures:s2" not in entry.fingerprint, (
        "a photograph at a depth the merge never touched is being watched")

    survived = ports.shelves.get_capture(LIB, "s2")
    from dataclasses import replace as _r
    ports.shelves.save_capture(LIB, _r(survived, image_id="img-new"))
    assert offer(journal, ports.map_store, ports.shelves, LIB).available, (
        "an untouched photograph refused the undo")


def test_a_read_that_started_before_the_merge_finishes_at_the_survivor():
    """§3.11 promised this in words and did not have it in code.

    *"`apply_diff` resolves through the alias so a read that started at A
    finishes at B rather than raising 'shelf no longer exists; nothing to
    apply' and discarding a whole diff."* The settle path swallows that
    exception, so the ENTIRE diff was discarded in silence while the read was
    stored DONE with a summary claiming books it never added.
    """
    from app.domain import Claim, ClaimTier, Diff, OutcomeKind, ClaimOutcome
    from app.reconcile_apply import apply_diff

    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    _merge(ports, journal, absorbed, survivor)

    claim = Claim(id="sp-1", spine_id="sp-1", capture_id="cap-1",
                  title="תמול שלשום", author="עגנון", tier=ClaimTier.MANUAL)
    diff = Diff(library_id=LIB.id, shelf_id=absorbed.id, depth=1,
                read_id="r-1",
                added=(ClaimOutcome(claim=claim, kind=OutcomeKind.ADDED),))
    apply_diff(diff, library=LIB, books=ports.books, shelves=ports.shelves,
               decisions=ports.decisions, clock=StubClock(90),
               ids=SeqIdGen("new"))

    landed = ports.books.books_on_shelf(LIB, (survivor.id,))
    assert [b.title for b in landed] == ["תמול שלשום"], (
        "the diff was discarded because the shelf it named had been merged")
    assert landed[0].copies[0].shelf_id == survivor.id


# --- what a quality review found unpinned ---------------------------------

def test_the_questions_half_of_the_inverse_is_a_real_inverse():
    """⚠ THREE independent mutants survived here, all one table over from a
    killed sibling: `_inverse`'s `minted_questions`, `_replay_ledger`'s
    re-open, and `_ledger`'s digest. `duplicate_questions` is one of the six
    tables §3.13 names and it had no undo coverage and no fingerprint coverage
    at all — so an undone merge left a duplicate open §5.4 question standing
    at the survivor, and moving one afterwards did not refuse the undo."""
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    ports.duplicates.save_question(LIB, DuplicateQuestion(
        id="q1", library_id=LIB.id, shelf_id=absorbed.id, depth=1,
        book_key="עגנון|תמול שלשום", read_id="r", spine_id="s",
        claim_title="תמול שלשום", claim_author="עגנון",
        existing_book_id="b1", opened_at="2026-05-01T00:00:00Z"))
    before = census(ports)

    _merge(ports, journal, absorbed, survivor)
    assert [q.shelf_id for q in ports.duplicates.list_open_questions(LIB)] == [
        survivor.id]

    undo(journal, ports.map_store, ports.shelves, ports.books, LIB)

    assert census(ports) == before, (
        "the question did not go home — an undone merge left it at the "
        "survivor, where nothing opened it")
    assert [q.shelf_id for q in ports.duplicates.list_open_questions(LIB)] == [
        absorbed.id]


def test_a_question_moved_after_the_merge_refuses_the_undo():
    """The fingerprint's half. `_ledger` digests questions, and nothing said
    so: deleting that digest passed every ring."""
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    ports.duplicates.save_question(LIB, DuplicateQuestion(
        id="q1", library_id=LIB.id, shelf_id=absorbed.id, depth=1,
        book_key="עגנון|תמול שלשום", read_id="r", spine_id="s",
        claim_title="תמול שלשום", claim_author="עגנון",
        existing_book_id="b1", opened_at="2026-05-01T00:00:00Z"))

    _merge(ports, journal, absorbed, survivor)
    ports.duplicates.delete_question(LIB, survivor.id, 1, "עגנון|תמול שלשום")

    said = offer(journal, ports.map_store, ports.shelves, LIB)
    assert said.available is False, "the undo did not notice the answer went"
    assert f"questions:{survivor.id}:1:עגנון|תמול שלשום" in said.changed


def test_the_fingerprint_is_digested_from_what_the_MERGE_wrote():
    """CLAUDE.md's own trap, on this item's four new key families.

    ⚠ Every `wrote[…]` a merge writes could be deleted with the whole ring
    green. `wrote` is the fix for the widest window in `map_undo` — recording
    happens after the edit, so a re-READ digests somebody else's work as this
    edit's own — and the harness that gates it for `map_edit` has no sibling
    here, because a merge's keys go through `_ledger` rather than `load_map`.
    """
    ports, journal = _world()
    drawn = _drawn(ports, columns=2)
    survivor, elsewhere = drawn.shelves[0], drawn.shelves[1]
    absorbed = _photo_born(ports)
    _book(ports, id="b1", title="בית", shelf_id=absorbed.id)
    _photo(ports, absorbed, id="a0", order=0)

    real = ports.books.books_on_shelf
    seen = []

    def interloping(library, ids):
        # ⚠ Inside the read the JOURNAL makes, which is the window. The first
        # call is the merge's own `gather`; the second is `_ledger` digesting
        # what the edit left behind, and a change committed between them is
        # what `wrote` must overrule.
        seen.append(True)
        if len(seen) == 2:
            from app.domain import refile_copy
            ports.books.save(library, refile_copy(
                ports.books.get(library, "b1"), "c-b1",
                shelf_id=elsewhere.id, depth=1))
        return real(library, ids)

    ports.books.books_on_shelf = interloping  # type: ignore[method-assign]
    try:
        _merge(ports, journal, absorbed, survivor)
    finally:
        ports.books.books_on_shelf = real  # type: ignore[method-assign]

    said = offer(journal, ports.map_store, ports.shelves, LIB)
    assert said.available is False, (
        "the journal wrote down another tab's work as its own, so the undo "
        "would revert it without a word")
    assert "copies:c-b1" in said.changed, said.changed


def test_a_chained_merge_can_be_taken_back():
    """Four survivors described one hole: two merges are performed by a test
    and neither is ever undone — the one path where `rewrite_aliases`' chain
    refusal, the alias digest and the replay order all matter at once."""
    ports, journal = _world()
    drawn = _drawn(ports, columns=2)
    first = drawn.shelves[0]
    oldest = _photo_born(ports, id="ph-0", label="הראשון")
    middle = _photo_born(ports, id="ph-1", label="האמצעי")
    _book(ports, id="b1", title="בית", shelf_id=oldest.id)

    _merge(ports, journal, oldest, middle)
    after_first = census(ports)
    _merge(ports, journal, ports.shelves.get_shelf(LIB, middle.id), first)

    assert offer(journal, ports.map_store, ports.shelves, LIB).available
    undo(journal, ports.map_store, ports.shelves, ports.books, LIB)

    assert census(ports) == after_first, (
        "undoing the second merge did not restore the first one's state")
    assert [(a.alias_id, a.shelf_id) for a in
            ports.shelves.list_aliases(LIB)] == [("ph-0", "ph-1")]
    assert ports.shelves.get_shelf(LIB, middle.id) is not None


def test_the_ladder_counts_what_actually_STANDS_on_either_shelf():
    """§3.12 spells it `max(A.depth, B.depth, deepest_occupied(A),
    deepest_occupied(B))` and only the first two halves were pinned.

    ⚠ Reachable, not theoretical: `new_book` and `refile_copy` do not check a
    copy's depth against the shelf, so a copy CAN stand deeper than its shelf
    declares. Taking the declarations alone then leaves it with nowhere to be,
    and `check_depth` raises for every screen that asks."""
    ports, journal = _world()
    survivor = _drawn(ports, depth=1).shelves[0]
    absorbed = _photo_born(ports, depth_count=1)
    _book(ports, id="b1", title="בית", shelf_id=absorbed.id, depth=3)

    out = _merge(ports, journal, absorbed, survivor)

    assert out.survivor.depth_count >= 3, (
        "a book stands at depth 3 on a shelf declaring fewer rows")
    assert out.survivor.check_depth(3) == 3


def test_the_ladder_counts_photographs_too():
    ports, journal = _world()
    survivor = _drawn(ports, depth=1).shelves[0]
    absorbed = _photo_born(ports, depth_count=3)
    _photo(ports, absorbed, id="a0", depth=3, order=0)
    shallow = ports.shelves.get_shelf(LIB, absorbed.id)
    from dataclasses import replace as _r
    ports.shelves.save_shelf(LIB, _r(shallow, depth_count=1))

    out = _merge(ports, journal, ports.shelves.get_shelf(LIB, absorbed.id),
                 survivor)
    assert out.survivor.depth_count >= 3


def test_a_read_running_on_the_SURVIVOR_refuses_the_merge_too():
    """The name says *either identity*; the test started a read on one. The
    survivor is arguably the more dangerous half — it keeps existing while its
    depth and its capture strip change under a running read."""
    ports, journal = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    shot = _photo(ports, survivor, id="s0", order=0)
    ports.reads.save_read(LIB, new_read(
        survivor, (shot,), id="r1", depth=1, mode="llmpage",
        started_at="2026-08-26T09:00:00Z"))

    assert _raises(MergeRefused, _merge, ports, journal, absorbed,
                   survivor).reason == "read_running"


def test_two_identities_may_not_remember_one_former_slot():
    """Owner, 2026-08-23: the address→survivor lookup must have exactly one
    answer. The store enforces it too — but by then a merge has already moved
    books, so the refusal has to arrive BEFORE the first write and with a
    sentence rather than a driver error."""
    ports, journal = _world()
    drawn = _drawn(ports, columns=2)
    survivor, other = drawn.shelves[0], drawn.shelves[1]
    where = other.address
    ports.shelves.delete_shelf(LIB, other.id)
    first = _photo_born(ports, id="ph-1", address=where)
    _merge(ports, journal, first, survivor)
    # A second identity is bound into the very cell the first one vacated…
    second = _photo_born(ports, id="ph-2")
    from app.map_edit import bind_shelf_to_slot
    section = ports.map_store.get_section(LIB, drawn.sections[0].id)
    bind_shelf_to_slot(ports.map_store, ports.shelves, LIB, second, section,
                       where)

    exc = _raises(MergeRefused, _merge, ports, journal,
                  ports.shelves.get_shelf(LIB, second.id), survivor)
    assert exc.reason == "address_taken"
    assert ports.shelves.get_shelf(LIB, second.id) is not None


def test_a_shelf_is_never_merged_into_itself_by_the_PREVIEW_either():
    """A preview that promises a state the write refuses is the one thing the
    shared `gather` exists to prevent."""
    ports, _ = _world()
    survivor = _drawn(ports).shelves[0]
    exc = _raises(MergeRefused, preview, ports, LIB, survivor, survivor,
                  strip=StripOrder.SURVIVOR_FIRST)
    assert exc.reason == "same_shelf"


def test_the_preview_counts_distinct_BOOKS_not_copies():
    """The number a person recognises. Every fixture held one copy per book,
    so `len(was_copies)` passed — and two copies of one work on one shelf
    would have printed the wrong number on the screen that exists to make the
    ✓ informed."""
    ports, _ = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    book = _book(ports, id="b1", title="בית", shelf_id=absorbed.id)
    from app.domain import add_copy
    ports.books.save(LIB, add_copy(book, copy_id="c2", shelf_id=absorbed.id,
                                   depth=1))

    seen = preview(ports, LIB, absorbed, survivor,
                   strip=StripOrder.SURVIVOR_FIRST)
    assert seen.books == 1, "two copies of one work counted as two books"
    assert seen.copies_per_depth == {1: 2}


def test_the_preview_counts_only_the_photographs_that_MOVE():
    """Under `ABSORBED_FIRST` the survivor's own strip is rewritten, so
    without the filter the preview reports the survivor's photographs as
    moving — on the screen whose whole job is to say what it costs."""
    ports, _ = _world()
    survivor = _drawn(ports).shelves[0]
    absorbed = _photo_born(ports)
    _photo(ports, survivor, id="s0", order=0)
    _photo(ports, survivor, id="s1", order=1)
    _photo(ports, absorbed, id="a0", order=0)

    seen = preview(ports, LIB, absorbed, survivor,
                   strip=StripOrder.ABSORBED_FIRST)
    assert seen.photos_per_depth == {1: 1}


def test_a_union_of_two_restores_keeps_the_replay_ORDER():
    """`merge_restores` is a pure function and nothing coalesces a merge, so
    this branch is exercised by nothing — and it was wrong.

    ⚠ `MapRestore.captures` says the sequence is part of the inverse, not a
    detail of writing it: `(shelf, depth, order)` is unique, so a replay in
    the wrong order lands on a slot whose occupant has not moved yet. A dict
    union built from the NEWER bag reordered it, which is exactly the
    sequence `_replay_ledger` says leaves an entry dead forever.
    """
    from app.domain.map_undo import MapRestore, merge_restores

    def cap(cap_id, order):
        return Capture(id=cap_id, shelf_id="sh", library_id=LIB.id, depth=1,
                       order=order)

    older = MapRestore(captures=(cap("a", 0), cap("b", 1), cap("c", 2)))
    newer = MapRestore(captures=(cap("c", 9), cap("d", 3)))

    both = merge_restores(older, newer)
    assert [c.id for c in both.captures] == ["a", "b", "c", "d"], (
        "the union reordered the replay, which is the one thing this bag "
        "promises to preserve")
    assert both.captures[2].order == 2, "older wins on a collision"
