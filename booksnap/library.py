# -*- coding: utf-8 -*-
"""The owner's confirmed library — the actual deliverable of cataloguing.

Until now the pipeline only produced *runs* (claims with tiers). This module
adds the persistent artifact those claims feed: a catalog of books the owner
has confirmed owning. Semantics, per the review-flow design:

  - AUTO claims enter the library automatically when a run completes, with
    status "auto" — precision at AUTO is measured ~0.9+, so waiting for a
    human tap on every one would waste the tier's whole point. They stay
    reversible: rejecting the claim later removes the book.
  - REVIEW claims wait for an explicit decision.
  - A rejected claim can be replaced from ranked alternatives ("wrong — find
    better"), or dismissed ("wrong — ignore": not a book / don't care).
  - Missing books can be added manually per image.

The library doubles as a retrieval source: `ConfirmedCatalog` serves it at
the HEAD of the catalog chain, so a book confirmed once matches instantly
(and offline) on every later shelf. Only confirmed/auto books ever enter —
feeding unverified claims back into retrieval would let phantoms self-
reinforce. This file is also the seed of the future shared DB (the public-
app plan): same records, Mongo instead of JSON.

Decisions are stored per (run_id, spine_id) in a separate file — run records
themselves stay immutable (the archive rule).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

from .catalog import CatalogEntry, normalize
from .config import CONFIG

_LOCK = threading.Lock()


def _lib_path() -> Path:
    return CONFIG.paths.work_dir / "library.json"


def _dec_path() -> Path:
    return CONFIG.paths.work_dir / "decisions.json"


def _read(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                    encoding="utf-8")


def book_key(title: str, author: str) -> str:
    return f"{normalize(title)}|{normalize(author)}"


def load_library() -> dict:
    return _read(_lib_path())


def load_decisions(run_id: Optional[str] = None) -> dict:
    d = _read(_dec_path())
    return d.get(run_id, {}) if run_id else d


def add_book(title: str, author: str, status: str, source: dict) -> dict:
    """Add/upgrade a library entry. A human decision outranks an auto one."""
    with _LOCK:
        lib = _read(_lib_path())
        books = lib.setdefault("books", {})
        key = book_key(title, author)
        cur = books.get(key)
        if cur is None or (cur.get("status") == "auto" and status == "approved"):
            books[key] = {"title": title, "author": author, "status": status,
                          "source": source}
        _write(_lib_path(), lib)
        return books[key]


def remove_book(title: str, author: str) -> bool:
    with _LOCK:
        lib = _read(_lib_path())
        gone = lib.get("books", {}).pop(book_key(title, author), None)
        _write(_lib_path(), lib)
        return gone is not None


def record_decision(run_id: str, spine_id: str, decision: dict) -> None:
    with _LOCK:
        d = _read(_dec_path())
        d.setdefault(run_id, {})[spine_id] = decision
        _write(_dec_path(), d)


def absorb_auto_claims(run_id: str, records: list[dict]) -> int:
    """Run completed: AUTO claims become library entries (status 'auto').

    Claims the owner already rejected in an earlier run of the same image are
    NOT re-added — a human decision must not be overridden by re-running.
    """
    rejected = {
        book_key(dec["rejected_title"], dec.get("rejected_author", ""))
        for per_run in _read(_dec_path()).values()
        for dec in per_run.values()
        if dec.get("rejected_title")
    }
    n = 0
    for r in records:
        m = r.get("match") or {}
        if m.get("tier") != "AUTO" or not m.get("title"):
            continue
        if book_key(m["title"], m.get("author", "")) in rejected:
            continue
        add_book(m["title"], m.get("author", ""), "auto",
                 {"run_id": run_id, "spine_id": r.get("spine_id", "")})
        n += 1
    return n


class ConfirmedCatalog:
    """The library as a retrieval source.

    Reloads lazily on file change, so books confirmed mid-session take effect
    on the next run without a server restart. Candidates are prefiltered by
    token overlap so unrelated queries return [] — required because this
    source AUGMENTS the chain (see LibraryFirstCatalog), it must not flood it.
    """

    def __init__(self):
        self._mtime = -1.0
        self._entries: list[CatalogEntry] = []

    def _refresh(self) -> None:
        p = _lib_path()
        mtime = p.stat().st_mtime if p.exists() else 0.0
        if mtime == self._mtime:
            return
        self._mtime = mtime
        self._entries = [
            CatalogEntry(f"lib:{key}", b["title"], b.get("author", ""))
            for key, b in (_read(p).get("books") or {}).items()]

    def candidates(self, query: str, limit: int = 15) -> list[CatalogEntry]:
        self._refresh()
        q = {t for t in normalize(query).split() if len(t) >= 3}
        out = []
        for e in self._entries:
            ent = set(e.norm_title.split()) | set(e.norm_author.split())
            if q & ent:
                out.append(e)
        return out[:limit]


class LibraryFirstCatalog:
    """Union the confirmed library's candidates with the chain's.

    NOT an on-empty cascade: the library must never block the chain (a shared
    token with a confirmed book would otherwise stop retrieval for a query
    about a different, unconfirmed book — e.g. a new series sibling). The
    matcher's gates rank the merged pool; a confirmed book that genuinely
    fits wins, everything else resolves exactly as before.
    """

    def __init__(self, library, chain):
        self.library = library
        self.chain = chain

    def candidates(self, query: str, limit: int = 15) -> list[CatalogEntry]:
        merged: dict[str, CatalogEntry] = {}
        for e in self.library.candidates(query, limit):
            merged.setdefault(normalize(e.title) + "|" + e.norm_author, e)
        for e in self.chain.candidates(query, limit):
            merged.setdefault(normalize(e.title) + "|" + e.norm_author, e)
        return list(merged.values())
