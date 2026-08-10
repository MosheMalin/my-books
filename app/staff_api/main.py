# -*- coding: utf-8 -*-
"""Composition root for the staff service.

⚠ A SECOND composition root, and deliberately NOT in ``COMPOSITION_ROOTS``.
That set is kept one element long precisely so a second entry is "a visible,
argued-about diff rather than an accident". The argument, made and now
enforced:

  the layering rule the exemption protects is ``app/api -X-> app/adapters``,
  and it is not weakened here, because nothing in this service is under
  ``app/api``. This file wires ``app.staff_api.queries`` — a read model that
  imports no adapter at all — so the exemption is not needed.

``tests/test_layering.py:test_the_staff_service_binds_no_adapter_and_so_needs_
no_exemption`` is what keeps that argument TRUE rather than merely written
down: the day this service binds a real adapter, that test fails and whoever
made it bind one adds this file to the list. Which is the discussion the list
exists to force.

⚠ It also does NOT import ``app.main``. That is not tidiness: importing the
product's composition root opens ``work/product.db`` and runs ``migrate()`` at
import time, so a read-only console would upgrade the owner's schema simply by
starting. Resolving the path here from the same environment variables is eight
duplicated lines and the right trade — the same call, for the same reason,
that `app/main.py` makes about the tuning server's ``_load_dotenv``.

Run it::

    uvicorn app.staff_api.main:app --host 0.0.0.0 --port 8758
"""
from __future__ import annotations

import os
from pathlib import Path

from app.staff_api.app import create_app
from app.staff_api.queries import StaffQueries


def _load_dotenv() -> None:
    """Read ``.env`` if present. A COPY of the product's, not an import.

    The product needed its own copy of the tuning server's for exactly this
    reason and recorded why; a third service reaching into a second one's
    composition root to borrow eight lines is the coupling H1 exists to stop.
    """
    path = Path(__file__).resolve().parents[2] / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def database_path() -> Path:
    """Where the product keeps its database — resolved exactly as it does.

    ``BOOKSNAP_DB`` wins; otherwise ``<BOOKSNAP_WORK>/product.db``, defaulting
    to ``work/``. If these ever diverge from `app/main.py` the console reports
    an empty system, which is the confusing failure this function exists to
    avoid — so it is one function with the rule written down, not an inline
    ``os.environ.get`` at the call site.
    """
    explicit = os.environ.get("BOOKSNAP_DB")
    if explicit:
        return Path(explicit)
    work = os.environ.get("BOOKSNAP_WORK")
    root = Path(work) if work else Path(__file__).resolve().parents[2] / "work"
    return root / "product.db"


def build() -> object:
    _load_dotenv()
    return create_app(StaffQueries(database_path()))


app = build()
