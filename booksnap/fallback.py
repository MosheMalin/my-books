# -*- coding: utf-8 -*-
"""Stage 4 — fallback (pluggable).

When deterministic OCR+match fails or is low-confidence, a spine crop can be
sent to a stronger engine. This module defines the seam only: a `Fallback`
protocol plus a no-op default. Concrete providers (Google Cloud Vision, Claude
vision) implement `read_spine()` and are injected at the orchestrator level, so
no provider or credential is baked into the core pipeline.
"""
from __future__ import annotations
from typing import Protocol, Optional
from dataclasses import dataclass


@dataclass
class FallbackResult:
    text: str = ""
    title: Optional[str] = None      # providers that return structured output
    author: Optional[str] = None
    provider: str = "none"
    raw: Optional[dict] = None


class Fallback(Protocol):
    def read_spine(self, crop_path: str) -> FallbackResult:
        """Read a single spine crop with a stronger engine."""
        ...


class NullFallback:
    """Default: does nothing. Keeps the pipeline fully deterministic/offline."""
    def read_spine(self, crop_path: str) -> FallbackResult:
        return FallbackResult(provider="none")


# --- Google Cloud Vision fallback -------------------------------------------
class GoogleVisionFallback:
    """Fallback via Google Cloud Vision `DOCUMENT_TEXT_DETECTION`.

    Deterministic, excellent Hebrew, ~$1.50/1000 images (first 1000/mo free).
    Returns raw text; feed it back through match.match_candidate().

    Auth & safety: this class never handles your key material directly. Cloud
    Vision does NOT support simple API keys; the client uses Application
    Default Credentials, normally established once with
    `gcloud auth application-default login` (no key file at all).
    GOOGLE_APPLICATION_CREDENTIALS is only consulted if you chose the
    downloaded service-account-key route. Nothing secret passes through
    booksnap code either way.

    Usage on the server:

        from google.cloud import vision
        from booksnap.fallback import GoogleVisionFallback
        fb = GoogleVisionFallback(vision.ImageAnnotatorClient())
        pipe = Pipeline(catalog=..., fallback=fb)
        records = pipe.run(images, use_fallback=True)

    `client` is injected so this stays unit-testable offline: any object with a
    `document_text_detection(image=...)` method returning an object exposing
    `.full_text_annotation.text` (and optional `.error.message`) works.
    """

    def __init__(self, client, image_ctor=None):
        self._client = client
        # google.cloud.vision.Image, injected so tests need no SDK installed
        self._image_ctor = image_ctor

    def read_spine(self, crop_path: str) -> "FallbackResult":
        with open(crop_path, "rb") as f:
            content = f.read()
        image = self._image_ctor(content=content) if self._image_ctor else {"content": content}
        resp = self._client.document_text_detection(image=image)
        err = getattr(getattr(resp, "error", None), "message", "")
        if err:
            return FallbackResult(provider="google_vision", raw={"error": err})
        text = getattr(getattr(resp, "full_text_annotation", None), "text", "") or ""
        # spines are vertical; Vision returns lines top-to-bottom already, but
        # collapse whitespace so the matcher sees a clean token stream
        text = " ".join(text.split())
        return FallbackResult(text=text, provider="google_vision")


# --- Claude vision fallback (structured output) -----------------------------
class ClaudeVisionFallback:
    """Fallback via Claude vision returning structured {title, author} directly,
    so no separate matching step is needed for what it resolves.

    `send` is injected: a callable(image_bytes: bytes) -> dict with keys
    'title' and 'author' (your app wraps the Anthropic client + prompt + JSON
    parsing). Kept abstract here so booksnap carries no SDK/credential coupling.
    """

    def __init__(self, send):
        self._send = send

    def read_spine(self, crop_path: str) -> "FallbackResult":
        with open(crop_path, "rb") as f:
            content = f.read()
        try:
            data = self._send(content) or {}
        except Exception as e:
            return FallbackResult(provider="claude_vision", raw={"error": str(e)})
        return FallbackResult(title=(data.get("title") or None),
                              author=(data.get("author") or None),
                              provider="claude_vision", raw=data)
