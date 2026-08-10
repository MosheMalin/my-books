# -*- coding: utf-8 -*-
"""The SYSTEM-admin service — cross-tenant, read-only, separate from `/api/v1`.

⚠⚠ **This is a different authorization axis, not a bigger role.** Everything
under ``app/api`` resolves a library through
:func:`app.api.deps.current_library`, which answers from the caller's
MEMBERSHIPS — by design, and §4.2's "a foreign record reads as ABSENT" depends
on it. A system administrator is not a member of the tenants they oversee, so
there is no membership for that resolver to find and no role that could
legitimately be added to :class:`app.domain.tenancy.Role` to express it: a Role
says who you are *within one library*, and putting ``SYSTEM_ADMIN`` in that
enum would make every membership row a place someone could grant themselves
the world.

So this is a second application (D2's "strangle, don't refactor" shape, the
same way the tuning server and the product coexist), with its own port, its
own credential, and its own prefix ``/api/staff/v1``. Nothing here is reachable
from the product API and nothing in the product API is weakened to serve it.

**Read-only, and enforced by not writing rather than by intention**: every
statement in :mod:`app.staff_api.queries` is a ``SELECT``, and the connection
deliberately does **not** call :func:`app.adapters.migrations.migrate`. The
second half matters more than it looks — CLAUDE.md records that merely
importing ``app.main`` advances the real database's schema, so a staff console
that opened the file the usual way would migrate the owner's data as a side
effect of being *looked at*.

Writes stay where they already are: an account-scoped act goes through
``/api/v1`` as the account, and member management does not exist yet in either
place (P4.1/P4.3).
"""
