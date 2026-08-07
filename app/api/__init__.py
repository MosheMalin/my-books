# -*- coding: utf-8 -*-
"""HTTP layer: FastAPI routers under /api/v1 plus their DTOs.

THIN by rule (H3): no domain rules live here, and no adapter is imported here
— routes depend on ports, and ``app/main.py`` binds the implementations.
DTOs are separate types from domain entities so a model change is not
automatically a breaking API change.
"""
