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
    Account,
    AmbiguousCopy,
    Book,
    Capability,
    Claim,
    ClaimTier,
    CopyAlreadyLentOut,
    CopyNotLentOut,
    DEFAULT_RESOLUTION,
    Decision,
    DecisionKind,
    DepthStatus,
    DiffSummary,
    DomainError,
    DuplicateQuestion,
    FIRE_TABLE,
    FireDecision,
    Library,
    LibraryNeedsAName,
    Membership,
    NoAdminLeft,
    POLICY,
    PolicyUndeclared,
    PromptKind,
    Provenance,
    Read,
    ReadAlreadyFinished,
    ReadStatus,
    RetractAction,
    Role,
    Shelf,
    Status,
    UnknownCopy,
    UnknownDepth,
    UnknownMember,
    User,
    VirtualShelfHasNoDepth,
    add_copy,
    add_depth,
    allowed,
    append_claim,
    approve,
    book_key,
    build_prompt,
    capture_onto_a_new_shelf,
    counts_toward_library,
    deletion_sites,
    depth_staleness,
    edit,
    edit_copy,
    fail_read,
    finish_read,
    fires,
    lend,
    new_account,
    new_book,
    new_capture,
    new_library,
    new_read,
    new_shelf,
    not_seen_streak,
    observe,
    open_or_refresh,
    pick_default_copy,
    plan_retraction,
    reconcile,
    relink_copy,
    remove_from_shelf,
    remove_member,
    rename_library,
    rename_shelf,
    return_copy,
    set_role,
    set_work_fields,
    stop_read,
    summarize,
    with_diff_summary,
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


def _banned_names(src: str, banned: set[str]) -> list[str]:
    """Every identifier in ``src`` that is one of ``banned``.

    ⚠ Six kinds of identifier, and five were added after a review measured
    them missing: a ``class Row``, a positional-only parameter, a lambda's
    parameter, an ``async def``'s parameter and a keyword argument all slipped
    through the first version, which walked only ``Name``, ``Attribute`` and a
    plain ``def``'s ordinary args. A lint with holes reads exactly like a lint
    without them.
    """
    tree = ast.parse(src)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in banned:
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in banned:
            found.add(node.attr)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef,
                               ast.AsyncFunctionDef)) and node.name in banned:
            found.add(node.name)
        elif isinstance(node, ast.keyword) and node.arg in banned:
            found.add(node.arg)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Lambda)):
            args = node.args
            for a in (args.posonlyargs + args.args + args.kwonlyargs
                      + [x for x in (args.vararg, args.kwarg) if x]):
                if a.arg in banned:
                    found.add(a.arg)
    return sorted(found)


def test_the_depth_naming_lint_can_actually_see_a_violation():
    """Gate the DETECTOR on a synthetic corpus, the way CLAUDE.md's dead-key
    trap says to: against the real modules the rule is unobservable once they
    are clean, so a lint that quietly stopped working would pass forever.

    Every line below is a shape that survived the first version of the check.
    """
    corpus = (
        "class Row:\n    pass\n"
        "def a(row, /): return row\n"
        "async def b(band): return band\n"
        "c = lambda rows: rows\n"
        "def d(*, bands): return bands\n"
        "def e(): f(row=1)\n"
        "def g(*band): pass\n"
    )
    caught = _banned_names(corpus, {"row", "rows", "band", "bands", "Row"})
    assert caught == ["Row", "band", "bands", "row", "rows"], caught
    assert _banned_names("def fine(depth, level, col): return depth",
                         {"row", "rows", "band", "bands"}) == []


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
    banned = {"row", "rows", "band", "bands"}
    # ⚠ FOUR modules since P6.1, not one. `place.py` and `map_edit.py` are the
    # likeliest to break the rule because they are full of grids: a section
    # has columns ACROSS and levels DOWN, and "row" is the word an unwary
    # reader reaches for to mean a level. It would then sit two lines from a
    # depth, which is exactly the collision §5.7 named. A review found the
    # scope stopping at `app/domain/`, so the grid arithmetic was outside it.
    # SIX since P6.4b: the undo journal is written in terms of the grid it
    # puts back, so it reaches for the same wrong word — and it caught one on
    # the day it was written (a local named `rows`, holding tables).
    # EIGHT since P6.4d, and the two new ones are the likeliest yet: a merge
    # is written in terms of TABLES, so "row" arrives meaning a database row
    # and lands two lines from a `depth` that means a shelf's row of books.
    # The undo journal caught one the day it was written and the merge caught
    # three the day this list grew.
    for module in ("app/domain/shelf.py", "app/domain/place.py",
                   "app/domain/map_undo.py", "app/domain/merge.py",
                   "app/map_edit.py", "app/map_merge.py",
                   "app/map_undo.py", "app/ports/map.py"):
        src = (REPO_ROOT / module).read_text(encoding="utf-8")
        offenders = _banned_names(src, banned)
        assert not offenders, (
            f"§5.7: in {module}, call it depth or level, never {offenders} — "
            "it collides with segment.py's horizontal bands"
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

    ⚠⚠ **This function said that and asserted its opposite.** The assertion
    read `["c", "a", "named"]` — the named shelf LAST — because a key
    beginning with the label puts the empty string first, and the sentence
    above, `Shelf.sort_key`'s docstring, `GET /shelves`'s docstring and both
    store implementations all agreed with each other about the intent while
    the code did the reverse. Nothing was red for four schema versions.
    P6.4c's picker is the first screen where the order is a decision aid, and
    that is where a review finally read it.
    """
    order = sorted(
        [_shelf(id="c", label="", created_at="2026-08-03"),
         _shelf(id="a", label="", created_at="2026-08-05"),
         _shelf(id="named", label="סלון", created_at="2026-08-01")],
        key=lambda s: s.sort_key,
    )
    assert [s.id for s in order] == ["named", "c", "a"]


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


def test_nothing_a_machine_read_enters_the_library_unapproved():
    """⚠ REVERSED 2026-08-09 (owner), and this test with it. reconcile() used
    to auto-enter an AUTO-tier claim, mirroring
    `booksnap/library.py::absorb_auto_claims`; the owner watched one real
    photo file fourteen books he was never asked about and called it wrong.
    UI_PLAN §6 already plans "auto-approve AUTO" as a Settings toggle — until
    it exists its value is OFF, and this is the test that keeps it off.

    Both machine tiers land in the SAME bucket now: tier decides how a
    finding is PRESENTED, never whether it enters."""
    shelf = _rshelf()
    for tier, score in ((ClaimTier.AUTO, 91.0), (ClaimTier.REVIEW, 60.0)):
        diff = reconcile(shelf, 1, [_rclaim(tier=tier, score=score)], {}, [],
                         read_id="r1")
        assert not diff.added, f"a {tier.value} claim entered without approval"
        assert len(diff.needs_decision) == 1
        assert diff.needs_decision[0].reason == "new_book_unconfirmed"


def test_a_book_the_owner_typed_in_needs_no_approval():
    """The one exception, and the reason it is not a hole: there is nobody
    left to ask. §5.1's ladder puts a person's word above every machine tier,
    so a hand-added finding enters at once — asking a human to approve what
    they just typed is the kind of ceremony that trains people to click
    through prompts."""
    shelf = _rshelf()
    diff = reconcile(shelf, 1, [_rclaim(tier=ClaimTier.MANUAL, score=0.0)],
                     {}, [], read_id="r1")
    assert len(diff.added) == 1
    assert not diff.needs_decision
    assert diff.added[0].reason == "manual_add"


def test_a_claim_answered_with_a_different_title_reads_as_settled():
    """⚠ Found LIVE (2026-08-09), by picking one of explain()'s runners-up
    and watching the row stay "awaiting approval".

    A claim's identity is the text the ENGINE read, frozen forever because it
    is evidence. A human answering it with different text — approve-as-
    corrected, pick a runner-up, or edit the book afterwards — creates a book
    under a DIFFERENT key. Keyed lookup alone then reports the claim as still
    unanswered, so the finding never settles and the next click makes a
    SECOND book. `Provenance.sighting` is what actually answers "which book
    did this spine produce"."""
    shelf = _rshelf()
    corrected = new_book(id="b1", library_id=LIB, title="ספר אחר לגמרי",
                         author="מישהו", copy_id="c1", shelf_id="sh1", depth=1,
                         provenance=(Provenance(run_id="r1", spine_id="rsp1",
                                                shelf_id="sh1", depth=1),))
    diff = reconcile(shelf, 1, [_rclaim()], {corrected.key: corrected}, [],
                     read_id="r1")

    assert not diff.needs_decision, "the answered claim was asked about again"
    assert len(diff.unchanged) == 1
    assert diff.unchanged[0].existing_book.id == "b1"
    assert diff.unchanged[0].book_key == corrected.key


def test_a_sighting_from_another_read_does_not_settle_this_claim():
    """The check is scoped to THIS read's own (run_id, spine_id) — a book
    another read placed here is a different question, and answering it
    silently would skip §5.4 entirely."""
    shelf = _rshelf()
    other = new_book(id="b1", library_id=LIB, title="ספר אחר לגמרי",
                     author="מישהו", copy_id="c1", shelf_id="sh1", depth=1,
                     provenance=(Provenance(run_id="an-older-read",
                                            spine_id="rsp1", shelf_id="sh1",
                                            depth=1),))
    diff = reconcile(shelf, 1, [_rclaim()], {other.key: other}, [],
                     read_id="r1")
    assert len(diff.needs_decision) == 1


def test_a_claims_book_that_has_since_moved_does_not_settle_it():
    """§5.7 #1: the copy is not here any more, so this row's read has nothing
    standing in it — the claim is open again, not silently satisfied by a
    book on another shelf."""
    shelf = _rshelf()
    moved = new_book(id="b1", library_id=LIB, title="ספר אחר לגמרי",
                     author="מישהו", copy_id="c1", shelf_id="sh9", depth=1,
                     provenance=(Provenance(run_id="r1", spine_id="rsp1",
                                            shelf_id="sh1", depth=1),))
    diff = reconcile(shelf, 1, [_rclaim()], {moved.key: moved}, [],
                     read_id="r1")
    assert len(diff.needs_decision) == 1


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

    # ONE surviving outcome, whichever bucket it lands in — the bucket moved
    # on 2026-08-09 (a new book now waits for approval), the dedup rule this
    # test is about did not.
    survivors = [*diff.added, *diff.needs_decision, *diff.unchanged]
    assert len(survivors) == 1, "an overlap produced two records for one book"
    assert survivors[0].claim.id == "rcl2", "the higher-score claim should win"
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

    assert len([*diff.added, *diff.needs_decision]) == 1,         "the pair did not collapse to one outcome"
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

    assert len([*diff.added, *diff.needs_decision]) == 1
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


# --- P2.8: the diff summary snapshot (§5.5/§5.6) ---------------------------

def test_summarize_captures_the_headline_counts_from_a_real_diff():
    """The plan's own example, literally: reconcile() -> summarize() must
    read as "+N added · N corrected · N unchanged · N not seen" for a diff
    shaped that way. Built from a real `reconcile()` call, not a hand-typed
    Diff, so this also exercises the wiring between the two functions.

    Note the shape after the 2026-08-09 reversal: a book the reader found and
    the library has never heard of counts as **needs_decision**, not `added`,
    and `added` now means only "a human typed it in". A history row for an
    engine read therefore leads with the pending count, which is the honest
    account of what that read did — it found things and asked."""
    shelf = _rshelf(depth_count=2)
    here = new_book(id="b1", library_id=LIB, title="מלכי הכופרים",
                    author="פול קארני", copy_id="c1", shelf_id="sh1", depth=1)
    missing = new_book(id="b2", library_id=LIB, title="ספר שלא נקרא",
                       author="", copy_id="c2", shelf_id="sh1", depth=1)
    books = {here.key: here, missing.key: missing}
    claims = [_rclaim(), _rclaim(2, title="ספר חדש", author="סופר"),
              _rclaim(3, title="ספר שהוקלד ביד", author="", tier=ClaimTier.MANUAL)]
    diff = reconcile(shelf, 1, claims, books, [], read_id="r1")

    summary = summarize(diff)
    assert summary == DiffSummary(added=1, unchanged=1, needs_decision=1,
                                  not_seen=1)
    assert summary.corrected == 0


def test_with_diff_summary_attaches_it_to_the_read():
    r = new_read(_shelf(), [new_capture(_shelf(), id="cap1")], id="r1",
                depth=1, mode="spines")
    r = finish_read(r, finished_at="2026-08-07T12:00:00+00:00")
    summarised = with_diff_summary(r, DiffSummary(added=3, corrected=1,
                                                  unchanged=12, not_seen=1))
    assert summarised.diff_summary == DiffSummary(added=3, corrected=1,
                                                   unchanged=12, not_seen=1)
    # The ORIGINAL read is untouched — same frozen-dataclass discipline as
    # every other domain operation (§5.2's "operations return a NEW object").
    assert r.diff_summary is None


# --- P2.8: not_seen_streak — the soft badge, never a removal (§5.6) --------
#
# `app.domain.history.not_seen_streak` derives a display count from a copy's
# own append-only provenance and a shelf's read archive. It has no way to
# remove anything (see the module docstring) — the removal rule itself is
# `reconcile()`'s (already covered above); these tests are about the COUNT.

def _hread(n: int, *, depth: int = 1, status: ReadStatus = ReadStatus.DONE,
          finished_at: str) -> Read:
    shelf = _rshelf(depth_count=3)
    cap = new_capture(shelf, id=f"hcap{n}", depth=depth)
    r = new_read(shelf, [cap], id=f"hr{n}", depth=depth, mode="spines",
                started_at=finished_at)
    if status is ReadStatus.DONE:
        r = finish_read(r, finished_at=finished_at)
    elif status is ReadStatus.STOPPED:
        r = stop_read(r, finished_at=finished_at)
    elif status is ReadStatus.FAILED:
        r = fail_read(r, error="boom", finished_at=finished_at)
    return r


def _copy_at(book: Book, copy_id: str = "c1") -> "Copy":
    return next(c for c in book.copies if c.id == copy_id)


def test_not_seen_streak_is_zero_when_the_most_recent_read_saw_it():
    r1 = _hread(1, finished_at="2026-08-01T00:00:00+00:00")
    book = observe(
        new_book(id="b1", library_id=LIB, title="ספר", author="", copy_id="c1"),
        Provenance(run_id="hr1", spine_id="sp1", shelf_id="sh1", depth=1,
                  captured_at="2026-08-01T00:00:00+00:00"),
    )
    assert not_seen_streak(_copy_at(book), "sh1", 1, [r1]) == 0


def test_not_seen_streak_counts_consecutive_misses_and_stops_at_a_hit():
    """The badge's whole point: two reads in a row that did not reconfirm
    the copy, a THIRD read that did, further back — the streak counts only
    the run of misses since the last real sighting, not every read ever."""
    seen = _hread(1, finished_at="2026-08-01T00:00:00+00:00")
    miss1 = _hread(2, finished_at="2026-08-02T00:00:00+00:00")
    miss2 = _hread(3, finished_at="2026-08-03T00:00:00+00:00")
    book = observe(
        new_book(id="b1", library_id=LIB, title="ספר", author="", copy_id="c1"),
        Provenance(run_id="hr1", spine_id="sp1", shelf_id="sh1", depth=1,
                  captured_at="2026-08-01T00:00:00+00:00"),
    )
    streak = not_seen_streak(_copy_at(book), "sh1", 1, [seen, miss1, miss2])
    assert streak == 2, "expected exactly the two most recent misses"


def test_not_seen_streak_is_scoped_to_the_depth_read():
    """§5.7 #1, carried into the badge: a front-row re-read must not age a
    copy that stands in the row behind. A miss at depth 2 must not count
    against a copy located at depth 1, and vice versa."""
    front_miss = _hread(1, depth=1, finished_at="2026-08-02T00:00:00+00:00")
    back_miss = _hread(2, depth=2, finished_at="2026-08-02T00:00:00+00:00")
    seen_at_depth_1 = _hread(3, depth=1, finished_at="2026-08-01T00:00:00+00:00")
    book = observe(
        new_book(id="b1", library_id=LIB, title="ספר", author="", copy_id="c1"),
        Provenance(run_id="hr3", spine_id="sp1", shelf_id="sh1", depth=1,
                  captured_at="2026-08-01T00:00:00+00:00"),
    )
    copy = _copy_at(book)
    assert not_seen_streak(copy, "sh1", 1, [front_miss, back_miss, seen_at_depth_1]) == 1
    # A copy that has NEVER stood at depth 2 has nothing to have missed there.
    assert not_seen_streak(copy, "sh1", 2, [front_miss, back_miss, seen_at_depth_1]) == 0


def test_not_seen_streak_ignores_reads_from_before_the_copy_stood_here():
    """A copy placed on the shelf yesterday must not inherit a streak from
    photographs taken long before it arrived — those reads say nothing
    about it."""
    old_read = _hread(1, finished_at="2020-01-01T00:00:00+00:00")
    book = observe(
        new_book(id="b1", library_id=LIB, title="ספר", author="", copy_id="c1"),
        Provenance(run_id="hr9", spine_id="sp1", shelf_id="sh1", depth=1,
                  captured_at="2026-08-01T00:00:00+00:00"),
    )
    assert not_seen_streak(_copy_at(book), "sh1", 1, [old_read]) == 0


def test_not_seen_streak_excludes_a_failed_read():
    """A read that blew up mid-spine produced no reliable evidence either
    way — it must neither extend nor reset the streak."""
    seen = _hread(1, finished_at="2026-08-01T00:00:00+00:00")
    failed = _hread(2, status=ReadStatus.FAILED,
                    finished_at="2026-08-02T00:00:00+00:00")
    book = observe(
        new_book(id="b1", library_id=LIB, title="ספר", author="", copy_id="c1"),
        Provenance(run_id="hr1", spine_id="sp1", shelf_id="sh1", depth=1,
                  captured_at="2026-08-01T00:00:00+00:00"),
    )
    assert not_seen_streak(_copy_at(book), "sh1", 1, [seen, failed]) == 0


def test_not_seen_streak_never_touches_the_copy_it_is_about():
    """The mutation-check the plan asks for by name: a function computing
    this badge must have no path to removal at all. Asserted the only way a
    PURE function can be — the input copy is bit-for-bit unchanged after
    computing even a long miss streak, and the function returns a plain int,
    never a Book/Copy a careless caller could mistake for "already updated"."""
    reads = [_hread(n, finished_at=f"2026-08-{n:02d}T00:00:00+00:00")
            for n in range(1, 6)]
    book = new_book(id="b1", library_id=LIB, title="ספר", author="",
                    copy_id="c1", shelf_id="sh1", depth=1,
                    provenance=(Provenance(run_id="hr0", spine_id="sp1",
                                          shelf_id="sh1", depth=1,
                                          captured_at="2026-07-01T00:00:00+00:00"),))
    copy_before = _copy_at(book)
    streak = not_seen_streak(copy_before, "sh1", 1, reads)
    assert streak == 5
    assert _copy_at(book) == copy_before, "computing the badge mutated the copy"


# --- P2.8: depth_staleness — the shelf's soft staleness line (UI_PLAN §3) --

def test_depth_staleness_flags_a_never_read_row_and_leaves_the_freshest_alone():
    front = _hread(1, depth=1, finished_at="2026-08-05T00:00:00+00:00")
    statuses = {s.depth: s for s in depth_staleness(3, [front])}
    assert statuses[1] == DepthStatus(depth=1, last_read_at="2026-08-05T00:00:00+00:00",
                                      is_stale=False)
    assert statuses[2].last_read_at is None and statuses[2].is_stale
    assert statuses[3].last_read_at is None and statuses[3].is_stale


def test_depth_staleness_flags_a_row_read_less_recently_than_the_freshest():
    old = _hread(1, depth=1, finished_at="2026-03-11T00:00:00+00:00")
    fresh = _hread(2, depth=2, finished_at="2026-08-05T00:00:00+00:00")
    statuses = {s.depth: s for s in depth_staleness(2, [old, fresh])}
    assert statuses[1].is_stale, "an older-than-the-freshest row must read as stale"
    assert not statuses[2].is_stale


def test_depth_staleness_all_fresh_when_every_row_was_read_together():
    same_time = "2026-08-05T00:00:00+00:00"
    r1 = _hread(1, depth=1, finished_at=same_time)
    r2 = _hread(2, depth=2, finished_at=same_time)
    statuses = depth_staleness(2, [r1, r2])
    assert all(not s.is_stale for s in statuses)


def test_depth_staleness_ignores_a_failed_read():
    failed = _hread(1, depth=1, status=ReadStatus.FAILED,
                    finished_at="2026-08-05T00:00:00+00:00")
    statuses = {s.depth: s for s in depth_staleness(1, [failed])}
    assert statuses[1].last_read_at is None, \
        "a failed read must not count as evidence the row was read"


def test_depth_staleness_never_mentions_row_or_band_in_the_module():
    """§5.7's naming discipline, carried into the new module the same way
    `test_depth_is_never_called_row_or_band_in_the_shelf_module` already
    enforces it for `app/domain/shelf.py` — prose may say "row"; identifiers
    must not."""
    import app.domain.history as history_module

    source = Path(history_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    for bad in ("row", "band"):
        assert bad not in names, f"{bad!r} used as an identifier in history.py"


# --- P2.10: retracting a finding (§12.2 #10, UI_PLAN §5) -------------------
#
# The workspace's ✕. Every case below is the line between UI_PLAN §5's
# "remove from shelf != delete from library" and CLAUDE.md's "a phantom rots
# silently" — see `app/domain/retract.py`'s module docstring.

READ_START = "2026-08-09T10:00:00+00:00"
READ_END = "2026-08-09T10:02:00+00:00"


def _read_for_retract() -> Read:
    """The read a retraction is scoped to — id and start time, which are the
    two facts `plan_retraction` needs to answer "did this read create the
    record?"."""
    return Read(id="r1", library_id=LIB, shelf_id="sh1", depth=1,
                capture_ids=("cap1",), mode="llmpage", status=ReadStatus.DONE,
                started_at=READ_START, finished_at=READ_END)


def _located(**kw) -> Book:
    """A book standing at (sh1, 1), sighted once by read ``r1`` and added to
    the library while that read was running — the shape a confirmed finding
    leaves behind."""
    args = dict(id="b1", library_id=LIB, title="מלכי הכופרים",
                author="פול קארני", copy_id="c1", shelf_id="sh1", depth=1,
                added_at=READ_END,
                provenance=(Provenance(run_id="r1", spine_id="sp1",
                                       shelf_id="sh1", depth=1),))
    args.update(kw)
    return new_book(**args)


def test_retracting_a_finding_this_read_created_deletes_the_record():
    """✕ undoes exactly what the finding did: the book exists only because
    this read found it and a human approved it, so nothing is left behind —
    CLAUDE.md's "a phantom silently rots in the catalog" is the failure this
    prevents."""
    book = _located()
    plan = plan_retraction(book, "sh1", 1, read=_read_for_retract())
    assert plan.action is RetractAction.DELETE_BOOK
    assert plan.copy_id == "c1"
    assert plan.decision_kind is DecisionKind.REJECTED


def test_retracting_never_deletes_a_book_that_predates_this_read():
    """UI_PLAN §5's separation, at its sharpest: an imported book (P1.3) or
    one an earlier read placed has a life of its own — a ✕ on one photo's
    finding takes it off this shelf and must never destroy the record.

    The rule asks WHO CREATED the record, not what status it wears: after
    2026-08-09 every machine-read book is confirmed by a human and so arrives
    APPROVED, which made the old status test unable to tell these apart."""
    book = _located(provenance=(Provenance(run_id="an-older-read",
                                           spine_id="sp9", shelf_id="sh1",
                                           depth=1),))
    plan = plan_retraction(book, "sh1", 1, read=_read_for_retract())
    assert plan.action is RetractAction.REMOVE_FROM_SHELF
    assert plan.copy_id == "c1"


def test_retracting_never_deletes_a_book_this_read_merely_reconfirmed():
    """The case provenance ALONE gets wrong, and the reason `added_at` is in
    the rule: a book that already existed and that this read reconfirmed gets
    its first-ever sighting from this very read (`observe()` appends one), so
    its provenance looks identical to a record the read created. When it
    joined the library is the fact that actually tells them apart."""
    older = _located(added_at="2026-01-01T00:00:00+00:00")
    plan = plan_retraction(older, "sh1", 1, read=_read_for_retract())
    assert plan.action is RetractAction.REMOVE_FROM_SHELF


def test_retracting_never_deletes_a_record_with_no_added_at():
    """P1.3's import can leave one, and "unknown" must read as OLDER — the
    safe direction is always to keep the book."""
    unknown = _located(added_at=None)
    plan = plan_retraction(unknown, "sh1", 1, read=_read_for_retract())
    assert plan.action is RetractAction.REMOVE_FROM_SHELF


def test_retracting_never_deletes_a_copy_declared_by_hand():
    """A copy from *"I have another copy"* has no provenance at all — no read
    ever created it. `all()` over an empty tuple is vacuously true, so
    without the explicit emptiness check this is exactly the case that would
    delete a record nobody read."""
    book = _located(provenance=())
    plan = plan_retraction(book, "sh1", 1, read=_read_for_retract())
    assert plan.action is RetractAction.REMOVE_FROM_SHELF


def test_retracting_never_deletes_a_book_that_has_a_second_copy():
    """The other copy stands somewhere else (or nowhere) and has nothing to do
    with this photo — deleting the book would take it with it."""
    book = add_copy(_located(), copy_id="c2")
    plan = plan_retraction(book, "sh1", 1, read=_read_for_retract())
    assert plan.action is RetractAction.REMOVE_FROM_SHELF
    assert plan.copy_id == "c1", "the copy standing HERE is the one retracted"


def test_retracting_targets_the_copy_at_this_row_not_the_one_behind_it():
    """§5.7 #1/#3: a retraction is scoped to the row photographed. Matching on
    shelf alone would take the back row's copy off the shelf instead."""
    book = add_copy(_located(), copy_id="c2", shelf_id="sh1", depth=2)
    plan = plan_retraction(book, "sh1", 2, read=_read_for_retract())
    assert plan.copy_id == "c2"


def test_retracting_a_finding_that_never_became_a_book_still_records_the_no():
    """§5.6: without the standing decision the very next read re-adds it. The
    answer must survive even when there is no record to remove."""
    plan = plan_retraction(None, "sh1", 1, read=_read_for_retract())
    assert plan.action is RetractAction.NOTHING
    assert plan.copy_id is None
    assert plan.decision_kind is DecisionKind.REJECTED


def test_retracting_a_book_that_no_longer_stands_here_removes_nothing():
    """Its copy moved (or was already taken off) since the read — there is
    nothing at this location to retract, and touching another location's copy
    would be exactly the §5.7 #3 mistake."""
    book = _located(shelf_id="sh9")
    plan = plan_retraction(book, "sh1", 1, read=_read_for_retract())
    assert plan.action is RetractAction.NOTHING
    assert plan.copy_id is None


def test_retracting_an_ambiguous_claim_records_wrong_book_not_rejected():
    """The two suppress identically; which one is stored is the audit trail of
    WHICH question was answered (`DecisionKind`'s own docstring)."""
    book = _located()
    plan = plan_retraction(book, "sh1", 1, read=_read_for_retract(), claimed_elsewhere=True)
    assert plan.decision_kind is DecisionKind.WRONG_BOOK


def test_a_retraction_never_mutates_the_book_it_is_about():
    """Pure by rule — `app.reconcile_apply` executes, this only decides."""
    book = _located()
    before = book
    plan_retraction(book, "sh1", 1, read=_read_for_retract())
    assert book == before


def test_deleting_a_book_records_a_no_at_every_row_it_stood_on():
    """A book seen on two rows was claimed on two rows, and a decision is
    scoped to one (shelf, depth) by §5.7 #1 — one decision per site is the
    only answer that suppresses everywhere it was actually found."""
    book = observe(_book(shelf_id="sh1", depth=1),
                   Provenance("r1", "sp1", shelf_id="sh1", depth=1))
    book = add_copy(book, copy_id="c2", shelf_id="sh2", depth=2)
    assert deletion_sites(book) == (("sh1", 1), ("sh2", 2))


def test_deleting_an_unlocated_book_suppresses_nothing():
    """The 251 imported books have no shelf. There is no row for a future
    read to re-find them on, so there is nothing to say no to."""
    assert deletion_sites(_book()) == ()


def test_two_copies_on_one_row_record_one_no_not_two():
    """The decision's key is (library, shelf, depth, book_key) — a second
    write for the same site is the same row, and duplicating it would only
    make the intent look ambiguous."""
    book = observe(_book(shelf_id="sh1", depth=1),
                   Provenance("r1", "sp1", shelf_id="sh1", depth=1))
    book = add_copy(book, copy_id="c2", shelf_id="sh1", depth=1)
    assert deletion_sites(book) == (("sh1", 1),)


# --- tenancy (P3.1, §4.1/§4.2/§4.3) ---------------------------------------

OWNER = User(id="usr-1", display_name="משה")
ACCOUNT = Account(id="acc-1", label="Malin")


def test_creating_an_account_makes_its_creator_an_admin():
    """An account saved without a membership is invisible to the person who
    made it (listing is BY USER) and administrable by nobody. Returning both
    from one call is what makes that state unreachable from a caller that
    simply forgot the second write.

    ⚠ The rule MOVED here at P3.7b. `new_library` used to carry it, because
    a library was the boundary; now access comes from the account, and a
    library that minted its own membership would invent a grant the resolver
    never consults."""
    account, membership = new_account(id="acc-1", owner=OWNER)
    assert membership.account_id == account.id
    assert membership.user_id == OWNER.id
    assert membership.role is Role.ADMIN


def test_creating_a_library_grants_nobody_anything():
    """The other half, and the one worth a named test: creating a library is
    no longer a permission event. It returns a Library and nothing else, so
    there is no second grant to drift out of step with the account's."""
    library = new_library(id="lib-1", label="משפחת מלין", account=ACCOUNT)
    assert library.account_id == ACCOUNT.id
    assert not isinstance(library, tuple)


def test_a_library_is_created_with_a_name():
    """The deliberate asymmetry with `Shelf`, whose label is optional because
    an unnamed shelf is shown by its own photograph. A library has no
    photograph — it is a row in the app-bar switcher, and two blank rows are
    two libraries the owner cannot tell apart (§4.3: "create a Library, name
    it")."""
    _raises(LibraryNeedsAName, new_library, id="lib-1", label="  ",
            account=ACCOUNT)
    _raises(LibraryNeedsAName, rename_library,
            Library(id="lib-1", account_id="acc-1", label="x"), "")


def test_a_backfilled_library_may_be_nameless_even_though_a_new_one_may_not():
    """Schema v12 backfills a row for every library id that already existed in
    the owner's data, and there is no label to recover. So the ENTITY must be
    able to represent one while the CONSTRUCTOR refuses to mint another —
    the same split as `Book`/`new_book`."""
    assert Library(id="dev-library", account_id="acc-1").label == ""


def test_the_last_admin_cannot_be_demoted_or_removed():
    """§4.2 gives only an admin "invite/remove members, change roles", so an
    account whose last admin steps down can never invite anyone, be renamed
    or be deleted — an unadministrable tenant only a database edit rescues.

    ⚠ Widened at P3.7b rather than moved: it used to protect one library and
    now protects every library the customer owns."""
    members = (Membership("usr-1", "acc-1", Role.ADMIN),
               Membership("usr-2", "acc-1", Role.EDITOR))
    _raises(NoAdminLeft, set_role, members, "usr-1", Role.VIEWER)
    _raises(NoAdminLeft, remove_member, members, "usr-1")


def test_an_admin_may_step_down_once_another_admin_exists():
    """The rule is "at least one", not "the first one forever" — otherwise
    handing the account over to someone else is impossible."""
    members = (Membership("usr-1", "acc-1", Role.ADMIN),
               Membership("usr-2", "acc-1", Role.ADMIN))
    left = remove_member(members, "usr-1")
    assert [m.user_id for m in left] == ["usr-2"]
    demoted = set_role(members, "usr-1", Role.VIEWER)
    assert {m.user_id: m.role for m in demoted}["usr-1"] is Role.VIEWER


def test_changing_a_role_replaces_it_rather_than_adding_a_second_membership():
    """One membership per (user, library) — the store declares it as a
    composite primary key, and a domain op that appended instead would make
    "what is my role here" ambiguous before the store ever saw it."""
    members = (Membership("usr-1", "acc-1", Role.ADMIN),
               Membership("usr-2", "acc-1", Role.VIEWER))
    after = set_role(members, "usr-2", Role.EDITOR)
    assert len(after) == 2
    assert [m.role for m in after] == [Role.ADMIN, Role.EDITOR]


def test_acting_on_a_non_member_raises_rather_than_inventing_a_membership():
    members = (Membership("usr-1", "acc-1", Role.ADMIN),)
    _raises(UnknownMember, set_role, members, "usr-9", Role.EDITOR)
    _raises(UnknownMember, remove_member, members, "usr-9")


def test_a_role_says_who_you_are_and_never_what_you_may_do():
    """§4.2's matrix lives in `app/domain/policy.py` (P3.2) — data, with ONE
    enforcement point. A `can()`/CAPABILITIES in the TENANCY module would be
    a second copy of it, and the two would drift the first time a capability
    moved a column. Structural on purpose, like the shelf-address test: the
    tempting mistake is to add it "while we're at it"."""
    src = (REPO_ROOT / "app" / "domain" / "tenancy.py").read_text(encoding="utf-8")
    names = {
        node.name for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.FunctionDef)
    } | {
        t.id for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Assign) for t in node.targets
        if isinstance(t, ast.Name)
    }
    banned = {"can", "may", "allows", "permits", "CAPABILITIES", "PERMISSIONS",
              "MATRIX", "POLICY"}
    assert not (names & banned), (
        f"§4.2's matrix is P3.2's, with one enforcement point: {sorted(names & banned)}"
    )


def test_a_library_is_not_a_place():
    """§4.1's own warning: a place you keep books (home, office, parents') is
    a Place (né PhysicalLibrary) — an address, and addresses arrive with the
    map (plan §1.1). Collapsing the two here is what would make the map's own
    hierarchy have to reconcile with this one.

    ⚠ P3.7b makes this guard sharper rather than weaker. A Library stopped
    being the boundary and became a partition inside an Account — which is
    exactly the moment "then it may as well be a room" becomes tempting. It
    may not. So the fields are asserted EXACTLY rather than by exclusion: the
    banned set below passed unchanged when `account_id` was added, which means
    it would equally have passed a `room_id`.
    """
    fields = set(Library.__dataclass_fields__)
    assert fields == {"id", "account_id", "label", "created_at"}, (
        f"the tenancy partition grew a field: {sorted(fields)} — if it is an "
        "address, it belongs to pillar 6's Place"
    )
    address = {"place", "place_id", "places", "bookcase", "room", "address",
               "col", "level", "geometry"}
    assert not (fields & address), (
        f"physical-place fields on the tenancy boundary: {sorted(fields & address)}"
    )


# --- policy (P3.2, §4.2) ----------------------------------------------------

def test_the_policy_matrix_is_vision_4_2_cell_for_cell():
    """The table-driven test the plan asks for by name: every (role ×
    capability) cell, against a second transcription of §4.2. Two copies of
    the table is the point — a cell change is a decision, and this is where
    it gets written down twice."""
    V, E, A = Role.VIEWER, Role.EDITOR, Role.ADMIN
    expected = {
        Capability.BROWSE: {V, E, A},
        Capability.SEE_LENDING: {V, E, A},
        # §12.2 #1, settled 2026-08-10: photos show the inside of a home.
        Capability.VIEW_PHOTOS: {E, A},
        Capability.CAPTURE: {E, A},
        Capability.REVIEW: {E, A},
        Capability.EDIT_BOOKS: {E, A},
        Capability.LEND: {E, A},
        Capability.EDIT_MAP: {E, A},
        Capability.MANAGE_MEMBERS: {A},
        Capability.MANAGE_KEYS: {A},
        Capability.MANAGE_LIBRARY: {A},
        Capability.DELETE_PHOTOS: {A},
        Capability.DELETE_LIBRARY: {A},
    }
    assert set(expected) == set(Capability), "a capability is missing a row here"
    for capability, grants in expected.items():
        for role in Role:
            assert allowed(role, capability) is (role in grants), (
                f"§4.2 cell reversed: {role.value} × {capability.value}"
            )


def test_every_capability_has_a_policy_row_and_an_undeclared_one_raises():
    """`allowed` must never DEFAULT an unknown capability — `False` reading as
    "denied by policy" when the truth is "nobody wrote the policy" is exactly
    how a new route ships unpoliced. Same stance as the fire table's
    `fires()`."""
    assert set(POLICY) == set(Capability)
    row = POLICY.pop(Capability.BROWSE)
    try:
        _raises(PolicyUndeclared, allowed, Role.ADMIN, Capability.BROWSE)
    finally:
        POLICY[Capability.BROWSE] = row


def test_a_viewer_reads_the_catalog_and_never_the_photographs():
    """§12.2 #1's settled cell, pinned on its own because it is the one most
    likely to be flipped casually: a Viewer browses what you own — titles,
    authors, lending state — not photographs of the inside of your home.
    Loosening later shows photos to people who could not see them; tightening
    later cannot un-show them."""
    assert allowed(Role.VIEWER, Capability.BROWSE)
    assert allowed(Role.VIEWER, Capability.SEE_LENDING)
    assert not allowed(Role.VIEWER, Capability.VIEW_PHOTOS)


def test_see_lending_matches_browse_until_a_route_splits_them():
    """Lending state is served INSIDE `BookDTO` on BROWSE routes — no route
    enforces SEE_LENDING on its own, so a stricter cell there would change
    nothing on the wire and the table would lie. If this fails you are
    tightening the cell: split lending out of the browse payload first, then
    delete this test."""
    assert POLICY[Capability.SEE_LENDING] == POLICY[Capability.BROWSE]


def test_destructive_and_governance_capabilities_are_admin_only():
    """§4.2's admin column, whole: deleting photos destroys the evidence every
    read points at, and members/keys/name are the tenant's own governance."""
    admin_only = (Capability.MANAGE_MEMBERS, Capability.MANAGE_KEYS,
                  Capability.MANAGE_LIBRARY, Capability.DELETE_PHOTOS,
                  Capability.DELETE_LIBRARY)
    for cap in admin_only:
        assert allowed(Role.ADMIN, cap)
        assert not allowed(Role.EDITOR, cap), f"{cap.value} leaked to editor"
        assert not allowed(Role.VIEWER, cap), f"{cap.value} leaked to viewer"


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))


# --- auth: sessions and login tokens (P4.1a, §3) ---------------------------

def test_a_session_lives_ninety_days_and_rolls_without_a_write_per_request():
    """Owner, 2026-08-13: 90-day ROLLING sessions. Rolling must not mean a
    store write per tap: `refreshed` answers None until the remaining life
    dips under the threshold, then pushes expiry back out to the full
    lifetime -- and a dead session (expired or revoked) never refreshes,
    because a refresh that resurrects is a session that cannot be killed."""
    from dataclasses import replace

    from app.domain.auth import (SESSION_LIFETIME, SESSION_REFRESH_BELOW,
                                 new_session, refreshed)

    born = "2026-08-13T12:00:00+00:00"
    s = new_session("tok", "u1", born)
    assert s.expires_at == "2026-11-11T12:00:00+00:00"  # born + 90 days
    assert s.live(born)
    assert not s.live(s.expires_at), "expiry is exclusive -- at the instant, dead"

    # Fresh: plenty of life left, no write due.
    assert refreshed(s, "2026-08-20T12:00:00+00:00") is None

    # Worn past the threshold (90 - 60 = 30 days in): expiry rolls out.
    later = "2026-09-15T12:00:00+00:00"
    rolled = refreshed(s, later)
    assert rolled is not None
    assert rolled.expires_at == "2026-12-14T12:00:00+00:00"  # later + 90
    assert rolled.token_hash == s.token_hash and rolled.created_at == s.created_at

    # Dead sessions never roll.
    assert refreshed(s, "2027-01-01T12:00:00+00:00") is None
    revoked = replace(s, revoked_at="2026-08-14T00:00:00+00:00")
    assert not revoked.live("2026-08-15T00:00:00+00:00")
    assert refreshed(revoked, later) is None
    assert SESSION_REFRESH_BELOW < SESSION_LIFETIME, "the roll must be reachable"


def test_a_login_token_expires_in_minutes_and_is_stored_as_a_hash():
    """§3: expiring -- an emailed credential outlives a coffee break, never
    an afternoon inbox. And nothing stored equals the token: the database
    holds sha256, so a leaked file logs nobody in."""
    import hashlib

    from app.domain.auth import hash_token, new_login_token

    t = new_login_token("secret-token", "A@B.com", "2026-08-13T12:00:00+00:00")
    assert t.expires_at == "2026-08-13T12:15:00+00:00"
    assert t.email == "a@b.com", "the address was not normalized at the mint"
    assert t.token_hash != "secret-token"
    assert t.token_hash == hashlib.sha256(b"secret-token").hexdigest()
    assert hash_token("secret-token") == t.token_hash


def test_an_email_address_has_one_spelling():
    """`Moshe@Example.COM ` and `moshe@example.com` are one inbox and must
    be one user -- case-folded whole (a distinction RFC 5321 allows and no
    real provider honours), trimmed, and nothing else."""
    from app.domain.auth import normalize_email

    assert normalize_email(" Moshe@Example.COM ") == "moshe@example.com"
    assert normalize_email("a.b+tag@x.co") == "a.b+tag@x.co", (
        "plus-tags and dots are the OWNER's business, not ours to fold")


# --- provider sign-in, the checklist (P4.2) --------------------------------

def test_only_a_verified_address_from_the_right_issuer_signs_anyone_in():
    """Every check an attacker-influenced answer has to survive. The
    email_verified flag is the load-bearing one: without it, anyone who
    types your address into a provider account they control is you."""
    from app.domain.oauth import GOOGLE, OAuthError, identity_from_claims

    import time

    good = {"iss": GOOGLE.issuer, "aud": "client-1", "nonce": "n1",
            "email": "Owner@Example.COM", "email_verified": True,
            "sub": "sub-1", "exp": time.time() + 300}
    who = identity_from_claims(good, GOOGLE, "client-1", "n1")
    assert who.email == "owner@example.com", "the address was not normalized"
    assert who.subject == "sub-1" and who.provider == "google"

    # Apple sends the flag as a STRING; both spellings mean verified.
    assert identity_from_claims({**good, "email_verified": "true"},
                                GOOGLE, "client-1", "n1").email

    for broken, why in (
        ({**good, "iss": "https://evil.test"}, "a forged issuer"),
        ({**good, "aud": "someone-elses-client"}, "another client's token"),
        ({**good, "aud": ["someone-elses-client"]}, "an audience list"),
        ({**good, "nonce": "n2"}, "a replayed token from another sign-in"),
        ({**good, "email_verified": False}, "an unverified address"),
        ({**good, "email_verified": None}, "a missing verified flag"),
        ({**good, "email": ""}, "no address at all"),
        ({**good, "sub": ""}, "no subject"),
        ({**good, "exp": time.time() - 1}, "an expired token"),
        ({k: v for k, v in good.items() if k != "exp"}, "no expiry at all"),
        ({**good, "exp": "soon"}, "an unreadable expiry"),
        ({**good, "email": "a" + chr(13) + chr(10) + "Bcc: evil@x.test@b.co"}, "a CRLF address"),
        ({**good, "email": "x" * 300 + "@b.co"}, "an absurd address"),
    ):
        try:
            identity_from_claims(broken, GOOGLE, "client-1", "n1")
        except OAuthError:
            pass
        else:
            raise AssertionError(f"{why} was accepted")

    # An empty nonce must never match an absent one.
    try:
        identity_from_claims({**good, "nonce": ""}, GOOGLE, "client-1", "")
    except OAuthError:
        pass
    else:
        raise AssertionError("an empty nonce matched")


def test_pkce_is_s256_and_never_plain():
    """PKCE binds the code to the client that asked. `plain` would put
    the verifier in the front-channel request — the one part of this flow
    that travels through the browser and its history."""
    import base64
    import hashlib

    from app.domain.oauth import pkce_challenge

    verifier = "a-verifier-that-is-long-enough-to-be-real"
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert pkce_challenge(verifier) == expected
    assert pkce_challenge(verifier) != verifier
    assert "=" not in pkce_challenge(verifier)


def test_apples_client_secret_is_a_real_es256_jwt():
    """Apple's client secret is a JWT we SIGN, not a string — and it is
    verified here against the public half, because a secret that only
    looks like a JWT fails at Apple's door with a message about the
    grant, not about the key."""
    import base64
    import json

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    from app.adapters.oidc import AppleProvider

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    provider = AppleProvider(client_id="com.example.booksnap",
                             team_id="TEAM123", key_id="KEY123",
                             private_key=pem,
                             redirect_uri="https://books.example.com/cb")
    secret = provider._client_secret()
    header_b64, payload_b64, signature_b64 = secret.split(".")

    def unpad(segment):
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))

    assert json.loads(unpad(header_b64)) == {"alg": "ES256", "kid": "KEY123"}
    claims = json.loads(unpad(payload_b64))
    assert claims["iss"] == "TEAM123"
    assert claims["sub"] == "com.example.booksnap"
    assert claims["aud"] == "https://appleid.apple.com"
    assert claims["exp"] > claims["iat"]

    raw = unpad(signature_b64)
    assert len(raw) == 64, "JOSE wants raw R||S, not the DER OpenSSL emits"
    der = utils.encode_dss_signature(
        int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key.public_key().verify(
        der, f"{header_b64}.{payload_b64}".encode(),
        ec.ECDSA(hashes.SHA256()))       # raises if the signature is wrong


def test_the_authorize_url_carries_what_the_provider_needs():
    """The front channel, spelled out — including the response_mode Apple
    will not release an email without."""
    from urllib.parse import parse_qs, urlparse

    from app.adapters.oidc import AppleProvider, OidcProvider

    google = OidcProvider(client_id="gid", client_secret="gsecret",
                          redirect_uri="https://books.example.com/g")
    url = google.authorize_url(state="st", nonce="no", challenge="ch")
    query = parse_qs(urlparse(url).query)
    assert urlparse(url).netloc == "accounts.google.com"
    assert query["code_challenge_method"] == ["S256"]
    assert query["response_type"] == ["code"]
    assert query["state"] == ["st"] and query["nonce"] == ["no"]
    assert "response_mode" not in query
    # The secret NEVER travels in the front channel.
    assert "gsecret" not in url

    apple = AppleProvider(client_id="aid", team_id="t", key_id="k",
                          private_key="", redirect_uri="https://x/a")
    assert parse_qs(urlparse(apple.authorize_url(
        state="s", nonce="n", challenge="c")).query)["response_mode"] == [
        "form_post"]


def test_the_token_endpoint_cannot_redirect_us_somewhere_else():
    """The whole no-signature-verification argument rests on "OUR TLS
    connection to a PINNED endpoint". urllib's default opener follows
    3xx — including to another host, and down to plain HTTP — which
    would quietly move the answer somewhere unpinned, and the nonce that
    gates it is not secret (it travels in the front channel). Measured at
    review; the opener refuses redirects now."""
    import urllib.request

    from app.adapters.oidc import _PINNED, _NoRedirects

    handlers = [type(h).__name__ for h in _PINNED.handlers]
    assert "_NoRedirects" in handlers, handlers
    assert _NoRedirects().redirect_request(
        None, None, 302, "Found", {}, "https://evil.test/token") is None, (
        "a redirect off the pinned token endpoint would be followed"
    )


# --- the physical map (P6.1, MAP_PLAN §3) ---------------------------------
#
# One test per reversible sentence, as everywhere else in this file. The
# sentences come from `planning/MAP_PLAN.md`, which nine passes of a
# standalone lab settled before any of this was written.


def _rect_args(**over):
    base = {"x": 0, "y": 0, "w": 4, "h": 2}
    base.update(over)
    return base


def test_plan_geometry_is_whole_abstract_units():
    """MAP_PLAN §3.4, and it is a bug fix rather than tidiness.

    Snapping moves a rectangle by ADDING a correction, and `x + (round(x)-x)`
    is not `round(x)` in floating point. The lab shipped a room that rendered
    as 11.000000000000004x9, and the dust then became a snap candidate for the
    next rectangle, which inherited it. The client sweeps it at both
    constructors; this refuses it at the door, because a canvas resize, a
    phone rotation or a zoom must never be able to corrupt a stored plan.
    """
    from app.domain import Rect

    assert Rect(1, 2, 3, 4).w == 3
    for bad in (_rect_args(x=1.5), _rect_args(w=11.000000000000004),
                _rect_args(y=True)):
        try:
            Rect(**bad)
        except DomainError:
            continue
        raise AssertionError(f"a plan accepted non-integer geometry: {bad}")
    for empty in (_rect_args(w=0), _rect_args(h=-3)):
        try:
            Rect(**empty)
        except DomainError:
            continue
        raise AssertionError(f"a plan accepted a sizeless rectangle: {empty}")


def test_a_sections_depth_default_is_copied_at_creation_never_read_live():
    """MAP_PLAN §3.3 — the trap this whole model is shaped around.

    If a case's depth were read live, editing it from 2 to 1 would silently
    delete the location of every book standing in the back row. So the default
    is copied into a shelf when the shelf is CREATED, and changing it
    afterwards touches nothing.
    """
    from app.domain import new_section, new_shelf, with_default_depth

    section = new_section(id="se", library_id="lib", bookcase_id="bc",
                          columns=1, default_levels=2, default_depth=2)
    standing = new_shelf(id="a", library_id="lib", depth_count=2)
    shallower = with_default_depth(section, 1)
    assert shallower.default_depth == 1
    assert standing.depth_count == 2, (
        "editing the section's default reached back into an existing shelf"
    )


def test_applying_a_depth_default_never_goes_below_an_occupied_row():
    """§3.3's last clause, and the one the lab could NOT implement because it
    had no books. Books stand behind; the depth stays, and the caller is told
    which shelves kept theirs so the screen can say so rather than silently
    doing less than it was asked."""
    from app.domain import apply_default_depth, new_section, new_shelf

    section = new_section(id="se", library_id="lib", bookcase_id="bc",
                          columns=1, default_levels=1, default_depth=1)
    empty = new_shelf(id="empty", library_id="lib", depth_count=3)
    occupied = new_shelf(id="full", library_id="lib", depth_count=3)
    result = apply_default_depth(section, [empty, occupied],
                                 deepest_occupied={"full": 2})
    by_id = {s.id: s for s in result.shelves}
    assert by_id["empty"].depth_count == 1, "an empty shelf resisted the default"
    assert by_id["full"].depth_count == 2, (
        "a book at depth 2 lost its location to a section default of 1"
    )
    assert [s.id for s in result.kept] == ["full"]


def test_erasing_a_slot_deletes_an_empty_shelf_and_detaches_an_occupied_one():
    """MAP_PLAN §3.1 plus §5.6's "never auto-remove", together.

    A drawn-but-never-used shelf is scaffolding and goes with its slot. A
    shelf holding captures or copies SURVIVES, unaddressed — its books keep
    their shelf, and what they lose is a location the owner has just erased
    from the drawing. Deleting it instead would destroy the record a re-read
    diffs against, because somebody redrew a bookcase.
    """
    from app.domain import ShelfAddress, new_shelf, plan_slot_removal

    scaffold = new_shelf(id="never-used", library_id="lib",
                         address=ShelfAddress("se", 1, 1))
    photographed = new_shelf(id="has-books", library_id="lib",
                             address=ShelfAddress("se", 1, 2))
    plan = plan_slot_removal([scaffold, photographed],
                             occupied_ids=["has-books"])
    assert plan.deleted == ("never-used",)
    assert plan.detached == ("has-books",), (
        "an occupied shelf was queued for deletion, not detachment"
    )
    assert plan.total == 2


def test_a_storey_or_a_site_with_anything_on_it_is_never_removed():
    """§3.7, and the refusal SAYS what is in the way — "cannot delete" with no
    reason is what makes the next reader delete the guard."""
    from app.domain import GroupingContents, NotEmpty, check_removable

    check_removable("floor f", GroupingContents())     # empty: silent
    try:
        check_removable("floor f", GroupingContents(places=2, bookcases=1))
    except NotEmpty as err:
        assert "2 room(s)" in str(err) and "1 bookcase(s)" in str(err), str(err)
    else:
        raise AssertionError("a storey with two rooms on it was removed")


def test_containment_reassigns_a_bookcase_and_never_orphans_it():
    """MAP_PLAN §4's third pass, promoted to a DOMAIN rule rather than an
    editor behaviour.

    Without it, nudging a case half a unit past its own wall silently loses
    its room — and a bookcase belongs to a room the way furniture does, not
    the way one rectangle overlaps another. Detaching is explicit.
    """
    from app.domain import (Rect, detach_bookcase, new_bookcase, new_place,
                            reattach_bookcase)

    salon = new_place(id="pl", library_id="lib", floor_id="fl",
                      rect=Rect(0, 0, 10, 8), name="סלון")
    case = new_bookcase(id="bc", library_id="lib", floor_id="fl",
                        rect=Rect(0, 0, 4, 1), place_id="pl")
    assert reattach_bookcase(case, None).place_id == "pl", (
        "a case dragged off every room was orphaned by geometry"
    )
    assert reattach_bookcase(case, salon).place_id == "pl"
    assert detach_bookcase(case).place_id is None, "detach must still work"


def test_a_bookcase_takes_its_rooms_storey_when_it_attaches():
    """§3.7: a case carries its own floor so an unattached one is SOMEWHERE
    rather than everywhere — and the two fields can never be set apart, or a
    case attached to the kitchen is recorded upstairs."""
    from app.domain import Rect, attach_bookcase, new_bookcase, new_place

    upstairs = new_place(id="pl2", library_id="lib", floor_id="fl2",
                         rect=Rect(0, 0, 6, 6))
    case = new_bookcase(id="bc", library_id="lib", floor_id="fl",
                        rect=Rect(0, 0, 4, 1))
    moved = attach_bookcase(case, upstairs)
    assert (moved.place_id, moved.floor_id) == ("pl2", "fl2")


def test_a_site_and_a_floor_are_never_part_of_an_address():
    """§3.7/§3.9, structurally — the same shape of assertion that keeps a
    bookcase out of `shelf.py`. Putting either into the address would
    re-address every shelf in the house the day somebody renames a building.
    """
    from dataclasses import fields

    from app.domain import ShelfAddress

    names = {f.name for f in fields(ShelfAddress)}
    assert names == {"section_id", "col", "level"}, names


def test_an_address_prints_only_what_discriminates():
    """§3.6: *a one-section case never says "section 1", because saying it
    would imply there is a section 2.* Applied to a single COLUMN too, by the
    same argument."""
    from app.domain import (Rect, ShelfAddress, address_parts, new_bookcase,
                            new_place, new_section)

    salon = new_place(id="pl", library_id="lib", floor_id="fl",
                      rect=Rect(0, 0, 9, 7), name="סלון")
    case = new_bookcase(id="bc", library_id="lib", floor_id="fl",
                        rect=Rect(0, 0, 4, 1), name="הכוננית הגדולה")
    plain = new_section(id="se", library_id="lib", bookcase_id="bc", columns=1)
    parts = address_parts(place=salon, bookcase=case, section=plain,
                          section_count=1, address=ShelfAddress("se", 1, 3))
    assert parts.section is None, "a one-section case announced section 1"
    assert parts.column is None, "a one-column case announced column 1"
    assert (parts.place, parts.bookcase, parts.level) == (
        "סלון", "הכוננית הגדולה", 3)
    assert parts.depth is None, "the front row announced itself"

    wide = new_section(id="se2", library_id="lib", bookcase_id="bc",
                       ordinal=2, columns=3)
    told = address_parts(place=salon, bookcase=case, section=wide,
                         section_count=2, address=ShelfAddress("se2", 2, 1),
                         depth=2)
    assert (told.section, told.column, told.depth) == (2, 2, 2)


def test_a_drawn_section_creates_one_slot_per_column_and_level():
    """MAP_PLAN §3.1: draw a case with 2 columns of 5 and TEN real shelves
    exist that were never photographed. The slot list is what `map_edit` fills
    — a section reporting the wrong slots would create shelves nobody can
    reach."""
    from app.domain import (ShelfAddress, new_section, with_column_count,
                            with_column_levels)

    section = new_section(id="se", library_id="lib", bookcase_id="bc",
                          columns=2, default_levels=5)
    assert len(section.addresses) == 10
    assert section.column_count == 2
    assert min(a.col for a in section.addresses) == 1, "columns are 1-based"
    assert min(a.level for a in section.addresses) == 1, "levels are 1-based"
    # …and 1-based means a 0 is REFUSED, not quietly re-based. An off-by-one
    # that raises is an off-by-one somebody fixes; one that silently addresses
    # the shelf next door is a book filed where it is not.
    for wrong in ((0, 1), (1, 0), (-1, 2)):
        try:
            ShelfAddress("se", *wrong)
        except DomainError:
            continue
        raise AssertionError(f"a 0-based address was accepted: {wrong}")

    grown = with_column_count(section, 3)
    assert len(grown.added) == 5 and grown.dropped == ()
    assert grown.section.column_levels == (5, 5, 5)

    # ⚠ UNEVEN columns, deliberately. With every column the same height,
    # dropping from the front and dropping from the end produce an IDENTICAL
    # address set — the mutation check caught this test passing either way. A
    # column is identified by its position across the face, so removing one
    # from the front renumbers every shelf to its right, and those numbers are
    # printed on addresses somebody has already been sent to find.
    ragged = with_column_levels(grown.section, 1, 2).section
    assert ragged.column_levels == (2, 5, 5)
    shrunk = with_column_count(ragged, 1)
    assert shrunk.section.column_levels == (2,), "the wrong column was kept"
    assert shrunk.added == (), "shrinking a section created a slot"
    assert len(shrunk.dropped) == 10
    assert {a.col for a in shrunk.dropped} == {2, 3}, (
        "shrinking took columns from somewhere other than the end"
    )


def test_a_column_shrinks_from_the_bottom_because_level_1_is_the_top():
    """The lab's convention, kept deliberately so the ported editor behaves
    identically — and written down because "level 3" has to mean one thing."""
    from app.domain import new_section, with_column_levels

    section = new_section(id="se", library_id="lib", bookcase_id="bc",
                          columns=1, default_levels=5)
    change = with_column_levels(section, 1, 3)
    assert {a.level for a in change.dropped} == {4, 5}, (
        "a column shrank from the top, so every printed address moved"
    )


def test_the_wishlist_stands_nowhere():
    """§5.7, one level out from the depth rule it already had: the wishlist is
    a list of books the owner does not own. Giving it a slot in a bookcase
    would put unowned books at a location that exists."""
    from app.domain import ShelfAddress, VirtualShelfHasNoDepth, new_shelf

    try:
        new_shelf(id="wish", library_id="lib", virtual=True,
                  address=ShelfAddress("se", 1, 1))
    except VirtualShelfHasNoDepth:
        return
    raise AssertionError("the wishlist was given a shelf in a bookcase")


def test_an_out_of_range_section_edit_raises_instead_of_clamping():
    """Found at review: the lenient answer sat on the DESTRUCTIVE path.

    `with_column_count(section, 0)` silently meant *shrink to one column*,
    dropping every other column's slots — and it disagreed with
    `Section.__post_init__`, which raises for the same value. One invalid
    input must not have two answers, and certainly not with the quiet one
    doing the damage.
    """
    from app.domain import (new_section, with_column_count, with_column_levels,
                            with_default_depth, with_default_levels)

    section = new_section(id="se", library_id="lib", bookcase_id="bc",
                          columns=3, default_levels=5)
    for call in (
        lambda: with_column_count(section, 0),
        lambda: with_column_count(section, -2),
        lambda: with_column_levels(section, 1, 0),
        lambda: with_default_levels(section, 0),
        lambda: with_default_depth(section, 0),
        lambda: with_default_depth(section, 99),
    ):
        try:
            call()
        except DomainError:
            continue
        raise AssertionError("an out-of-range section edit was clamped")
    # …and the section is untouched by any of it.
    assert section.column_levels == (5, 5, 5)


def test_a_slot_list_is_column_major_because_ids_are_minted_from_it():
    """`Section.addresses` states an order and, until a review said so,
    nothing held it. It is not decoration: `map_edit._fill` walks it to mint
    shelf ids, so the order decides which id lands on which slot — and P6.3
    has to match it or a re-import files every shelf one place over."""
    from app.domain import new_section

    section = new_section(id="se", library_id="lib", bookcase_id="bc",
                          columns=2, default_levels=2)
    assert [(a.col, a.level) for a in section.addresses] == [
        (1, 1), (1, 2), (2, 1), (2, 2)], "the slot list is not column-major"


def test_the_front_row_never_announces_itself():
    """§5.7: the back row is a real location, stated only when it is NOT the
    obvious one. A review caught the original assertion being vacuous — it
    passed no depth at all, so `None` proved nothing."""
    from app.domain import (Rect, ShelfAddress, address_parts, new_bookcase,
                            new_place, new_section)

    salon = new_place(id="pl", library_id="lib", floor_id="fl",
                      rect=Rect(0, 0, 9, 7), name="סלון")
    case = new_bookcase(id="bc", library_id="lib", floor_id="fl",
                        rect=Rect(0, 0, 4, 1), name="כוננית")
    section = new_section(id="se", library_id="lib", bookcase_id="bc",
                          columns=1)
    at = ShelfAddress("se", 1, 1)
    said = address_parts(place=salon, bookcase=case, section=section,
                         section_count=1, address=at, depth=1)
    assert said.depth is None, "the front row announced itself"
    assert address_parts(place=salon, bookcase=case, section=section,
                         section_count=1, address=at, depth=2).depth == 2


def test_a_site_and_a_floor_must_be_named_but_a_room_need_not_be():
    """The same call as "library name mandatory, shelf label optional": a
    site or a storey exists only because there are two of them, and an
    unnamed one in a picker is unusable. A room is recognisable by its shape
    and its neighbours, which is what a drawing is for."""
    from app.domain import Rect, new_floor, new_place, new_site

    for call in (
        lambda: new_site(id="s", library_id="lib", name="  "),
        lambda: new_floor(id="f", library_id="lib", site_id="s", name=""),
    ):
        try:
            call()
        except DomainError:
            continue
        raise AssertionError("an unnamed site or storey was accepted")
    unnamed = new_place(id="p", library_id="lib", floor_id="f",
                        rect=Rect(0, 0, 4, 4))
    assert unnamed.name == ""


def test_a_section_is_numbered_from_one_and_a_bookcase_faces_a_real_side():
    """Two guards with no gate until a review counted them. `ordinal` is what
    the address PRINTS, and `front` decides which physical end is column 1
    (§7.3) — a bad value in either sends the owner to the wrong place."""
    from app.domain import Rect, Section, new_bookcase

    for call in (
        lambda: Section(id="se", library_id="lib", bookcase_id="bc",
                        ordinal=0),
        lambda: new_bookcase(id="bc", library_id="lib", floor_id="fl",
                             rect=Rect(0, 0, 4, 1), front="UP"),
    ):
        try:
            call()
        except DomainError:
            continue
        raise AssertionError("a section ordinal of 0, or a nonsense front")


def test_a_new_section_copies_the_shape_of_the_one_it_stands_on():
    """The lab's rule (`model.ts:addSection`): *a hutch usually has about as
    many columns as the base it stands on*, so starting from a blank 1x5
    would mean re-entering what is already on screen."""
    from app.domain import new_section, next_section, renumber_sections

    base = new_section(id="base", library_id="lib", bookcase_id="bc",
                       ordinal=1, columns=3, default_levels=4, default_depth=2)
    hutch = next_section("bc", [base], id="hutch", where="top")
    assert hutch.ordinal == 2
    assert hutch.column_count == 3, "the hutch forgot the base's width"
    assert (hutch.default_levels, hutch.default_depth) == (4, 2)
    assert hutch.library_id == "lib"

    # Added at the BOTTOM, everything above moves up — `ordinal` is unique
    # per bookcase and is what the address prints, so the gap cannot stay.
    plinth = next_section("bc", [base, hutch], id="plinth", where="bottom")
    closed = renumber_sections([plinth, base, hutch])
    assert [s.id for s in closed] == ["plinth", "base", "hutch"]
    assert [s.ordinal for s in closed] == [1, 2, 3]


def test_the_depth_confirmation_can_say_how_many_shelves_it_would_change():
    """§3.3 requires the apply to be *"an explicit action, showing the count
    affected"*, so the count has to exist before the action does. The lab had
    it; the first cut of this module did not."""
    from app.domain import new_section, new_shelf, shelves_differing_from_default_depth

    section = new_section(id="se", library_id="lib", bookcase_id="bc",
                          columns=1, default_levels=3, default_depth=1)
    standing = [new_shelf(id="a", library_id="lib", depth_count=2),
                new_shelf(id="b", library_id="lib", depth_count=1),
                new_shelf(id="c", library_id="lib", depth_count=3)]
    assert shelves_differing_from_default_depth(section, standing) == 2


def test_applying_the_level_default_levels_every_column():
    """The explicit, opt-in counterpart of the depth apply, and the one the
    elevation's *apply to every column* button calls. It was exported with no
    caller and no test; a review found it a no-op-able."""
    from app.domain import (apply_default_levels, new_section,
                            with_column_levels, with_default_levels)

    section = new_section(id="se", library_id="lib", bookcase_id="bc",
                          columns=3, default_levels=4)
    ragged = with_column_levels(section, 2, 1).section
    assert ragged.column_levels == (4, 1, 4)

    evened = apply_default_levels(with_default_levels(ragged, 5))
    assert evened.section.column_levels == (5, 5, 5)
    # (4,1,4) -> (5,5,5): one new level on each tall column, four on the short
    # one. Six real shelves, and every one of them a row §3.1 says comes into
    # being the moment the grid does.
    assert len(evened.added) == 6, [(a.col, a.level) for a in evened.added]
    assert evened.dropped == (), "levelling every column dropped a slot"

    # ⚠ It prunes its gaps like every other extent change (P6.3.2). A quality
    # review found this the ONE `_pruned` call site nothing covered: remove it
    # and the whole suite stays green, while `POST /sections/{id}/levels`
    # answers 400 — "a gap stands in the case, and column 1 level 4 is
    # outside…" — for a request that is entirely legitimate.
    from app.domain import with_gaps

    holed = with_gaps(evened.section, [(1, 4)], gap=True).section
    lowered = apply_default_levels(with_default_levels(holed, 2))
    assert lowered.section.column_levels == (2, 2, 2)
    assert lowered.section.gaps == (), (
        "levelling every column kept a gap below the new height, so the next "
        "read of this section raises instead of rendering it"
    )


def test_a_photo_born_shelf_can_be_bound_into_a_drawn_slot_and_let_go_again():
    """P6.4's entry point, and the round trip that makes it safe: binding
    gives an address, unbinding takes only the address — the label, the depth
    and the shelf itself survive, because they are what its books point at."""
    from app.domain import ShelfAddress, bind_shelf, new_shelf, unbind_shelf

    photographed = new_shelf(id="sh", library_id="lib", label="מדף הסלון",
                             depth_count=2, created_at="2026-01-01T00:00:00Z")
    assert not photographed.is_addressed
    bound = bind_shelf(photographed, ShelfAddress("se", 2, 3))
    assert bound.is_addressed and bound.address.col == 2
    assert (bound.label, bound.depth_count) == ("מדף הסלון", 2)
    loose = unbind_shelf(bound)
    assert loose.address is None
    assert (loose.label, loose.depth_count, loose.created_at) == (
        "מדף הסלון", 2, "2026-01-01T00:00:00Z")


def test_a_real_lab_drawing_fits_the_domain_and_names_the_two_shifts():
    """MAP_PLAN §5's stated P6.1 deliverable, and P6.3's specification.

    `fixtures/map/lab_plan_v4.json` is a plan in the lab's own exported shape.
    Loading it through the domain pins the two places the lab's document and
    this model deliberately DISAGREE, so the port discovers them here rather
    than on the owner's data:

      1. **col and level are 0-based in the document, 1-based in the domain.**
         The domain REFUSES a 0 instead of re-basing it silently, so a
         forgotten `+1` raises rather than filing every book one shelf over;
      2. **section ids must be carried, not rebuilt.** `persist.ts` regenerates
         them from array position because "nothing outside the document refers
         to one" — a sentence that stopped being true when `shelves.section_id`
         did. Rebuilding by position also renumbers everything above a section
         inserted at the bottom.

    It is a real drawing shape on purpose: two storeys, an unattached case, an
    unnamed case, a two-section bookcase and a ragged column — each of which
    makes some rule observable that a tidy one-of-everything plan hides.
    """
    import json

    from app.domain import (Bookcase, Floor, Place, Rect, Section, ShelfAddress,
                            new_bookcase, new_floor, new_place, new_section)

    raw = json.loads(
        (REPO_ROOT / "fixtures" / "map" / "lab_plan_v4.json").read_text(
            encoding="utf-8"))
    assert raw["format"] == "booksnap.map-lab.plan" and raw["version"] == 4
    plan = raw["plan"]

    # Every floor of the document becomes a Floor of ONE site — the level the
    # lab never had (§3.9), so the import invents exactly one and says so.
    floors = [new_floor(id=f["id"], library_id="lib", site_id="st",
                        name=f["name"]) for f in plan["floors"]]
    assert [f.name for f in floors] == ["Ground floor", "Upstairs"]

    rooms = {r["id"]: new_place(id=r["id"], library_id="lib",
                                floor_id=r["floorId"], name=r["name"],
                                rect=Rect(**{k: r["rect"][k]
                                             for k in "xywh"}))
             for r in plan["rooms"]}
    assert rooms["r1"].rect == Rect(0, 0, 12, 9)
    assert rooms["r3"].floor_id == "f2", "a room lost its storey"

    # An unattached case keeps its floor — §3.7's "somewhere, not everywhere".
    cases = [new_bookcase(id=c["id"], library_id="lib", floor_id=c["floorId"],
                          name=c["name"], front=c["front"],
                          place_id=c["roomId"],
                          rect=Rect(**{k: c["rect"][k] for k in "xywh"}))
             for c in plan["cases"]]
    loose = [c for c in cases if c.place_id is None]
    assert [c.id for c in loose] == ["c3"] and loose[0].floor_id == "f2"
    assert [c.name for c in cases if not c.name] == [""], (
        "the fixture is meant to carry an unnamed case"
    )

    # Sections, ids CARRIED from the document rather than regenerated.
    big = plan["cases"][0]
    sections = [
        Section(id=f"{big['id']}:s{i + 1}", library_id="lib",
                bookcase_id=big["id"], ordinal=i + 1,
                column_levels=tuple(s["columnLevels"]),
                default_levels=s["defaultLevels"],
                default_depth=s["defaultDepth"])
        for i, s in enumerate(big["sections"])
    ]
    assert [s.ordinal for s in sections] == [1, 2]
    assert sections[0].column_levels == (5, 5, 3), "the ragged column flattened"
    assert sections[0].column_count == 3

    # …and the SHIFT. The document's (0,0) is the domain's (1,1); the domain
    # refuses the document's own numbering outright.
    for shelf in big["sections"][0]["shelves"]:
        address = ShelfAddress(sections[0].id, shelf["col"] + 1,
                               shelf["level"] + 1)
        assert address in sections[0].addresses, (
            f"{address} is outside the grid the section describes"
        )
    try:
        ShelfAddress(sections[0].id, big["sections"][0]["shelves"][0]["col"],
                     big["sections"][0]["shelves"][0]["level"])
    except DomainError:
        pass
    else:
        raise AssertionError(
            "the document's 0-based address was accepted as-is, so an "
            "importer that forgot the +1 would file every book one place over"
        )

    # The shelf the document says is one row deep inside a two-deep section:
    # its own depth, copied at creation and never read back through (§3.3).
    odd = [s for s in big["sections"][0]["shelves"] if s["depth"] == 1]
    assert odd, "the fixture is meant to carry a per-shelf depth override"
    assert sections[0].default_depth == 2


def test_a_gapped_cell_leaves_the_levels_below_it_exactly_where_they_were():
    """The owner's sentence, 2026-08-22: *"the lower shelves should not get up
    now. They should remain in place."*

    This is the whole reason a gap is a MASK and not a resize, and it is the
    one behaviour that distinguishes them: shrinking column 2 from 5 levels to
    2 would also remove the cell at level 3 — and would take levels 4 and 5
    with it, renumbering nothing but destroying the shelves whose addresses
    the owner has already been told to walk to.
    """
    from app.domain import new_section, with_gaps

    section = new_section(id="se", library_id="lib", bookcase_id="bc",
                          columns=3, default_levels=5)
    change = with_gaps(section, [(2, 3)], gap=True)

    assert [(a.col, a.level) for a in change.dropped] == [(2, 3)], (
        "gapping one cell released something other than that cell"
    )
    assert change.section.column_levels == (5, 5, 5), (
        "the extent moved: a gap is a mask over the case, not a resize of it"
    )
    below = {(a.col, a.level) for a in change.section.addresses if a.col == 2}
    assert below == {(2, 1), (2, 2), (2, 4), (2, 5)}, (
        "the shelves under the hole were renumbered, so every address printed "
        "for a book in column 2 now names a different shelf"
    )


def test_a_section_that_is_entirely_gaps_is_still_a_section():
    """*"When marking a cell and clicking on delete — it should not delete the
    bookcase itself"* (owner). Structural, not a UI courtesy: the extent is
    what the furniture IS, and no number of gaps touches it."""
    from app.domain import new_section, with_gaps

    section = new_section(id="se", library_id="lib", bookcase_id="bc",
                          columns=2, default_levels=3)
    every = [(col, level) for col in (1, 2) for level in (1, 2, 3)]
    change = with_gaps(section, every, gap=True)

    assert change.section.addresses == (), "a cell survived being gapped"
    assert change.section.column_count == 2
    assert change.section.column_levels == (3, 3), (
        "gapping every cell shrank the case, so the owner's next tap has "
        "nothing to switch back on"
    )


def test_switching_a_gap_back_on_mints_a_slot_at_the_same_address():
    """The other half of the owner's ask: *"user should be able to click on a
    'missing' cell and make it a real shelf again"*. The address is the same
    one it had, which is what makes it a restore rather than a new cell."""
    from app.domain import new_section, with_gaps

    section = new_section(id="se", library_id="lib", bookcase_id="bc",
                          columns=2, default_levels=4)
    holed = with_gaps(section, [(1, 2), (1, 3)], gap=True).section
    back = with_gaps(holed, [(1, 2)], gap=False)

    assert [(a.col, a.level) for a in back.added] == [(1, 2)]
    assert back.section.gaps == ((1, 3),), "the other hole was filled in too"
    assert back.dropped == (), "restoring a cell released a shelf"

    # ⚠ Both no-op directions, because `with_gaps` CLAIMS them and a quality
    # review found nothing holding the claim: making either raise left the
    # suite green. They are what makes a retried request safe — the client
    # whose response was dropped sends the same instruction again.
    again = with_gaps(holed, [(1, 3)], gap=True)          # already a gap
    assert again.section.gaps == holed.gaps
    assert again.added == () and again.dropped == ()
    never = with_gaps(holed, [(2, 1)], gap=False)         # never was one
    assert never.section.gaps == holed.gaps
    assert never.added == () and never.dropped == ()


def test_an_out_of_range_gap_raises_instead_of_gapping_something_near_it():
    """Same rule `with_column_count` records, on the same grounds: the lenient
    answer sits on the destructive path. A cell that is not in the section
    cannot be resolved to one that is — least of all silently."""
    from app.domain import DomainError, Section, new_section, with_gaps

    section = new_section(id="se", library_id="lib", bookcase_id="bc",
                          columns=2, default_levels=3)
    for cells in ([(9, 1)], [(0, 1)], [(1, 4)], [(1, 0)], [(1, 1), (2, 9)], []):
        try:
            with_gaps(section, cells, gap=True)
        except DomainError:
            continue
        raise AssertionError(f"{cells} was accepted against a 2x3 section")
    assert section.gaps == ()

    # And the record itself cannot hold one, so no path — a store load, an
    # import, a future route — can put a hole outside the wood.
    try:
        Section(id="se", library_id="lib", bookcase_id="bc",
                column_levels=(3,), gaps=((1, 9),))
    except DomainError:
        return
    raise AssertionError("a section was built with a gap outside its extent")


def test_a_gap_goes_with_the_wood_when_the_column_it_stands_in_shrinks():
    """A gap at level 5 of a column that becomes 3 levels tall is a hole in
    something that is no longer there. It is pruned, so growing the column
    back yields a SHELF — the alternative is a case that returns taller with
    an invisible cell missing from the middle of it.

    The cell that is still inside the shorter column stays a gap: it is a hole
    in wood that never went away.
    """
    from app.domain import new_section, with_column_count, with_column_levels, with_gaps

    section = new_section(id="se", library_id="lib", bookcase_id="bc",
                          columns=2, default_levels=5)
    holed = with_gaps(section, [(1, 2), (1, 5), (2, 1)], gap=True).section

    shorter = with_column_levels(holed, 1, 3).section
    assert shorter.gaps == ((1, 2), (2, 1)), (
        "a gap survived the level it stood at being removed"
    )
    taller = with_column_levels(shorter, 1, 5)
    assert (1, 5) in [(a.col, a.level) for a in taller.added], (
        "the column grew back with a hole nobody asked for"
    )

    # The same rule when a whole column goes.
    narrower = with_column_count(holed, 1).section
    assert narrower.gaps == ((1, 2), (1, 5)), (
        "column 2's gap outlived column 2"
    )


def test_a_new_section_copies_the_shape_of_its_neighbour_but_not_its_holes():
    """What saves re-entering is how wide and how tall. A hole is where
    something ELSE stands (a television), and the hutch above the base does
    not inherit the television."""
    from app.domain import new_section, next_section, with_gaps

    base = with_gaps(
        new_section(id="s1", library_id="lib", bookcase_id="bc",
                    columns=3, default_levels=4),
        [(2, 2)], gap=True,
    ).section
    hutch = next_section("bc", [base], id="s2")

    assert hutch.column_count == 3 and hutch.column_levels == (4, 4, 4)
    assert hutch.gaps == (), "the hutch inherited the base's television"


def test_two_sections_holding_the_same_cells_compare_equal_whatever_the_order():
    """The editor sends cells in the order the owner tapped them. A section
    that differs from itself only by that order is a write nobody asked for —
    and, once P6.4b journals map edits, an undo entry for a change that never
    happened."""
    from app.domain import Section

    one = Section(id="se", library_id="lib", bookcase_id="bc",
                  column_levels=(4, 4), gaps=((2, 3), (1, 1), (2, 3)))
    other = Section(id="se", library_id="lib", bookcase_id="bc",
                    column_levels=(4, 4), gaps=((1, 1), (2, 3)))

    assert one.gaps == ((1, 1), (2, 3)), "the mask was not normalised"
    assert one == other
    assert (2, 3) in one.gaps and (2, 4) not in one.gaps


# --- the shelf alias (P6.4a, MAP_PLAN §3.11) -------------------------------

def _alias(alias_id, shelf_id, **kw):
    from app.domain.alias import ShelfAlias

    return ShelfAlias(alias_id=alias_id, library_id="lib", shelf_id=shelf_id,
                      merged_at="2026-08-25T10:00:00+00:00", **kw)


def test_identities_lists_the_survivor_first_and_then_what_it_absorbed():
    """The list every question about a merged shelf must be asked under.

    ⚠ §3.11 rewrites nothing, so a copy that arrived with an absorbed identity
    still names IT — six tables name a shelf and only two have a foreign key,
    which is why the alternative (rewrite every reference) reports a clean
    `foreign_key_check` over a library whose locations have quietly moved. The
    port tells every `books_on_shelf` caller to build its argument here, so
    the ORDER and the completeness are both contract.
    """
    from app.domain.alias import identities

    aliases = (_alias("A", "S"), _alias("B", "S"), _alias("C", "other"))
    assert identities("S", aliases) == ("S", "A", "B"), (
        "the survivor comes first, and every absorbed identity follows")
    assert identities("other", aliases) == ("other", "C")
    assert identities("never-merged", aliases) == ("never-merged",), (
        "a shelf nothing absorbed is still one identity, not zero")


def test_absorbed_by_answers_only_for_the_shelf_asked_about():
    """Behind the *formerly …* line, and behind `identities`."""
    from app.domain.alias import absorbed_by

    aliases = (_alias("A", "S"), _alias("B", "other"))
    assert [a.alias_id for a in absorbed_by("S", aliases)] == ["A"]
    assert absorbed_by("nobody", aliases) == ()


def test_a_shelf_may_not_be_an_alias_of_itself():
    """Not pedantry: `resolve` would answer with the id it was handed, so
    every caller would believe the shelf was still there — and the row would
    make it permanently undeletable, which is the cycle hazard in miniature.

    ⚠ Nothing downstream catches it. Traced through `save_alias` on both
    implementations: the survivor is live, it is not an `alias_id`, and it has
    no absorbees, so every branch passes and the row inserts.
    """
    from app.domain.alias import DomainError

    try:
        _alias("A", "A")
    except DomainError as exc:
        assert "itself" in str(exc), exc
    else:
        raise AssertionError("a shelf was stored as an alias of itself")


def test_an_alias_belongs_to_a_library():
    """H2, at the door — the same rule every entity in this domain carries."""
    from app.domain.alias import DomainError, ShelfAlias

    try:
        ShelfAlias(alias_id="A", library_id="", shelf_id="S",
                   merged_at="2026-08-25T10:00:00+00:00")
    except DomainError:
        pass
    else:
        raise AssertionError("an alias was built with no library")


def test_a_slot_that_already_holds_a_shelf_refuses_the_bind_itself():
    """MAP_PLAN §3.14, at the level that decides it.

    ⚠ This gate exists because the rule survived its own mutation one level
    up: delete the check from `plan_bind` and `bind_shelf_to_slot` still
    refuses, because `shelves_by_slot` catches the write and the caller
    translates it. That is redundant enforcement, which is the pattern here —
    but a rule whose only proof runs through a unique index is a rule that
    disappears the day somebody writes a second caller, and §3.14's whole
    point is that binding stops at a taken slot rather than resolving it.
    """
    from app.domain import (
        Section, ShelfAddress, SlotTaken, new_shelf, plan_bind,
    )

    section = Section(id="se", library_id="lib", bookcase_id="bc", ordinal=1,
                      column_levels=(2, 2))
    homeless = new_shelf(id="photo-born", library_id="lib")
    occupant = new_shelf(id="drawn", library_id="lib", label="מדף א",
                         address=ShelfAddress("se", 1, 1))

    try:
        plan_bind(homeless, section, ShelfAddress("se", 1, 1), occupant)
    except SlotTaken as exc:
        assert exc.occupant is occupant, (
            "the refusal must carry the shelf the decision was made about")
        assert "מדף א" in str(exc)
    else:
        raise AssertionError("a bind landed on top of another shelf")

    # ...and the same slot, free, is exactly what it is for.
    assert plan_bind(homeless, section, ShelfAddress("se", 1, 1),
                     None).address == ShelfAddress("se", 1, 1)


def test_the_bind_ladder_answers_about_the_SHELF_before_the_slot():
    """⚠ The order is argued at length in `plan_bind` and was enforced by
    nothing: a review swapped the two blocks and the whole ring stayed green,
    because no test built the one case that tells them apart — an addressed
    shelf aimed at an OCCUPIED slot.

    Only the last rung offers a next step (*merge instead?*, P6.4d). Offering
    it to somebody whose request was impossible for a simpler reason is how a
    dangerous button gets pressed by accident, and that is the whole of §3.14's
    argument for keeping bind and merge apart.
    """
    from app.domain import (
        AlreadyOnTheMap, Section, ShelfAddress, new_shelf, plan_bind,
    )

    section = Section(id="se", library_id="lib", bookcase_id="bc", ordinal=1,
                      column_levels=(2, 2))
    standing = new_shelf(id="drawn", library_id="lib",
                         address=ShelfAddress("se", 1, 2))
    occupant = new_shelf(id="other", library_id="lib",
                         address=ShelfAddress("se", 1, 1))

    try:
        plan_bind(standing, section, ShelfAddress("se", 1, 1), occupant)
    except AlreadyOnTheMap:
        pass
    else:
        raise AssertionError(
            "an addressed shelf aimed at a taken slot was offered the merge")


def test_binding_a_shelf_to_the_cell_it_ALREADY_stands_in_is_a_no_op():
    """The promise `PUT` makes, and the reason the refusal above is not
    reached by a double tap.

    A retry after a dropped response, or two taps on one picker option, used
    to answer `AlreadyOnTheMap` — which the client renders as *the drawing has
    changed since*, a false statement about the owner's own request landing.
    The unbind beside it has always answered 200 for the same event.
    """
    from app.domain import Section, ShelfAddress, new_shelf, plan_bind

    section = Section(id="se", library_id="lib", bookcase_id="bc", ordinal=1,
                      column_levels=(2, 2))
    where = ShelfAddress("se", 1, 1)
    standing = new_shelf(id="drawn", library_id="lib", address=where)

    assert plan_bind(standing, section, where, standing) == standing
    assert plan_bind(standing, section, where, None) == standing


def test_an_address_naming_another_section_is_refused_by_the_rule_itself():
    """⚠ Unreachable from the only caller today — the route builds the
    address from the section it just loaded — and gated here anyway, because
    `plan_bind` is exported and the next caller will not be that one. A
    review deleted the clause and nothing failed."""
    from app.domain import DomainError, Section, ShelfAddress, new_shelf, plan_bind

    section = Section(id="se", library_id="lib", bookcase_id="bc", ordinal=1,
                      column_levels=(2, 2))
    homeless = new_shelf(id="photo-born", library_id="lib")
    try:
        plan_bind(homeless, section, ShelfAddress("elsewhere", 1, 1), None)
    except DomainError as exc:
        assert "elsewhere" in str(exc)
    else:
        raise AssertionError("a shelf was bound into another section's cell")
