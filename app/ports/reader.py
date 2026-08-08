# -*- coding: utf-8 -*-
"""The Reader port — ``booksnap.Pipeline`` behind a seam (P2.4).

``booksnap.Pipeline`` is the recognition core's one entrypoint (segment ->
OCR -> match, or a whole-page mode), and it is exactly the kind of thing H1
keeps out of ``app/domain`` and ``app/api``: it imports cv2, shells out to
tesseract, and may call a paid vision API. This Protocol is what lets the
rest of the product depend on "something that turns photographs into claims"
without depending on any of that:

  - a stub satisfies it in milliseconds, so ``tests/test_api.py`` never starts
    a real engine — H4 ring 3's rule, the same reason ``MemoryBookStore``
    exists;
  - it is the one place P5's cost metering will hook in later — every call is
    a chargeable event, whichever engine ends up answering it.

May import ``app.domain`` only (H1). The concrete adapter
(``app.adapters.booksnap_reader.BooksnapReader``) is the one allowed to import
``booksnap`` and a ``BlobStore``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from app.domain import LibraryRef


@dataclass(frozen=True)
class ReadRequest:
    """One photo to read.

    ``image_key`` is a ``BlobStore`` key, not bytes — the port stays ignorant
    of where or how images are stored (that is ``BlobStore``'s job, D1), and a
    stub implementation for tests needs no blob store at all. The concrete
    adapter resolves the key to bytes itself.
    """

    capture_id: str
    image_key: str


@dataclass(frozen=True)
class ReadAlternative:
    """One ranked candidate for a claim's OCR text — the Reader-side twin of
    ``app.domain.read.Alternative`` (P2.7). Kept separate from its domain
    counterpart for the same reason ``ReadClaim`` is kept separate from
    ``Claim``: this port must not import ``app.domain.read`` beyond
    ``LibraryRef``, so the concrete adapter that DOES have ``booksnap.match``
    in scope has somewhere to put ``explain()``'s output without minting a
    domain object itself."""

    title: str
    author: str = ""
    score: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class ReadClaim:
    """What the Reader hands back for one detected spine.

    Deliberately NOT ``app.domain.read.Claim`` — that type has an ``id``, and
    minting ids is the caller's job (``IdGen``), not the engine's. The caller
    (the read job, ``app.api.routers.reads``) maps one of these onto a domain
    ``Claim`` per spine, generating the id and — for ``crop`` — writing the
    bytes into ``BlobStore`` to get a ``crop_key``.
    """

    spine_id: str
    capture_id: str
    text: str = ""
    title: str = ""
    author: str = ""
    tier: str = "unmatched"      # "auto" | "review" | "unmatched"
    score: float = 0.0
    catalog_id: str | None = None
    crop: bytes | None = None    # the spine crop, if the engine produced one
    box: tuple[int, int, int, int] | None = None
    # Ranked runners-up from `booksnap.match.explain()`, powering the review
    # UI's "why?" (P2.7). Computed against the SAME catalog query text already
    # used to produce this claim's match, so a disk-cached catalog (NLICatalog)
    # answers it for free — never a second live lookup. Empty when the engine
    # has no `explain()` (a structured fallback provider) or no OCR text at all.
    alternatives: tuple[ReadAlternative, ...] = ()


class Reader(Protocol):
    """Turns photographs of a shelf into claims.

    Implemented by ``BooksnapReader`` (over ``booksnap.Pipeline``) in
    production, and by a stub in every test that needs one — H4 ring 3 never
    invokes the real engine.
    """

    def read(
        self,
        library: LibraryRef,
        requests: Sequence[ReadRequest],
        *,
        mode: str,
        progress: Callable[[dict], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[ReadClaim]:
        """Read every request. ``mode`` is passed straight through to the
        engine — modes are the engine's own (plan P2.4), not redefined here.

        ``should_stop``, if given, is polled between images/spines — the same
        cooperative-stop shape as ``Pipeline.run``'s ``should_stop`` — and the
        claims already produced are RETURNED, not discarded, when it fires.
        """

    def unavailable(self, mode: str) -> str | None:
        """Why ``mode`` cannot run right now, or ``None`` if it can.

        A preflight, asked at the HTTP door before a read is accepted. It
        exists because a read runs in a WORKER THREAD: a missing
        ``ANTHROPIC_API_KEY`` discovered there surfaces as a ``failed`` read
        with a traceback in a log nobody is watching, minutes after the click,
        and the owner is left guessing whether the photo or the shelf was the
        problem. The tuning server learned the same lesson
        (``booksnap/server.py:start_run`` rejects a keyless mode up front).

        **On the port rather than in the route** — the route must not know
        which credential which engine needs, or it is coupled to whichever
        adapter happens to be bound. A stub reader answers ``None`` for every
        mode and needs no environment at all, which is exactly why the API ring
        stays offline.

        The returned string is shown to the user, so it says what to DO ("set
        X, then restart"), not merely what is absent.
        """

    def code_version(self) -> dict:
        """Git sha + dirty flag, or whatever a stub wants to report — the
        same idea as ``booksnap/server.py``'s run archive, so a Read can be
        interpreted against the code that produced it later."""

    def config_snapshot(self) -> dict:
        """Every tunable, as it stood for this read — the experiment
        variable, same reasoning as the tuning server's per-run config
        snapshot."""
