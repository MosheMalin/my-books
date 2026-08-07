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
    FIRE_TABLE,
    AmbiguousCopy,
    Book,
    Claim,
    ClaimTier,
    CopyAlreadyLentOut,
    CopyNotLentOut,
    DEFAULT_RESOLUTION,
    Decision,
    DecisionKind,
    DomainError,
    DuplicateQuestion,
    FireDecision,
    Provenance,
    PromptKind,
    ReadAlreadyFinished,
    ReadStatus,
    Shelf,
    Status,
    UnknownCopy,
    UnknownDepth,
    VirtualShelfHasNoDepth,
    add_copy,
    add_depth,
    append_claim,
    approve,
    build_prompt,
    capture_onto_a_new_shelf,
    book_key,
    counts_toward_library,
    edit,
    edit_copy,
    fail_read,
    fires,
    finish_read,
    lend,
    new_book,
    new_capture,
    new_read,
    new_shelf,
    observe,
    open_or_refresh,
    pick_default_copy,
    reconcile,
    relink_copy,
    remove_from_shelf,
    rename_shelf,
    return_copy,
    set_work_fields,
    stop_read,
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


def test_observe_refuses_to_move_an_already_located_copy():
    """The other half of the rule `relink_copy` exists to override: a bare
    read must never relocate a copy on its own claim alone, even with an
    explicit copy_id — only a human's §5.4 answer (`relink_copy`) may."""
    b = _book(shelf_id="s1")
    out = observe(b, Provenance("r2", "sp2", shelf_id="s9"), copy_id="c1")
    assert out.copy("c1").shelf_id == "s1", "observe() moved a located copy"


def test_relink_copy_is_the_only_path_that_moves_a_located_copy():
    """§5.4's 'already listed copy' answer, at the domain level: a human
    decision relocates the copy, appends the sighting, and never demotes."""
    b = approve(_book(shelf_id="s1"))
    out = relink_copy(b, "c1", Provenance("r2", "sp2", shelf_id="s9", depth=2))
    assert out.copy("c1").location == ("s9", 2)
    assert [p.sighting for p in out.copy("c1").provenance] == \
        [("r2", "sp2")], "the sighting was not appended"
    assert out.status is Status.APPROVED, "relink must not demote"


def test_relink_copy_is_idempotent_per_sighting():
    b = _book(shelf_id="s1")
    prov = Provenance("r2", "sp2", shelf_id="s9")
    out = relink_copy(b, "c1", prov)
    out = relink_copy(out, "c1", prov)
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


def test_a_photo_that_names_no_shelf_still_gets_one():
    """P2.2's binding rule, in the domain rather than a router because it is a
    decision: EVERY capture has a shelf identity from the moment it exists. A
    photo with no shelf is a read with nothing to reconcile against (§5.6), so
    "assign it later" is deliberately not a state the model offers.

    The shelf comes out unnamed and one row deep — identity is free, so nothing
    is demanded before the first photo can be filed.
    """
    shelf, capture = capture_onto_a_new_shelf(
        shelf_id="sh1", library_id=LIB, capture_id="cap1",
        image_id="IMG_6082", captured_at="2026-08-07",
    )
    assert capture.shelf_id == shelf.id, "the photo was not bound to its shelf"
    assert shelf.is_named is False
    assert shelf.depth_count == 1
    assert capture.slot == ("sh1", 1, 0)
    assert capture.image_id == "IMG_6082"


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


# --- P2.4: Read and Claim ---------------------------------------------------

def _claim(n: int = 1, **kw) -> Claim:
    args = dict(id=f"cl{n}", spine_id=f"sp{n}", capture_id="cap1")
    args.update(kw)
    return Claim(**args)


def test_a_read_is_scoped_to_one_shelf_and_depth_or_it_is_refused():
    """§5.7 #1: "not seen in this read" is only meaningful against the row
    that was actually photographed. A capture from another shelf, or another
    row of this one, must not be able to enter a single Read — both are
    checked, and independently, so a change that keeps only one half would
    still be caught."""
    shelf = _shelf(depth_count=2)
    here = new_capture(shelf, id="cap1", depth=1)
    other_depth = new_capture(shelf, id="cap2", depth=2)
    other_shelf = new_capture(_shelf(id="sh2"), id="cap3", depth=1)

    new_read(shelf, [here], id="r1", depth=1, mode="spines")   # the good case

    e = _raises(DomainError, new_read, shelf, [here, other_depth],
                id="r2", depth=1, mode="spines")
    assert "depth" in str(e)
    e = _raises(DomainError, new_read, shelf, [here, other_shelf],
                id="r3", depth=1, mode="spines")
    assert "shelf" in str(e)


def test_a_read_needs_at_least_one_capture():
    shelf = _shelf()
    _raises(DomainError, new_read, shelf, [], id="r1", depth=1, mode="spines")


def test_a_read_at_an_undeclared_depth_is_refused():
    """Same rule `new_capture` already enforces (§5.7), reached the same way:
    `new_read` takes the Shelf and checks depth against it, so an undeclared
    row cannot enter through this door either."""
    shelf = _shelf()   # depth_count=1
    here = new_capture(shelf, id="cap1", depth=1)
    _raises(UnknownDepth, new_read, shelf, [here], id="r1", depth=2, mode="spines")


def test_a_stopped_read_keeps_its_claims_and_is_not_a_failure():
    """Pipeline.run's own contract, echoed at the domain level: a stopped
    read is a REAL partial result. `error` must stay unset, and the claims
    collected before the stop must survive exactly as `finish_read` would
    leave them."""
    shelf = _shelf()
    cap = new_capture(shelf, id="cap1")
    r = new_read(shelf, [cap], id="r1", depth=1, mode="spines")
    r = append_claim(r, _claim(1))
    r = append_claim(r, _claim(2))

    stopped = stop_read(r, finished_at="2026-08-07T12:00:00+00:00")
    assert stopped.status is ReadStatus.STOPPED
    assert stopped.error is None
    assert [c.id for c in stopped.claims] == ["cl1", "cl2"], \
        "a stop must not discard the claims already collected"


def test_a_failed_read_keeps_its_claims_and_records_why():
    shelf = _shelf()
    cap = new_capture(shelf, id="cap1")
    r = new_read(shelf, [cap], id="r1", depth=1, mode="spines")
    r = append_claim(r, _claim(1))

    failed = fail_read(r, error="no engine credentials",
                       finished_at="2026-08-07T12:00:00+00:00")
    assert failed.status is ReadStatus.FAILED
    assert failed.error == "no engine credentials"
    assert len(failed.claims) == 1, "a failure must not discard prior claims"


def test_claims_cannot_be_appended_after_a_read_finishes():
    """The rule that makes a Read's claims append-only, all the way to the
    end of its life: once terminal, nothing may add more evidence to it —
    reconciliation and copy resolution both read a FINISHED read's claims as
    a fixed snapshot."""
    shelf = _shelf()
    cap = new_capture(shelf, id="cap1")
    r = new_read(shelf, [cap], id="r1", depth=1, mode="spines")
    done = finish_read(r, finished_at="2026-08-07T12:00:00+00:00")

    _raises(ReadAlreadyFinished, append_claim, done, _claim(9))
    _raises(ReadAlreadyFinished, finish_read, done,
            finished_at="2026-08-07T12:00:01+00:00")
    _raises(ReadAlreadyFinished, stop_read, done,
            finished_at="2026-08-07T12:00:01+00:00")
    _raises(ReadAlreadyFinished, fail_read, done, error="x",
            finished_at="2026-08-07T12:00:01+00:00")


def test_a_claim_names_its_spine_and_capture():
    _raises(DomainError, Claim, id="cl1", spine_id="", capture_id="cap1")
    _raises(DomainError, Claim, id="cl1", spine_id="sp1", capture_id="")


def test_claim_tier_defaults_to_unmatched():
    """A claim always exists once a spine was read — even one the matcher had
    nothing to say about — so it needs a real tier value rather than a null
    one standing in for "no match"."""
    assert _claim().tier is ClaimTier.UNMATCHED


# --- P2.5: reconciliation (§5.6) — the pure diff engine --------------------
#
# `reconcile()` is the item's whole point: (shelf state, claims, decisions) ->
# diff. Every named rule from the plan's H5 checklist gets its own test here.

def _rshelf(**kw):
    args = dict(id="sh1", library_id=LIB, depth_count=2)
    args.update(kw)
    return new_shelf(**args)


def _rclaim(n: int = 1, **kw) -> Claim:
    args = dict(id=f"rcl{n}", spine_id=f"rsp{n}", capture_id="cap1",
                title="מלכי הכופרים", author="פול קארני",
                tier=ClaimTier.AUTO, score=90.0)
    args.update(kw)
    return Claim(**args)


def test_a_book_already_here_gets_no_new_record_and_no_review_prompt():
    """§5.6 row 1: same shelf, same depth -> append provenance, nothing else.
    Guards reconcile() routing an already-here match through NEEDS_DECISION
    (a needless question) or ADDED (a second record for a book that never
    moved) instead of UNCHANGED."""
    shelf = _rshelf()
    here = new_book(id="b1", library_id=LIB, title="מלכי הכופרים",
                    author="פול קארני", copy_id="c1", shelf_id="sh1", depth=1)
    diff = reconcile(shelf, 1, [_rclaim()], {here.key: here}, [], read_id="r1")

    assert len(diff.unchanged) == 1
    assert not diff.added and not diff.needs_decision
    outcome = diff.unchanged[0]
    assert outcome.existing_copy_id == "c1"
    assert outcome.reason == "same_location"


def test_a_book_on_another_shelf_asks_instead_of_guessing():
    """§5.4's real case, through reconcile(): a claim matching a book
    confirmed elsewhere in the library goes to needs_decision, never
    silently into added or unchanged."""
    shelf = _rshelf()
    elsewhere = new_book(id="b1", library_id=LIB, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    diff = reconcile(shelf, 1, [_rclaim()], {elsewhere.key: elsewhere}, [],
                     read_id="r1")

    assert not diff.added and not diff.unchanged
    assert len(diff.needs_decision) == 1
    outcome = diff.needs_decision[0]
    assert outcome.reason == "ambiguous_location"
    assert outcome.existing_book.id == "b1"


def test_another_depth_of_the_same_shelf_also_asks():
    """§5.7 #3: a different row of the SAME shelf is a different location,
    not "still here" — the ask fires exactly as for a different shelf."""
    shelf = _rshelf(depth_count=2)
    back_row = new_book(id="b1", library_id=LIB, title="מלכי הכופרים",
                        author="פול קארני", copy_id="c1", shelf_id="sh1", depth=2)
    diff = reconcile(shelf, 1, [_rclaim()], {back_row.key: back_row}, [],
                     read_id="r1")
    assert len(diff.needs_decision) == 1
    assert diff.needs_decision[0].reason == "ambiguous_location"


def test_a_book_not_in_the_library_is_added_at_auto_tier():
    shelf = _rshelf()
    diff = reconcile(shelf, 1, [_rclaim()], {}, [], read_id="r1")
    assert len(diff.added) == 1
    assert not diff.unchanged and not diff.needs_decision
    assert diff.added[0].reason == "new_book_auto"


def test_a_review_tier_new_book_waits_for_a_human_instead_of_auto_entering():
    """The rule `booksnap/library.py::absorb_auto_claims` already applies
    (REVIEW claims wait for an explicit decision), carried into reconcile():
    unlike an AUTO claim, a REVIEW-tier claim for a book the library has
    never heard of must not silently become `added` — `Status` has no
    "pending" rung to create it at honestly."""
    shelf = _rshelf()
    claim = _rclaim(tier=ClaimTier.REVIEW, score=60.0)
    diff = reconcile(shelf, 1, [claim], {}, [], read_id="r1")
    assert not diff.added, "a REVIEW-tier claim auto-entered the library"
    assert len(diff.needs_decision) == 1
    assert diff.needs_decision[0].reason == "review_tier_new_book"


def test_a_previously_rejected_claim_is_never_re_added():
    """§5.6 row 4 — the plan's own words: 'a human decision must not be
    overridden by re-running'. Same rule
    `booksnap/library.py::absorb_auto_claims` already enforces for the
    tuning server, carried into the product's reconciliation."""
    shelf = _rshelf()
    key = book_key("מלכי הכופרים", "פול קארני")
    rejection = Decision(library_id=LIB, shelf_id="sh1", depth=1,
                         book_key=key, kind=DecisionKind.REJECTED)
    diff = reconcile(shelf, 1, [_rclaim()], {}, [rejection], read_id="r1")
    assert not diff.added, "a rejected claim was re-added"
    assert len(diff.rejected) == 1
    assert diff.rejected[0].reason == "rejected"


def test_a_wrong_book_decision_suppresses_the_ambiguous_claim_too():
    """§5.4's third answer, replayed: once a human says "not this book",
    the SAME (shelf, depth, book_key) never asks — or adds — again."""
    shelf = _rshelf()
    elsewhere = new_book(id="b1", library_id=LIB, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    wrong = Decision(library_id=LIB, shelf_id="sh1", depth=1,
                     book_key=elsewhere.key, kind=DecisionKind.WRONG_BOOK)
    diff = reconcile(shelf, 1, [_rclaim()], {elsewhere.key: elsewhere},
                     [wrong], read_id="r1")
    assert not diff.needs_decision and not diff.unchanged and not diff.added
    assert len(diff.rejected) == 1
    assert diff.rejected[0].reason == "wrong_book"


def test_approval_survives_a_worse_re_read_through_reconcile():
    """§5.6 row 5: reconcile() must route an already-here match to
    `unchanged` REGARDLESS of how weak this read's claim is — never to
    needs_decision (re-questioning an approved book) or added (duplicating
    it). `Status.merge`'s own never-demote guarantee (already covered at the
    book level) is what then keeps APPROVED once the outcome is applied."""
    shelf = _rshelf()
    approved = approve(new_book(id="b1", library_id=LIB, title="מלכי הכופרים",
                                author="פול קארני", copy_id="c1",
                                shelf_id="sh1", depth=1))
    weak_claim = _rclaim(tier=ClaimTier.REVIEW, score=12.0)
    diff = reconcile(shelf, 1, [weak_claim], {approved.key: approved}, [],
                     read_id="r1")
    assert len(diff.unchanged) == 1
    assert diff.unchanged[0].existing_book.status is Status.APPROVED
    assert not diff.needs_decision, "a weaker re-read re-questioned an approved book"


def test_a_book_this_read_did_not_find_is_reported_not_seen_never_removed():
    """§5.6's central rule: absence from one read is weak evidence (measured
    recall 0.78-0.83). reconcile() reports the fact; there is no operation
    here that removes anything — not_seen carries the UNMODIFIED book."""
    shelf = _rshelf()
    here = new_book(id="b1", library_id=LIB, title="ספר שלא נקרא", author="",
                    copy_id="c1", shelf_id="sh1", depth=1)
    diff = reconcile(shelf, 1, [], {here.key: here}, [], read_id="r1")
    assert not diff.added and not diff.unchanged and not diff.needs_decision
    assert len(diff.not_seen) == 1
    assert diff.not_seen[0].book is here, "not_seen must carry the SAME, unmodified book"
    assert diff.not_seen[0].copy_id == "c1"


def test_not_seen_is_scoped_to_the_depth_actually_read():
    """§5.7 #1: a front-row re-read of a 3-row shelf must not flag the other
    rows' books as missing — comparing against the whole shelf would flag
    two thirds of it, every single time."""
    shelf = _rshelf(depth_count=3)
    front = new_book(id="b1", library_id=LIB, title="ספר קדמי", author="",
                     copy_id="c1", shelf_id="sh1", depth=1)
    middle = new_book(id="b2", library_id=LIB, title="ספר אמצעי", author="",
                      copy_id="c2", shelf_id="sh1", depth=2)
    back = new_book(id="b3", library_id=LIB, title="ספר אחורי", author="",
                    copy_id="c3", shelf_id="sh1", depth=3)
    books = {b.key: b for b in (front, middle, back)}
    claim = _rclaim(title="ספר קדמי", author="")
    diff = reconcile(shelf, 1, [claim], books, [], read_id="r1")

    assert len(diff.unchanged) == 1 and diff.unchanged[0].existing_book.id == "b1"
    assert diff.not_seen == (), (
        "a front-row read flagged books on OTHER rows as not seen"
    )


def test_two_captures_of_one_depth_claiming_the_same_book_collapse_to_one():
    """§5.7 #2: overlap dedup applies WITHIN a depth. Two claims (as two
    overlapping captures of one row would each produce) naming the same book
    must collapse to ONE outcome — never two records, and never an
    ambiguous "second copy" ask for a book that never left the shelf."""
    shelf = _rshelf()
    weak = _rclaim(1, capture_id="capA", score=70.0)
    strong = _rclaim(2, capture_id="capB", score=91.0)
    diff = reconcile(shelf, 1, [weak, strong], {}, [], read_id="r1")

    assert len(diff.added) == 1, "an overlap produced two records for one book"
    assert diff.added[0].claim.id == "rcl2", "the higher-score claim should win"
    assert len(diff.ignored) == 1
    assert diff.ignored[0].reason == "duplicate_within_depth"
    assert diff.ignored[0].superseded_by == "rcl2"


def test_an_already_listed_decision_relinks_without_asking_again():
    """The `corrected` bucket's main case: once a human has answered §5.4's
    prompt with "already listed copy", a REPEAT of the exact same (shelf,
    depth, book_key) applies it automatically — no second ask."""
    shelf = _rshelf()
    elsewhere = new_book(id="b1", library_id=LIB, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    already = Decision(library_id=LIB, shelf_id="sh1", depth=1,
                       book_key=elsewhere.key, kind=DecisionKind.ALREADY_LISTED,
                       copy_id="c1")
    diff = reconcile(shelf, 1, [_rclaim()], {elsewhere.key: elsewhere},
                     [already], read_id="r1")
    assert not diff.needs_decision
    assert len(diff.corrected) == 1
    outcome = diff.corrected[0]
    assert outcome.existing_copy_id == "c1"
    assert outcome.reason == "relinked_by_decision"


def test_an_another_copy_decision_replays_without_asking_again():
    """§5.4's second answer, replayed the same way — but this ends in a
    fresh copy, so unlike the relink case there is no existing id to carry."""
    shelf = _rshelf()
    elsewhere = new_book(id="b1", library_id=LIB, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    another = Decision(library_id=LIB, shelf_id="sh1", depth=1,
                       book_key=elsewhere.key, kind=DecisionKind.ANOTHER_COPY)
    diff = reconcile(shelf, 1, [_rclaim()], {elsewhere.key: elsewhere},
                     [another], read_id="r1")
    assert not diff.needs_decision
    assert len(diff.corrected) == 1
    outcome = diff.corrected[0]
    assert outcome.existing_copy_id is None, "a fresh copy has no id yet"
    assert outcome.reason == "new_copy_by_decision"


def test_a_stale_already_listed_decision_falls_back_to_asking():
    """The decision names a copy that no longer exists (it was deleted, or
    the id was simply wrong) — reconcile() must not crash or silently
    misresolve; it asks again rather than guessing."""
    shelf = _rshelf()
    elsewhere = new_book(id="b1", library_id=LIB, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    stale = Decision(library_id=LIB, shelf_id="sh1", depth=1,
                     book_key=elsewhere.key, kind=DecisionKind.ALREADY_LISTED,
                     copy_id="gone")
    diff = reconcile(shelf, 1, [_rclaim()], {elsewhere.key: elsewhere},
                     [stale], read_id="r1")
    assert len(diff.needs_decision) == 1
    assert diff.needs_decision[0].reason == "ambiguous_location"


def test_a_book_already_here_wins_over_a_stale_suppressing_decision():
    """Ordering matters: reconcile() checks "is it already standing here"
    BEFORE consulting decisions, so a leftover REJECTED/WRONG_BOOK decision
    from before the book existed at this location cannot suppress a claim
    that is now correctly reconfirming it."""
    shelf = _rshelf()
    here = new_book(id="b1", library_id=LIB, title="מלכי הכופרים",
                    author="פול קארני", copy_id="c1", shelf_id="sh1", depth=1)
    stale_reject = Decision(library_id=LIB, shelf_id="sh1", depth=1,
                            book_key=here.key, kind=DecisionKind.REJECTED)
    diff = reconcile(shelf, 1, [_rclaim()], {here.key: here}, [stale_reject],
                     read_id="r1")
    assert len(diff.unchanged) == 1, "a stale decision suppressed a real match"
    assert not diff.rejected


def test_a_decision_from_a_different_location_is_refused_not_silently_dropped():
    """Defense in depth: reconcile()'s caller must pre-scope decisions to
    the EXACT (shelf, depth) being reconciled. A mismatched one is a wiring
    bug and must be loud — silently skipping it would look identical to
    "no decision yet" and mask the bug."""
    shelf = _rshelf()
    wrong_depth = Decision(library_id=LIB, shelf_id="sh1", depth=2,
                           book_key="x|y", kind=DecisionKind.REJECTED)
    _raises(DomainError, reconcile, shelf, 1, [], {}, [wrong_depth], read_id="r1")


def test_reconcile_refuses_an_undeclared_depth():
    shelf = _rshelf()  # depth_count=2
    _raises(UnknownDepth, reconcile, shelf, 5, [], {}, [], read_id="r1")


def test_a_claim_with_no_title_has_no_book_identity():
    shelf = _rshelf()
    blank = _rclaim(title="", author="")
    diff = reconcile(shelf, 1, [blank], {}, [], read_id="r1")
    assert not diff.added and not diff.unchanged and not diff.needs_decision
    assert len(diff.ignored) == 1
    assert diff.ignored[0].reason == "no_identity"


# --- P2.6: copy resolution — the fire/never-fire table (§5.4) --------------
#
# One named test per row of FIRE_TABLE, each driving the REAL reconcile()
# through the exact situation the row describes and cross-checking the
# outcome's reason against fires() — so a table edited without a matching
# change to reconcile() (or the reverse) is a loud mismatch here, not a
# silent drift between documentation and behaviour.

def test_fire_row_two_spines_same_shelf_same_run_never_asks():
    shelf = _rshelf()
    weak = _rclaim(1, capture_id="capA", score=70.0)
    strong = _rclaim(2, capture_id="capA", score=91.0)
    diff = reconcile(shelf, 1, [weak, strong], {}, [], read_id="r1")

    assert len(diff.added) == 1, "the pair did not collapse to one outcome"
    ignored = [o for o in diff.ignored if o.reason == "duplicate_within_depth"]
    assert len(ignored) == 1
    assert fires(ignored[0].reason) is FireDecision.NEVER_ASK


def test_fire_row_same_shelf_and_depth_later_run_never_asks():
    shelf = _rshelf()
    here = new_book(id="b1", library_id=LIB, title="מלכי הכופרים",
                    author="פול קארני", copy_id="c1", shelf_id="sh1", depth=1)
    diff = reconcile(shelf, 1, [_rclaim()], {here.key: here}, [], read_id="r1")

    assert len(diff.unchanged) == 1
    assert not diff.needs_decision
    assert fires(diff.unchanged[0].reason) is FireDecision.NEVER_ASK


def test_fire_row_overlapping_captures_at_one_depth_never_asks():
    """Two DIFFERENT captures (unlike the same-run row above, which uses one)
    claiming the same book at one depth — §5.3's overlap dedup. Mechanically
    the SAME collapse as the same-run row (both are `duplicate_within_depth`),
    which is exactly what FIRE_TABLE says: two situations, one mechanism."""
    shelf = _rshelf()
    from_capture_a = _rclaim(1, capture_id="capA", score=80.0)
    from_capture_b = _rclaim(2, capture_id="capB", score=85.0)
    diff = reconcile(shelf, 1, [from_capture_a, from_capture_b], {}, [],
                     read_id="r1")

    assert len(diff.added) == 1
    ignored = [o for o in diff.ignored if o.reason == "duplicate_within_depth"]
    assert len(ignored) == 1
    assert fires(ignored[0].reason) is FireDecision.NEVER_ASK


def test_fire_row_a_different_shelf_row_or_library_asks():
    shelf = _rshelf()
    elsewhere = new_book(id="b1", library_id=LIB, title="מלכי הכופרים",
                         author="פול קארני", copy_id="c1", shelf_id="sh9", depth=1)
    diff = reconcile(shelf, 1, [_rclaim()], {elsewhere.key: elsewhere}, [],
                     read_id="r1")

    assert len(diff.needs_decision) == 1
    outcome = diff.needs_decision[0]
    assert outcome.reason == "ambiguous_location"
    assert fires(outcome.reason) is FireDecision.ASK


def test_fire_table_rows_sharing_a_reason_agree_with_each_other():
    """Rows 1 and 3 both resolve through `duplicate_within_depth` — this
    asserts the table itself is not self-contradictory, which is the thing
    that would make fires() return a decision depending on which row a
    caller happened to think of first."""
    by_reason: dict[str, set] = {}
    for rule in FIRE_TABLE:
        by_reason.setdefault(rule.reconcile_reason, set()).add(rule.decision)
    disagreements = {r: d for r, d in by_reason.items() if len(d) > 1}
    assert not disagreements, f"FIRE_TABLE disagrees with itself: {disagreements}"


def test_fires_refuses_a_reason_outside_the_table():
    """review_tier_new_book is a REAL reconcile() reason, but it answers a
    different question ("is this a real book?", not "which copy is this?")
    and was never a candidate for §5.4's prompt. Silently returning
    NEVER_ASK for it would be indistinguishable from the table having
    covered it on purpose."""
    _raises(DomainError, fires, "review_tier_new_book")
    _raises(DomainError, fires, "no_identity")
    _raises(DomainError, fires, "some_future_reason_nobody_wrote_yet")


# --- P2.6: the two cheap wins (§5.4) ---------------------------------------

def test_pick_default_copy_prefers_an_unlocated_copy():
    """§5.4: 'default to the copy that has no shelf assigned' — checked
    FIRST, ahead of recency, even when a located copy was seen very
    recently and the unlocated one never has been."""
    b = _book(shelf_id="sh1", depth=1)  # copy c1, located
    b = add_copy(b, copy_id="c2")       # copy c2, never located
    assert pick_default_copy(b).id == "c2"


def test_pick_default_copy_falls_back_to_least_recently_seen():
    """§5.4: '...or the least-recently-seen', once every copy has somewhere
    to be — the copy whose last sighting is oldest is the one most likely
    to be the object that just reappeared somewhere new."""
    b = _book(shelf_id="sh1", depth=1)
    b = add_copy(b, copy_id="c2", shelf_id="sh2", depth=1)
    b = observe(b, Provenance("r-old", "sp-old", shelf_id="sh1", depth=1,
                              captured_at="2020-01-01T00:00:00Z"), copy_id="c1")
    b = observe(b, Provenance("r-new", "sp-new", shelf_id="sh2", depth=1,
                              captured_at="2026-01-01T00:00:00Z"), copy_id="c2")
    assert pick_default_copy(b).id == "c1", "the OLDER sighting should win"


def test_pick_default_copy_treats_no_provenance_as_least_recently_seen():
    """A copy declared by hand (P1.7's 'I have another copy') and never
    actually read has no sighting at all — the extreme case of 'least
    recently seen', so it must win over a located copy that HAS been seen,
    however long ago."""
    b = _book(shelf_id="sh1", depth=1)
    b = observe(b, Provenance("r1", "sp1", shelf_id="sh1", depth=1,
                              captured_at="2020-01-01T00:00:00Z"), copy_id="c1")
    b = add_copy(b, copy_id="c2", shelf_id="sh2", depth=1)  # never read
    assert pick_default_copy(b).id == "c2"


def test_build_prompt_is_the_plain_three_way_by_default():
    b = _book(shelf_id="sh1", depth=1)
    prompt = build_prompt(b)
    assert prompt.kind is PromptKind.THREE_WAY
    assert prompt.candidate_copy_id == "c1"
    assert prompt.lent_to is None


def test_build_prompt_asks_the_sharper_question_when_the_candidate_is_lent_out():
    """§5.4's first cheap win: 'if the existing copy is marked lent out and
    now shows up on a shelf, ask the better question — you lent this to
    Dana — is it back?'"""
    b = _book(shelf_id="sh1", depth=1)
    b = lend(b, "c1", lent_to="דנה", lent_at="2026-08-01T00:00:00Z")
    prompt = build_prompt(b)
    assert prompt.kind is PromptKind.LENT_OUT_RETURN
    assert prompt.candidate_copy_id == "c1"
    assert prompt.lent_to == "דנה"


def test_build_prompt_ignores_a_returned_loan():
    """A copy that WAS lent and has since come back must not trigger the
    lent-out question — Lending.is_out, not merely Lending is not None, is
    the check."""
    b = _book(shelf_id="sh1", depth=1)
    b = lend(b, "c1", lent_to="דנה", lent_at="2026-08-01T00:00:00Z")
    b = return_copy(b, "c1", returned_at="2026-08-05T00:00:00Z")
    prompt = build_prompt(b)
    assert prompt.kind is PromptKind.THREE_WAY


def test_build_prompt_only_checks_the_default_candidate_not_any_copy():
    """A DIFFERENT copy being lent out must not leak the sharper question
    onto a prompt about the unlocated candidate — the two cheap wins share
    one candidate on purpose (build_prompt's own docstring), so a lent-out
    copy that pick_default_copy would never pick must not change anything."""
    b = _book(shelf_id="sh1", depth=1)
    b = lend(b, "c1", lent_to="דנה", lent_at="2026-08-01T00:00:00Z")
    b = add_copy(b, copy_id="c2")  # unlocated -- this is the default candidate
    prompt = build_prompt(b)
    assert prompt.kind is PromptKind.THREE_WAY
    assert prompt.candidate_copy_id == "c2"


# --- P2.6: the default when a question is skipped (§5.4) -------------------

def test_default_resolution_is_already_listed():
    """§5.4, verbatim: 'default when the question is skipped or the run is
    never reviewed: already listed copy'. A missed duplicate is mildly
    wrong and trivially fixed later; an invented one is a phantom that rots
    silently — see test_reconcile_apply.py / test_api.py for the end-to-end
    proof that using this default really does relink rather than duplicate;
    this test pins the constant a reversal would have to change first."""
    assert DEFAULT_RESOLUTION is DecisionKind.ALREADY_LISTED


# --- P2.6: the durable queue entity -----------------------------------------

def test_open_or_refresh_opens_a_fresh_question():
    q = open_or_refresh(
        None, new_id="q1", library_id=LIB, shelf_id="sh1", depth=1,
        book_key="k|a", read_id="r1", spine_id="sp1", claim_title="t",
        claim_author="a", existing_book_id="b1", when="2026-08-07T00:00:00Z",
        captured_at="2026-08-01T00:00:00Z",
    )
    assert q.id == "q1"
    assert q.opened_at == "2026-08-07T00:00:00Z"


def test_open_or_refresh_preserves_the_original_id_and_opened_at():
    """A re-skip on a LATER read of the same (shelf, depth, book_key) must
    not reset how long the question has been waiting, and must not change
    the URL a client may already have open on it."""
    first = open_or_refresh(
        None, new_id="q1", library_id=LIB, shelf_id="sh1", depth=1,
        book_key="k|a", read_id="r1", spine_id="sp1", claim_title="t",
        claim_author="a", existing_book_id="b1", when="2026-08-01T00:00:00Z",
        captured_at="2026-08-01T00:00:00Z",
    )
    refreshed = open_or_refresh(
        first, new_id="q2-should-be-ignored", library_id=LIB, shelf_id="sh1",
        depth=1, book_key="k|a", read_id="r2", spine_id="sp9",
        claim_title="t2", claim_author="a2", existing_book_id="b1",
        when="2026-08-07T00:00:00Z", captured_at="2026-08-07T00:00:00Z",
    )
    assert refreshed.id == "q1", "the id must survive a refresh"
    assert refreshed.opened_at == "2026-08-01T00:00:00Z", (
        "opened_at must survive a refresh, not reset to the later read's time"
    )
    # But the claim context DOES update -- the LATEST sighting is what a
    # human should see when they finally look at the queue.
    assert refreshed.read_id == "r2" and refreshed.claim_title == "t2"


def test_duplicate_question_requires_a_shelf_and_a_positive_depth():
    _raises(DomainError, DuplicateQuestion, id="q1", library_id=LIB,
           shelf_id="", depth=1, book_key="k|a", read_id="r1", spine_id="sp1",
           claim_title="t", claim_author="a", existing_book_id="b1",
           opened_at="2026-08-01T00:00:00Z")
    _raises(DomainError, DuplicateQuestion, id="q1", library_id=LIB,
           shelf_id="sh1", depth=0, book_key="k|a", read_id="r1",
           spine_id="sp1", claim_title="t", claim_author="a",
           existing_book_id="b1", opened_at="2026-08-01T00:00:00Z")


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))
