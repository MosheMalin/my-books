# -*- coding: utf-8 -*-
"""Precision / recall against hand-labelled shelves.

Until now runs were compared by AUTO/REVIEW counts, which cannot distinguish
"found more books" from "invented more books". Measured on IMG_7849 both
failure modes were live at once: ~8 of 14 real books found, but 19 phantom
titles reported alongside them. Those pull in opposite directions and need
separate numbers.

Scoring is on the DISTINCT set of books a run reports for a photo — that set is
the actual deliverable of cataloguing. A phantom costs precision; a miss costs
recall. For this project precision is the more expensive failure: a missing
book gets noticed when the owner scans the shelf, a wrong one silently rots in
the catalog.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from rapidfuzz import fuzz

from .catalog import normalize
from .config import REPO_ROOT

GROUND_TRUTH_PATH = REPO_ROOT / "ground_truth.json"
TITLE_HIT = 82          # normalized token_set_ratio to call two titles the same
AUTHOR_HIT = 72


@dataclass
class Book:
    title: str
    author: str = ""
    subtitle: str = ""

    @property
    def variants(self) -> list[str]:
        """Title with and without its subtitle — either may be printed on the
        spine, so a prediction matching either is correct."""
        t = normalize(self.title)
        if not self.subtitle:
            return [t]
        return [t, normalize(f"{self.title} {self.subtitle}")]


@dataclass
class Score:
    image: str
    tp: list[tuple[str, str]] = field(default_factory=list)   # (truth, predicted)
    fp: list[str] = field(default_factory=list)               # phantom books
    fn: list[str] = field(default_factory=list)               # missed books

    @property
    def precision(self) -> float:
        d = len(self.tp) + len(self.fp)
        return len(self.tp) / d if d else 0.0

    @property
    def recall(self) -> float:
        d = len(self.tp) + len(self.fn)
        return len(self.tp) / d if d else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"image": self.image,
                "precision": round(self.precision, 3),
                "recall": round(self.recall, 3),
                "f1": round(self.f1, 3),
                "n_truth": len(self.tp) + len(self.fn),
                "n_predicted": len(self.tp) + len(self.fp),
                "correct": [t for t, _ in self.tp],
                "phantom": self.fp,
                "missed": self.fn}


def load_ground_truth(path: str | Path = GROUND_TRUTH_PATH) -> dict[str, list[Book]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, list[Book]] = {}
    for image, rec in (data.get("images") or {}).items():
        out[image] = [Book(title=b["title"], author=b.get("author", ""),
                           subtitle=b.get("subtitle", ""))
                      for b in rec.get("books", [])]
    return out


# Hebrew attaches particles to the front of words: ה (definite), ו (and),
# כ (as/like), ב ל מ ש. Editions differ freely on them — the same Herriot book
# is printed "כל הדברים הנבונים והנפלאים" and "כל הדברים נבונים כמופלאים".
# Comparing raw, those score 71 and the book is counted BOTH as a phantom and
# as a miss, double-punishing a correct identification. Scoring therefore
# compares with particles stripped as well as intact.
_PREFIXES = ("ה", "ו", "כ", "ב", "ל", "מ", "ש")


def _depre(text: str) -> str:
    out = []
    for tok in text.split():
        while len(tok) > 3 and tok[0] in _PREFIXES:
            tok = tok[1:]
        out.append(tok)
    return " ".join(out)


def _title_sim(pred: str, book: Book) -> float:
    p = normalize(pred)
    best = max(fuzz.token_set_ratio(p, v) for v in book.variants)
    dp = _depre(p)
    best = max(best, *(fuzz.token_set_ratio(dp, _depre(v)) for v in book.variants))
    return best


def score_predictions(predictions: Iterable[dict], truth: list[Book],
                      image: str = "") -> Score:
    """Greedy best-first assignment of predicted books to ground-truth books.

    Each truth entry can be claimed once: two spines naming the same book are
    one catalog entry, not two hits. Author agreement breaks ties but is not
    required — a correct title with an unread author still identifies the book.
    """
    # distinct predicted titles, best (highest-scoring) instance kept
    uniq: dict[str, dict] = {}
    for p in predictions:
        t = (p.get("title") or "").strip()
        if not t:
            continue
        key = normalize(t)
        if key and (key not in uniq or (p.get("score") or 0) > (uniq[key].get("score") or 0)):
            uniq[key] = p

    pairs = []
    for key, p in uniq.items():
        for i, b in enumerate(truth):
            s = _title_sim(p["title"], b)
            if s >= TITLE_HIT:
                a = fuzz.token_set_ratio(normalize(p.get("author") or ""),
                                         normalize(b.author)) if b.author else 0
                pairs.append((s + 0.1 * a, key, i))
    pairs.sort(reverse=True)

    used_truth: set[int] = set()
    used_pred: set[str] = set()
    score = Score(image=image)
    for _, key, i in pairs:
        if key in used_pred or i in used_truth:
            continue
        used_pred.add(key)
        used_truth.add(i)
        score.tp.append((truth[i].title, uniq[key]["title"]))
    score.fp = [uniq[k]["title"] for k in uniq if k not in used_pred]
    score.fn = [b.title for i, b in enumerate(truth) if i not in used_truth]
    return score


def score_run(found: Iterable[dict], image_name: str,
              ground_truth: Optional[dict[str, list[Book]]] = None,
              tiers: Optional[set[str]] = None) -> Optional[Score]:
    """Score one image's rows from /api/results. `tiers` filters which
    confidence tiers count as reported books (default: AUTO + REVIEW)."""
    gt = ground_truth if ground_truth is not None else load_ground_truth()
    truth = gt.get(image_name)
    if truth is None:
        return None
    tiers = tiers or {"AUTO", "REVIEW"}
    preds = [f for f in found
             if f.get("title") and (f.get("tier") in tiers)
             and (not image_name or f.get("image_name") == image_name)]
    return score_predictions(preds, truth, image=image_name)
