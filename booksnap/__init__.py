# -*- coding: utf-8 -*-
"""booksnap — deterministic Hebrew bookshelf cataloguer.

Pipeline: segment shelf photos into spines -> line-based Tesseract OCR ->
token-gated fuzzy match against a catalog -> optional stronger-engine fallback.
"""
from .pipeline import Pipeline
from .catalog import LocalCatalog, Catalog, CatalogEntry, normalize
from .nli_catalog import NLICatalog
from .fallback import (Fallback, NullFallback, FallbackResult,
                       GoogleVisionFallback, ClaudeVisionFallback)
from .config import CONFIG, Config

__all__ = ["Pipeline", "LocalCatalog", "NLICatalog", "Catalog", "CatalogEntry",
           "normalize", "Fallback", "NullFallback", "FallbackResult",
           "GoogleVisionFallback", "ClaudeVisionFallback", "CONFIG", "Config"]
