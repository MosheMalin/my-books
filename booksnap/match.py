# -*- coding: utf-8 -*-
"""Stage 3 — matching.

Score OCR candidates against catalog entries with token-level evidence gates:
a match needs real content-token overlap, not mere string similarity, which
is what kept garbage OCR from resolving to spurious titles.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import fuzz

from .config import CONFIG, MatchConfig
from .catalog import Catalog, CatalogEntry, normalize
from .types import Match, OcrResult


def _tokens(s: str, cfg: MatchConfig) -> list[str]:
    # digit tokens survive the length floor: dropping them made numeric
    # titles ("14", "1984") structurally unmatchable (IMG_8131)
    return [t for t in normalize(s).split()
            if len(t) >= cfg.token_min_len or (t.isdigit() and len(t) >= 2)]


def _content(tokens: list[str], cfg: MatchConfig) -> list[str]:
    return [t for t in tokens if t not in cfg.stopwords]


def _is_junk_title(title_tokens: list[str], cfg: MatchConfig) -> bool:
    """True when a catalog title carries no identifying content of its own —
    only volume/part markers or publisher boilerplate."""
    if not title_tokens:
        return True
    junk = cfg.junk_title_words | cfg.publisher_words
    return all(t in junk for t in title_tokens)


@lru_cache(maxsize=20000)
def _ngrams(s: str, n: int = 3) -> frozenset[str]:
    """Character n-grams of a normalised string, word-boundary padded.

    Cached because a shelf re-compares the same catalog titles against many
    spines; on the measured data ~1.6k unique titles serve ~30 spines.
    """
    out: set[str] = set()
    for w in s.split():
        p = f" {w} "
        out.update(p[i:i + n] for i in range(max(1, len(p) - n + 1)))
    return frozenset(out)


def ngram_sim(a: str, b: str, n: int = 3) -> float:
    """Character n-gram cosine similarity, 0-100.

    Hebrew glues particles onto words (ה/ו/כ/ב/ל) and inflects freely, so two
    spellings of one title share most of their character shape while losing
    whole-token equality — which is what token-level fuzzing keys on.
    N-grams degrade gracefully there, cost nothing to compute, and need no
    model or download. This is the cheap test of the hypothesis that a
    *semantic* Hebrew model (DictaBERT) would buy accuracy: if character shape
    already captures it, embeddings have little left to add.
    """
    A, B = _ngrams(a, n), _ngrams(b, n)
    if not A or not B:
        return 0.0
    return 100.0 * len(A & B) / ((len(A) ** 0.5) * (len(B) ** 0.5))


_PREFIXES = ("ה", "ו", "כ", "ב", "ל", "מ", "ש")


def strip_prefix(tok: str) -> str:
    """Drop leading Hebrew particles, keeping at least a 3-char stem.

    Purely orthographic and deterministic — no model, no lookup. The stem
    guard stops short words being eaten down to nothing (מן -> מן, not ן).
    """
    while len(tok) > 3 and tok[0] in _PREFIXES:
        tok = tok[1:]
    return tok


def _token_hit(q: str, c: str, cfg: MatchConfig) -> bool:
    """Does query token `q` match catalog token `c`?

    The bar rises for short catalog tokens: at the flat 78 threshold, `היה`
    (OCR noise) scored 86 against `החיה` and manufactured a title.

    Particle-stripped forms are compared too, so הנבונים/נבונים and
    והנפלאים/כמופלאים count as agreement — edition spellings, not different
    words. The higher short-token bar still applies to the stems.
    """
    thr = cfg.short_token_ratio if len(c) <= cfg.short_token_len else cfg.token_ratio
    if fuzz.ratio(q, c) >= thr:
        return True
    # Words fused by OCR: whole-page Vision read "ג'ראלד דארלציפור הלעג",
    # gluing author to title, so the catalog token ציפור matched nothing even
    # though it is plainly present. If a long catalog token appears inside a
    # longer query token, that IS the word. Length floor keeps short/common
    # tokens from matching by accident inside unrelated strings.
    if (len(c) >= cfg.embedded_token_len and len(q) > len(c)
            and c in q):
        return True
    # ...and the mirror image, words CUT by the reader: the spine
    # יומנו של סטארטאפיסט was read "יומנו של סטארט", and the truncated
    # סטארט matched nothing in the true title while fully matching a wrong
    # book titled סטארט. A long query token found at the start of a longer
    # catalog token is that word, truncated. Same length floor.
    if (len(q) >= cfg.embedded_token_len and len(c) > len(q)
            and c.startswith(q)):
        return True
    if not cfg.strip_prefixes:
        return False
    qs, cs = strip_prefix(q), strip_prefix(c)
    if qs == q and cs == c:
        return False                      # nothing was stripped; no second bite
    thr = cfg.short_token_ratio if len(cs) <= cfg.short_token_len else cfg.token_ratio
    return fuzz.ratio(qs, cs) >= thr


@dataclass(slots=True)
class _Signals:
    """Everything one (read, entry) pair measures, computed once.

    The gates need far more than the public `info` dict carries — the token
    lists, the coverage ratios and the normalized read all feed rejection
    rules — so they travel together instead of as a dozen parameters.
    """
    entry: CatalogEntry
    info: dict
    query_tokens: list[str]
    tt: list[str]           # catalog title tokens above the length floor
    at: list[str]           # catalog author tokens above the length floor
    tt_content: list[str]   # tt minus stopwords
    mt: list[str]           # title tokens this read matched
    ma: list[str]           # author tokens this read matched
    own_hits: list[str]     # title hits that aren't the author's own name
    q: str                  # the whole normalized read
    q_content: list[str]    # deduped, stopword-free read tokens
    tcov: float
    tcov_c: float
    acov: float
    qcov: float
    title_sim: float
    n_title_hits: int
    has_distinct_title: bool


def _signals(query_tokens: list[str], entry: CatalogEntry,
             cfg: MatchConfig, query_text: str = "") -> _Signals:
    """Measure one catalog entry against one read — no judgement, no gates.

    `query_text` (the raw OCR string) feeds the WHOLE-TITLE similarities.
    Token filtering drops short words (כן, אב) from `query_tokens`, but
    `norm_title` keeps them — comparing filtered query to unfiltered title
    penalised exactly the right entry: on IMG_8125 the read
    "כן, אדוני ראש הממש" scored higher against "אדוני ראש הממשלה" (a
    different book) than against "כן, אדוני ראש הממשלה", purely because the
    query side had lost its כן. Comparing full text to full text is
    symmetric, so short words count on both sides or neither.
    """
    tt = [t for t in entry.norm_title.split()
          if len(t) >= cfg.token_min_len or (t.isdigit() and len(t) >= 2)]
    at = [t for t in entry.norm_author.split() if len(t) >= cfg.token_min_len]

    # The read side of word-fusion: a spine printed סנוקראש was read as the
    # two words "סנו קראש", so no single query token could hit the catalog
    # token. A long catalog token found verbatim in the SPACELESS read is
    # present — the mirror of the embedded-token rule, which handles fusion
    # on the catalog side.
    qcat = "".join(query_tokens)
    fused = {c for c in tt + at
             if len(c) >= cfg.embedded_token_len and c in qcat}

    def matched(catalog_tokens):
        return [c for c in catalog_tokens
                if c in fused
                or any(_token_hit(x, c, cfg) for x in query_tokens)]

    mt, ma = matched(tt), matched(at)
    # An author token that also appears in the TITLE is double-counting, not
    # corroboration: the NLI record 'ארץ לא נודעת' by 'מטה ארץ ישראל. כנס
    # מסבירים' outscored the true Connie Willis book on run 18 purely
    # because its junk author repeats the title word ארץ.
    ma = [a for a in ma if a not in tt]
    tt_content, mt_content = _content(tt, cfg), _content(mt, cfg)
    tcov = len(mt) / len(tt) if tt else 0.0
    acov = len(ma) / len(at) if at else 0.0
    tcov_c = (len(mt_content) / len(tt_content)) if tt_content else 0.0
    n_title_hits = len(mt_content)
    # A matched title token that is just the entry's AUTHOR printed inside the
    # title is an echo, not independent title evidence: the author-only read
    # "משירי דן אלמגור" matched אלמגור in the title "דן אלמגור: איש חסיד היה"
    # and invented that book (run 16). Echo hits still count for
    # coverage/score, but cannot by themselves establish existence.
    echo = [c for c in mt_content
            if any(c == a or fuzz.ratio(c, a) >= 90 for a in at)]
    own_hits = [c for c in mt_content if c not in echo]
    has_distinct_title = any(len(t) >= cfg.distinctive_len for t in own_hits)

    q = normalize(query_text) if query_text else " ".join(query_tokens)
    # whole-title similarity — separates series siblings (מלכי הכופרים vs
    # ספינות מן המערב) and, as a gate, rejects titles unlike the OCR text.
    title_sim = fuzz.token_set_ratio(q, entry.norm_title)
    if cfg.strip_prefixes:
        title_sim = max(title_sim, fuzz.token_set_ratio(
            " ".join(strip_prefix(t) for t in query_tokens),
            " ".join(strip_prefix(t) for t in entry.norm_title.split())))

    # How much of what the OCR actually read does this entry account for? A
    # short title can score perfect coverage while explaining almost none of
    # the spine; this is the signal that catches that.
    q_content = _content(list(dict.fromkeys(query_tokens)), cfg)
    # "explained" is deliberately SOFTER than a scoring hit: a read token a
    # letter away from a catalog token (לכת ~ מלכת at 86, under the 90
    # short-token bar) is still explained BY this entry — run 18's fragment
    # read "לכת השלג" was thrown away as a lone-title subset because its
    # near-miss token counted as unexplained. Soft hits never add evidence
    # or score; they only stop the rejection rules from misreading coverage.
    explained = sum(1 for x in q_content
                    if any(_token_hit(x, c, cfg) for c in tt + at)
                    or any(x in c for c in fused)
                    or any(fuzz.ratio(x, c) >= cfg.soft_author_ratio
                           for c in tt + at))
    qcov = explained / len(q_content) if q_content else 0.0

    info = {
        "id": entry.id, "title": entry.title, "author": entry.author,
        "title_hits": mt_content, "author_hits": ma,
        "tcov": tcov, "tcov_c": tcov_c, "acov": acov, "qcov": qcov,
        "n_title_hits": n_title_hits, "has_distinct_title": has_distinct_title,
        "n_title_content": len(tt_content),
        "n_query_content": len(q_content),
        # spine reads usually carry the author too, which dilutes an n-gram
        # cosine taken against the title alone — "נהר השמים / גרגורי בנפורד"
        # scored 49.96 vs "נהר השמים הגדול" and died on the gate by 0.04.
        # When the entry has an author, the read is also compared against
        # title+author; the higher of the two is the honest similarity.
        "title_sim": title_sim,
        "ngram_sim": max(ngram_sim(q, entry.norm_title),
                         ngram_sim(q, f"{entry.norm_title} {entry.norm_author}".strip())
                         if entry.norm_author else 0.0),
        "score": 0.0, "rejected": None,
    }
    return _Signals(
        entry=entry, info=info, query_tokens=query_tokens,
        tt=tt, at=at, tt_content=tt_content, mt=mt, ma=ma,
        own_hits=own_hits, q=q, q_content=q_content,
        tcov=tcov, tcov_c=tcov_c, acov=acov, qcov=qcov, title_sim=title_sim,
        n_title_hits=n_title_hits, has_distinct_title=has_distinct_title,
    )


def _evaluate(query_tokens: list[str], entry: CatalogEntry,
              cfg: MatchConfig, query_text: str = "") -> dict:
    """Score one catalog entry, always returning the reasoning.

    `rejected` names the gate that refused the entry (None if it passed), so
    the same code can both match and explain why a book did or didn't win.
    """
    s = _signals(query_tokens, entry, cfg, query_text)
    reason = _rejection(s, cfg)
    if reason:
        s.info["rejected"] = reason
        return s.info
    s.info["score"] = (60 * s.tcov_c + 25 * s.tcov + 15 * s.acov
                       + 0.30 * s.title_sim)
    return s.info


def _rejection(s: _Signals, cfg: MatchConfig) -> str | None:
    """Apply the evidence gates in order; name the first one that refuses.

    Every block below is a regression fence with a run number attached, not a
    general principle — re-measure with tools/sweep.py before loosening one.
    """
    entry, info, query_tokens = s.entry, s.info, s.query_tokens
    tt, at, tt_content = s.tt, s.at, s.tt_content
    mt, ma, own_hits = s.mt, s.ma, s.own_hits
    q, q_content = s.q, s.q_content
    tcov, acov, qcov, title_sim = s.tcov, s.acov, s.qcov, s.title_sim
    n_title_hits, has_distinct_title = s.n_title_hits, s.has_distinct_title

    # ULTRA-SHORT titles (ג'ם normalizes to גם, 2 chars) have no token above
    # the length floor at all: tt is empty, so such a book is structurally
    # unmatchable — junk-gated — no matter how well it was read (run 17,
    # ג'ם by פרדריק פול, present in three catalogs). When the whole
    # normalized title appears verbatim as a word of the read AND a
    # non-echoing author corroborates at >=50%, that IS the book.
    _tiny_ma = [a for a in ma if a != entry.norm_title]
    tiny_title = bool(
        not tt and entry.norm_title and at
        and len(_tiny_ma) / len(at) >= 0.5
        and re.search(rf"(?:^| ){re.escape(entry.norm_title)}(?: |$)", q))

    # A catalog title made only of volume/part words is not identifying: a
    # spine printed "ספר שלישי" would otherwise resolve to a book literally
    # titled "השלישי". Same for imprint boilerplate ("ספרית פועלים").
    if _is_junk_title(tt_content or tt, cfg) and not tiny_title:
        return "catalog title is only volume/publisher boilerplate"

    # EXISTENCE GATE — title evidence only. Author agreement may raise the
    # tier but must never be what makes a match exist: pooling title and
    # author evidence let one noise token plus a series author invent a title.
    # One narrow exception (IMG_8129): a SHORT one-word title (עדן, הצלם) can
    # never produce 2 hits or a 5-char token, making such books structurally
    # unmatchable. When the ENTIRE title is matched and the author strongly
    # corroborates, that is real evidence — this is not author-alone (the
    # full title must still match), so the original bug can't return.
    # Author hits that are themselves title echoes cannot corroborate: the
    # entry "סוזנה" by "סוזנה, דוד" is a SELF-ECHO — the single read token
    # סוזנה (actually Susanna Clarke's first name) scored tcov=1.0 AND
    # acov=0.5 at once and invented the book on run 17. Corroboration must
    # come from a read token that is not the same word as the title hit.
    ma_own = [a for a in ma
              if not any(a == c or fuzz.ratio(a, c) >= 90 for c in mt)]
    acov_own = len(ma_own) / len(at) if at else 0.0
    full_title_with_author = (tt and tcov == 1.0 and n_title_hits >= 1
                              and acov_own >= 0.5)
    # ...and a read that IS the title, verbatim: "צל אפל" read cleanly still
    # had zero usable tokens (צל under the length floor, אפל short of
    # distinctive), making the book unmatchable however well it was read.
    # Whole-string equality of the full normalized read is strong evidence.
    verbatim_title = bool(entry.norm_title) and q == entry.norm_title
    # ...or one OCR letter away from it: the fragment read "לכת השלג" (run
    # 18) is plainly the title מלכת השלג, but its only hit השלג sits under
    # the distinctive bar and no author was read. Whole-string fuzz.ratio is
    # length-sensitive — unlike token_set_ratio, a SUBSET title scores low
    # (השחור vs השחורים is 86) — so a 92 floor admits one-letter reads
    # without reopening the subset pathology.
    near_verbatim = (bool(entry.norm_title)
                     and fuzz.ratio(q, entry.norm_title) >= 92)
    # A FULLY-matched multi-token author plus at least half the title is real
    # evidence even when every matched title token is short or fuzzy: the
    # read "שרך, אלי לאה סאקס" (misread שלך) carries the author לאה סאקס in
    # full and half of the title שלך, אלי — but אלי is under the distinctive
    # bar and שלך was misread, so title evidence alone can never see it.
    # Unlike the original pooled-evidence bug, one noise token cannot fire
    # this: it takes BOTH a 2+-token author at 100% AND half the title.
    author_backed = (len(ma) >= 2 and acov >= 1.0 and tt and tcov >= 0.5
                     and len(own_hits) >= 1)
    if not (len(own_hits) >= 2 or has_distinct_title or full_title_with_author
            or verbatim_title or near_verbatim or author_backed or tiny_title):
        return ("no title evidence beyond the author's own name "
                "(needs 2 title tokens, or 1 of "
                f"{cfg.distinctive_len}+ chars)")
    # A ONE-word read is inherently ambiguous between every title containing
    # that word, so its single hit must be EXACT: the barely-visible spine of
    # הענן השחור was read as just "השחור" and went AUTO on ז'נה's השחורים
    # via the truncated-prefix rule (run 18). An exact one-word hit still
    # matches (המחזורית, שוגון) and the tier guards keep it honest.
    if (len(q_content) <= 1 and not verbatim_title
            and not any(x == c for x in query_tokens for c in own_hits)):
        return ("a one-word read needs an exact title-word hit "
                "(fuzzy/truncated is ambiguous across titles)")
    if title_sim < cfg.min_title_sim:
        return f"title similarity {title_sim} < {cfg.min_title_sim}"
    if cfg.min_ngram_sim > 0 and info["ngram_sim"] < cfg.min_ngram_sim:
        return (f"n-gram similarity {info['ngram_sim']:.0f} < "
                f"{cfg.min_ngram_sim:.0f}")
    # A claim hanging on a SINGLE matched title word, explaining at most half
    # of what was read, with no author signal at all, is the subset pathology
    # outright: the entry "covers itself" and ignores the rest of the spine.
    # Run 16 wrongs of exactly this shape: הקומקום claiming הציפציק של
    # הקומקום, שפירא claiming אדבר איתן רחל שפירא, המבוך claiming קאדרו
    # המבוך זוחל, סטארט claiming יומנו של סטארט גידי רף — and, once the lone
    # entry is rejected, a two-word sibling stepping into the hole (הזריחה
    # הזהובה for טקסי הזריחה, ספר יהודית for השדים יהודית קגן), which is why
    # the rule keys on matched-hit count, not the entry's word count.
    # The demotion in _tier is not enough — the wrong claim displaces the
    # true book and surfaces as a wrong REVIEW.
    # Author support is judged at a RELAXED ratio without the short-token
    # escalation: the read "וורקרוס מארי לו" scores מארי~מרי at 86, under the
    # 90 short-token bar, yet that is plainly the right author — while the
    # wrong claims here have zero author signal at any bar. (80, not lower:
    # רינה~אריה already scores 75.)
    # A fully-explained read (verbatim one-word title, qcov 1.0) still passes.
    if cfg.reject_lone_title_partial and qcov <= 0.5 and len(own_hits) <= 1:
        soft_author = bool(ma) or any(
            fuzz.ratio(x, a) >= cfg.soft_author_ratio
            for x in query_tokens for a in at)
        if not soft_author:
            return ("a single matched title word explains at "
                    "most half the read, with no author signal")

    return None


def _score_entry(query_tokens: list[str], entry: CatalogEntry,
                 cfg: MatchConfig, query_text: str = ""):
    info = _evaluate(query_tokens, entry, cfg, query_text)
    if info["rejected"]:
        return None
    return (info["score"], info["tcov"], info["tcov_c"], info["acov"],
            len(info["title_hits"]) + len(info["author_hits"]),
            info["n_title_hits"], info["has_distinct_title"], info["qcov"],
            info["n_title_content"], info["n_query_content"])


def explain(text: str, catalog: Catalog, cfg: MatchConfig = CONFIG.match,
            limit: int = 6) -> dict:
    """Rank every catalog candidate for one OCR string, keeping the rejected
    ones and the reason. Powers the UI's "why did this spine match?" view."""
    qt = _tokens(text, cfg)
    cands = [_evaluate(qt, e, cfg, text) for e in catalog.candidates(text)]
    # passing entries first (best score), then near-misses by title evidence
    passed = sorted([c for c in cands if not c["rejected"]],
                    key=lambda c: -c["score"])
    failed = sorted([c for c in cands if c["rejected"] and c["title_hits"]],
                    key=lambda c: (-c["n_title_hits"], -c["title_sim"]))
    return {"query_tokens": qt,
            "candidates": (passed + failed)[:limit],
            "n_passed": len(passed)}


def _tier(tcov, tcov_c, acov, evidence, n_title_hits, has_distinct_title,
          cfg: MatchConfig, qcov: float = 1.0,
          n_title_content: int = 99, n_query_content: int = 99) -> str:
    # AUTO requires the title to be substantially matched — author agreement
    # alone (common across a series) is never enough.
    strong_title = tcov_c >= cfg.auto_title_content_cov and (
        n_title_hits >= 2 or has_distinct_title)
    # ...and the candidate must account for a real share of what was read, or
    # a one-word title trivially "covers itself" and auto-accepts.
    if qcov < cfg.auto_min_query_cov:
        return "REVIEW"
    # A ONE-content-word title that leaves part of the read unexplained is the
    # subset pathology in miniature: the entry "covers itself" perfectly while
    # ignoring the rest of the spine. Measured wrong-AUTOs of exactly this
    # shape: "סליחה" claiming the read "סליחה שטעינו", "ציפורים" claiming
    # "ציפורים וקרובים". When the read is fully explained (ארבינקא קישון ->
    # title+author) a one-word title can still be AUTO.
    if n_title_content <= 1 and qcov < 1.0:
        return "REVIEW"
    # ...and the mirror image: a ONE-word read trivially satisfies qcov=1.0
    # yet is far too little evidence to auto-accept a multi-word title.
    # Measured on IMG_8124: the fragment "המחזורית" went AUTO on an NLI DVD
    # record "די וי די המערכה המחזורית והמחזוריות". A one-word read may still
    # be AUTO on a one-word title (שוגון, קמצ'טקה).
    if n_query_content <= 1 and n_title_content >= 2:
        return "REVIEW"
    if tcov >= cfg.auto_title_cov and strong_title:
        return "AUTO"
    if strong_title and acov >= cfg.auto_author_cov:
        return "AUTO"
    return "REVIEW"


_ROMAN = frozenset({"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
                    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"})


def _volume_core(norm_title: str, cfg: MatchConfig) -> tuple[str, ...]:
    """Title tokens with volume designators (חלק/כרך/ספר, digits, romans)
    removed — two titles with the same core are volumes of one work."""
    return tuple(t for t in norm_title.split()
                 if not (t.isdigit() or t in _ROMAN or t in cfg.junk_title_words))


def match_candidate(text: str, catalog: Catalog,
                    cfg: MatchConfig = CONFIG.match) -> Match | None:
    qt = _tokens(text, cfg)
    if not qt:
        return None
    best, runners = None, []
    for entry in catalog.candidates(text):
        res = _score_entry(qt, entry, cfg, text)
        if res is None:
            continue
        runners.append((res[0], entry))
        if best is None or res[0] > best[0][0]:
            best = (res, entry)
    if best is None:
        return None
    (score, tcov, tcov_c, acov, ev, nth, hdt, qcov, ntc, nqc), entry = best
    tier = _tier(tcov, tcov_c, acov, ev, nth, hdt, cfg, qcov, ntc, nqc)
    # Volume ambiguity: when a rival candidate scores IDENTICALLY and differs
    # from the winner only in volume designators the read never showed, the
    # matcher literally cannot tell the volumes apart — a spine reading
    # "יומני רובורצח" went AUTO on כרך 1 while כרך 2 (the actual book) sat in
    # the same list with the same score. That coin-flip must not auto-accept.
    if tier == "AUTO":
        core = _volume_core(entry.norm_title, cfg)
        qt_set = set(qt)
        for s, rival in runners:
            if (rival.id != entry.id and abs(s - score) < 1e-6
                    and rival.norm_title != entry.norm_title
                    and _volume_core(rival.norm_title, cfg) == core):
                # only when the read shows NONE of the differing volume
                # tokens: a spine that actually printed "1000" or "III" has
                # picked its volume; a bare "יומני רובורצח" has not.
                diff = (set(entry.norm_title.split())
                        ^ set(rival.norm_title.split()))
                if not diff & qt_set:
                    tier = "REVIEW"
                    break
    return Match(title=entry.title, author=entry.author, tier=tier,
                 score=round(score, 1), matched_text=text,
                 catalog_id=entry.id, qcov=round(qcov, 3))


def retrieval_variants(text: str, cfg: MatchConfig = CONFIG.match) -> list[str]:
    """Alternative retrieval queries for a read that matched nothing.

    The sources' search engines are LITERAL: probed live (2026-08-06), a
    split word returns junk while the fused form is indexed (simania has
    סנוקראש; the read "סנו קראש" returns 0 results), and one misread token
    poisons the whole query (המוסד האחד found none of the 8 מוסד books that
    המוסד אסימוב returns). Variants: (a) space-collapsed, for short reads;
    (b) leave-one-out over content tokens. The ORIGINAL read remains the
    only evidence — variants are retrieval keys, never matching input.
    """
    qt = normalize(text).split()
    out: list[str] = []
    if 2 <= len(qt) <= 3:
        out.append("".join(qt))
    if 3 <= len(qt) <= 6:
        for i, t in enumerate(qt):
            if len(t) < 3:
                continue                  # dropping a particle changes nothing
            out.append(" ".join(qt[:i] + qt[i + 1:]))
    return out


def match_second_pass(text: str, catalog: Catalog,
                      cfg: MatchConfig = CONFIG.match) -> Match | None:
    """Re-retrieve an unmatched read through query VARIANTS and match the
    results against the original read. Only ever called for spines the first
    pass left unmatched, so the extra source queries stay proportional to
    what actually failed."""
    qt = _tokens(text, cfg)
    if not qt:
        return None
    best = None
    seen: set[str] = set()
    for v in retrieval_variants(text, cfg):
        for entry in catalog.candidates(v):
            if entry.id in seen:
                continue
            seen.add(entry.id)
            res = _score_entry(qt, entry, cfg, text)
            if res is None:
                continue
            if best is None or res[0] > best[0][0]:
                best = (res, entry)
    if best is None:
        return None
    (score, tcov, tcov_c, acov, ev, nth, hdt, qcov, ntc, nqc), entry = best
    return Match(title=entry.title, author=entry.author,
                 tier=_tier(tcov, tcov_c, acov, ev, nth, hdt, cfg, qcov,
                            ntc, nqc),
                 score=round(score, 1), matched_text=text,
                 catalog_id=entry.id, qcov=round(qcov, 3))


def match_spine(ocr: OcrResult, catalog: Catalog,
                cfg: MatchConfig = CONFIG.match) -> Match | None:
    """Match the best of all OCR candidates (full text + each line)."""
    candidates = [ocr.text, *ocr.lines]
    rank = {"AUTO": 2, "REVIEW": 1}
    best, best_key = None, (-1, -1.0)
    for cand in candidates:
        if not cand or len(normalize(cand)) < 4:
            continue
        m = match_candidate(cand, catalog, cfg)
        if m:
            key = (rank[m.tier], m.score)
            if key > best_key:
                best, best_key = m, key
    return best


def candidates_for_spine(ocr: OcrResult, catalog: Catalog,
                         cfg: MatchConfig = CONFIG.match) -> dict[str, dict]:
    """Every catalog entry this spine could plausibly be, best score per entry.

    Unlike `match_spine` (which collapses to one winner immediately) this keeps
    the full candidate set, which global assignment needs in order to let
    spines trade candidates with each other.
    """
    best: dict[str, dict] = {}
    for cand in [ocr.text, *ocr.lines]:
        if not cand or len(normalize(cand)) < 4:
            continue
        qt = _tokens(cand, cfg)
        if not qt:
            continue
        for entry in catalog.candidates(cand):
            info = _evaluate(qt, entry, cfg, cand)
            if info["rejected"]:
                continue
            info["entry"] = entry
            info["matched_text"] = cand
            prev = best.get(entry.id)
            if prev is None or info["score"] > prev["score"]:
                best[entry.id] = info
    return best


def resolve_assignment(per_spine: list[dict[str, dict]],
                       cfg: MatchConfig = CONFIG.match) -> list[Match | None]:
    """Assign spines to catalog entries as a SET-TO-SET problem.

    Each spine independently taking its best entry is what produced 15-24
    reported books for a 14-book shelf: an imprint line, a volume marker and a
    genuine spine could all claim their own title with nobody competing. Here
    the whole shelf is solved at once with the Hungarian algorithm
    (`scipy.optimize.linear_sum_assignment`), maximising total score subject to
    a one-to-one constraint, so:

      * two spines cannot both take the same book — the better one wins and the
        other is left unassigned rather than demoted to a wrong title;
      * a weak claimant only wins an entry no stronger spine wants;
      * anything scoring below `assign_min_score` is dropped, so "no book here"
        is a possible answer for a shelf label or a segmentation artifact.

    This is the standard formulation in the literature (see CLAUDE.md refs).
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    entry_ids = sorted({eid for c in per_spine for eid in c})
    out: list[Match | None] = [None] * len(per_spine)
    if not entry_ids:
        return out

    col = {eid: j for j, eid in enumerate(entry_ids)}
    scores = np.zeros((len(per_spine), len(entry_ids)), dtype=float)
    for i, cands in enumerate(per_spine):
        for eid, info in cands.items():
            scores[i, col[eid]] = info["score"]

    rows, cols = linear_sum_assignment(scores, maximize=True)
    for i, j in zip(rows, cols):
        s = scores[i, j]
        if s < cfg.assign_min_score:
            continue                      # better to report nothing
        info = per_spine[i][entry_ids[j]]
        entry = info["entry"]
        out[i] = Match(
            title=entry.title, author=entry.author,
            tier=_tier(info["tcov"], info["tcov_c"], info["acov"],
                       len(info["title_hits"]) + len(info["author_hits"]),
                       info["n_title_hits"], info["has_distinct_title"],
                       cfg, info["qcov"], info.get("n_title_content", 99),
                       info.get("n_query_content", 99)),
            score=round(s, 1), matched_text=info["matched_text"],
            catalog_id=entry.id, qcov=round(info["qcov"], 3))
    return out


def resolve_near_duplicates(matches: list[Match | None],
                            title_thresh: int = 85,
                            author_thresh: int = 60) -> list[Match | None]:
    """Drop weaker claims whose TITLE near-duplicates a stronger claim.

    `resolve_duplicates` only sees identical catalog ids; page modes need
    more, because overlapping tiles read the same spine twice and the partial
    read routinely matches a DIFFERENT catalog edition of the same book
    (measured on IMG_8125: הצחקתם אותנו claimed twice via two entries; on
    IMG_8123 the שוויק set claimed once per edition record). Two claims with
    near-identical titles and compatible authors are one physical book — the
    stronger claim already explains it, so the weaker is dropped, not shown.

    Author compatibility guards genuinely-distinct same-title books: authors
    must fuzzy-agree, or at least one be unknown.
    """
    rank = {"AUTO": 2, "REVIEW": 1}
    order = sorted((i for i, m in enumerate(matches) if m),
                   key=lambda i: (rank[matches[i].tier], matches[i].score),
                   reverse=True)
    kept: list[int] = []
    for i in order:
        m = matches[i]
        for j in kept:
            w = matches[j]
            t_same = fuzz.token_set_ratio(normalize(m.title),
                                          normalize(w.title)) >= title_thresh
            a_ok = (not m.author or not w.author
                    or fuzz.token_set_ratio(normalize(m.author),
                                            normalize(w.author)) >= author_thresh)
            if t_same and a_ok and not _distinct_volumes(m, w):
                matches[i] = None
                break
        else:
            kept.append(i)
    return matches


def suppress_fragment_reads(texts: list[str],
                            matches: list[Match | None]) -> list[Match | None]:
    """Unmatch reads that are a token-subset of another matched read.

    Overlapping tiles produce partial re-reads of the same spine; the
    fragment then matches whatever record best fits the fragment alone.
    Measured on IMG_8124: the fragment "המחזורית" (from the הטבלה המחזורית
    spine, fully read elsewhere) claimed an NLI DVD record. If every token of
    read A appears in a longer matched read B, A is a partial view of B's
    spine — B's claim already speaks for it.
    """
    def contained(a: set[str], b: set[str]) -> bool:
        # substring containment, not exact-token: the fragment "ראה אתמול"
        # (from the נתראה אתמול spine) must count as inside "נתראה אתמול...".
        # EVERY token must be found, including short ones — but short tokens
        # satisfy by substring, so the truncated "ה" of "מכונת הזמן ה..."
        # matches inside המקרית, while a real short word that distinguishes a
        # sibling (לימודי אש vs לימודי רעל) blocks the suppression. A read of
        # only sub-3-char tokens is never treated as contained.
        # Particle-stripped forms count too: the fragment "המשפחה שלי הרגו
        # מישהו" is a partial view of the "כולם במשפחה שלי הרגו מישהו" spine,
        # and only the ה/ב particle kept המשפחה from being found in במשפחה.
        if not any(len(t) >= 3 for t in a):
            return False
        return all(any(t in u or strip_prefix(t) in u for u in b) for t in a)

    rank = {"AUTO": 2, "REVIEW": 1}
    toks = [set(normalize(t).split()) for t in texts]

    def world(k: int) -> set[str]:
        # a claim's "world": its read plus its matched entry's title+author.
        # "הסכין ה פיליפ פולמן" is a torn re-read of the הסכין המעודן spine
        # but carries פיליפ, which only the ENTRY (not the fuller read) has.
        m = matches[k]
        return toks[k] | set(normalize(f"{m.title} {m.author}").split())

    for i, m in enumerate(matches):
        if not m or not toks[i]:
            continue
        for j, other in enumerate(matches):
            if i == j or other is None:
                continue
            # ASYMMETRIC containment, not length: the fragment fits entirely
            # inside the fuller claim's world while the fuller claim has
            # substance the fragment lacks (הזהוב). Token counts mislead —
            # a torn read plus a stray letter can be "longer" than the clean
            # read it duplicates. A read naming a DIFFERENT author (מכונת
            # הזמן ה.ג. ולס next to the Haldeman book) is not contained and
            # keeps its claim.
            # Suppression demands STRICT superiority, judged by (tier, qcov,
            # score) — NOT raw score. Scores of claims on different entries
            # are incomparable: a fragment matching a short wrong title gets
            # perfect coverage and an inflated score (run 16: the fragment
            # read "המפתיעה על בעלי החיים לוסי קוק" outscored 111.9 vs 92.3
            # the clean read of the true האמת המפתיעה על בעלי החיים). qcov —
            # how much of its OWN read each claim explains — is the honest
            # comparison: the wrong twin leaves half its read unexplained.
            # Score stays as the final tie-break, and the IMG_8133 protection
            # holds: a clean read (qcov 1.0) still cannot be eaten by a
            # compound read's series-record claim that explains less.
            if (contained(toks[i], world(j)) and not contained(toks[j], world(i))
                    and (rank[other.tier], other.qcov, other.score)
                    > (rank[m.tier], m.qcov, m.score)):
                matches[i] = None
                break
    return matches


def suppress_author_fragments(texts: list[str],
                              matches: list[Match | None]) -> list[Match | None]:
    """Unmatch records whose ENTIRE read is another matched book's author.

    Page reading emits the author line of a spine as its own block when the
    title is illegible; that name-only block then matches whatever catalog
    entry happens to be TITLED like the name (measured on IMG_8125: the block
    "ענת זייידמן" went AUTO on a book titled "זיידמן" while the real book —
    הומור, by ענת זיידמן — was matched from its own block). A read that is
    just an author's name is evidence FOR that author's book, never a book of
    its own.
    """
    def name_only(q_toks: list[str], a_toks: list[str]) -> bool:
        """True when the read carries NOTHING beyond the author's name.

        Every substantive read token must correspond to an author token
        (fuzzy or substring). The earlier heuristic (length guard +
        token_set_ratio) suppressed any SHORT title+author read whose author
        matched — measured on IMG_8131: "אקסלרנדו צ'רלס סטרוס" was eaten
        because two of its three tokens were the author of OTHER matched
        Stross books. אקסלרנדו corresponds to no author token, so under this
        rule the read keeps its claim.
        """
        core = [t for t in q_toks if len(t) >= 3]
        if not core:
            return False
        # substring correspondence needs a REAL author token on the other
        # side: initials ("מ.מ.טרופ" -> tokens מ,מ,טרופ) made the single
        # letter מ "contained in" nearly every Hebrew word, and this pass ate
        # correct matches (מחשבות על המציאות) as author fragments.
        return all(any(fuzz.ratio(t, a) >= 85
                       or (len(a) >= 3 and (t in a or a in t))
                       for a in a_toks) for t in core)

    def name_like(t: str, a_toks: list[str]) -> bool:
        # stricter than name_only's correspondence: a SHORT contributing
        # token that merely sits inside a longer author name is not that
        # name (אלי ⊂ אליצור almost erased שלך, אלי) — substring only
        # counts for tokens long enough to BE a name.
        return any(fuzz.ratio(t, a) >= 85
                   or (len(t) >= 5 and len(a) >= 3 and (t in a or a in t))
                   for a in a_toks)

    cfg = CONFIG.match
    for i, (text, m) in enumerate(zip(texts, matches)):
        if not m:
            continue
        q_toks = normalize(text).split()
        # which read tokens actually SUPPLIED title evidence for this claim?
        title_toks = [t for t in normalize(m.title).split()
                      if len(t) >= cfg.token_min_len]
        contributing = [t for t in q_toks if len(t) >= 3
                        and any(_token_hit(t, c, cfg) for c in title_toks)]
        for other in matches:
            if other is None or other is m or not other.author:
                continue
            a_toks = normalize(other.author).split()
            if name_only(q_toks, a_toks):
                matches[i] = None
                break
            # Evidence-level variant: even when the read carries extra junk,
            # a claim whose EVERY contributing title token is another matched
            # book's author name was built from a person, not a title — the
            # read "ההחזק פיטר ס. ביגל" (the החדקרן האחרון spine) went AUTO
            # on the Bruegel BIOGRAPHY 'פיטר ברויגל' because פיטר+ביגל, the
            # true book's AUTHOR, fully covered that title (run 18). A claim
            # with any title evidence of its own (אקסלרנדו) is untouched.
            if (contributing and other.catalog_id != m.catalog_id
                    and all(name_like(t, a_toks) for t in contributing)):
                matches[i] = None
                break
    return matches


def postprocess_matches(texts: list[str], matches: list[Match | None],
                        cfg: MatchConfig = CONFIG.match) -> list[Match | None]:
    """The whole-shelf cleanup that follows per-spine matching, in its one
    canonical order (run_page and the sweep must stay identical)."""
    matches = resolve_duplicates(matches, cfg)
    matches = resolve_near_duplicates(matches)
    matches = suppress_fragment_reads(texts, matches)
    matches = suppress_author_fragments(texts, matches)
    return matches


def apply_second_pass(ocrs, matches: list[Match | None], catalog: Catalog,
                      cfg: MatchConfig = CONFIG.match) -> list[Match | None]:
    """Variant-retrieval rescue for spines that are STILL unmatched after the
    shelf cleanup, followed by a re-run of that cleanup over the new claims.

    Order matters and was measured (run 18): the second pass originally ran
    before dedup/suppression, so a spine whose weak first-pass claim was
    LATER dropped (המוסד האחד matched the shelf-mate's המוסד השמימי, then
    lost the dedup) never got its variant queries — and the true המוסד האחר
    stayed unfound. Rescue after cleanup, then clean up again so second-pass
    claims obey every duplicate/fragment rule.
    """
    texts = [o.text for o in ocrs]
    added = False
    for i, (o, m) in enumerate(zip(ocrs, matches)):
        if m is None and o.text:
            matches[i] = match_second_pass(o.text, catalog, cfg)
            added = added or matches[i] is not None
    if added:
        matches = postprocess_matches(texts, matches, cfg)
    return matches


_MARKER_ROMAN = re.compile(r"^[ivxIVX]{1,4}$")
_MARKER_STARS = re.compile(r"[*★]+")
_MARKER_DIGIT = re.compile(r"^\d{1,2}$")
_MARKER_PART = re.compile(r"(?:כרך|חלק|ספר)\s+([א-ת]|\d{1,2})\b")


def volume_marker(text: str) -> str:
    """Extract a volume/part marker from a RAW read string ('', if none).

    Two spines of a multi-volume set read identically except for this marker
    (Strange & Norrell I / II, יער דנקטון * / **), and the duplicate-
    resolution passes must not collapse them into one book. Works on the raw
    text because normalize() strips asterisks entirely."""
    m = _MARKER_PART.search(text)
    if m:
        return m.group(1)
    stars = _MARKER_STARS.findall(text)
    if stars:
        return "*" * max(len(s) for s in stars)
    for tok in text.split():
        if _MARKER_ROMAN.match(tok):
            return tok.lower()
    for tok in text.replace("-", " ").split():
        if _MARKER_DIGIT.match(tok):
            return tok
    return ""


def _distinct_volumes(a: Match, b: Match) -> bool:
    """True when both claims' reads carry volume markers that DIFFER — two
    volumes of one set, not two reads of one spine. Requires both sides to
    show a marker: a marker missing on one side is just a partial read."""
    ma, mb = volume_marker(a.matched_text), volume_marker(b.matched_text)
    return bool(ma) and bool(mb) and ma != mb


def resolve_duplicates(matches: list[Match | None],
                       cfg: MatchConfig = CONFIG.match) -> list[Match | None]:
    """Within one shelf, the same catalog entry shouldn't win twice.

    The highest-scoring claimant keeps its tier. A rival scoring close to it
    may be a genuine second copy, so it is demoted to REVIEW rather than
    dropped. A rival scoring far below the winner is far more likely a
    mis-assignment (the winner already explains that title) and is dropped, so
    it becomes unmatched and goes to the fallback instead of showing a wrong
    book.
    """
    by_id: dict[str, list[int]] = {}
    for i, m in enumerate(matches):
        if m and m.catalog_id is not None:
            by_id.setdefault(m.catalog_id, []).append(i)
    for cid, idxs in by_id.items():
        if len(idxs) < 2:
            continue
        winner = max(idxs, key=lambda i: matches[i].score)
        cutoff = matches[winner].score * cfg.dup_drop_frac
        for i in idxs:
            if i == winner:
                continue
            # reads carrying DIFFERENT volume markers are different volumes
            # of one set matched to the same series record — a genuine
            # second book, never a mis-assignment. Keep it for review.
            if _distinct_volumes(matches[i], matches[winner]):
                matches[i].tier = "REVIEW"
                continue
            if matches[i].score < cutoff:
                matches[i] = None
            elif matches[i].tier == "AUTO":
                matches[i].tier = "REVIEW"
    return matches
