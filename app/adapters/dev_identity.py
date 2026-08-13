# -*- coding: utf-8 -*-
"""System clock and id generation — the two ambient adapters.

⚠ ``DevPrincipal`` lived here until P4.1b and is deliberately GONE, not
disabled: identity comes from the session cookie
(``app.api.principal.session_principal``), and a flag that could restore a
hardcoded principal would be an authentication bypass wearing a dev badge.
Local development signs in like production does — the dev mailer prints the
link to the server log (``app.adapters.console_mailer``).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


class SystemClock:
    """Implements ``app.ports.Clock``."""

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


class UuidIdGen:
    """Implements ``app.ports.IdGen``."""

    def new_id(self) -> str:
        return uuid.uuid4().hex
