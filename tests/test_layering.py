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
        FRAMEWORKS | DRIVERS | {"app.ports", "app.adapters", "app.api"},
        "app/domain must be pure Python (H1)",
    )
    assert not bad, "\n".join(bad)


def test_domain_reaches_into_the_core_only_for_normalize():
    """``app/domain -> booksnap`` is DOWNWARD and legal (H1's diagram puts the
    core below the domain; only ``booksnap -> app`` is forbidden). P1.1 uses
    it deliberately: the product's search keys must be produced by the same
    ``normalize()`` the matcher uses, or the two drift.

    But only that. ``booksnap.catalog`` is stdlib-only and pure; the pipeline,
    the OCR modules and the server are not, and importing one of them here
    would put cv2/tesseract behind a 'milliseconds, no I/O' rule test.
    """
    ALLOWED = {"booksnap.catalog"}
    bad = []
    for f in _py_files("app/domain"):
        for name, lineno in _imports(f):
            if name == "booksnap" or name.startswith("booksnap."):
                if name not in ALLOWED:
                    bad.append(
                        f"{_module_path(f)}:{lineno} imports {name} — "
                        f"app/domain may import only {sorted(ALLOWED)}"
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


def test_the_staff_service_never_imports_the_product_api():
    """Two applications, and the separation is the whole point of the split.

    ``/api/v1`` resolves a library through the CALLER'S MEMBERSHIPS
    (``app/api/deps.py:current_library``, §4.2), which is exactly the question
    an operator's console cannot ask — it must see tenants nobody invited it
    to. That is why `app/staff_api/` exists at all rather than a loosened
    product route.

    Reusing the product's routers or dependencies here would drag that
    membership resolution back in, and the tempting way to make it fit is to
    loosen it — which weakens tenant isolation for every household at once.
    So the console reads through the staff service and WRITES through
    ``/api/v1`` as an ordinary member: two surfaces, one authorization model
    each. See planning/ADMIN_CONSOLE_PLAN.md, "Reading is cross-tenant;
    writing is not".
    """
    bad = _violations(
        "app/staff_api", {"app.api"},
        "the staff service must not reuse the product's routes or deps",
    )
    assert not bad, "\n".join(bad)


def test_the_staff_service_never_imports_the_product_composition_root():
    """⚠ Importing ``app.main`` MIGRATES the owner's real database.

    The composition root opens ``work/product.db`` at import time and
    ``SqliteBookStore.__init__`` runs ``migrate()`` — CLAUDE.md records this
    being discovered the hard way. A console that is READ-ONLY BY CONSTRUCTION
    would then upgrade the owner's schema as a side effect of being looked at.
    ``app/staff_api/main.py`` resolves the database path from the same
    environment variables instead, and says so.
    """
    bad = _violations(
        "app/staff_api", {"app.main"},
        "importing the product's composition root migrates the real database",
    )
    assert not bad, "\n".join(bad)


def test_the_staff_service_binds_no_adapter_and_so_needs_no_exemption():
    """The recorded reason ``app/staff_api/main.py`` is NOT in COMPOSITION_ROOTS.

    A second composition root exists, which the exemption list is deliberately
    shaped to make a visible, argued-about diff. The argument, from that file's
    own docstring: the rule the exemption protects is
    ``app/api -X-> app/adapters``, and nothing here is under ``app/api`` — this
    service wires a read model that imports no adapter at all, so the exemption
    is not needed yet.

    This test is what keeps that argument TRUE rather than merely written down.
    The day the staff service binds a real adapter, this test fails and the
    person who made it bind one adds it to the list — which is the discussion
    the list exists to force.
    """
    bad = _violations(
        "app/staff_api", {"app.adapters"},
        "add app/staff_api/main.py to COMPOSITION_ROOTS and argue for it",
    )
    assert not bad, "\n".join(bad)


def test_the_staff_service_never_runs_a_migration():
    """Read-only by construction, checked structurally and not only by review.

    ``tests/test_staff_api.py`` pins ``user_version`` across every query, which
    catches a
    migration that RUNS. This catches the import that would let one.

    ⚠ It is REDUNDANT rather than primary, and a review measured exactly how:
    ``from app.adapters import migrations`` evades it (``_imports`` yields the
    module name ``app.adapters``, and ``"migrations" in name`` is False) and is
    caught by ``test_the_staff_service_binds_no_adapter…`` instead. Verified in
    both directions. So this rule earns its keep only the day ``migrations``
    moves out of ``app/adapters`` — do not delete the adapter rule believing
    this one covers it. Recorded rather than "fixed": both spellings are caught
    today, which is the property that matters.
    """
    bad = []
    for f in _py_files("app/staff_api"):
        for name, lineno in _imports(f):
            if "migrations" in name:
                bad.append(
                    f"{_module_path(f)}:{lineno} imports {name} — the staff "
                    f"service must never advance the owner's schema"
                )
    assert not bad, "\n".join(bad)


def test_the_product_never_imports_the_staff_service():
    """The other direction, which matters more.

    ``app/staff_api`` answers cross-tenant questions with its own credential.
    A product module reaching into it would put a surface that reads EVERY
    household's data one import away from a route that authenticates as one
    member — the exact shape of an isolation bug §4.2 exists to prevent.

    ⚠ ``app/main.py`` is NOT exempted here, unlike everywhere else in this
    file: it is a composition root for the PRODUCT, and the staff service has
    its own.
    """
    bad = []
    for rel in ("app/api", "app/domain", "app/ports", "app/adapters", "app/main.py"):
        for f in _py_files(rel):
            for name, lineno in _imports(f):
                if name == "app.staff_api" or name.startswith("app.staff_api."):
                    bad.append(
                        f"{_module_path(f)}:{lineno} imports {name} — the "
                        f"product must not depend on the operator's service"
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
