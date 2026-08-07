# -*- coding: utf-8 -*-
"""Request-scoped dependencies.

H2, verbatim: *there is exactly one function resolving principal -> library*.
That function is :func:`current_library`, and ``tests/test_api.py`` asserts
that every ``/api/v1`` route has it somewhere in its dependency chain — a new
route that reaches for "the" library instead fails the suite rather than
quietly working until pillar 3.

There is also **no module-level mutable state** here (H2, §1.3). The provider
is bound per-application via ``dependency_overrides`` in ``create_app``, not
stashed in a module global the way ``booksnap/server.py``'s job dict is.
"""
from __future__ import annotations

from fastapi import Depends

from app.domain import LibraryRef
from app.ports import Clock, IdGen, Principal
from app.ports.store import BookStore


def get_principal() -> Principal:
    """Placeholder provider, replaced per-app by ``create_app``.

    Raising here rather than returning a default is deliberate: an app that
    forgot to bind an identity adapter must fail loudly on the first request,
    not silently serve someone else's library.
    """
    raise RuntimeError(
        "no Principal provider bound; build the app via app.api.app.create_app"
    )


def current_library(principal: Principal = Depends(get_principal)) -> LibraryRef:
    """The single principal -> library resolution point (H2)."""
    return principal.library


# The remaining ports, same pattern as get_principal: placeholders that FAIL
# rather than defaulting, replaced per-application in create_app. The api
# layer names the PORT; app/main.py decides which adapter satisfies it (H1).

def get_book_store() -> BookStore:
    raise RuntimeError("no BookStore bound; build the app via create_app")


def get_clock() -> Clock:
    raise RuntimeError("no Clock bound; build the app via create_app")


def get_id_gen() -> IdGen:
    raise RuntimeError("no IdGen bound; build the app via create_app")
