# -*- coding: utf-8 -*-
"""A ``TestClient`` that reuses ONE event-loop thread for the whole process.

Why this exists — measured, not guessed. ``starlette.testclient.TestClient``
spins up an anyio *blocking portal* (a background thread running its own
asyncio event loop) on ``__enter__`` and tears it down on ``__exit__``. That
costs ~110ms, and ``tests/test_api.py`` enters one 153 times, so roughly
**17 of its 38 seconds were spent starting and stopping threads**, not testing
anything. The portal is a transport detail; nothing in this repo asserts a
property of it.

The substitution is deliberately as small as it can be: we do NOT reimplement
``TestClient.__enter__``. We swap what ``anyio.from_thread.start_blocking_portal``
returns *for the duration of that one call*, so starlette keeps doing its own
lifespan startup/shutdown, its own memory streams, its own exit stack. If a
future starlette rearranges those internals this file keeps working; it only
breaks if starlette stops using a blocking portal at all, which would fail
loudly (``AttributeError``) rather than silently.

⚠ Safe because tests run SEQUENTIALLY inside a process. ``tests/run_all.py``
parallelises across processes, never threads, precisely so shared per-process
state like this portal — and the env-var juggling in ``test_reader_wiring`` —
stays single-threaded. Do not run two tests concurrently in one interpreter.
"""
from __future__ import annotations

import atexit
import contextlib
from typing import Any

import anyio.from_thread
from starlette.testclient import TestClient as _StarletteTestClient

_portal = None
_portal_cm = None
# Bound at import, before anything can patch the name — otherwise the patch
# below calls back into this function and recurses.
_start_blocking_portal = anyio.from_thread.start_blocking_portal


def shared_portal():
    """The one portal, started on first use and closed at interpreter exit."""
    global _portal, _portal_cm
    if _portal is None:
        _portal_cm = _start_blocking_portal(backend="asyncio")
        _portal = _portal_cm.__enter__()
        atexit.register(_close_portal)
    return _portal


def _close_portal() -> None:
    global _portal, _portal_cm
    if _portal_cm is not None:
        cm, _portal_cm, _portal = _portal_cm, None, None
        with contextlib.suppress(Exception):
            cm.__exit__(None, None, None)


@contextlib.contextmanager
def _lend(portal):
    """Hand out the shared portal and, on exit, leave it running."""
    yield portal


class TestClient(_StarletteTestClient):
    """Drop-in ``TestClient`` whose portal outlives the client.

    Same public behaviour: ``with TestClient(app) as c`` still runs the app's
    lifespan, and a client used without ``with`` still works (a bare request
    borrows the shared portal instead of building a throwaway one, which is
    where the *worst* of the cost was — that path paid the ~110ms per REQUEST,
    not per test).
    """

    def __enter__(self):
        real = anyio.from_thread.start_blocking_portal
        anyio.from_thread.start_blocking_portal = (
            lambda *a, **kw: _lend(shared_portal()))
        try:
            return super().__enter__()
        finally:
            anyio.from_thread.start_blocking_portal = real

    @contextlib.contextmanager
    def _portal_factory(self) -> Any:
        yield self.portal if self.portal is not None else shared_portal()
