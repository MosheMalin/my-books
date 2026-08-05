# -*- coding: utf-8 -*-
"""Make a run's catalog retrieval reproducible.

The tune-and-measure loop had a hole: replaying a stored run's OCR through the
current matcher gave different results than the run itself recorded (run #7
stored 9 correct books, replayed 5). OCR was identical, so the difference was
*retrieval* — NLI is a live search engine, and its answers move with our query
code, its own index, and transient failures. That makes "did my change help?"
unanswerable, because the catalog moved underneath the comparison.

Fix: record every catalog lookup a run performs, then replay against that
recording. Retrieval becomes a fixed input, exactly like the stored OCR text,
so any difference in results is attributable to the code under test.

    live run:   RecordingCatalog(NLICatalog(...))  -> save_log(...)
    replay:     ReplayCatalog.from_file(...)       -> deterministic
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .catalog import CatalogEntry


class RecordingCatalog:
    """Wraps any Catalog and logs each query's returned entries.

    Transparent: the matcher cannot tell the difference, so recording never
    changes what a run produces.
    """

    def __init__(self, inner):
        self.inner = inner
        self.log: dict[str, list[dict[str, str]]] = {}

    def candidates(self, query: str, limit: int = 15) -> list[CatalogEntry]:
        entries = self.inner.candidates(query, limit)
        # first answer wins: identical queries must not diverge within a run
        self.log.setdefault(query, [
            {"id": e.id, "title": e.title, "author": e.author} for e in entries])
        return entries

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.log, ensure_ascii=False), encoding="utf-8")

    @property
    def stats(self) -> dict[str, Any]:
        return {"queries": len(self.log),
                "entries": sum(len(v) for v in self.log.values())}


class ReplayCatalog:
    """Serves exactly what a recorded run saw. No network, fully deterministic.

    A query the run never made returns nothing and is counted in `misses` —
    that is a real signal, not an error: it means the code under test is now
    asking the catalog something different, so its recall gain (or loss) is
    partly a *retrieval* change and cannot be credited to matching alone.
    """

    def __init__(self, log: dict[str, list[dict[str, str]]]):
        self._log = log
        self.misses: list[str] = []

    @classmethod
    def from_file(cls, path: str | Path) -> "ReplayCatalog":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def candidates(self, query: str, limit: int = 15) -> list[CatalogEntry]:
        rows = self._log.get(query)
        if rows is None:
            self.misses.append(query)
            return []
        return [CatalogEntry(r["id"], r["title"], r.get("author", ""))
                for r in rows]

    def __len__(self) -> int:
        return sum(len(v) for v in self._log.values())
