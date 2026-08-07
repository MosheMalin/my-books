# -*- coding: utf-8 -*-
"""H4 ring 1 — rule tests over app/domain. No I/O, milliseconds.

The standard from the plan, verbatim: *a test that fails if the decision is
reversed* — not a coverage number. So there is nothing here testing that a
dataclass stores what you put in it. Every test below corresponds to a
sentence in VISION.md that someone could plausibly "fix" later, plus the
migration contract P1.3 depends on.

Three of these are named in the plan's H5 checklist for pillar 1:

  - the matcher never auto-creates a copy ................... §5.1
  - an approved book is never demoted by a worse re-read .... §5.6
  - *remove from shelf* != *delete from library* ............ UI_PLAN §5
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.domain import (
    AmbiguousCopy,
    Book,
    CopyAlreadyLentOut,
    CopyNotLentOut,
    DomainError,
    Provenance,
    Shelf,
    Status,
    UnknownCopy,
    UnknownDepth,
    VirtualShelfHasNoDepth,
    add_copy,
    add_depth,
    approve,
    book_key,
    counts_toward_library,
    edit,
    edit_copy,
    lend,
    new_book,
    new_capture,
    new_shelf,
    observe,
    remove_from_shelf,
    rename_shelf,
    return_copy,
    set_work_fields,
)

LIB = "lib-1"


def _book(**kw) -> Book:
    args = dict(id="b1", library_id=LIB, title="מלכי הכופרים",
                author="פול קארני", copy_id="c1")
    args.update(kw)
    return new_book(**args)


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"expected {exc.__name__}, nothing raised")


# --- H5: the matcher never auto-creates a copy (§5.1) ---------------------

def test_a_read_never_creates_a_copy_however_often_it_fires():
    """Two spines claiming one book is overwhelmingly a mis-assignment, not a
    genuine duplicate — which is what dup_drop_frac already encodes. If a
    re-read could create a copy, that rule would be silently undone."""
    b = _book(shelf_id="s1")
    for i in range(20):
        b = observe(b, Provenance(f"run{i}", f"sp{i}", shelf_id="s1"))
    assert b.copy_count == 1, "a read created a copy"


def test_only_two_functions_in_the_domain_may_construct_a_copy():
    """Structural, not behavioural: walks the module and fails if a Copy()
    appears anywhere but the two paths a human action reaches.

    A behavioural test only covers the sequences it thought of. This one
    covers the code that does not exist yet — which is the point, because the
    reconciliation engine (P2.3) is written into this same package later.
    """
    allowed = {"new_book", "add_copy"}
    src = (REPO_ROOT / "app" / "domain" / "book.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "Copy" and fn.name not in allowed):
                offenders.append(f"{fn.name}() at line {node.lineno}")
    assert not offenders, (
        "Copy() constructed outside " + str(sorted(allowed)) + ": "
        + "; ".join(offenders) + " — §5.1, duplicates enter by human action only"
    )


def test_add_copy_is_the_creation_path_and_marks_it_manual():
    """"I have another copy" is the strongest evidence the system ever gets."""
    b = add_copy(_book(), copy_id="c2", label="כריכה רכה")
    assert b.copy_count == 2
    assert b.copy("c2").status is Status.MANUAL
    assert b.copy("c1").status is Status.AUTO, "the original was changed"


def test_a_read_on_a_different_shelf_asks_instead_of_guessing():
    """§5.4's real case. Guessing is destructive both ways: relinking moves a
    book that didn't move, creating invents a phantom."""
    b = _book(shelf_id="s1")
    _raises(AmbiguousCopy, observe, b, Provenance("r2", "sp2", shelf_id="s2"))


def test_a_read_never_silently_picks_among_several_copies():
    """§5.4 says the user picks. Its suggested default (the unshelved copy) is
    a default to SHOW, not one the domain may take."""
    b = add_copy(_book(shelf_id="s1"), copy_id="c2")
    _raises(AmbiguousCopy, observe, b, Provenance("r2", "sp2", shelf_id="s9"))
    # …but once the human has answered, the id resolves it.
    out = observe(b, Provenance("r2", "sp2", shelf_id="s9"), copy_id="c2")
    assert out.copy("c2").shelf_id == "s9"
    assert out.copy_count == 2


def test_same_shelf_re_read_never_asks():
    """The 'never ask' row of §5.4: same shelf, same copy, append and move on.
    This prompt firing often is what makes it click-through-approved."""
    b = _book(shelf_id="s1")
    out = observe(b, Provenance("r2", "sp2", shelf_id="s1"))
    assert out.copy_count == 1
    assert len(out.copy("c1").provenance) == 1


# --- H5: an approved book is never demoted by a worse re-read (§5.6) ------

def test_approval_survives_a_worse_re_read():
    """Measured recall is 0.78-0.83, so a re-read failing to confirm is weak
    evidence. Treating it as authoritative would silently undo human work."""
    b = approve(_book(shelf_id="s1"))
    assert b.status is Status.APPROVED
    b = observe(b, Provenance("r2", "sp2", shelf_id="s1"), status=Status.AUTO)
    assert b.status is Status.APPROVED, "a re-read demoted an approved book"


def test_manual_outranks_everything():
    b = edit(_book(shelf_id="s1"), title="מלכי הכופרים")
    assert b.status is Status.MANUAL
    b = observe(b, Provenance("r2", "sp2", shelf_id="s1"), status=Status.APPROVED)
    assert b.status is Status.MANUAL


def test_the_ladder_is_auto_then_approved_then_manual():
    assert Status.MANUAL.outranks(Status.APPROVED)
    assert Status.APPROVED.outranks(Status.AUTO)
    assert not Status.AUTO.outranks(Status.APPROVED)
    assert Status.merge(Status.AUTO, Status.APPROVED) is Status.APPROVED
    assert Status.merge(Status.APPROVED, Status.AUTO) is Status.APPROVED
    assert Status.merge(Status.MANUAL, Status.APPROVED) is Status.MANUAL


def test_a_read_can_still_raise_an_untouched_book():
    """Never-demote must not become never-change: an AUTO book confirmed by a
    later human action still moves up."""
    b = _book(shelf_id="s1")
    assert b.status is Status.AUTO
    assert approve(b).status is Status.APPROVED


def test_book_status_is_the_strongest_claim_among_its_copies():
    """Derived, not stored, so it cannot disagree with the copies."""
    b = add_copy(_book(), copy_id="c2")  # c2 is manual
    assert b.copy("c1").status is Status.AUTO
    assert b.status is Status.MANUAL


# --- H5: remove from shelf != delete from library (UI_PLAN §5) ------------

def test_remove_from_shelf_keeps_the_book_the_copy_and_its_history():
    """The book may simply have moved (§5.6). Two destructive actions,
    deliberately separate — this is the non-destructive one."""
    b = observe(_book(shelf_id="s1"), Provenance("r1", "sp1", shelf_id="s1"))
    b = set_work_fields(b, rating=5, notes="חשוב")
    out = remove_from_shelf(b, "c1")

    assert out.copy_count == 1, "removing from a shelf removed the copy"
    assert out.copy("c1").shelf_id is None
    assert len(out.copy("c1").provenance) == 1, "history was discarded"
    assert out.work.rating == 5 and out.work.notes == "חשוב"
    assert out.title == b.title and out.key == b.key


def test_a_book_cannot_be_left_with_no_copies():
    """§5.2: at least one copy. Emptying a book is deleting it, and that is a
    separately-confirmed store operation, not a side effect of an edit."""
    _raises(DomainError, Book, id="b", library_id=LIB, title="t", copies=())


# --- append-only provenance (§5.2) ---------------------------------------

def test_provenance_is_appended_never_overwritten():
    b = _book(shelf_id="s1")
    b = observe(b, Provenance("r1", "sp1", shelf_id="s1", captured_at="2026-01-01"))
    b = observe(b, Provenance("r2", "sp7", shelf_id="s1", captured_at="2026-02-02"))
    prov = b.copy("c1").provenance
    assert [p.sighting for p in prov] == [("r1", "sp1"), ("r2", "sp7")]
    assert prov[0].captured_at == "2026-01-01", "the earlier entry was rewritten"
    assert b.copy("c1").last_seen.run_id == "r2"


def test_replaying_the_same_read_does_not_inflate_history():
    """Idempotent per (run_id, spine_id). That is idempotency, not
    overwriting — no existing entry is modified or dropped."""
    b = _book(shelf_id="s1")
    p = Provenance("r1", "sp1", shelf_id="s1")
    b = observe(b, p)
    b = observe(b, p)
    assert len(b.copy("c1").provenance) == 1


def test_entities_are_frozen_so_history_cannot_be_reassigned():
    """The structural half of 'append-only'."""
    b = _book()
    for target, attr in ((b, "title"), (b.copies[0], "provenance")):
        try:
            setattr(target, attr, "x")
        except Exception:
            continue
        raise AssertionError(f"{type(target).__name__}.{attr} is mutable")


# --- book-level vs copy-level split (§5.2) -------------------------------

def test_user_fields_land_on_the_right_side_of_the_split():
    """A rating describes the work; you don't rate your second copy
    differently. Tags/condition/lending describe the object."""
    book_level = set(vars(_book().work))
    copy_level = set(vars(_book().copies[0].fields))
    assert book_level == {"rating", "notes", "read_status"}
    assert copy_level == {"tags", "condition", "acquired_at"}
    assert hasattr(_book().copies[0], "lending"), "lending is per copy (§5.2)"
    assert not hasattr(_book(), "lending"), "lending must not be book-level"


def test_editing_the_title_marks_every_copy_manual():
    """Title and author are book-level: a person vouched for this identity."""
    b = add_copy(_book(), copy_id="c2")
    out = edit(b, title="ספינות מן המערב")
    assert out.title == "ספינות מן המערב"
    assert all(c.status is Status.MANUAL for c in out.copies)


# --- H5: lending is per copy, never per book (§5.2, P1.7) -----------------
#
# The structural half — Book has no lending attribute, only Copy does — is
# `test_user_fields_land_on_the_right_side_of_the_split` above. These are the
# behavioural half: lending one copy of a multi-copy book must not touch the
# others, and the state machine (out / not out) must refuse a double-lend or
# a return with nothing open.

def test_lending_one_copy_leaves_its_sibling_untouched():
    b = add_copy(_book(), copy_id="c2")
    out = lend(b, "c1", lent_to="דנה", lent_at="2026-08-01", due_at="2026-09-01")
    assert out.copy("c1").lending.lent_to == "דנה"
    assert out.copy("c1").lending.is_out
    assert out.copy("c2").lending is None, "lending leaked onto a sibling copy"


def test_a_copy_already_out_must_be_returned_before_lending_again():
    """Otherwise the earlier borrower's name is silently overwritten — exactly
    the fact "who has my books" (§5.2) exists to answer correctly."""
    b = lend(_book(), "c1", lent_to="דנה", lent_at="2026-08-01")
    exc = _raises(CopyAlreadyLentOut, lend, b, "c1",
                  lent_to="יוסי", lent_at="2026-08-05")
    assert "דנה" in str(exc), "the error should name who has it"


def test_returning_keeps_the_lending_record_as_history():
    """Not cleared to None — same reasoning as provenance being append-only:
    who last borrowed a copy is part of its history, not a transient flag."""
    b = lend(_book(), "c1", lent_to="דנה", lent_at="2026-08-01")
    out = return_copy(b, "c1", returned_at="2026-08-20")
    lending = out.copy("c1").lending
    assert lending is not None and lending.lent_to == "דנה"
    assert lending.returned_at == "2026-08-20"
    assert not lending.is_out


def test_cannot_return_a_copy_that_was_never_lent():
    _raises(CopyNotLentOut, return_copy, _book(), "c1", returned_at="2026-08-20")


def test_cannot_return_a_copy_already_returned():
    b = lend(_book(), "c1", lent_to="דנה", lent_at="2026-08-01")
    b = return_copy(b, "c1", returned_at="2026-08-20")
    _raises(CopyNotLentOut, return_copy, b, "c1", returned_at="2026-08-21")


def test_a_copy_can_be_lent_again_once_returned():
    b = lend(_book(), "c1", lent_to="דנה", lent_at="2026-08-01")
    b = return_copy(b, "c1", returned_at="2026-08-20")
    out = lend(b, "c1", lent_to="יוסי", lent_at="2026-08-21")
    assert out.copy("c1").lending.lent_to == "יוסי"


def test_lending_an_unknown_copy_id_raises():
    _raises(UnknownCopy, lend, _book(), "nope", lent_to="דנה", lent_at="x")


def test_edit_copy_changes_label_and_fields_but_not_status():
    """Object-level metadata is not a claim about the book's IDENTITY, unlike
    editing title/author — so unlike `edit()`, this must not touch status."""
    b = _book()  # c1 is auto
    out = edit_copy(b, "c1", label="כריכה רכה", tags=("מתנה",), condition="טוב")
    assert out.copy("c1").label == "כריכה רכה"
    assert out.copy("c1").fields.tags == ("מתנה",)
    assert out.copy("c1").fields.condition == "טוב"
    assert out.copy("c1").status is Status.AUTO, "a metadata edit must not raise status"


def test_edit_copy_only_touches_fields_that_were_passed():
    b = edit_copy(_book(), "c1", label="כריכה רכה", tags=("מתנה",), condition="טוב")
    out = edit_copy(b, "c1", condition="קרוע")
    assert out.copy("c1").label == "כריכה רכה", "an omitted field was cleared"
    assert out.copy("c1").fields.tags == ("מתנה",), "an omitted field was cleared"
    assert out.copy("c1").fields.condition == "קרוע"


# --- search keys and the P1.3 migration contract --------------------------

def test_book_key_is_byte_identical_to_the_legacy_library_key():
    """P1.3 imports 251 real books out of library.json, which is keyed by
    booksnap.library.book_key. If these two ever disagree the import silently
    becomes a re-keying exercise and duplicates appear."""
    from booksnap.library import book_key as legacy

    for t, a in [("מלכי הכופרים", "פול קארני"),
                 ("הצ'ופצ'יק של הקומקום", "מאיר שלו"),
                 ("שָׁלוֹם עוֹלָם", ""),
                 ("Sapiens", "Yuval Noah Harari"),
                 ("ספר   עם רווחים", "מחבר")]:
        assert book_key(t, a) == legacy(t, a), (t, a)


def test_search_keys_fold_what_the_matcher_folds():
    """The keys are normalize()-derived, so nikud, final letters and in-word
    geresh behave for search exactly as they do for matching."""
    assert _book(title="שָׁלוֹם").normalized_title == "שלומ"
    # geresh DELETED in-word, not space-split — the run-16 lesson.
    assert _book(title="הצ'ופצ'יק").normalized_title == "הצופציק"


def test_author_sorts_by_surname_in_both_shapes_the_real_data_uses():
    """§6's "sort by author" means the shelf order. Sorting the stored string
    files everyone under their GIVEN name, which makes the sort useless for
    finding an author. Both shapes in the owner's 251 books are covered: 232
    are `given surname`, 19 are `surname, given`."""
    from app.domain import author_sort_key

    assert author_sort_key("גרג הורביץ").startswith("הורביצ")
    assert author_sort_key("אסימוב, אייזיק").startswith("אסימוב")
    # A trailing parenthetical is part of "the rest", never the surname.
    assert author_sort_key("מאירי, יואב (אדריכל)").startswith("מאירי")
    # Same surname, different given names: the rest of the name is kept so
    # they order by it instead of falling through to an unrelated tiebreak.
    assert author_sort_key("אבשלום אליצור") > author_sort_key("אברהם אליצור")
    # One-word and empty names must not crash or produce a leading space,
    # which would sort before every real key.
    assert author_sort_key("הומרוס") == "הומרוס"
    assert author_sort_key("") == ""
    assert not author_sort_key("ניל גיימן").startswith(" ")


def test_author_sort_key_is_not_the_author_identity_key():
    """`normalized_author` is what the author FILTER matches on and half the
    search haystack. Reordering it to sort nicely would silently change which
    books an author chip returns, so the two keys are separate on purpose."""
    b = _book(author="גרג הורביץ")
    assert b.normalized_author == "גרג הורביצ"
    assert b.author_sort == "הורביצ גרג"


def test_normalize_is_not_reimplemented_in_the_domain():
    """A copied normalizer drifts, and when it drifts the product's search
    keys stop agreeing with the matcher's. One function, one place."""
    src = (REPO_ROOT / "app" / "domain").rglob("*.py")
    defs = [f.name for f in src
            if "def normalize(" in f.read_text(encoding="utf-8")]
    assert not defs, f"normalize() re-implemented in app/domain: {defs}"


def test_unknown_copy_is_rejected():
    _raises(UnknownCopy, remove_from_shelf, _book(), "nope")


# --- P2.1: shelf identity, without the address (plan §1.1) ----------------

def _shelf(**kw):
    args = dict(id="sh1", library_id=LIB, label="סלון, כוננית 2, מדף 3")
    args.update(kw)
    return new_shelf(**args)


def test_a_shelf_carries_no_address_only_identity():
    """§1.1 splits shelf IDENTITY (here, pillar 2) from shelf ADDRESS (place →
    bookcase → col → level, pillar 6). Structural rather than behavioural on
    purpose: the tempting mistake is to add `bookcase` here "while we're at
    it", and then two modules own an address and the map has to reconcile
    them. Until then the label IS the location, which §1.1 calls enough.
    """
    fields = set(Shelf.__dataclass_fields__)
    address = {"place", "place_id", "bookcase", "bookcase_id", "col",
               "column", "level", "x", "y", "geometry"}
    assert not (fields & address), (
        f"shelf address fields in pillar 2: {sorted(fields & address)}"
    )


def test_depth_is_never_called_row_or_band_in_the_shelf_module():
    """§5.7's named ⚠: `segment.py` already uses *band* for the horizontal
    rows found WITHIN one photo, and `Spine.band` is in the stored record
    format. That is a vertical concept; this one is front-to-back. Someone
    reading `spine_id = IMG_1234_b0_s07` alongside a `shelf.row` would
    reasonably conflate them, and the resulting bug is a book filed in a row
    that does not exist.

    Identifiers only — prose may say "row" (the UI string is *"add a row
    behind this one"*), and the ban is on what code calls it.
    """
    src = (REPO_ROOT / "app" / "domain" / "shelf.py").read_text(encoding="utf-8")
    banned = {"row", "rows", "band", "bands"}
    offenders = sorted({
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(ast.parse(src))
        if (isinstance(node, ast.Name) and node.id in banned)
        or (isinstance(node, ast.Attribute) and node.attr in banned)
    } | {
        a.arg for fn in ast.walk(ast.parse(src))
        if isinstance(fn, ast.FunctionDef)
        for a in fn.args.args + fn.args.kwonlyargs if a.arg in banned
    })
    assert not offenders, (
        f"§5.7: call it depth, never {offenders} — it collides with "
        "segment.py's horizontal bands"
    )


def test_a_shelf_needs_no_label_because_identity_is_free():
    """Owner's call, 2026-08-07, reversing the earlier reading that made the
    label the interim location and therefore mandatory. A shelf must exist and
    be re-findable; it does not have to be described. An unnamed one is shown
    by the image it came from, which the owner recognises without a caption.

    The rule this protects is that capture never becomes a two-step action:
    requiring a label to file the first photo buys an interim answer to "where
    is it?" that pillar 6 replaces anyway.
    """
    anonymous = _shelf(label="")
    assert anonymous.is_named is False
    assert rename_shelf(anonymous, "סלון").is_named is True
    # And back — a label the owner no longer wants is not worth keeping just
    # to avoid an empty string.
    assert rename_shelf(rename_shelf(anonymous, "סלון"), "").is_named is False


def test_unnamed_shelves_order_by_when_they_were_photographed():
    """With labels optional, most early shelves share the empty one — so
    "sorted by label" would be a block of visually identical rows in id order,
    which is arbitrary to the person reading it. Creation order at least
    matches the sequence they were photographed in.

    Named shelves still come first and alphabetically: a shelf someone
    bothered to name is one they will look for by name.
    """
    order = sorted(
        [_shelf(id="c", label="", created_at="2026-08-03"),
         _shelf(id="a", label="", created_at="2026-08-05"),
         _shelf(id="named", label="סלון", created_at="2026-08-01")],
        key=lambda s: s.sort_key,
    )
    assert [s.id for s in order] == ["c", "a", "named"]


def test_depth_is_declared_and_a_capture_cannot_invent_one():
    """§5.7: nothing in an image says "this is the row behind" — the front
    books are simply absent — so depth cannot be detected and must be
    declared. A capture at depth 2 of a one-row shelf would create a location
    with no counterpart in the room, and P2.3 would reconcile against it."""
    shelf = _shelf()
    assert new_capture(shelf, id="cap1").depth == 1
    _raises(UnknownDepth, new_capture, shelf, id="cap2", depth=2)

    deeper = add_depth(shelf)
    assert deeper.depth_count == 2 and deeper.depths == (1, 2)
    assert new_capture(deeper, id="cap2", depth=2).depth == 2


def test_the_wishlist_is_not_furniture_and_does_not_count():
    """The wishlist is `Shelf{virtual: true}` (P2.1) — a real list, kept where
    the user looks for it, but not a place. It has no row behind it, and
    counting it among the shelves inflates both the shelf list and the
    apparent size of a library of books the owner does not own yet."""
    wish = _shelf(id="wish", label="רשימת משאלות", virtual=True)
    assert counts_toward_library(_shelf()) is True
    assert counts_toward_library(wish) is False
    _raises(VirtualShelfHasNoDepth, add_depth, wish)
    _raises(VirtualShelfHasNoDepth, _shelf,
            id="w2", label="x", virtual=True, depth_count=2)


def test_a_capture_is_identified_by_shelf_depth_and_order():
    """§5.3's key, all three parts. Order is what gives a shelf's book list a
    sensible left-to-right sequence; depth is what stops two captures of
    physically different scenes being treated as two views of one."""
    shelf = add_depth(_shelf())
    front = new_capture(shelf, id="cap1", depth=1, order=0)
    behind = new_capture(shelf, id="cap2", depth=2, order=0)
    assert front.slot == ("sh1", 1, 0)
    assert behind.slot == ("sh1", 2, 0)
    assert front.slot != behind.slot, "depth dropped out of a capture's identity"


# --- P2.1: a location is (shelf, depth) together (§5.7) -------------------

def test_a_different_row_of_the_same_shelf_is_a_different_location():
    """§5.7 #3 puts "a different row of the same shelf" in the ASK column of
    §5.4's firing table. Matching on shelf alone would answer it silently, and
    answer it *already-listed* — relinking a copy that never moved onto the
    row behind it, and losing the second copy that is genuinely there."""
    b = _book(shelf_id="sh1", depth=1)
    b = observe(b, Provenance("r1", "sp1", shelf_id="sh1", depth=1))
    assert b.copy("c1").location == ("sh1", 1)

    e = _raises(AmbiguousCopy, observe, b,
                Provenance("r2", "sp9", shelf_id="sh1", depth=2))
    assert "sh1" in str(e)


def test_the_front_row_is_depth_one_however_it_was_written():
    """A copy on a shelf with no depth and one at depth 1 are the same
    physical place. Compared field-by-field they read as two, which would fire
    §5.4's prompt on a book that never moved — so a located copy always
    carries a depth."""
    b = _book(shelf_id="sh1")
    assert b.copy("c1").depth == 1
    b = observe(b, Provenance("r1", "sp1", shelf_id="sh1"))
    assert b.copy("c1").provenance[0].location == ("sh1", 1)
    assert b.copy("c1").location == ("sh1", 1), "the same place read as two"


def test_a_depth_without_a_shelf_is_refused_not_dropped():
    """A row of nothing. It is always a wiring bug — most likely clearing
    `shelf_id` and forgetting `depth` — and dropping it quietly would make
    *remove from shelf* look right while leaking the old row into the next
    place the copy stands."""
    _raises(DomainError, _book, depth=2)
    _raises(DomainError, Provenance, "r1", "sp1", None, None, 2)


def test_removing_from_a_shelf_clears_the_depth_too():
    """The other half of the rule above, and the one a later "simplification"
    would drop: clearing only `shelf_id` raises here rather than silently
    leaving a copy that remembers a row it no longer stands in."""
    b = _book(shelf_id="sh1", depth=2)
    b = remove_from_shelf(b, "c1")
    assert b.copy("c1").location is None
    assert b.copy("c1").depth is None


def test_a_read_adopts_shelf_and_depth_together():
    """An unlocated copy is the one relink a read may perform (§5.4). Adopting
    the shelf without the depth would put the book on the right shelf at
    whatever row it last remembered — which for a fresh copy is none, and for
    a re-used one is wrong."""
    b = _book()
    assert b.copy("c1").location is None
    b = observe(b, Provenance("r1", "sp1", shelf_id="sh7", depth=3))
    assert b.copy("c1").location == ("sh7", 3)


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))
