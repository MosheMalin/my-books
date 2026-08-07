# -*- coding: utf-8 -*-
"""The API contract check (D3): server DTOs -> OpenAPI -> generated TS types.

Two artefacts are committed, and both must be reproducible from the code:

  1. ``app/api/openapi.json``          — what the server publishes;
  2. ``app/web/src/api/schema.d.ts``   — the TypeScript types generated from it.

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
TS_PATH = WEB_DIR / "src" / "api" / "schema.d.ts"


def build_schema() -> str:
    """Serialise the live OpenAPI document, deterministically.

    Sorted keys and a fixed indent so the committed file diffs only when the
    API actually changes — dict ordering must never author a diff.
    """
    from app.main import app  # composition root: what the server really serves

    return json.dumps(app.openapi(), indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def _npx() -> str | None:
    if not (WEB_DIR / "node_modules").is_dir():
        return None
    return shutil.which("npx")


def build_ts(into: Path) -> None:
    """Run openapi-typescript over the committed schema."""
    npx = _npx()
    assert npx, "no npx"
    subprocess.run(
        [npx, "--no-install", "openapi-typescript",
         str(OPENAPI_PATH), "-o", str(into)],
        cwd=str(WEB_DIR), check=True,
    )


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def cmd_write() -> int:
    OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPENAPI_PATH.write_text(build_schema(), encoding="utf-8")
    print(f"wrote {OPENAPI_PATH.relative_to(REPO_ROOT)}")
    if _npx():
        TS_PATH.parent.mkdir(parents=True, exist_ok=True)
        build_ts(TS_PATH)
        print(f"wrote {TS_PATH.relative_to(REPO_ROOT)}")
    else:
        print("skip: app/web/node_modules missing — TS types not regenerated "
              "(run `npm install` in app/web)")
    return 0


def cmd_check() -> int:
    live = build_schema()
    committed = _read(OPENAPI_PATH)
    if live != committed:
        print("CONTRACT DRIFT: app/api/openapi.json is stale.")
        print("The API's DTOs or routes changed without regenerating the "
              "published schema. Fix with:")
        print("    python tools/api_contract.py --write")
        print("    git add app/api/openapi.json app/web/src/api/schema.d.ts")
        return 1

    if not _npx():
        print("contract: OpenAPI in step; TS check skipped "
              "(no app/web/node_modules on this machine)")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "schema.d.ts"
        build_ts(out)
        if _read(out) != _read(TS_PATH):
            print("CONTRACT DRIFT: app/web/src/api/schema.d.ts is stale.")
            print("The client's types no longer match the schema. Fix with:")
            print("    python tools/api_contract.py --write")
            return 1

    print("contract: OpenAPI and generated TS types are both in step")
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
