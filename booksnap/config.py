# -*- coding: utf-8 -*-
"""Central configuration for the booksnap pipeline.

Every tunable lives here so the stages stay logic-only. Paths resolve
relative to this file unless overridden by environment variables, so the
package runs unchanged on a dev box or a server.
"""
from __future__ import annotations
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PKG_ROOT.parent

# Windows installer locations, checked when tesseract isn't on PATH. A server
# launched from a GUI/service often doesn't inherit the user's PATH edits.
_WINDOWS_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def _env_path(var: str, default: Path) -> Path:
    v = os.environ.get(var)
    return Path(v).expanduser().resolve() if v else default


def _find_tesseract() -> str:
    """Locate the tesseract binary: explicit override, PATH, then the usual
    Windows install dirs. Returns the bare name if nothing is found, so the
    error surfaces at call time with a useful message."""
    override = os.environ.get("BOOKSNAP_TESSERACT")
    if override:
        return override
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    for cand in _WINDOWS_CANDIDATES:
        if Path(cand).exists():
            return cand
    return "tesseract"


@dataclass(frozen=True)
class Paths:
    tessdata_best: Path = _env_path("BOOKSNAP_TESSDATA_BEST", REPO_ROOT / "tessdata")
    tessdata_fast: Path = _env_path("BOOKSNAP_TESSDATA_FAST", REPO_ROOT / "tessfast")
    work_dir: Path = _env_path("BOOKSNAP_WORK", REPO_ROOT / "work")
    tesseract_cmd: str = field(default_factory=_find_tesseract)

    def ensure(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        (self.work_dir / "crops").mkdir(exist_ok=True)
        (self.work_dir / "debug").mkdir(exist_ok=True)


@dataclass(frozen=True)
class SegmentConfig:
    work_width: int = 1600            # images downscaled to this width for analysis
    min_band_frac: float = 0.15       # a shelf band must be >= this frac of height
    min_spine_frac: float = 0.013     # min spine width as frac of work width
    # boundary signal weights: long-vertical-edge, colour change, shadow crease
    w_coverage: float = 1.2
    w_colour: float = 0.8
    w_darkness: float = 0.4
    peak_prominence: float = 0.10     # frac of max signal
    row_ink_frac: float = 0.007       # row is "book" if vertical-edge coverage exceeds
    crop_pad_frac: float = 0.08       # horizontal padding added around each spine crop


@dataclass(frozen=True)
class OcrConfig:
    langs: tuple[str, ...] = ("heb", "Hebrew")   # best-model languages for the final pass
    fast_lang: str = "heb"                        # fast-model language for screening
    strip_max_width: int = 220        # cap rotated-strip height (=spine width) in px
    line_heights: tuple[int, ...] = (48, 80)      # normalise each text line to these
    line_min_px: int = 10             # ignore detected text bands thinner than this
    min_word_conf: int = 35           # Tesseract word-confidence floor
    min_heb_chars: int = 2            # a scored word needs at least this many Heb chars
    good_enough_score: int = 800      # stop escalating a line once it beats this
    psm_line: int = 7                 # single-line page-segmentation mode


@dataclass(frozen=True)
class MatchConfig:
    token_min_len: int = 3            # tokens shorter than this are ignored
    token_ratio: int = 78            # per-token fuzzy-match acceptance (RapidFuzz ratio)
    # Short tokens are cheap to hit by accident: a 1-letter difference on a
    # 3-4 char word still scores ~86 (היה vs החיה), which was inventing matches.
    short_token_len: int = 4          # tokens this length or shorter...
    short_token_ratio: int = 90       # ...must clear this higher bar
    distinctive_len: int = 5          # a lone matched token this long counts as evidence
    # A catalog token at least this long, found INSIDE a longer OCR token,
    # counts as present — OCR routinely fuses adjacent words on a spine
    # ("דארלציפור" = author+title with the space lost).
    embedded_token_len: int = 5
    # Whole-title agreement floor. Previously title similarity only *ranked*
    # candidates; it never rejected one, so a single fuzzy token could carry a
    # title that looks nothing like the OCR text.
    # Swept on the 26-spine Durrell shelf: three confirmed-wrong matches sit at
    # <=37, while a correct match on badly-degraded OCR sits at 50.8. Anything
    # in 45-50 separates them; 47 is centred in that band. Re-measure if the
    # catalog changes — a real (NLI) catalog will move these numbers.
    min_title_sim: int = 47
    # Within a shelf, a duplicate claim scoring far below the winner is much
    # more likely a mis-assignment than a second physical copy -> drop it.
    dup_drop_frac: float = 0.70
    auto_title_cov: float = 0.6       # AUTO if this frac of title tokens matched
    auto_title_content_cov: float = 0.5   # ...or this frac of *content* title tokens
    auto_author_cov: float = 0.5      # ...with this frac of author tokens
    # How much of the OCR text the candidate has to explain before it can be
    # AUTO. Coverage ratios alone are gameable by very short titles: against
    # the 9M-record NLI index, the one-word title "ציפורי" (Sepphoris) scored
    # tcov=1.0 on a spine reading "ציפורי ישראל והמזרח התיכון" and went AUTO
    # while explaining 1 of 8 tokens. Measured: wrong matches 0.20-0.29,
    # correct ones 0.45-1.00.
    auto_min_query_cov: float = 0.35
    # --- global assignment (see match.resolve_assignment) ---
    # Spines and catalog entries are matched as two SETS, not independently:
    # every spine picking its own best entry is what let 15-24 phantom books be
    # reported for a 14-book shelf. Assignment forces them to compete.
    # Hebrew glues particles (ה ו כ ב ל מ ש) onto word fronts, and editions
    # differ freely on them: the same Herriot book is printed
    # "כל הדברים הנבונים והנפלאים" and "כל הדברים נבונים כמופלאים".
    # Comparing raw, those score 71; particle-stripped, 98 — while genuinely
    # different titles stay ~31.
    # MEASURED in the matcher: no gain on either labelled shelf, and precision
    # on IMG_7849 fell 0.62 -> 0.50. The per-token fuzz threshold (78) already
    # absorbs a one-letter prefix on a long word, so stripping only widens what
    # can match. It IS needed in scoring.py, where whole-title token_set_ratio
    # is strict enough that edition spellings scored 71 and were counted as
    # both a phantom and a miss. Different comparison, different answer.
    strip_prefixes: bool = False
    # Character n-gram cosine floor between OCR text and candidate title.
    # token_set_ratio has a pathology: a SHORT title that is a subset of the
    # query scores a perfect 100 — which is how the one-word "ציפורי"
    # (Sepphoris, an archaeological site) beat the real book and went AUTO on a
    # spine reading "ציפורי ישראל והמזרח התיכון". N-gram cosine scores that
    # pair 51 because it penalises length mismatch, while still scoring genuine
    # edition variants (הנבונים/נבונים) 73. Swept on the labelled shelves.
    # Swept 0/30/40/45/50/55 on both labelled shelves (3 run x 2 tier sets).
    # 50 gives precision >= 0.88 on EVERY measurement, which is the metric that
    # matters here, and the best mean F1 for auto+review (0.65 vs 0.58 at 0).
    # Caveat: only 3 measurements — the useful band is broad (40-50) and the
    # per-shelf optimum differs, so treat 50 as "inside the good range", not as
    # a tuned constant. Re-sweep when more shelves are labelled.
    min_ngram_sim: float = 50.0       # 0 disables
    # Global assignment measured WORSE than per-spine on IMG_7849 (precision
    # 0.56 vs 0.62): against an open 9M-record catalog the one-to-one
    # constraint just makes a losing spine take its second-best (wrong) entry
    # instead of being dropped. Kept for closed-catalog experiments.
    use_assignment: bool = False
    assign_min_score: float = 58.0     # below this a spine stays unassigned
    # Catalog entries whose title is only a volume/part marker, and spine text
    # that is publisher/imprint boilerplate. Measured on IMG_7849: phantoms
    # included הרביעי / השלישי / החלק הראשון / הבן החמישי (series volume text)
    # and three different titles containing פנטסיה (an imprint line).
    junk_title_words: frozenset[str] = field(default_factory=lambda: frozenset({
        "הראשון", "השני",
        "השלישי", "הרביעי",
        "החמישי", "השישי",
        "חלק", "כרך", "כרוך",
        "ספר", "סדרה",
        "טרילוגיה",
    }))
    publisher_words: frozenset[str] = field(default_factory=lambda: frozenset({
        "הוצאת", "ספרית",
        "ספריית", "מועדון",
        "קוראי", "מעריב",
        "פועלים", "כתר",
        "זמורה", "ביתן",
        "כנרת", "עם עובד",
    }))
    stopwords: frozenset[str] = field(default_factory=lambda: frozenset({
        "\u05e9\u05dc", "\u05d0\u05ea", "\u05e2\u05dd", "\u05e2\u05dc", "\u05db\u05dc",
        "\u05dc\u05d0", "\u05d6\u05d4", "\u05d4\u05d5\u05d0", "\u05d4\u05d9\u05d0",
        "\u05d0\u05e0\u05d9", "\u05d1\u05df", "\u05d1\u05ea", "\u05de\u05df",
        "\u05d0\u05dc", "\u05d2\u05dd", "\u05d0\u05d5", "\u05db\u05d9", "\u05de\u05d4",
        "\u05de\u05d9", "\u05d9\u05e9",
    }))


@dataclass(frozen=True)
class LlmReaderConfig:
    """mode='llmpage' — whole-photo reading with a vision LLM (llmreader.py).

    MEASURED (Aug 2026, tools/llm_read_probe.py, 35-book fixture): the model
    and BOTH preprocessing steps are load-bearing.
      - haiku whole-photo: read 0/35 (confabulated entire shelves);
      - sonnet whole-photo: 1/35 — read vertical spines LETTER-REVERSED;
      - sonnet + 2x2 tiles + 90cw rotation: 18/21 and 14/14 raw read-rate.
    Tiles keep near-native pixel density per spine (a whole shelf downscaled
    to the model's 2576px vision ceiling leaves ~70px per spine); rotation
    makes the vertical spine text horizontal, which stops reversed reads.
    """
    model: str = os.environ.get("BOOKSNAP_LLM_MODEL", "claude-sonnet-5")
    grid_rows: int = 2
    grid_cols: int = 2
    tile_overlap_frac: float = 0.15   # tiles overlap so no spine is only cut
    # 'both' reads in both 90° rotations (2x cost, ~$0.15/photo): Hebrew
    # spines are printed in either direction, and reads VARY between passes
    # (measured on IMG_8125: סליחה was only ever read by the second rotation;
    # אוי למנצחים read correctly in one pass, garbled in another). The union
    # feeds the matcher, whose gates + near-dup resolution absorb the noise.
    rotate: str = "both"              # 'cw' | 'ccw' | 'none' | 'both'
    max_edge: int = 2576              # sonnet/opus high-res vision ceiling (px)
    jpeg_quality: int = 88
    max_tokens: int = 8000            # adaptive thinking shares this budget


@dataclass(frozen=True)
class Config:
    paths: Paths = field(default_factory=Paths)
    segment: SegmentConfig = field(default_factory=SegmentConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    match: MatchConfig = field(default_factory=MatchConfig)
    llm: LlmReaderConfig = field(default_factory=LlmReaderConfig)


CONFIG = Config()
