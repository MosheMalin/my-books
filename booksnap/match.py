# -*- coding: utf-8 -*-
"""Stage 3 — matching.

Score OCR candidates against catalog entries with token-level evidence gates:
a match needs real content-token overlap, not mere string similarity, which
is what kept garbage OCR from resolving to spurious titles.
"""
from __future__ import annotations
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
    if not cfg.strip_prefixes:
        return False
    qs, cs = strip_prefix(q), strip_prefix(c)
    if qs == q and cs == c:
        return False                      # nothing was stripped; no second bite
    thr = cfg.short_token_ratio if len(cs) <= cfg.short_token_len else cfg.token_ratio
    return fuzz.ratio(qs, cs) >= thr


def _evaluate(query_tokens: list[str], entry: CatalogEntry,
              cfg: MatchConfig, query_text: str = "") -> dict:
    """Score one catalog entry, always returning the reasoning.

    `rejected` names the gate that refused the entry (None if it passed), so
    the same code can both match and explain why a book did or didn't win.

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

    def matched(catalog_tokens):
        return [c for c in catalog_tokens
                if any(_token_hit(x, c, cfg) for x in query_tokens)]

    mt, ma = matched(tt), matched(at)
    tt_content, mt_content = _content(tt, cfg), _content(mt, cfg)
    tcov = len(mt) / len(tt) if tt else 0.0
    acov = len(ma) / len(at) if at else 0.0
    tcov_c = (len(mt_content) / len(tt_content)) if tt_content else 0.0
    n_title_hits = len(mt_content)
    has_distinct_title = any(len(t) >= cfg.distinctive_len for t in mt_content)

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
    explained = sum(1 for x in q_content
                    if any(_token_hit(x, c, cfg) for c in tt + at))
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

    # A catalog title made only of volume/part words is not identifying: a
    # spine printed "ספר שלישי" would otherwise resolve to a book literally
    # titled "השלישי". Same for imprint boilerplate ("ספרית פועלים").
    if _is_junk_title(tt_content or tt, cfg):
        info["rejected"] = "catalog title is only volume/publisher boilerplate"
        return info

    # EXISTENCE GATE — title evidence only. Author agreement may raise the
    # tier but must never be what makes a match exist: pooling title and
    # author evidence let one noise token plus a series author invent a title.
    # One narrow exception (IMG_8129): a SHORT one-word title (עדן, הצלם) can
    # never produce 2 hits or a 5-char token, making such books structurally
    # unmatchable. When the ENTIRE title is matched and the author strongly
    # corroborates, that is real evidence — this is not author-alone (the
    # full title must still match), so the original bug can't return.
    full_title_with_author = (tt and tcov == 1.0 and n_title_hits >= 1
                              and acov >= 0.5)
    # ...and a read that IS the title, verbatim: "צל אפל" read cleanly still
    # had zero usable tokens (צל under the length floor, אפל short of
    # distinctive), making the book unmatchable however well it was read.
    # Whole-string equality of the full normalized read is strong evidence.
    verbatim_title = bool(entry.norm_title) and q == entry.norm_title
    if not (n_title_hits >= 2 or has_distinct_title or full_title_with_author
            or verbatim_title):
        info["rejected"] = "no title evidence (needs 2 title tokens, or 1 of " \
                           f"{cfg.distinctive_len}+ chars)"
        return info
    if title_sim < cfg.min_title_sim:
        info["rejected"] = f"title similarity {title_sim} < {cfg.min_title_sim}"
        return info
    if cfg.min_ngram_sim > 0 and info["ngram_sim"] < cfg.min_ngram_sim:
        info["rejected"] = (f"n-gram similarity {info['ngram_sim']:.0f} < "
                            f"{cfg.min_ngram_sim:.0f}")
        return info

    info["score"] = 60 * tcov_c + 25 * tcov + 15 * acov + 0.30 * title_sim
    return info


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


def match_candidate(text: str, catalog: Catalog,
                    cfg: MatchConfig = CONFIG.match) -> Match | None:
    qt = _tokens(text, cfg)
    if not qt:
        return None
    best = None
    for entry in catalog.candidates(text):
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
                 catalog_id=entry.id)


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
            catalog_id=entry.id)
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
            if t_same and a_ok:
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
        if not any(len(t) >= 3 for t in a):
            return False
        return all(any(t in u for u in b) for t in a)

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
            # Suppression demands STRICT superiority: on IMG_8133 the clean
            # read "יד הכאוס מרגרט..." (correct volume) TIED the compound
            # read's series-record claim and was wrongly eaten — a tie means
            # we cannot tell which claim is better, so both stay and the
            # review flow decides.
            if (contained(toks[i], world(j)) and not contained(toks[j], world(i))
                    and (rank[other.tier], other.score) > (rank[m.tier], m.score)):
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
        return all(any(fuzz.ratio(t, a) >= 85 or t in a or a in t
                       for a in a_toks) for t in core)

    for i, (text, m) in enumerate(zip(texts, matches)):
        if not m:
            continue
        q_toks = normalize(text).split()
        for other in matches:
            if other is None or other is m or not other.author:
                continue
            if name_only(q_toks, normalize(other.author).split()):
                matches[i] = None
                break
    return matches


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
            if matches[i].score < cutoff:
                matches[i] = None
            elif matches[i].tier == "AUTO":
                matches[i].tier = "REVIEW"
    return matches
