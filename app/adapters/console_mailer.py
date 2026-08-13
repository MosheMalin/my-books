# -*- coding: utf-8 -*-
"""The dev Mailer: the login link goes to the server log, not a mailbox.

Local development has no mail provider and needs none — the developer IS the
person signing in, and the server console is a mailbox they are already
reading. This adapter prints the full link, which is exactly the credential
the real adapter must never log; that inversion is the point of it being an
ADAPTER, chosen by the composition root, impossible to reach from a route
(the Mailer port's contract).

The production adapter arrives with P4.4, when the deployment knows its own
address and provider. Until then `app/main.py` binds this one.
"""
from __future__ import annotations

import sys

#: Where the emailed link lands in the CLIENT: the login screen reads the
#: token off its own hash route (P4.1b). One copy here — the production
#: adapter composes the same shape from its configured public base URL.
LINK_PATH = "/#/login?token="


class ConsoleMailer:
    """Implements ``app.ports.auth.Mailer`` by printing to stderr."""

    def __init__(self, base_url: str = "http://localhost:5173") -> None:
        # The DEV base: Vite's client, which proxies /api here. Configured
        # by the composition root, never read from the environment in here.
        self.base_url = base_url.rstrip("/")

    def send_login_link(self, email: str, token: str) -> None:
        link = f"{self.base_url}{LINK_PATH}{token}"
        # stderr, like uvicorn's own log lines, so it is visible in the
        # terminal that started the server and in preview_logs.
        print(
            f"[booksnap] sign-in link for {email}:\n"
            f"[booksnap]   {link}\n"
            f"[booksnap] (dev mailer — a real mailbox arrives with P4.4)",
            file=sys.stderr,
            flush=True,
        )
