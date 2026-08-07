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

    def code_version(self) -> dict:
        """Git sha + dirty flag, or whatever a stub wants to report — the
        same idea as ``booksnap/server.py``'s run archive, so a Read can be
        interpreted against the code that produced it later."""

    def config_snapshot(self) -> dict:
        """Every tunable, as it stood for this read — the experiment
        variable, same reasoning as the tuning server's per-run config
        snapshot."""
