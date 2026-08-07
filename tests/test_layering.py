# -*- coding: utf-8 -*-
"""H1 — layering, enforced by an AST walk over imports rather than by intent.

The rule (IMPLEMENTATION_PLAN §2 H1) is that arrows point down only::

    booksnap/     recognition core. PURE. never imports app/.
    app/domain/   entities + rules. no framework, no driver, no other app layer.
    app/ports/    Protocols. may import domain. nothing else from app.
    app/adapters/ implementations. may import ports + domain + drivers.
    app/api/      FastAPI + DTOs. may import ports + domain. NOT adapters.
    app/main.py   the composition root — the single exemption, imports anything.

The most important line is the first one: the accuracy work and the product
work run on separate branches against the same tree, and this test is what
guarantees they cannot collide. The second most important is
``app/api/ -X-> app/adapters/``, because that is the one a hurried commit
breaks, and once broken the datastore decision (D1) stops being reversible.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# The single file allowed to cross layers. Kept as a set so adding a second
# one is a visible, argued-about diff rather than an accident.
COMPOSITION_ROOTS = {"app/main.py"}

# Third-party names a pure layer must not touch. Frameworks and drivers only —
# stdlib is fine (domain rules legitimately use dataclasses, datetime, re).
FRAMEWORKS = {
    "fastapi", "starlette", "uvicorn", "pydantic", "httpx", "requests",
    "flask", "django",
}
DRIVERS = {
    "sqlite3", "psycopg", "psycopg2", "sqlalchemy", "redis", "boto3",
    "google", "anthropic", "cv2", "pytesseract",
}


def _module_path(path: Path) -> str:
    """Repo-relative posix path, e.g. 'app/api/deps.py'."""
    return path.relative_to(REPO_ROOT).as_posix()


def _imports(path: Path) -> list[tuple[str, int]]:
    """Every imported top-level-ish module name in a file, with line numbers.

    ``import a.b.c``      -> 'a.b.c'
    ``from a.b import c`` -> 'a.b'
    Relative imports are resolved against the file's own package so that
    ``from .dev_identity import X`` inside app/adapters reads as
    'app.adapters.dev_identity'.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pkg_parts = path.relative_to(REPO_ROOT).parent.as_posix().split("/")
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level > 1 \
                    else pkg_parts
                mod = ".".join([p for p in base if p] + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            found.append((mod, node.lineno))
    return found


def _py_files(rel: str) -> list[Path]:
    root = REPO_ROOT / rel
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _violations(rel_root: str, forbidden: set[str], why: str) -> list[str]:
    """Report every import in ``rel_root`` whose dotted name starts with a
    forbidden prefix. Composition roots are exempt."""
    out = []
    for f in _py_files(rel_root):
        mp = _module_path(f)
        if mp in COMPOSITION_ROOTS:
            continue
        for name, lineno in _imports(f):
            head = name.split(".")[0]
            if name in forbidden or head in forbidden or any(
                name.startswith(p + ".") for p in forbidden
            ):
                out.append(f"{mp}:{lineno} imports {name} — {why}")
    return out


# --- the rules ------------------------------------------------------------

def test_core_never_imports_app():
    """booksnap/ stays pure. This is the one that protects the accuracy work."""
    bad = _violations(
        "booksnap", {"app"},
        "the recognition core must not depend on the product app (H1)",
    )
    assert not bad, "\n".join(bad)


def test_accuracy_tools_never_import_app():
    """The measurement harness must keep measuring the CORE.

    Scoped to the scripts the pre-commit accuracy gate actually runs, not to
    all of tools/ — product-side tooling (the OpenAPI contract check) lives
    there too and legitimately imports ``app``. If sweep or spotcheck ever
    imported the product, a product bug could move a baseline number.
    """
    ACCURACY_TOOLS = ("tools/sweep.py", "tools/spotcheck.py", "tools/rescore.py")
    bad = []
    for rel in ACCURACY_TOOLS:
        bad += _violations(
            rel, {"app"},
            "the accuracy harness must not depend on the product app (H1)",
        )
    assert not bad, "\n".join(bad)


def test_domain_is_pure():
    """No framework, no driver, no other app layer — domain is testable in ms."""
    bad = _violations(
        "app/domain",
        FRAMEWORKS | DRIVERS | {"app.ports", "app.adapters", "app.api", "booksnap"},
        "app/domain must be pure Python (H1)",
    )
    assert not bad, "\n".join(bad)


def test_ports_depend_only_on_domain():
    """Ports are Protocols. A port that imports a driver is not a port."""
    bad = _violations(
        "app/ports",
        FRAMEWORKS | DRIVERS | {"app.adapters", "app.api"},
        "app/ports may import app.domain only (H1)",
    )
    assert not bad, "\n".join(bad)


def test_api_does_not_import_adapters():
    """The rule that keeps D1 (the datastore choice) reversible."""
    bad = _violations(
        "app/api", {"app.adapters"},
        "app/api must depend on ports, not implementations (H1)",
    )
    assert not bad, "\n".join(bad)


def test_api_does_not_import_the_tuning_server():
    """The product API and the audit surface are separate applications (D2)."""
    bad = _violations(
        "app/api", {"booksnap.server"},
        "the product API must not import the tuning server (D2)",
    )
    assert not bad, "\n".join(bad)


def test_composition_root_exists_and_is_the_only_exemption():
    """Guards the exemption list itself: a stale entry would silently disable
    the api->adapters rule for a file that no longer needs it."""
    for rel in COMPOSITION_ROOTS:
        assert (REPO_ROOT / rel).exists(), f"exempted file is missing: {rel}"
    # It must actually be a composition root, i.e. it does wire an adapter.
    names = [n for n, _ in _imports(REPO_ROOT / "app/main.py")]
    assert any(n.startswith("app.adapters") for n in names), \
        "app/main.py no longer wires an adapter; remove its exemption"


def test_detector_catches_a_planted_violation():
    """A rule test that never fires is indistinguishable from a broken one.

    Writes a would-be violation through the same AST path and asserts it is
    reported — so a refactor that quietly stops parsing imports gets caught.
    """
    import tempfile

    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp:
        d = Path(tmp) / "app" / "domain"
        d.mkdir(parents=True)
        (d / "bad.py").write_text(
            "from fastapi import APIRouter\nimport sqlite3\n", encoding="utf-8"
        )
        rel = Path(tmp).relative_to(REPO_ROOT).as_posix() + "/app/domain"
        bad = _violations(rel, FRAMEWORKS | DRIVERS, "planted")
        assert len(bad) == 2, bad


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))
