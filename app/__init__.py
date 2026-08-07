# -*- coding: utf-8 -*-
"""booksnap product application.

Deliberately a SEPARATE package from ``booksnap/`` (the recognition core) and
from ``booksnap/server.py`` (the accuracy-tuning surface). See
``planning/IMPLEMENTATION_PLAN.md`` H1/D2: strangle, don't refactor — the
tuning server keeps ``/api/*`` and its single-file vanilla UI; the product
speaks ``/api/v1/*`` and is served from ``app/web/``.

Layering, enforced by ``tests/test_layering.py``:

    domain  <- ports <- adapters <- api          (arrows point down only)
    app/main.py is the single composition root and may import everything.
"""

__version__ = "0.1.0"
API_VERSION = "v1"
API_PREFIX = "/api/v1"
