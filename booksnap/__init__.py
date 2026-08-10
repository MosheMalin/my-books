# -*- coding: utf-8 -*-
"""booksnap — deterministic Hebrew bookshelf cataloguer.

Pipeline: segment shelf photos into spines -> line-based Tesseract OCR ->
token-gated fuzzy match against a catalog -> optional stronger-engine fallback.

⚠ **Every name here is resolved lazily (PEP 562), and that is load-bearing,
not tidiness.** This module used to import ``.pipeline`` eagerly, which pulls
in ``segment`` -> ``scipy.signal`` + ``cv2``: **6.4 seconds**, paid by anything
that touched the package at all. `app/domain/*` is allowed to import
``booksnap.catalog`` and nothing else from the core precisely so the product's
domain rules stay "milliseconds, no I/O" (CLAUDE.md, the layering rules) — but
`import booksnap.catalog` runs this file first, so every domain module, every
store, and the product server's own startup were paying for the whole CV stack
to read one ``normalize()``. The layering rule was honest and the package
defeated it.

Nothing about the public surface changes: ``from booksnap import Pipeline``,
``import booksnap; booksnap.CONFIG`` and ``from booksnap import *`` all still
work. The import simply happens on first use.
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

# name -> the submodule that defines it
_EXPORTS = {
    "Pipeline": "pipeline",
    "LocalCatalog": "catalog",
    "Catalog": "catalog",
    "CatalogEntry": "catalog",
    "normalize": "catalog",
    "NLICatalog": "nli_catalog",
    "Fallback": "fallback",
    "NullFallback": "fallback",
    "FallbackResult": "fallback",
    "GoogleVisionFallback": "fallback",
    "ClaudeVisionFallback": "fallback",
    "CONFIG": "config",
    "Config": "config",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    """Resolve an export, or a submodule, on first touch."""
    where = _EXPORTS.get(name)
    if where is not None:
        return getattr(importlib.import_module(f".{where}", __name__), name)
    try:
        # `booksnap.match` after a bare `import booksnap` used to work by
        # accident, because pipeline had already imported it. Keep that.
        return importlib.import_module(f".{name}", __name__)
    except ModuleNotFoundError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}") from None


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()))


if TYPE_CHECKING:                            # static analysis sees the real names
    from .catalog import Catalog, CatalogEntry, LocalCatalog, normalize
    from .config import CONFIG, Config
    from .fallback import (ClaudeVisionFallback, Fallback, FallbackResult,
                           GoogleVisionFallback, NullFallback)
    from .nli_catalog import NLICatalog
    from .pipeline import Pipeline
