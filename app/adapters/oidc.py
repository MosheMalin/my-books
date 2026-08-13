# -*- coding: utf-8 -*-
"""Google and Apple, over stdlib HTTP (P4.2).

No provider SDK and no OAuth framework: the authorization-code flow is
three redirects and one POST, and a library here would hide the exact
decisions the domain module argues about (which claims are checked, which
are not, and why). `urllib` is what `booksnap`'s NLI catalogue already
uses for the same reason.

Two differences between the providers, both absorbed here so the routes
see one interface:

  - **the client secret.** Google's is a string. Apple's is a JWT the
    client SIGNS with an ES256 key downloaded once from their developer
    console — so `AppleProvider` mints one per exchange, short-lived;
  - **the response mode.** Apple posts the callback cross-site, which is
    why the flow's state lives server-side (see `app/domain/oauth.py`).

⚠ The ID Token's signature is deliberately NOT verified, and that is
sound ONLY because of how it arrives — see `app/domain/oauth.py`'s module
note for the OIDC Core §3.1.3.7 argument. The claims are still checked,
all of them, by the domain's one checklist.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from app.domain.oauth import (
    APPLE,
    GOOGLE,
    OAuthError,
    Provider,
    VerifiedIdentity,
    identity_from_claims,
)

#: Long enough for a slow mobile network, short enough that a stuck
#: provider cannot pin a request thread for a minute.
TIMEOUT = 15


class OidcProvider:
    """Implements ``app.ports.oauth.IdentityProvider`` for Google."""

    provider: Provider = GOOGLE

    def __init__(self, *, client_id: str, client_secret: str,
                 redirect_uri: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    @property
    def key(self) -> str:
        return self.provider.key

    # --- front channel ---------------------------------------------------

    def authorize_url(self, *, state: str, nonce: str, challenge: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.provider.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if self.provider.form_post:
            # Apple will not release the email scope without it.
            params["response_mode"] = "form_post"
        return f"{self.provider.authorize_endpoint}?{urllib.parse.urlencode(params)}"

    # --- back channel ----------------------------------------------------

    def _client_secret(self) -> str:
        return self.client_secret

    def exchange(self, *, code: str, verifier: str,
                 nonce: str) -> VerifiedIdentity:
        body = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self._client_secret(),
            "code_verifier": verifier,
        }).encode("ascii")
        request = urllib.request.Request(
            self.provider.token_endpoint, data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
                payload = json.loads(answer.read().decode("utf-8"))
        except Exception as exc:                      # network, HTTP, JSON
            # The provider's own error text can carry the code we sent;
            # it goes in the log, never to the caller.
            raise OAuthError(f"the token exchange failed: {exc}") from exc

        token = payload.get("id_token")
        if not token:
            raise OAuthError("the provider returned no id_token")
        return identity_from_claims(_claims(token), self.provider,
                                    self.client_id, nonce)


class AppleProvider(OidcProvider):
    """Apple, whose client secret is a JWT we sign per exchange."""

    provider: Provider = APPLE

    def __init__(self, *, client_id: str, team_id: str, key_id: str,
                 private_key: str, redirect_uri: str) -> None:
        super().__init__(client_id=client_id, client_secret="",
                         redirect_uri=redirect_uri)
        self.team_id = team_id
        self.key_id = key_id
        self.private_key = private_key

    def _client_secret(self) -> str:
        """A short-lived ES256 JWT, per Apple's spec.

        Signed here with `cryptography` (already a dependency) rather than
        adding a JWT library for one token: the structure is two base64
        segments and a signature, and the alternative is a dependency
        whose only use is this function.
        """
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, utils

        now = int(time.time())
        header = {"alg": "ES256", "kid": self.key_id}
        payload = {
            "iss": self.team_id,
            "iat": now,
            "exp": now + 300,          # minutes: it is used once, right now
            "aud": self.provider.issuer,
            "sub": self.client_id,
        }
        signing_input = b".".join(
            (_b64(json.dumps(header, separators=(",", ":")).encode()),
             _b64(json.dumps(payload, separators=(",", ":")).encode()))
        )
        key = serialization.load_pem_private_key(
            self.private_key.encode("utf-8"), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise OAuthError("Apple's sign-in key must be an EC private key")
        der = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        # JOSE wants the raw R||S pair, not the DER structure OpenSSL emits.
        r, s = utils.decode_dss_signature(der)
        raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return b".".join((signing_input, _b64(raw))).decode("ascii")


def _b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _claims(id_token: str) -> dict:
    """The ID Token's payload, decoded but NOT signature-verified.

    See `app/domain/oauth.py` for why that is sound here and nowhere
    else. The `exp` check stays, because a provider replaying its own
    stale token is a different question from who signed it.
    """
    try:
        _header, payload, _signature = id_token.split(".")
        padded = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except Exception as exc:
        raise OAuthError("the id_token is not a readable JWT") from exc

    expiry = claims.get("exp")
    if not isinstance(expiry, (int, float)):
        raise OAuthError("the id_token has no expiry")
    if datetime.now(timezone.utc).timestamp() > float(expiry):
        raise OAuthError("the id_token has expired")
    return claims
