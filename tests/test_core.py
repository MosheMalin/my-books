# -*- coding: utf-8 -*-
"""Minimal test suite — run with:  python -m pytest tests/  (or python tests/test_core.py)

Covers the matcher's evidence gates and normalization, which are the logic most
likely to regress silently. OCR/segmentation are validated visually on samples.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from booksnap.catalog import normalize, LocalCatalog, CatalogEntry
from booksnap.match import match_candidate, resolve_duplicates
from booksnap.types import Match


def _catalog():
    return LocalCatalog([
        CatalogEntry("0", "מלכי הכופרים", "פול קארני"),
        CatalogEntry("1", "ספינות מן המערב", "פול קארני"),
        CatalogEntry("2", "לימודי אש", "מריה וי סניידר"),
        CatalogEntry("3", "לימודי רעל", "מריה וי סניידר"),
    ])


def test_normalize_strips_nikud_and_punct():
    # nikud and punctuation gone; final mem folded to regular mem by design
    assert normalize("שָׁלוֹם, עוֹלָם!") == "שלומ עולמ"


def test_normalize_folds_final_letters():
    # final mem -> regular mem, so OCR final/medial confusion is harmless
    assert normalize("שלום") == normalize("שלו\u05dd".replace("\u05dd", "\u05de"))


def test_garbage_does_not_match():
    # random Hebrew-looking noise must not resolve to any title
    assert match_candidate("אאא הש שי בב", _catalog()) is None


def test_correct_title_wins_over_sibling():
    # OCR of מלכי הכופרים (slightly corrupted) must beat the sibling ספינות
    m = match_candidate("פול קארני מלכי הכופרם", _catalog())
    assert m is not None and m.title == "מלכי הכופרים"


def test_author_alone_is_not_auto():
    # author match with no real title evidence must not be AUTO
    m = match_candidate("פול קארני", _catalog())
    assert m is None or m.tier == "REVIEW"


def test_series_siblings_separated():
    a = match_candidate("מריה וי סניידר לימודי אש", _catalog())
    b = match_candidate("מריה וי סניידר לימודי רעל", _catalog())
    assert a.title == "לימודי אש"
    assert b.title == "לימודי רעל"


def test_dedup_demotes_second_claimant():
    m1 = Match("מלכי הכופרים", "פול קארני", "AUTO", 90.0, catalog_id="0")
    m2 = Match("מלכי הכופרים", "פול קארני", "AUTO", 70.0, catalog_id="0")
    resolved = resolve_duplicates([m1, m2])
    tiers = sorted(m.tier for m in resolved)
    assert tiers == ["AUTO", "REVIEW"]   # higher score keeps AUTO


# --- regressions from real mis-matches on the Durrell shelf ----------------
# Each of these produced a confidently wrong title in run #2.

def _durrell_catalog():
    return LocalCatalog([
        CatalogEntry("0", "החיה בחבילה", "ג'ראלד דארל"),
        CatalogEntry("1", "ציפור הלעג", "ג'ראלד דארל"),
        CatalogEntry("2", "משפחתי וחיות אחרות", "ג'ראלד דארל"),
    ])


def test_noise_token_plus_author_does_not_invent_title():
    # Real OCR of "הפיקניק ומהומות אחרות" (absent from the catalog). The stray
    # token היה scored 86 against החיה and, pooled with the author tokens,
    # passed the old evidence gate. Nothing here is real title evidence.
    text = "דארל הפקנקומהוגוות אחות הבש וה חי ספרית פעלים ג'ראלד דארל הפיקמק ומהוממות אחרות היה"
    m = match_candidate(text, _durrell_catalog())
    assert m is None or m.title != "החיה בחבילה", f"invented {m.title!r}"


def test_author_agreement_alone_cannot_create_a_match():
    # Author reads perfectly, title is unreadable: must not resolve to a title.
    m = match_candidate("ג'ראלד דארל ג'ראלד דארל", _durrell_catalog())
    assert m is None


def test_title_unlike_the_query_is_rejected():
    # OCR of "ציפורי ישראל והמזרח התיכון" (absent from the catalog). ציפורי
    # fuzz-matches ציפור at 91, but the whole title looks nothing like the text.
    text = "ציפורי ישראל והמזרת התיכון ציפורי ישראל והמזוח התיכון"
    m = match_candidate(text, _durrell_catalog())
    assert m is None or m.title != "ציפור הלעג", f"invented {m.title!r}"


def test_short_subset_title_is_rejected_by_ngram_gate():
    """token_set_ratio scores a short title that is a SUBSET of the query 100.

    That pathology let the one-word "ציפורי" (Sepphoris) beat the real book on
    a spine reading "ציפורי ישראל והמזרח התיכון" and go AUTO. Character n-gram
    cosine penalises the length mismatch (51 vs 100) and rejects it.
    """
    import dataclasses
    from rapidfuzz import fuzz
    from booksnap.match import ngram_sim
    from booksnap.config import CONFIG
    q, t = normalize("ציפורי ישראל והמזרח התיכון"), normalize("ציפורי")
    assert fuzz.token_set_ratio(q, t) == 100, "pathology precondition"
    assert ngram_sim(q, t) < 60, ngram_sim(q, t)

    # NOTE: this pair scores 51, so the SHIPPED threshold (50) does not reject
    # it — 55 would, but swept worse overall. The gate is a broad precision
    # win, not a fix for this one spine; asserting otherwise would be a test
    # that lies about what the product does.
    cat = LocalCatalog([CatalogEntry("0", "ציפורי", "ויס, זאב")])
    cfg = dataclasses.replace(CONFIG.match, min_ngram_sim=55)
    assert match_candidate("ציפורי ישראל והמזרת התיכון", cat, cfg) is None
    assert match_candidate("ציפורי ישראל והמזרת התיכון", cat) is not None


def test_fused_ocr_words_still_match():
    """Whole-page OCR read "ג'ראלד דארלציפור הלעג" — author glued to title.

    The catalog token ציפור is plainly present but matched nothing, so a real
    book on the shelf was reported missing.
    """
    cat = LocalCatalog([CatalogEntry("0", "ציפור הלעג", "ג'ראלד דארל")])
    m = match_candidate("ג'ראלד דארלציפור הלעג", cat)
    assert m is not None and m.title == "ציפור הלעג", m


def test_ngram_keeps_edition_spelling_variants():
    """The gate must not reject the same book printed with different particles."""
    from booksnap.match import ngram_sim
    a = normalize("כל הדברים הנבונים והנפלאים")
    b = normalize("כל הדברים נבונים כמופלאים")
    assert ngram_sim(a, b) >= 60, ngram_sim(a, b)


def test_dedup_drops_far_weaker_claim():
    # The same entry legitimately won elsewhere on the shelf; a claim far below
    # the winner is a mis-assignment, not a second copy.
    strong = Match("ציפור הלעג", "ג'ראלד דארל", "AUTO", 95.0, catalog_id="1")
    weak = Match("ציפור הלעג", "ג'ראלד דארל", "REVIEW", 55.0, catalog_id="1")
    resolved = resolve_duplicates([strong, weak])
    assert resolved[0] is strong and resolved[1] is None




def test_near_duplicate_titles_collapse_to_one_claim():
    """Same book matched via two catalog editions -> weaker claim dropped."""
    from booksnap.match import resolve_near_duplicates
    a = Match(title="הצחקתם אותנו", author="גל נור, יצחק", tier="AUTO",
              score=122.5, catalog_id="sim1")
    b = Match(title="הצחקתם אותנו : בדיחות פוליטיות", author="יצחק גל-נור",
              tier="REVIEW", score=72.5, catalog_id="nli9")
    out = resolve_near_duplicates([a, b])
    assert out[0] is a and out[1] is None


def test_near_duplicate_spares_series_siblings():
    from booksnap.match import resolve_near_duplicates
    a = Match(title="לימודי אש", author="מריה וי סניידר", tier="AUTO",
              score=115.0, catalog_id="1")
    b = Match(title="לימודי רעל", author="מריה וי סניידר", tier="AUTO",
              score=115.0, catalog_id="2")
    out = resolve_near_duplicates([a, b])
    assert out[0] is a and out[1] is b


def test_author_fragment_cannot_claim_a_title():
    """A read that is purely another matched book's author name is unmatched."""
    from booksnap.match import suppress_author_fragments
    real = Match(title="הומור", author="ענת זיידמן", tier="AUTO",
                 score=122.5, catalog_id="s1")
    phantom = Match(title="זיידמן", author="מרום, דוד א. מחבר", tier="AUTO",
                    score=106.2, catalog_id="s2")
    texts = ["הומור ענת ז", "ענת זייידמן"]     # triple-yod OCR typo included
    out = suppress_author_fragments(texts, [real, phantom])
    assert out[0] is real and out[1] is None


def test_author_fragment_spares_title_plus_author_reads():
    from booksnap.match import suppress_author_fragments
    a = Match(title="ארבינקא", author="אפרים קישון", tier="AUTO",
              score=122.5, catalog_id="s1")
    b = Match(title="ספר משפחתי", author="אפרים קישון", tier="AUTO",
              score=122.5, catalog_id="s2")
    texts = ["ארבינקא קישון", "ספר משפחתי קישון"]   # title+author: keep both
    out = suppress_author_fragments(texts, [a, b])
    assert out[0] is a and out[1] is b




def test_author_fragment_guard_spares_reads_containing_the_name():
    """A full title+author read that merely CONTAINS another book's author
    must survive (token_set subset pathology; measured: המלון הגיקי-עברי)."""
    from booksnap.match import suppress_author_fragments
    a = Match(title="רצינות ההומור", author="רות בונדי", tier="AUTO",
              score=122.5, catalog_id="s1")
    b = Match(title="המלון הגיקי-עברי", author="שנקולבסקי, רפאל", tier="AUTO",
              score=115.0, catalog_id="s2")
    texts = ["רצינות ההומור בונדי", "המלון הגיקי-עברי של גבע רות בונדי"]
    out = suppress_author_fragments(texts, [a, b])
    assert out[0] is a and out[1] is b




def test_short_title_words_count_in_whole_title_similarity():
    """Token filtering drops 2-char words (כן) from the query; the whole-title
    similarity must compare full text to full text, or the entry WITHOUT the
    short word wins (measured on IMG_8125: אדוני ראש הממשלה beat the correct
    כן, אדוני ראש הממשלה on the read "כן, אדוני ראש הממש")."""
    cat = LocalCatalog([
        CatalogEntry("0", "אדוני ראש הממשלה", "יהודה אבנר"),
        CatalogEntry("1", "כן, אדוני ראש הממשלה", "ג'ונתן לין"),
    ])
    m = match_candidate("כן, אדוני ראש הממש", cat)
    assert m is not None and m.catalog_id == "1", m and m.title




def test_one_word_title_explaining_partial_read_is_review():
    """The subset pathology in miniature: a single-content-word title that
    leaves part of the read unexplained must not be AUTO (measured phantoms:
    "סליחה" on the read "סליחה שטעינו", "ציפורים" on "ציפורים וקרובים")."""
    cat = LocalCatalog([CatalogEntry("0", "סליחה", "ישראל הר")])
    m = match_candidate("סליחה שטעינו", cat)
    assert m is not None and m.tier == "REVIEW", m and m.tier
    # ...but a one-word title whose read is FULLY explained stays AUTO
    cat2 = LocalCatalog([CatalogEntry("0", "ארבינקא", "אפרים קישון")])
    m2 = match_candidate("ארבינקא קישון", cat2)
    assert m2 is not None and m2.tier == "AUTO", m2 and m2.tier




def test_one_word_read_cannot_auto_a_multiword_title():
    """Mirror of the one-word-title cap: a ONE-word read trivially has
    qcov=1.0 but is too little evidence for a multi-word title (measured on
    IMG_8124: fragment "המחזורית" went AUTO on an NLI DVD record)."""
    cat = LocalCatalog([CatalogEntry("0", "די וי די המערכה המחזורית והמחזוריות", "")])
    m = match_candidate("המחזורית", cat)
    assert m is None or m.tier == "REVIEW", m and m.tier
    # a one-word read on a one-word title stays AUTO (שוגון on IMG_8123)
    cat2 = LocalCatalog([CatalogEntry("0", "שוגון", "ג'יימס קלאוול")])
    m2 = match_candidate("שוגון", cat2)
    assert m2 is not None and m2.tier == "AUTO", m2 and m2.tier


def test_fragment_read_yields_to_its_full_read():
    """A read whose tokens are a subset of a longer matched read is a partial
    re-read of the same spine — its independent claim is dropped."""
    from booksnap.match import suppress_fragment_reads
    full = Match(title="הטבלה המחזורית", author="פרימו לוי", tier="AUTO",
                 score=130.0, catalog_id="s1")
    frag = Match(title="די וי די המערכה המחזורית והמחזוריות", author="",
                 tier="AUTO", score=86.7, catalog_id="n1")
    texts = ["הטבלה המחזורית פרימו לוי", "המחזורית"]
    out = suppress_fragment_reads(texts, [full, frag])
    assert out[0] is full and out[1] is None
    # distinct spines with overlapping words survive
    a = Match(title="לימודי אש", author="סניידר", tier="AUTO", score=115,
              catalog_id="a")
    b = Match(title="לימודי רעל", author="סניידר", tier="AUTO", score=115,
              catalog_id="b")
    out2 = suppress_fragment_reads(["לימודי אש", "לימודי רעל"], [a, b])
    assert out2[0] is a and out2[1] is b




def test_short_oneword_title_matchable_with_author_corroboration():
    """עדן/הצלם class: a short one-word title can never yield 2 hits or a
    5-char token, so it was structurally unmatchable. Full title match +
    strong author agreement is real evidence -> REVIEW (never author-alone:
    the whole title must still match)."""
    cat = LocalCatalog([CatalogEntry("0", "עדן", "סטניסלב לם")])
    m = match_candidate("עדן סטניסלב לם", cat)
    assert m is not None and m.title == "עדן", m
    # author alone must still NOT create a match
    assert match_candidate("סטניסלב לם", LocalCatalog(
        [CatalogEntry("0", "עדן", "סטניסלב לם")])) is None


def test_ngram_gate_not_diluted_by_author_in_read():
    """The read carries the author; n-gram cosine vs the title ALONE punished
    exactly the right entry (נהר השמים הגדול died on the gate by 0.04)."""
    cat = LocalCatalog([CatalogEntry("0", "נהר השמים הגדול", "גרגורי בנפורד")])
    m = match_candidate("נהר השמים / גרגורי בנפורד", cat)
    assert m is not None and m.title == "נהר השמים הגדול", m


def test_fragment_suppression_is_substring_tolerant():
    """"ראה אתמול" is a torn read of the נתראה אתמול spine — ראה is not an
    exact token of the fuller read, but it is inside נתראה."""
    from booksnap.match import suppress_fragment_reads
    full = Match(title="נתראה אתמול", author="רייצ'ל לין סולומון", tier="AUTO",
                 score=130.0, catalog_id="s1")
    frag = Match(title="אתמול", author="אבדי, אהרן", tier="REVIEW",
                 score=115.0, catalog_id="n1")
    texts = ["נתראה אתמול רייצ'ל לין סולומון", "ראה אתמול"]
    out = suppress_fragment_reads(texts, [full, frag])
    assert out[0] is full and out[1] is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
