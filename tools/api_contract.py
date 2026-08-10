# -*- coding: utf-8 -*-
"""The API contract check (D3): server DTOs -> OpenAPI -> generated TS types.

FOUR artefacts are committed, in two pairs — one pair per SERVICE — and all
four must be reproducible from the code:

  the product API, ``/api/v1``, which BOTH clients call:
  1. ``app/api/openapi.json``                — what that server publishes;
  2. ``app/ui/src/api/schema.d.ts``          — its types, in the shared client
                                               package because both call it.

  the staff API, ``/api/staff/v1``, which only the console calls:
  3. ``app/staff_api/openapi.json``          — what that server publishes;
  4. ``app/admin/src/api/staff-schema.d.ts`` — its types, in the console,
                                               because nothing else speaks it.

⚠ The staff pair is new, and it retires a real duplication: the console's
``api/staff.ts`` MIRRORED ``app/staff_api/app.py``'s DTOs by hand — both files
said so and asked the reader to keep them in step, under a constraint that
forbade touching this tool. With that gone, a renamed staff DTO is a compile
error in the console instead of an ``undefined`` in a table.

Keeping them in git (rather than generating at build time) is what turns a DTO
rename into a *reviewable diff* and a client *compile* error, instead of a
runtime surprise noticed by a user. This script is the gate that stops the two
from drifting apart.

Usage::

    python tools/api_contract.py --write    # regenerate both, after a DTO change
    python tools/api_contract.py --check    # fail on drift (pre-commit)

The TypeScript half self-skips when ``app/web/node_modules`` is absent, the
same way ``tools/spotcheck.py`` skips on a machine without the run data — a
gate that can't run must not be a gate that blocks.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

OPENAPI_PATH = REPO_ROOT / "app" / "api" / "openapi.json"
WEB_DIR = REPO_ROOT / "app" / "web"
ADMIN_DIR = REPO_ROOT / "app" / "admin"
STAFF_OPENAPI_PATH = REPO_ROOT / "app" / "staff_api" / "openapi.json"
STAFF_TS_PATH = ADMIN_DIR / "src" / "api" / "staff-schema.d.ts"
# ⚠ The generated types live in the SHARED client package, not in either
# app. Both clients call ``/api/v1`` — the console writes through it even
# though it READS from the staff service — so a copy per app would be a second
# generated artefact this check does not police, and it would drift in
# silence. One file, two consumers, one compile error when a DTO is renamed.
TS_PATH = REPO_ROOT / "app" / "ui" / "src" / "api" / "schema.d.ts"


def build_schema() -> str:
    """Serialise the live OpenAPI document, deterministically.

    Sorted keys and a fixed indent so the committed file diffs only when the
    API actually changes — dict ordering must never author a diff.
    """
    from app.main import app  # composition root: what the server really serves

    return json.dumps(app.openapi(), indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def build_staff_schema() -> str:
    """The staff service's OpenAPI, built WITHOUT touching the database.

    ⚠ ``app/staff_api/main.py`` resolves the real ``work/product.db`` and
    ``StaffQueries.__init__`` opens it to ``self_check()`` — so importing that
    composition root just to read a schema would make generating a contract
    depend on the owner's data being present and intact. ``create_app`` takes
    its read model injected (the same reason ``app.api.app.create_app`` takes
    its ports), so a stand-in is enough here: no route is ever CALLED, only
    described.
    """
    from typing import cast

    from app.staff_api.app import create_app
    from app.staff_api.queries import StaffQueries

    app = create_app(cast(StaffQueries, object()))
    return json.dumps(app.openapi(), indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def _npx() -> str | None:
    if not (WEB_DIR / "node_modules").is_dir():
        return None
    return shutil.which("npx")


def build_ts(into: Path, source: Path = OPENAPI_PATH) -> None:
    """Run openapi-typescript over a committed schema.

    ⚠ Always from ``app/web``, whichever schema is being converted: that is
    the only package carrying the ``openapi-typescript`` devDependency, and a
    second copy of a tool this repo runs from one place would be exactly the
    duplication the OUTPUT path already settles. Where the generator RUNS says
    nothing about who owns the contract.
    """
    npx = _npx()
    assert npx, "no npx"
    subprocess.run(
        [npx, "--no-install", "openapi-typescript",
         str(source), "-o", str(into)],
        cwd=str(WEB_DIR), check=True,
    )


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def cmd_write() -> int:
    for path, builder in ((OPENAPI_PATH, build_schema),
                          (STAFF_OPENAPI_PATH, build_staff_schema)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(builder(), encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    if _npx():
        for source, into in ((OPENAPI_PATH, TS_PATH),
                             (STAFF_OPENAPI_PATH, STAFF_TS_PATH)):
            into.parent.mkdir(parents=True, exist_ok=True)
            build_ts(into, source)
            print(f"wrote {into.relative_to(REPO_ROOT)}")
    else:
        print("skip: app/web/node_modules missing — TS types not regenerated "
              "(run `npm install` in app/web)")
    return 0


def cmd_check() -> int:
    # ⚠ Both services are checked, and every stale artefact is REPORTED
    # before returning — stopping at the first hides the rest and turns one
    # regenerate-and-rerun cycle into several. Same property `tools/check.py`
    # has, for the same reason.
    stale: list[Path] = []
    for path, builder in ((OPENAPI_PATH, build_schema),
                          (STAFF_OPENAPI_PATH, build_staff_schema)):
        if builder() != _read(path):
            stale.append(path)
            print(f"CONTRACT DRIFT: {path.relative_to(REPO_ROOT)} is stale.")
            print("  Its DTOs or routes changed without regenerating the "
                  "published schema.")

    if not _npx():
        if stale:
            print("Fix with: python tools/api_contract.py --write")
            return 1
        print("contract: both OpenAPI documents in step; TS check skipped "
              "(no app/web/node_modules on this machine)")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        pairs = ((OPENAPI_PATH, TS_PATH), (STAFF_OPENAPI_PATH, STAFF_TS_PATH))
        for i, (source, committed) in enumerate(pairs):
            # Generated from the COMMITTED schema on purpose: this half asks
            # "do the client's types match what is published", which stays a
            # real and separate question even when the schema itself is stale.
            out = Path(tmp) / f"schema{i}.d.ts"
            build_ts(out, source)
            if _read(out) != _read(committed):
                stale.append(committed)
                print(f"CONTRACT DRIFT: {committed.relative_to(REPO_ROOT)} "
                      "is stale.")
                print("  The client's types no longer match the schema.")

    if stale:
        print("Fix with:")
        print("    python tools/api_contract.py --write")
        print("    git add " + " ".join(
            str(p.relative_to(REPO_ROOT)) for p in stale))
        return 1

    print("contract: both services' schemas and generated TS types are in step")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true",
                   help="regenerate the committed schema and TS types")
    g.add_argument("--check", action="store_true",
                   help="fail if either committed artefact is stale")
    args = ap.parse_args(argv)
    return cmd_write() if args.write else cmd_check()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
