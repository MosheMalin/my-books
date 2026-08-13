# -*- coding: utf-8 -*-
"""Offline integration tests for the NLI catalog and fallback adapters.

These use mocked transports/clients so they run with NO network, NO API key,
and NO cloud SDK installed. They prove the wiring — query building, response
parsing, matcher hand-off, fallback re-matching — so you can trust the plumbing
before onboarding Google Cloud or an NLI key.

Run:  python tests/test_integrations.py
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from booksnap.nli_catalog import NLICatalog
from booksnap.fallback import GoogleVisionFallback, ClaudeVisionFallback
from booksnap.match import match_candidate
from booksnap.catalog import LocalCatalog, CatalogEntry


# --- fake NLI: returns records shaped like the real API, ignores the key ----
FAKE_NLI_RECORDS = [
    {"recordid": "990001", "title": "מלכי הכופרים / פול קארני",
     "creator": "קארני, פול"},
    {"recordid": "990002", "title": "ספינות מן המערב", "creator": "קארני, פול"},
    {"recordid": "990003", "title": "מלחמות הברזל", "creator": "קארני, פול"},
]


def fake_nli_transport(url: str) -> str:
    assert "api.nli.org.il/openlibrary/search" in url
    assert "query=" in url
    return json.dumps(FAKE_NLI_RECORDS)


def test_nli_query_is_title_scoped_and_per_term():
    cat = NLICatalog(api_key="k", transport=fake_nli_transport)
    url = cat._term_url(cat._pick_terms("פול קארני הכופרם הש שי")[0])
    # title-scoped (not `any`), one term per query, Hebrew url-encoded
    assert "query=title%2Ccontains%2C" in url and "%D7" in url


# Real NLI shape, captured from a live response: a bare JSON list whose fields
# are Dublin Core URIs wrapping values in [{"@value": ...}]. The old parser
# stringified those dicts into the title; this fixture locks the fix in.
LIVE_SHAPE = [{
    "@id": "https://www.nli.org.il/en/books/NNL_ALEPH990012",
    "http://purl.org/dc/elements/1.1/title":
        [{"@value": "חברברי הסונה / ג'ראלד דארל ; תורגם מאנגלית"}],
    "http://purl.org/dc/elements/1.1/creator":
        [{"@value": "דארל, ג'ראלד, 1925-1995$$Qדארל, ג'ראלד"}],
    "http://purl.org/dc/elements/1.1/type": [{"@value": "book"}],
    "http://purl.org/dc/elements/1.1/recordid": [{"@value": "990012"}],
}, {
    "@id": "https://www.nli.org.il/en/archives/NNL_ARCHIVE_1",
    "http://purl.org/dc/elements/1.1/title": [{"@value": "תצלומים אישיים."}],
    "http://purl.org/dc/elements/1.1/type": [{"@value": "archive"}],
}]


def test_page_reader_groups_paragraphs_with_boxes():
    """Whole-page mode: paragraphs -> PageBlocks with pixel boxes, offline."""
    from booksnap.pagereader import GoogleVisionPageReader

    class Sym:
        def __init__(s, t): s.text, s.property = t, None
    class Word:
        def __init__(s, t): s.symbols = [Sym(c) for c in t]
    class V:
        def __init__(s, x, y): s.x, s.y = x, y
    class Box:
        def __init__(s, x0, y0, x1, y1):
            s.vertices = [V(x0, y0), V(x1, y0), V(x1, y1), V(x0, y1)]
    class Para:
        def __init__(s, words, box):
            s.words = [Word(w) for w in words]
            s.bounding_box, s.confidence = box, 0.9
    class Blk:
        def __init__(s, paras): s.paragraphs = paras
    class Page:
        def __init__(s, blocks): s.blocks = blocks
    class Ann:
        def __init__(s, pages): s.pages = pages
    class Resp:
        error = type("E", (), {"message": ""})()
        full_text_annotation = Ann([Page([Blk([
            Para(["ג'ראלד", "דארל", "לחתן", "את", "אמא"], Box(10, 20, 60, 400)),
            Para(["xx"], Box(0, 0, 5, 5)),          # too short, must be dropped
        ])])])
    class Client:
        def document_text_detection(self, image=None): return Resp()

    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".jpg")
    os.write(fd, b"not-a-real-jpeg"); os.close(fd)
    try:
        blocks = GoogleVisionPageReader(Client()).read_page(path)
    finally:
        os.unlink(path)
    assert len(blocks) == 1, f"got {len(blocks)} blocks"
    b = blocks[0]
    assert "לחתן את אמא" in b.text, b.text
    assert (b.x0, b.y0, b.x1, b.y1) == (10, 20, 60, 400)
    assert b.is_vertical      # spine text is taller than wide


def test_overlapping_blocks_merge_into_one_spine():
    """Books are solid objects: texts sharing a region are one spine."""
    from booksnap.pagereader import PageBlock, merge_overlapping
    # author paragraph sitting inside the same narrow spine column as the title
    author = PageBlock(text="ג'ראלד דארל", x0=10, y0=20, x1=60, y1=220)
    title = PageBlock(text="גן האלים", x0=12, y0=100, x1=58, y1=400)
    other = PageBlock(text="ספר אחר", x0=200, y0=20, x1=250, y1=400)
    out = merge_overlapping([author, title, other], thresh=0.35)
    assert len(out) == 2, [b.text for b in out]
    merged = [b for b in out if "דארל" in b.text][0]
    assert "גן האלים" in merged.text
    assert (merged.x0, merged.y0, merged.x1, merged.y1) == (10, 20, 60, 400)


def test_replay_catalog_is_deterministic():
    """Recorded retrieval replays exactly; unseen queries are counted, not faked."""
    from booksnap.replay import RecordingCatalog, ReplayCatalog
    inner = LocalCatalog([CatalogEntry("0", "גן האלים", "ג'ראלד דארל")])
    rec = RecordingCatalog(inner)
    rec.candidates("דארל גן האלים")
    replay = ReplayCatalog(rec.log)
    assert [e.title for e in replay.candidates("דארל גן האלים")] == ["גן האלים"]
    assert replay.candidates("never asked") == []
    assert replay.misses == ["never asked"]


def test_nli_parses_live_jsonld_shape():
    ents = NLICatalog._parse(json.dumps(LIVE_SHAPE))
    assert len(ents) == 1, "archive records must be filtered out"
    e = ents[0]
    assert e.title == "חברברי הסונה", f"got {e.title!r}"
    assert e.author == "דארל, ג'ראלד", f"got {e.author!r}"


def test_nli_parse_and_match_end_to_end():
    cat = NLICatalog(api_key="guest", transport=fake_nli_transport)
    ents = cat.candidates("פול קארני הכופרם")
    titles = {e.title for e in ents}
    assert "מלכי הכופרים" in titles          # trailing '/ author' stripped
    # the matcher, given NLI candidates, picks the right sibling
    m = match_candidate("פול קארני מלכי הכופרם", cat)
    assert m is not None and m.title == "מלכי הכופרים"


def test_nli_empty_ocr_returns_no_candidates():
    cat = NLICatalog(api_key="guest", transport=fake_nli_transport)
    assert cat.candidates("אב") == []        # nothing usable to query with


def test_nli_transport_failure_is_safe():
    calls = []

    def boom(url):
        calls.append(url)
        raise ConnectionError("network down")

    cat = NLICatalog(api_key="guest", transport=boom)
    # ⚠ The backoff is zeroed, not the retry COUNT. `_fetch` sleeps
    # `retry_backoff * (attempt + 1)` between attempts, so at the shipped 1.5s
    # this one test slept 22.5s — 28% of the whole python suite — waiting for
    # a network that was never going to answer. Sleeping proves nothing here;
    # what the test is about is that a dead transport degrades to "no
    # candidates" instead of raising. Asserting the retries and the failure
    # COUNT below covers strictly more than the sleep did.
    cat.retry_backoff = 0
    assert cat.candidates("פול קארני הכופרם") == []   # degrades to no match
    assert cat.failed_fetches > 0                     # and says it failed
    assert cat.last_error == "network down"
    # every query really was retried `retries` times before being given up on
    assert len(calls) == cat.retries * cat.failed_fetches


# --- fake Google Vision client ----------------------------------------------
class _FakeAnnotation:
    def __init__(self, text): self.text = text


class _FakeResp:
    def __init__(self, text):
        self.full_text_annotation = _FakeAnnotation(text)
        self.error = type("E", (), {"message": ""})()


class _FakeVisionClient:
    def __init__(self, text): self._text = text
    def document_text_detection(self, image=None):
        return _FakeResp(self._text)


def test_google_vision_returns_clean_text(tmp_path=None):
    import tempfile, os
    fb = GoogleVisionFallback(_FakeVisionClient("מלכי\nהכופרים\nפול קארני"))
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"fakejpeg")
        p = f.name
    try:
        r = fb.read_spine(p)
        assert r.provider == "google_vision"
        assert r.text == "מלכי הכופרים פול קארני"   # newlines collapsed
    finally:
        os.unlink(p)


def test_claude_vision_returns_structured(tmp_path=None):
    import tempfile, os
    fb = ClaudeVisionFallback(lambda b: {"title": "מלכי הכופרים",
                                         "author": "פול קארני"})
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"fakejpeg")
        p = f.name
    try:
        r = fb.read_spine(p)
        assert r.title == "מלכי הכופרים" and r.author == "פול קארני"
        assert r.provider == "claude_vision"
    finally:
        os.unlink(p)


# --- LLM page reader (mode='llmpage') ---------------------------------------
def _tmp_jpeg(w=200, h=120):
    import tempfile
    from PIL import Image
    f = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    Image.new("RGB", (w, h), (200, 180, 150)).save(f, format="JPEG")
    f.close()
    return f.name


def test_llm_unrotate_box_roundtrip():
    """Tile boxes in rotated coords must map back to original pixels exactly."""
    from booksnap.llmreader import _unrotate_box
    W, H = 100, 60
    box = (10, 20, 40, 50)                       # in original coordinates
    # forward maps (see PIL ROTATE_270/ROTATE_90 semantics)
    cw = (H - box[3], box[0], H - box[1], box[2])
    ccw = (box[1], W - box[2], box[3], W - box[0])
    assert _unrotate_box(cw, "cw", W, H) == box
    assert _unrotate_box(ccw, "ccw", W, H) == box
    assert _unrotate_box(box, "none", W, H) == box


def test_llm_reader_tiles_dedupe_and_survive_tile_failure():
    from booksnap.config import LlmReaderConfig
    from booksnap.llmreader import ClaudePageReader

    calls = []

    def fake_send(jpeg: bytes) -> str:
        calls.append(len(jpeg))
        if len(calls) == 1:      # overlap: same title, author illegible here
            return json.dumps({"books": [
                {"title": "גן האלים", "author": ""},
                {"title": "", "author": "ריק"}]})       # empty title dropped
        if len(calls) == 2:      # richer read of the same book + a new one
            return json.dumps({"books": [
                {"title": "גן האלים", "author": "ג'ראלד דארל"},
                {"title": "קרובתי רוזי", "author": ""}]})
        raise ConnectionError("tile 3 boom")            # must not sink the rest

    cfg = LlmReaderConfig(grid_rows=3, grid_cols=1, rotate="cw")
    rdr = ClaudePageReader(send=fake_send, cfg=cfg)
    p = _tmp_jpeg()
    import os
    try:
        blocks = rdr.read_page(p)
    finally:
        os.unlink(p)
    texts = [b.text for b in blocks]
    assert texts.count("גן האלים ג'ראלד דארל") == 1     # deduped, richer kept
    assert "גן האלים" not in texts                       # poorer duplicate gone
    assert "קרובתי רוזי" in texts
    assert len(blocks) == 2, texts
    assert len(rdr.errors) == 1 and "boom" in rdr.errors[0]
    for b in blocks:            # boxes must land inside the ORIGINAL image
        assert 0 <= b.x0 < b.x1 <= 200 and 0 <= b.y0 < b.y1 <= 120, vars(b)


def test_llmpage_end_to_end_pipeline():
    """mode='llmpage': reader blocks -> matcher -> records, fully offline."""
    import os
    import tempfile
    from booksnap.config import LlmReaderConfig
    from booksnap.llmreader import ClaudePageReader
    from booksnap.pipeline import Pipeline

    def fake_send(jpeg: bytes) -> str:
        return json.dumps({"books": [
            {"title": "מלכי הכופרים", "author": "פול קארני"}]})

    cat = LocalCatalog([CatalogEntry("0", "מלכי הכופרים", "פול קארני"),
                        CatalogEntry("1", "ספינות מן המערב", "פול קארני")])
    cfg = LlmReaderConfig(grid_rows=1, grid_cols=1, rotate="none")
    pipe = Pipeline(catalog=cat,
                    page_reader=ClaudePageReader(send=fake_send, cfg=cfg),
                    crops_dir=tempfile.mkdtemp())
    p = _tmp_jpeg()
    try:
        recs = pipe.run([p], mode="llmpage")
    finally:
        os.unlink(p)
    assert len(recs) == 1
    r = recs[0]
    assert r.ocr.engine == "claude_page"
    assert r.match is not None and r.match.title == "מלכי הכופרים"
    assert r.match.tier == "AUTO"          # clean read of a catalog title
    assert not r.needs_fallback


# --- Simania catalog adapter ------------------------------------------------
FAKE_SIMANIA = {
    "suggestions": [
        {"type": "book", "id": 1, "title": "חברברי הסוונה [מהדורה חדשה]",
         "author": "ג'ראלד דארל", "series": None},
        {"type": "book", "id": 2, "title": "האימפריה השנייה (השניה)",
         "author": "פול קארני", "series": "ממלכות האל", "seriesNumber": 4},
        {"type": "author", "id": 9, "title": "ג'ראלד דארל"},   # not a book
    ]
}


def test_simania_parses_cleans_and_queries_raw():
    from booksnap.simania_catalog import SimaniaCatalog
    urls = []

    def transport(url):
        urls.append(url)
        return json.dumps(FAKE_SIMANIA)

    cat = SimaniaCatalog(transport=transport, delay_s=0)
    ents = cat.candidates("לחתן את אמא ג'ראלד דארל")
    titles = {e.title for e in ents}
    # edition annotations stripped; non-book suggestions dropped
    assert "חברברי הסוונה" in titles, titles
    assert "האימפריה השנייה" in titles, titles
    assert all(not e.title.startswith("ג'ראלד") for e in ents)
    # RAW final letters must survive into the query URL (the NLI lesson:
    # folding ן->נ silently misses every title ending in a final letter)
    import urllib.parse
    q = urllib.parse.unquote(urls[0])
    assert "לחתן" in q and "לחתנ" not in q, q
    # multi-window strategy for long queries: full + leading + trailing
    assert len(urls) >= 3


def test_fallback_catalog_thin_union_is_optional():
    """min_results>1 enables thin-union (kept for experiments; measured worse
    as a default): the secondary joins a thin primary harvest, deduped."""
    from booksnap.simania_catalog import FallbackCatalog
    thin = LocalCatalog([CatalogEntry("f", "מלכוד 22 סרט של מייק ניקולס", "")])
    rich = LocalCatalog([CatalogEntry(str(i), f"ספר {i}", "") for i in range(4)])
    nli = LocalCatalog([CatalogEntry("n", "מילכוד 22", "הלר, ג'וזף")])

    got = FallbackCatalog(thin, nli, min_results=3).candidates("מלכוד 22")
    assert {e.id for e in got} == {"f", "n"}       # union on thin harvest
    got = FallbackCatalog(rich, nli, min_results=3).candidates("מלכוד 22")
    assert {e.id for e in got} == {"0", "1", "2", "3"}   # rich -> primary only


def test_simania_transport_failure_is_safe():
    from booksnap.simania_catalog import SimaniaCatalog

    def boom(url):
        raise ConnectionError("down")
    assert SimaniaCatalog(transport=boom, delay_s=0).candidates("גן האלים") == []


def test_fallback_catalog_default_is_on_empty():
    """Default semantics: the secondary joins only when the primary found
    NOTHING — thin-union (min_results=3) and rescue queries both measured
    worse (see simania_catalog.FallbackCatalog docstring)."""
    from booksnap.simania_catalog import FallbackCatalog
    hits = LocalCatalog([CatalogEntry("p", "ספר ראשי", "מחבר")])
    second = LocalCatalog([CatalogEntry("s", "ספר משני", "מחבר")])

    class Empty:
        def candidates(self, q, limit=15):
            return []

    assert [e.id for e in FallbackCatalog(hits, second).candidates("x")] == ["p"]
    assert [e.id for e in FallbackCatalog(Empty(), second).candidates("x")] == ["s"]


def test_truncated_llm_read_is_never_auto():
    """A read the model marked as cut off ('...') caps at REVIEW."""
    import os
    import tempfile
    from booksnap.config import LlmReaderConfig
    from booksnap.llmreader import ClaudePageReader
    from booksnap.pipeline import Pipeline

    def fake_send(jpeg: bytes) -> str:
        return json.dumps({"books": [
            {"title": "מלכי הכופרים...", "author": "פול קארני"}]})

    cat = LocalCatalog([CatalogEntry("0", "מלכי הכופרים", "פול קארני")])
    cfg = LlmReaderConfig(grid_rows=1, grid_cols=1, rotate="none")
    pipe = Pipeline(catalog=cat,
                    page_reader=ClaudePageReader(send=fake_send, cfg=cfg),
                    crops_dir=tempfile.mkdtemp())
    p = _tmp_jpeg()
    try:
        recs = pipe.run([p], mode="llmpage")
    finally:
        os.unlink(p)
    assert recs[0].match is not None and recs[0].match.title == "מלכי הכופרים"
    assert recs[0].match.tier == "REVIEW", recs[0].match.tier


# --- last-resort shop catalogs ----------------------------------------------
REBOOKS_HTML = '''
<h3 class="wd-entities-title title post-title">
  <a href="https://rebooks.org.il/product/x" rel="bookmark">הקרע &#8211; וולטר ג'ון ויליאמס</a>
</h3>
<h3 class="wd-entities-title title post-title"><a href="y">ספר אחר לגמרי</a></h3>'''

BOOKSEFER_HTML = '''
<div class="box-product__title text-center"> קמט בזמן מדלין לאנגל ספרי מדע בדיוני חסר </div>
<div class="box-product__title text-center"> עוד ספר כלשהו אזל </div>'''


def test_rebooks_and_booksefer_parse_and_clean():
    from booksnap.extra_catalogs import BooksferCatalog, RebooksCatalog
    rb = RebooksCatalog(transport=lambda url: REBOOKS_HTML, delay_s=0)
    titles = [e.title for e in rb.candidates("הקרע")]
    assert "הקרע – וולטר ג'ון ויליאמס" in titles, titles

    bs = BooksferCatalog(transport=lambda url: BOOKSEFER_HTML, delay_s=0)
    titles = [e.title for e in bs.candidates("קמט בזמן")]
    # category marker + stock word stripped; author kept (it is spine text)
    assert "קמט בזמן מדלין לאנגל" in titles, titles
    assert "עוד ספר כלשהו" in titles, titles


def test_chain_catalog_unions_until_min_results():
    from booksnap.extra_catalogs import ChainCatalog
    calls = []

    class Src:
        def __init__(self, name, out):
            self.name, self.out = name, out
        def candidates(self, q, limit=15):
            calls.append(self.name)
            return self.out

    rich = [CatalogEntry(str(i), f"ספר מספר {i}", "") for i in range(3)]
    one = [CatalogEntry("x1", "הספר הנכון", "")]
    # a rich first source stops the cascade
    assert ChainCatalog([Src("a", rich), Src("b", one)]).candidates("x") == rich
    assert calls == ["a"]
    calls.clear()
    # a THIN first source no longer blocks the one that has the right book
    # (שלושה ימים בספטמבר case: wrong-but-nonempty used to stop the chain)
    got = ChainCatalog([Src("a", one),
                        Src("b", [CatalogEntry("x2", "ספר נוסף", "")])]).candidates("x")
    assert {e.id for e in got} == {"x1", "x2"} and calls == ["a", "b"]
    # min_results=1 restores the pure on-empty cascade
    calls.clear()
    assert ChainCatalog([Src("a", one), Src("b", rich)],
                        min_results=1).candidates("x") == one
    assert calls == ["a"]


def test_extra_catalog_transport_failure_is_safe():
    from booksnap.extra_catalogs import RebooksCatalog

    def boom(url):
        raise ConnectionError("down")
    assert RebooksCatalog(transport=boom, delay_s=0).candidates("ספר") == []




# --- confirmed library / review flow -----------------------------------------
def test_library_roundtrip_and_confirmed_catalog(tmp_dir=None):
    import tempfile
    import booksnap.library as lib
    d = Path(tempfile.mkdtemp())
    lib._lib_path = lambda: d / "library.json"
    lib._dec_path = lambda: d / "decisions.json"

    # AUTO claims absorbed on run completion, rejected ones never re-enter
    lib.record_decision("r0", "s9", {"action": "reject_ignore",
                                     "rejected_title": "ספר שגוי",
                                     "rejected_author": "מישהו"})
    n = lib.absorb_auto_claims("r1", [
        {"spine_id": "s1", "match": {"tier": "AUTO", "title": "גן האלים",
                                     "author": "ג'ראלד דארל"}},
        {"spine_id": "s2", "match": {"tier": "REVIEW", "title": "ספר אחר",
                                     "author": ""}},
        {"spine_id": "s3", "match": {"tier": "AUTO", "title": "ספר שגוי",
                                     "author": "מישהו"}},
    ])
    assert n == 1                                  # REVIEW waits; rejected blocked
    books = lib.load_library()["books"]
    assert len(books) == 1 and list(books.values())[0]["status"] == "auto"

    # human approval upgrades; rejection removes
    lib.add_book("גן האלים", "ג'ראלד דארל", "approved", {})
    assert list(lib.load_library()["books"].values())[0]["status"] == "approved"
    assert lib.remove_book("גן האלים", "ג'ראלד דארל")
    assert lib.load_library()["books"] == {}

    # ConfirmedCatalog: overlap-filtered; LibraryFirst UNIONS, never gates
    lib.add_book("קמט בזמן", "מדלין ל'אנגל", "approved", {})
    cc = lib.ConfirmedCatalog()
    assert [e.title for e in cc.candidates("קמט בזמן מדלין")] == ["קמט בזמן"]
    assert cc.candidates("ספר לא קשור בכלל") == []
    chain = LocalCatalog([CatalogEntry("c1", "רוח בדלת", "מדלן ל'אנגל")])
    both = lib.LibraryFirstCatalog(cc, chain).candidates("קמט בזמן")
    assert {e.title for e in both} == {"קמט בזמן", "רוח בדלת"}




def test_nli_creator_strips_roles_and_dates():
    """"לו, מרי, 1984- מחבר" leaked into the UI; roles and life dates are
    cataloguer metadata, not spine text."""
    from booksnap.nli_catalog import _clean_creator
    assert _clean_creator("לו, מרי, 1984- מחבר") == "לו, מרי"
    assert _clean_creator("שנקולבסקי, רפאל, 1928-1986 מחבר מאייר") == "שנקולבסקי, רפאל"
    assert _clean_creator("דארל, ג'ראלד, 1925-1995$$Qדארל, ג'ראלד") == "דארל, ג'ראלד"
    assert _clean_creator("קארני, פול") == "קארני, פול"




def test_union_catalog_merges_all_sources():
    """Simania junk must not block NLI's exact hit (על דם ואור class)."""
    from booksnap.extra_catalogs import UnionCatalog
    junk = LocalCatalog([CatalogEntry(str(i), f"ספר לא קשור {i}", "")
                         for i in range(4)])
    nli = LocalCatalog([CatalogEntry("n", "על דם ואור", "קמילה מונק")])
    got = UnionCatalog([junk, nli]).candidates("על דם ואור קמילה מונק")
    assert any(e.title == "על דם ואור" for e in got), [e.title for e in got]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")


def test_the_composition_root_writes_no_tenancy_at_all():
    """P4.1b deleted the bootstrap; building the app must not write ONE
    tenancy row. Asserted behaviourally — `build()` runs against a temp
    database seeded with somebody else's account, and every table is
    byte-identical after — because the first version grepped `app/main.py`
    for verb strings and a one-line `getattr` spelling walked straight
    past it (P4.1b's quality review, demonstrated)."""
    import os
    import sqlite3
    import tempfile

    from app.adapters.sqlite_store import SqliteTenancyStore
    from app.domain import Account, Library, Membership, Role, User

    def rows(db):
        conn = sqlite3.connect(str(db))
        try:
            return {
                table: conn.execute(
                    f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("users", "accounts", "memberships", "libraries")
            }
        finally:
            conn.close()

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "boot.db"
        tenancy = SqliteTenancyStore(db)
        tenancy.save_user(User(id="alice"))
        tenancy.save_account(Account(id="acc-family", label="Family"))
        tenancy.save_membership(Membership("alice", "acc-family", Role.ADMIN))
        tenancy.save_library(Library(id="lib-home", account_id="acc-family",
                                     label="הבית"))
        before = rows(db)

        saved = {k: os.environ.get(k) for k in ("BOOKSNAP_DB",
                                                "BOOKSNAP_BLOBS")}
        os.environ["BOOKSNAP_DB"] = str(db)
        os.environ["BOOKSNAP_BLOBS"] = str(Path(tmp) / "blobs")
        try:
            import app.main

            app.main.build()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        assert rows(db) == before, (
            "building the app wrote tenancy rows — the composition root "
            "is minting or joining accounts again (P4.1b deleted that)"
        )


_REPO = Path(__file__).resolve().parent.parent


def nl_join(lines) -> str:
    return "\n".join(lines)


# --- the deployment's load-bearing choices (P4.4) --------------------------
#
# Nothing in the gate runs docker, so these assert the PROPERTIES the
# deployment turns on — each one is a decision that would otherwise drift
# silently, and each has a stated reason in DEPLOY.md.

def test_the_deployment_refuses_to_start_the_staff_service_without_a_token():
    """The staff service fails OPEN without its token (the owner's local
    posture, 2026-08-13) — which must never reach the internet. Compose's
    `:?` guard is what makes the deployment refuse rather than inherit
    it."""
    compose = (_REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert "BOOKSNAP_STAFF_TOKEN: ${BOOKSNAP_STAFF_TOKEN:?" in compose, (
        "the staff service can be deployed without a token"
    )
    assert "BOOKSNAP_PUBLIC_URL: ${BOOKSNAP_PUBLIC_URL:?" in compose, (
        "the sign-in link would point at localhost, which on the "
        "recipient's phone is the recipient's phone"
    )
    assert "BOOKSNAP_SMTP_HOST: ${BOOKSNAP_SMTP_HOST:?" in compose, (
        "with no SMTP host the dev mailer prints sign-in links to the "
        "container log — a live credential for anyone who can read it"
    )


def test_only_the_tls_proxy_publishes_a_port():
    """One public door. The api and staff services `expose` (container
    network) but must never `ports:` (host) — a published :8757 is the
    unauthenticated-LAN posture P4.1b just closed, re-opened on the
    internet, and a published :8758 is every tenant behind one token."""
    import re

    raw = (_REPO / "docker-compose.yml").read_text(encoding="utf-8")
    # Comments stripped first: this file EXPLAINS why the api service has
    # no `ports:`, and a checker fooled by its own documentation is a
    # checker nobody keeps.
    compose = nl_join(line for line in raw.splitlines()
                      if not line.lstrip().startswith("#"))
    blocks = re.split(r"^  (\w[\w-]*):$", compose, flags=re.M)[1:]
    services = dict(zip(blocks[::2], blocks[1::2]))
    def published_ports(body: str) -> list[str]:
        """The `ports:` list only — `expose:` is the container network and
        publishes nothing on the host."""
        out: list[str] = []
        collecting = False
        for line in body.splitlines():
            if re.match(r"^\s+ports:\s*$", line):
                collecting = True
                continue
            if collecting:
                if re.match(r"^\s+-\s", line):
                    out.append(line.strip())
                elif line.strip():
                    collecting = False
        return out

    for name in ("api", "staff", "backup"):
        for entry in published_ports(services[name]):
            assert entry.startswith('- "127.0.0.1:'), (
                f"the {name} service publishes {entry} on a PUBLIC "
                f"interface — only the TLS proxy may. Loopback is allowed: "
                f"it is what lets `ssh -L` reach the staff service while "
                f"the internet cannot."
            )
    assert "ports:" in services["caddy"]


def test_the_image_keeps_the_free_reading_path_installed():
    """Tesseract and the Hebrew models ship in the image: the free
    deterministic path IS §10's graceful-degradation answer, and an image
    that can only run the paid engine stops working when a quota does."""
    dockerfile = (_REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "tesseract-ocr-heb" in dockerfile
    # One worker: the job runner's state lives on the app INSTANCE (§1.3).
    assert '"--workers", "1"' in dockerfile
    # ⚠ Never "*": uvicorn then takes the LEFTMOST X-Forwarded-For, i.e.
    # whatever the caller typed, and the per-source rate door becomes the
    # attacker's own field (measured: 120 links from one host, 0
    # refusals). Latent behind Caddy's default, live the moment anyone
    # adds `trusted_proxies` or a second balancer.
    assert '"--forwarded-allow-ips", "*"' not in dockerfile
    assert '"--forwarded-allow-ips"' in dockerfile


def test_the_deploy_runbook_names_the_drill_command_that_exists():
    """A runbook whose command has drifted is worse than none — this is
    the document someone follows at 3am."""
    runbook = (_REPO / "DEPLOY.md").read_text(encoding="utf-8")
    assert "tools/restore.py --drill" in runbook
    assert "--i-mean-it" in runbook
    assert (_REPO / "tools" / "restore.py").exists()
    assert (_REPO / "deploy" / "Caddyfile").exists()
    # The build context must not ship the owner's database or secrets.
    ignored = (_REPO / ".dockerignore").read_text(encoding="utf-8")
    for secret in (".env", "work/", "**/node_modules/"):
        assert secret in ignored, f"{secret} reaches the build daemon"
