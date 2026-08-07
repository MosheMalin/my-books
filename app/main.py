# -*- coding: utf-8 -*-
"""Composition root — the ONE module allowed to import across every layer.

``tests/test_layering.py`` names this file as its single exemption. Everything
else obeys the one-way rule; wiring has to happen somewhere, and confining it
to one file is what keeps "who constructs the adapters?" from leaking back
into the api layer.

Run it with::

    uvicorn app.main:app --port 8757

Port 8757 by convention, one above the tuning server's 8756, so both can run
side by side through pillars 1-2 (Risk 1 in the plan).
"""
from __future__ import annotations

from pathlib import Path

from app.adapters.dev_identity import DevPrincipal
from app.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = REPO_ROOT / "app" / "web" / "dist"


def build() -> object:
    """Bind adapters to ports and return the ASGI app."""
    # One instance is correct today (a hardcoded dev identity is immutable and
    # request-independent). P4.1 replaces this with a per-request session read;
    # the signature does not change, which is the point of the stub.
    principal = DevPrincipal()
    return create_app(principal_provider=lambda: principal, web_dist=WEB_DIST)


app = build()
