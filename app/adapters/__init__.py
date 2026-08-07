# -*- coding: utf-8 -*-
"""Adapters: concrete implementations of the ports.

May import ``app.ports`` and ``app.domain``, plus whatever driver/framework it
takes to do the job. May NOT be imported by ``app.api`` — only the composition
root (``app/main.py``) wires an adapter to a port.
"""
