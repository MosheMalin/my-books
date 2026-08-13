# -*- coding: utf-8 -*-
"""The composition root's bootstrap, run as a real process (P4.1a).

`app.main` migrates whatever BOOKSNAP_DB names the moment it is imported,
so these tests never import it in-process — each spawns a python that
builds the app against a TEMP database and then asserts on the file left
behind. Slower than an import (one interpreter each) but honest about the
one thing under test: what starting the server does to a database.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _boot(db: Path, env_extra: dict[str, str]) -> None:
    env = os.environ.copy()
    env.update(
        BOOKSNAP_DB=str(db),
        BOOKSNAP_BLOBS=str(db.parent / "blobs"),
        BOOKSNAP_DEV_PRINCIPAL="dev-owner",
        BOOKSNAP_DEV_LIBRARY="dev-library",
    )
    env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr


def test_the_bootstrap_links_the_owner_address_to_the_existing_user():
    """The identity anchor (P4.1a's migration review). The owner's real
    user row predates email; the magic link resolves users BY email and by
    nothing else. While the dev bootstrap still exists it links the
    address from BOOKSNAP_OWNER_EMAIL — normalized, and only into a BLANK
    email: a row the redeem flow wrote is never overwritten."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "boot.db"
        _boot(db, {"BOOKSNAP_OWNER_EMAIL": " Owner@Example.COM "})
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute(
                "SELECT email FROM users WHERE id = 'dev-owner'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "the bootstrap did not create the dev user"
        assert row[0] == "owner@example.com", (
            "BOOKSNAP_OWNER_EMAIL did not reach the user row normalized"
        )

        # Second boot with a DIFFERENT address: the filled email stays —
        # one-way, like the library label the same function fills.
        _boot(db, {"BOOKSNAP_OWNER_EMAIL": "someone-else@example.com"})
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute(
                "SELECT email FROM users WHERE id = 'dev-owner'"
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == "owner@example.com", (
            "a later boot overwrote the linked address"
        )


def test_the_bootstrap_without_an_owner_email_leaves_the_row_blank():
    """No address, no invention — the same refusal as v12's blank labels.
    An invented address would be OUR string in the identity column that
    decides who owns 286 books."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "boot.db"
        _boot(db, {"BOOKSNAP_OWNER_EMAIL": ""})
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute(
                "SELECT email FROM users WHERE id = 'dev-owner'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None and row[0] is None
