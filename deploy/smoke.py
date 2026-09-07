"""End-to-end smoke test INSIDE the built image (P4.4).

Drives the real ASGI app in-process — the same one uvicorn serves — so it
proves the image, not a stand-in: sign-in from nothing, the sign-up that
mints the world, the built client being served, and a backup + drill.

Under a URL prefix (``BOOKSNAP_BASE_PATH=/booksnap``, the
malinvishne.com/booksnap deployment) every request below carries the prefix,
the way it arrives from the proxy — and the page's asset URLs are checked to
carry it too, which is the build-time half of the same setting.
"""
import re
import sys

from fastapi.testclient import TestClient

import app.main
from app.adapters.console_mailer import ConsoleMailer

captured = []


class Capturing(ConsoleMailer):
    def send_login_link(self, email, token):
        captured.append((email, token))
        super().send_login_link(email, token)


# Same wiring, one adapter swapped so the test can read the "mail".
from app.api.deps import get_mailer  # noqa: E402

client = TestClient(app.main.app)
app.main.app.dependency_overrides[get_mailer] = lambda: Capturing(
    "https://books.example.com")

BASE = app.main.base_path()          # "" at a domain root, "/booksnap" under one
API = f"{BASE}/api/v1"
print(f"base path: {BASE!r}")

ok = True


def check(label, got, want):
    global ok
    good = got == want
    ok = ok and good
    print(f"{'ok  ' if good else 'FAIL'} {label}: {got}")


check("no cookie -> /books 401", client.get(f"{API}/books").status_code, 401)
check("request a link", client.post(f"{API}/auth/link",
                                    json={"email": "owner@example.com"}).status_code, 202)
check("the link was mailed", len(captured), 1)

token = captured[0][1]
r = client.post(f"{API}/auth/session", json={"token": token})
check("redeem -> 201", r.status_code, 201)
check("session cookie set", "booksnap_session" in r.cookies, True)
check("signed in -> /libraries 200",
      client.get(f"{API}/libraries").status_code, 200)
check("a fresh database is EMPTY", client.get(f"{API}/libraries").json(), [])

made = client.post(f"{API}/libraries", json={"label": "משפחת מלין"})
check("sign-up mints the world", made.status_code, 201)
check("...as its admin", made.json()["role"], "admin")
check("and the books route now resolves",
      client.get(f"{API}/books").status_code, 200)

page = client.get(f"{BASE}/").text
check("the built client is served", "<div id=\"root\">" in page, True)
assets = sorted(set(re.findall(r'(?:src|href)="(/[^"]*?)assets/', page)))
check("...built for THIS prefix", assets, [f"{BASE}/"])
if BASE:
    bare = client.get(BASE, follow_redirects=False)
    check("the bare prefix redirects INTO the prefix",
          bare.headers.get("location", "").endswith(f"{BASE}/"), True)
check("the docs page is OFF by default",
      client.get(f"{API}/docs").status_code, 404)

from tools import backup as backup_tool  # noqa: E402
from tools import restore as restore_tool  # noqa: E402
from pathlib import Path  # noqa: E402

target = backup_tool.run(app.main.db_path(), app.main.blob_root(),
                         Path("/data/backups"))
findings = restore_tool.drill(target)
check("the drill passes in the image", len(findings["libraries"]), 1)
check("...and the library it found is the one signed up",
      findings["libraries"][0][0], "משפחת מלין")

print("SMOKE PASSED" if ok else "SMOKE FAILED")
sys.exit(0 if ok else 1)
