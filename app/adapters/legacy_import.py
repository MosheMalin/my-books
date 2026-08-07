# -*- coding: utf-8 -*-
"""Import today's ``work/`` JSON into Book/Copy entities (plan P1.3, H6, §11.2).

A **required deliverable**, not a convenience: the owner's 251 confirmed books
and 155 review decisions cannot be re-derived — re-running the pipeline would
reproduce the claims but not the human judgements on them (§11.3). It also
doubles as the first real test of the schema.

Inputs, and what each is actually used for:

  ``library.json``    the books. THE source of record for what is owned.
  ``store.json``      run and image timestamps only, to date the sightings.
  ``decisions.json``  cross-check, plus the rejections that have no home yet.
  ``runs/*``          **not consumed.** Per-spine records and crop paths are
                      real data, but a crop needs a BlobStore (P3.5) and a
                      spine needs a Capture (P2.1). Importing them now would
                      mean importing them again later, differently.

Honest scope, per the plan: 251 books, their statuses, and ONE provenance
entry each. Location fields stay null by design (§1.1 — a book's physical
location comes from the map) and the UI hides them until then.

Split deliberately: :func:`read_snapshot` does the I/O, :func:`to_books` is
PURE. That is what lets the mapping be tested against committed fixtures with
no filesystem at all, and what makes the tricky parts (re-keying, status
mapping) testable one case at a time.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.domain import Book, LibraryRef, Provenance, Status, book_key, new_book
from app.ports.store import BookStore

# A human picked this title from the matcher's RANKED ALTERNATIVES rather than
# typing it (`decisions.json` action "replace", 5 books). Judgement call:
# imported as APPROVED, not MANUAL, because the text is the catalog's and only
# the CHOICE is the person's — `manual` is reserved for text a human authored
# (UI_PLAN §5). Either way it outranks `auto` and no re-read can demote it, so
# the only thing riding on this is the status filter's label.
REPLACED_STATUS = Status.APPROVED


@dataclass(frozen=True)
class LegacySnapshot:
    """The raw JSON, exactly as it sits on disk. No interpretation yet."""

    books: dict            # library.json -> {"books": {...}}
    runs: dict             # store.json   -> {"runs": [...]} keyed by run_id
    images: dict           # store.json   -> {"images": {...}}
    decisions: dict        # decisions.json -> {run_id: {spine_id: {...}}}


@dataclass(frozen=True)
class ImportReport:
    """What the import did, in terms a person can check against the source."""

    books_read: int = 0
    books_written: int = 0
    already_present: tuple[str, ...] = ()
    rekeyed: tuple[str, ...] = ()
    by_status: dict[str, int] = field(default_factory=dict)
    rejections_not_migrated: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()

    def summary(self) -> str:
        lines = [
            f"read {self.books_read} books from library.json",
            f"wrote {self.books_written}"
            + (f", skipped {len(self.already_present)} already present"
               if self.already_present else ""),
            "  status: " + ", ".join(
                f"{k} {v}" for k, v in sorted(self.by_status.items())),
        ]
        if self.rekeyed:
            lines.append(
                f"  re-keyed {len(self.rekeyed)} books whose stored key predates "
                f"a normalize() change (see to_books)")
        if self.rejections_not_migrated:
            lines.append(
                f"  !! {len(self.rejections_not_migrated)} rejected claims NOT "
                f"migrated — they need a shelf to be rejected ON (P2.3, §5.6). "
                f"Until then a re-read could re-add them.")
        for p in self.problems:
            lines.append(f"  !! {p}")
        return "\n".join(lines)


# --- I/O ------------------------------------------------------------------

def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_snapshot(work_dir: Path) -> LegacySnapshot:
    """Read the four files. Missing ones read as empty rather than raising —
    a machine with no runs should import an empty library, not crash."""
    store = _load(work_dir / "store.json")
    return LegacySnapshot(
        books=_load(work_dir / "library.json").get("books") or {},
        runs=_runs_by_id(store.get("runs")),
        images=store.get("images") or {},
        decisions=_load(work_dir / "decisions.json") or {},
    )


def _runs_by_id(raw) -> dict:
    """``store.json``'s ``runs`` is a DICT keyed by run_id.

    Handled explicitly, and both shapes accepted, because getting this wrong
    fails SILENTLY: iterating a dict yields its keys, so a list comprehension
    over ``raw`` produces strings, every ``isinstance(r, dict)`` guard drops
    them, and the result is an empty run index. Nothing raises — the books
    still import, they just quietly lose their dates. That is exactly the bug
    the committed fixture caught.
    """
    if isinstance(raw, dict):
        return {k: v for k, v in raw.items() if isinstance(v, dict)}
    return {r["run_id"]: r for r in (raw or [])
            if isinstance(r, dict) and r.get("run_id")}


# --- pure mapping ---------------------------------------------------------

def stable_id(library_id: str, key: str, suffix: str = "") -> str:
    """Deterministic id from (library, book key).

    Deterministic rather than random so the import is RE-RUNNABLE: the same
    book always lands on the same id, so a second run updates rather than
    duplicating. Ids stay stable when a title is later edited — the id is the
    identity, the key is derived — which is exactly why they are minted from
    the key once and never again.
    """
    h = hashlib.blake2s(f"{library_id}|{key}{suffix}".encode("utf-8"),
                        digest_size=8)
    return h.hexdigest()


def _status_of(entry: dict) -> Status:
    source = entry.get("source") or {}
    if source.get("manual"):
        return Status.MANUAL          # the owner typed this book in
    if source.get("replaced"):
        return REPLACED_STATUS        # picked from ranked alternatives
    return Status.APPROVED if entry.get("status") == "approved" else Status.AUTO


def _seen_at(snapshot: LegacySnapshot, source: dict) -> str | None:
    """When this sighting happened.

    Prefer the IMAGE's upload time: a spine id is ``<image_id>_b<n>_s<nn>``, so
    the photo is identifiable without touching runs/*. Fall back to the run's
    end time, which is what a hand-typed book (``owner-fb-…`` / ``manual-…``,
    no image) has. ``None`` when neither is known — better than a made-up date.
    """
    spine_id = str(source.get("spine_id") or "")
    image_id = spine_id.split("_", 1)[0] if "_" in spine_id else ""
    image = snapshot.images.get(image_id)
    if image and image.get("uploaded_at"):
        return image["uploaded_at"]
    run = snapshot.runs.get(source.get("run_id") or "")
    if run:
        return run.get("finished_at") or run.get("started_at")
    return None


def to_books(
    snapshot: LegacySnapshot,
    library: LibraryRef,
) -> tuple[list[Book], list[str], list[str]]:
    """Map the snapshot to entities. PURE — no filesystem, no store.

    Returns ``(books, rekeyed, problems)``.
    """
    books: list[Book] = []
    rekeyed: list[str] = []
    problems: list[str] = []
    seen: dict[str, str] = {}

    for stored_key, entry in snapshot.books.items():
        title = (entry.get("title") or "").strip()
        author = (entry.get("author") or "").strip()
        if not title:
            problems.append(f"{stored_key!r}: no title, skipped")
            continue

        # RECOMPUTE the key; never trust the stored one. 30 of the owner's 251
        # keys were written before normalize() stopped space-splitting geresh
        # (run 16), so they read e.g. "צ רלס סטרוס" where today's key is
        # "צרלס סטרוס". Importing those verbatim would give 30 books a key no
        # future lookup could ever produce. Measured: re-keying yields 251
        # distinct keys with zero collisions.
        key = book_key(title, author)
        if key != stored_key:
            rekeyed.append(stored_key)
        if key in seen:
            problems.append(
                f"{stored_key!r} and {seen[key]!r} collapse to one key "
                f"{key!r} under the current normalize(); kept the first")
            continue
        seen[key] = stored_key

        source = entry.get("source") or {}
        when = _seen_at(snapshot, source)
        run_id = str(source.get("run_id") or "")
        spine_id = str(source.get("spine_id") or "")
        provenance = (
            (Provenance(run_id=run_id, spine_id=spine_id,
                        shelf_id=None,          # §1.1: location comes with the map
                        captured_at=when),)
            if run_id or spine_id else ()
        )

        book_id = stable_id(library.id, key)
        books.append(new_book(
            id=book_id,
            library_id=library.id,
            title=title,
            author=author,
            copy_id=stable_id(library.id, key, suffix="|copy-1"),
            status=_status_of(entry),
            shelf_id=None,
            provenance=provenance,
            added_at=when,
        ))

    return books, rekeyed, problems


def unmigrated_rejections(snapshot: LegacySnapshot) -> list[str]:
    """Claims the owner rejected outright ("wrong — ignore").

    §5.6 says a book the user rejected must not be re-added by a later run,
    and `booksnap/library.py::absorb_auto_claims` enforces that today by
    reading this file. The product has nowhere to put it yet: a rejection is
    scoped to a SHELF, and shelves arrive in P2.1. Reported rather than
    dropped, so the gap is visible instead of discovered by a re-read.
    """
    out = []
    for per_run in snapshot.decisions.values():
        for dec in per_run.values():
            if dec.get("action") == "reject_ignore" and dec.get("rejected_title"):
                out.append(
                    f"{dec['rejected_title']} / {dec.get('rejected_author', '')}"
                    .strip(" /"))
    return sorted(set(out))


# --- the import -----------------------------------------------------------

def import_legacy(
    work_dir: Path,
    library: LibraryRef,
    store: BookStore,
) -> ImportReport:
    """Read ``work_dir`` and write into ``store``. Safe to re-run.

    A book already in the library is SKIPPED, never overwritten: after the
    first import the owner starts editing, and a second run must not silently
    revert those edits. Resuming a half-finished import therefore works, and
    "did it already run?" is not a question anyone has to answer.

    "Already present" is checked by **id AND key**, and the id is the load-
    bearing half. Once the owner fixes an imported title the book's key
    changes, so a key-only check reads as absent — and would then re-save
    under the SAME deterministic id, replacing the correction with the
    original text. Exactly the destruction this function exists to prevent.
    """
    snapshot = read_snapshot(work_dir)
    books, rekeyed, problems = to_books(snapshot, library)

    written = 0
    skipped: list[str] = []
    by_status: dict[str, int] = {}
    for book in books:
        if (store.get(library, book.id) is not None
                or store.get_by_key(library, book.key) is not None):
            skipped.append(book.key)
            continue
        store.save(library, book)
        written += 1
        by_status[book.status.value] = by_status.get(book.status.value, 0) + 1

    return ImportReport(
        books_read=len(snapshot.books),
        books_written=written,
        already_present=tuple(skipped),
        rekeyed=tuple(rekeyed),
        by_status=by_status,
        rejections_not_migrated=tuple(unmigrated_rejections(snapshot)),
        problems=tuple(problems),
    )
