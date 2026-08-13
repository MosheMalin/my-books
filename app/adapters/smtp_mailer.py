# -*- coding: utf-8 -*-
"""The production Mailer: a sign-in link, over SMTP (P4.4).

Plain ``smtplib``, no dependency. The alternatives were provider SDKs, and
they buy nothing here: one message type, no templates, no tracking, and a
household's volume. What a provider DOES give is deliverability, which is a
matter of which SMTP host these credentials belong to — so that choice stays
in configuration rather than in code.

⚠ **Every value that reaches a header is checked for CR/LF.** An address is
user input (the sign-in route accepts any shape a mailbox could plausibly
have), and a newline inside one is SMTP header injection: a forged ``Bcc``
riding out under our credentials. P4.1a's security review measured exactly
that payload reaching the dev mailer, which is why the shape check exists at
the route — this is the second line, at the door where it would actually
become mail.

The token NEVER reaches a log here. That inversion is the whole reason the
dev adapter is a different class: `ConsoleMailer` exists to print the link,
this one exists to make sure nothing but the recipient sees it.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from app.adapters.console_mailer import LINK_PATH


class SmtpMailer:
    """Implements ``app.ports.auth.Mailer``."""

    #: A real mailbox — the login screen says nothing extra (contrast
    #: `ConsoleMailer.delivery`, which tells the developer to read the log).
    delivery = "mail"

    def __init__(self, *, host: str, port: int, username: str,
                 password: str, sender: str, base_url: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = _no_headers(sender, "sender")
        self.base_url = base_url.rstrip("/")

    def send_login_link(self, email: str, token: str) -> None:
        recipient = _no_headers(email, "recipient")
        link = f"{self.base_url}{LINK_PATH}{token}"

        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = "כניסה ל-booksnap"
        # Hebrew first, English under it — the product's own rule, and a
        # sign-in mail is the first thing a new member ever sees from it.
        message.set_content(
            f"קישור הכניסה שלך:\n\n{link}\n\n"
            f"הקישור תקף לרבע שעה וניתן לשימוש פעם אחת.\n"
            f"אם לא ביקשת אותו, אפשר להתעלם מההודעה.\n\n"
            f"---\n"
            f"Your sign-in link:\n\n{link}\n\n"
            f"It is valid for fifteen minutes and can be used once.\n"
            f"If you did not ask for it, you can ignore this message.\n"
        )

        # STARTTLS on the submission port: the credential and the link both
        # travel over the wire, and the link IS a credential for 15 minutes.
        context = ssl.create_default_context()
        with smtplib.SMTP(self.host, self.port, timeout=20) as server:
            server.starttls(context=context)
            if self.username:
                server.login(self.username, self.password)
            server.send_message(message)


def _no_headers(value: str, what: str) -> str:
    """Refuse CR/LF before it can become a header (see the module note)."""
    if any(c in value for c in "\r\n"):
        raise ValueError(f"the {what} address contains a line break")
    return value
