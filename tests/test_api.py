# -*- coding: utf-8 -*-
"""H4 ring 3 — API tests: shapes, status codes, and the two meta-tests.

The meta-tests matter more than the endpoint test. They are structural rules
over *every* route, so they keep holding as routes are added by later items:

  - every API route is under ``/api/v1`` (H3 — no unversioned endpoint ever
    ships, not even by accident during a hurried item);
  - every API route resolves its library through ``deps.current_library``
    (H2 — a route that reaches for "the" library works fine today and has to
    be rewritten at pillar 3; this is what makes that impossible).

Pillar 3 adds a third to this file: every route is policy-checked, and a route
with no policy declaration FAILS rather than defaulting to open.

Built with a stub principal, so nothing here depends on the dev adapter.
"""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/_fastclient

from fastapi.routing import APIRoute
from _fastclient import TestClient          # starlette's, on a shared portal

from app import API_PREFIX, __version__
from app.adapters.disk_blobs import DiskBlobStore
from app.adapters.queued_jobs import QueuedJobRunner
from app.adapters.memory_store import (
    MemoryBookStore,
    MemoryDecisionStore,
    MemoryDuplicateQueue,
    MemoryReadStore,
    MemoryShelfStore,
    MemoryTenancyStore,
)
from app.api import deps
from app.api.app import bind_ports, create_app
from app.domain import (
    Account,
    Decision,
    DecisionKind,
    Library,
    LibraryRef,
    Membership,
    Provenance,
    Role,
    Status,
    User,
    new_book,
)
from app.ports.reader import ReadAlternative, ReadClaim

TEST_ACCOUNT = "acc-test"
# ⚠ "zzz" so the account order and the LABEL order disagree. With
# "acc-other" they coincided, and `GET /libraries`' own re-sort — the one
# whose comment says it exists so the switcher does not reshuffle — could
# be deleted with the whole ring green (P3.7b's quality review).
OTHER_ACCOUNT = "acc-zzz"
TEST_LIBRARY = LibraryRef(id="lib-test", label="Test library")


class StubClock:
    def now_iso(self) -> str:
        return "2026-08-07T12:00:00+00:00"


class SeqIdGen:
    """Deterministic ids, so a test can name what it just created."""

    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"id-{self._n}"


class StubPrincipal:
    """Implements app.ports.Principal without touching any adapter."""

    def __init__(self, library: LibraryRef = TEST_LIBRARY, pid: str = "p-test"):
        self._library = library
        self._id = pid

    @property
    def id(self) -> str:
        return self._id

    @property
    def library(self) -> LibraryRef:
        return self._library


def _tenancy(principal: StubPrincipal) -> MemoryTenancyStore:
    """A tenancy store that already knows this principal and its library.

    Seeded rather than empty because that is the state every app reaches at
    startup: `app/main.py` bootstraps the user and its membership, and a
    test whose store disagreed with its own principal would be testing a
    wiring bug, not a rule. Tests that WANT the disagreement (a foreign
    library, an unknown one) build their own.
    """
    store = MemoryTenancyStore()
    store.save_user(User(id=principal.id))
    store.save_account(Account(id=TEST_ACCOUNT))
    store.save_membership(Membership(principal.id, TEST_ACCOUNT, Role.ADMIN))
    store.save_library(Library(id=principal.library.id,
                               account_id=TEST_ACCOUNT,
                               label=principal.library.label))
    return store


# --- app recycling ---------------------------------------------------------
# ⚠ Why apps are pooled rather than built per test. FastAPI resolves a route's
# dependency graph LAZILY — on that route's first request — and the analysis
# (pydantic signature introspection, one `get_dependant` per route) costs ~50ms
# per app. This file builds 153 of them, which measured as 29 of its 39
# seconds: more time spent re-deriving the same route table than running the
# assertions.
#
# A pooled app is not a shortcut around anything the tests check. The ports are
# rebound through `app.api.app.bind_ports` — the SAME function `create_app`
# calls, so `_always`'s pydantic deep-copy trap is still exercised — and the
# overrides are CLEARED first, so an optional port (blobs, reader) left unbound
# by this call cannot inherit the previous test's. Everything a test can
# actually write to lives in the stores, and those are still fresh per test.
#
# It is also closer to production than the old shape: a real server builds one
# app and serves every request through it.
#
# ⚠ Apps come back at the END OF THE TEST, not when a client closes. Recycling
# on `TestClient.__exit__` is the tempting version and it barely worked: a
# large family of tests here builds `c = TestClient(_app(...))` with no `with`
# — perfectly legal, the client works — so 135 apps were built for 138 tests
# and the pool was empty at the end. Returning them from `after_each` also
# guarantees two apps live at once stay DISTINCT for as long as the test runs,
# which the tenant-isolation tests need.
_APP_POOL: list = []
_IN_USE: list = []


def after_each() -> None:
    """Called by ``tests/run_all.py`` after every test in this module."""
    _APP_POOL.extend(_IN_USE)
    _IN_USE.clear()


def _app(principal: StubPrincipal | None = None, store=None, shelves=None,
         blobs=None, reads=None, reader=None, jobs=None, decisions=None,
         duplicates=None, tenancy=None, recycle: bool = True):
    """Build (or recycle) an app with these ports bound.

    :param recycle: pass ``False`` for an app whose per-app state a later test
        must not inherit. Everything else is recycled at the end of the test.
    """
    p = principal or StubPrincipal()
    ports = dict(
        principal_provider=lambda: p,
        tenancy_store=tenancy if tenancy is not None else _tenancy(p),
        book_store=store if store is not None else MemoryBookStore(),
        shelf_store=shelves if shelves is not None else MemoryShelfStore(),
        blob_store=blobs,
        read_store=reads if reads is not None else MemoryReadStore(),
        decision_store=decisions if decisions is not None else MemoryDecisionStore(),
        duplicate_queue=duplicates if duplicates is not None else MemoryDuplicateQueue(),
        reader=reader,
        job_runner=jobs if jobs is not None else QueuedJobRunner(),
        clock=StubClock(),
        id_gen=SeqIdGen(),
    )
    if not recycle:
        return create_app(**ports)
    if _APP_POOL:
        app = _APP_POOL.pop()
        app.dependency_overrides.clear()
        bind_ports(app, **ports)
    else:
        app = create_app(**ports)
    _IN_USE.append(app)
    return app


@contextmanager
def _blobs():
    """A real DiskBlobStore on a temp dir.

    Not a stub: the whole point of P2.3 is that the bytes survive a round trip
    and come back decodable, and a fake that returns whatever it was handed
    would assert nothing about the part that can actually be wrong.
    """
    tmp = tempfile.mkdtemp(prefix="booksnap-blobs-")
    try:
        yield DiskBlobStore(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _png(size=(40, 30), colour=(200, 30, 30)) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format="PNG")
    return out.getvalue()


def _mpo(size=(60, 40), *, orientation: int | None = None) -> bytes:
    """A GENUINE Multi-Picture Object — what a phone camera actually emits.

    ⚠ This helper exists because `_jpeg()` does not reproduce reality. A modern
    iPhone or Samsung "JPEG" is usually an MPO: a JPEG container carrying a
    second embedded frame (HDR, depth, the second lens). PIL reports
    `format='MPO'`, and the upload validator's format whitelist rejected it —
    so every synthetic test passed while EVERY REAL PHOTO 415'd.

    A real MPO, written by PIL's own MPO encoder, not a stand-in.
    """
    from PIL import Image

    first = Image.new("RGB", size, (200, 40, 40))
    second = Image.new("RGB", size, (40, 40, 200))
    out = io.BytesIO()
    kw = {}
    if orientation is not None:
        exif = first.getexif()
        exif[0x0112] = orientation
        kw["exif"] = exif
    first.save(out, format="MPO", save_all=True, append_images=[second], **kw)
    return out.getvalue()


def _heic_header() -> bytes:
    """Just enough of a HEIC container to be recognised, not decoded.

    The point is the ERROR MESSAGE: HEIC is the iPhone default whenever the
    camera is not on "Most Compatible", so a refusal has to say what to change.
    """
    return b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1" + b"\x00" * 64


def _jpeg(size=(40, 30), *, orientation: int | None = None) -> bytes:
    """A JPEG, optionally carrying an EXIF rotation flag like a phone photo."""
    from PIL import Image

    img = Image.new("RGB", size, (30, 90, 200))
    out = io.BytesIO()
    if orientation is None:
        img.save(out, format="JPEG")
    else:
        exif = img.getexif()
        exif[0x0112] = orientation
        img.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def _seed(store, library: LibraryRef, *titles: str, status=Status.AUTO,
          author: str = "פול קארני"):
    """Ids continue from what is already there, so two _seed calls in one test
    don't overwrite each other — the first book is always b1."""
    base = store.count(library)
    for i, title in enumerate(titles, start=base + 1):
        store.save(library, new_book(
            id=f"b{i}", library_id=library.id, title=title,
            author=author, copy_id=f"c{i}", status=status,
            added_at="2026-01-01T00:00:00+00:00",
        ))


def _api_routes(app) -> list[tuple[str, APIRoute]]:
    """(effective path, route) for every product API route.

    FastAPI >= 0.13x defers ``include_router`` into an ``_IncludedRouter``
    node, so ``app.routes`` is no longer flat and a route's own ``.path`` is
    router-relative (``/meta``, not ``/api/v1/meta``). ``iter_route_contexts``
    is the public flattener; the fallback keeps this suite working on the
    older layout that ``requirements.txt`` still allows.

    Schema/docs endpoints are plain starlette Routes, so filtering on APIRoute
    already excludes them.
    """
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:
        return [(r.path, r) for r in app.routes if isinstance(r, APIRoute)]
    return [(c.path, c.original_route) for c in iter_route_contexts(app.routes)
            if isinstance(c.original_route, APIRoute)]


# --- the endpoint ---------------------------------------------------------

def test_meta_returns_service_and_library():
    with TestClient(_app()) as client:
        r = client.get(f"{API_PREFIX}/meta")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["app"] == "booksnap"
    assert body["version"] == __version__
    assert body["api_version"] == "v1"
    assert body["library"] == {"id": "lib-test", "label": "Test library"}


def test_meta_follows_the_principal_not_a_global():
    """Two apps, two principals, no leakage — the shape §1.3 requires before a
    second tenant exists."""
    other = StubPrincipal(LibraryRef(id="lib-other", label="Other"), pid="p-2")
    with TestClient(_app()) as c1, TestClient(_app(other)) as c2:
        a = c1.get(f"{API_PREFIX}/meta").json()
        b = c2.get(f"{API_PREFIX}/meta").json()
    assert a["library"]["id"] == "lib-test"
    assert b["library"]["id"] == "lib-other"


# --- tenancy: the resolver and the switcher (P3.1, §1.3/§4.1) --------------

def _second_library(principal: StubPrincipal, tenancy: MemoryTenancyStore,
                    *, member: bool = True, library_id: str = "lib-2",
                    label: str = "Office",
                    account_id: str = OTHER_ACCOUNT) -> None:
    """A library under a SECOND account, member or not.

    ⚠ A second account, not a second library of the caller's own: since
    P3.7b a role is held per account, so a library added under TEST_ACCOUNT
    is one the caller already reaches with the role they already have — which
    would make `member=False` unable to express "not yours" at all.
    """
    if tenancy.get_account(account_id) is None:
        tenancy.save_account(Account(id=account_id))
    tenancy.save_library(Library(id=library_id, account_id=account_id,
                                 label=label,
                                 created_at="2026-08-01T00:00:00+00:00"))
    if member:
        tenancy.save_membership(
            Membership(principal.id, account_id, Role.EDITOR))


def test_the_request_chooses_the_library_not_the_server():
    """§1.3's whole point: a library reference travels on every request. Until
    P3.1 the header was sent by the client and ignored by the server."""
    p = StubPrincipal()
    tenancy = _tenancy(p)
    _second_library(p, tenancy)
    with TestClient(_app(p, tenancy=tenancy)) as client:
        body = client.get(f"{API_PREFIX}/meta",
                          headers={deps.LIBRARY_HEADER: "lib-2"}).json()
    assert body["library"] == {"id": "lib-2", "label": "Office"}


def test_the_books_a_request_sees_follow_the_library_it_named():
    """The resolver is one function, so proving it on `meta` proves the shape
    — but the failure that matters is a WRITE or a LIST answering from the
    wrong tenant, so it is asserted on the books route too."""
    p = StubPrincipal()
    tenancy = _tenancy(p)
    _second_library(p, tenancy)
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "ספר של הבית")
    _seed(store, LibraryRef("lib-2", "Office"), "ספר של המשרד")
    with TestClient(_app(p, store=store, tenancy=tenancy)) as client:
        here = client.get(f"{API_PREFIX}/books").json()
        there = client.get(f"{API_PREFIX}/books",
                           headers={deps.LIBRARY_HEADER: "lib-2"}).json()
    assert [b["title"] for b in here["items"]] == ["ספר של הבית"]
    assert [b["title"] for b in there["items"]] == ["ספר של המשרד"]


def test_a_library_the_caller_is_not_a_member_of_is_404_not_403():
    """§4.2: a foreign library must not be distinguishable from a fictional
    one. Asserted from the ONE place that can see every library, because a
    403 here would confirm the existence of another household's collection."""
    p = StubPrincipal()
    tenancy = _tenancy(p)
    _second_library(p, tenancy, member=False)
    with TestClient(_app(p, tenancy=tenancy)) as client:
        foreign = client.get(f"{API_PREFIX}/meta",
                             headers={deps.LIBRARY_HEADER: "lib-2"})
        fictional = client.get(f"{API_PREFIX}/meta",
                               headers={deps.LIBRARY_HEADER: "lib-nothing"})
    assert foreign.status_code == 404, foreign.text
    assert fictional.status_code == 404
    assert foreign.json() == fictional.json(), \
        "a foreign library answers differently from one that does not exist"


def test_a_request_with_no_library_header_still_gets_the_default_one():
    """Every curl, every OpenAPI example and most of this suite send no
    header. Refusing them would buy no safety — a caller with no header still
    reaches only their own library."""
    with TestClient(_app()) as client:
        assert client.get(f"{API_PREFIX}/meta").json()["library"]["id"] == "lib-test"


def test_the_switcher_lists_this_users_libraries_with_their_roles():
    p = StubPrincipal()
    tenancy = _tenancy(p)
    _second_library(p, tenancy)
    # A THIRD customer, so "not a member" is expressible: lib-2's account
    # already has this caller in it.
    _second_library(p, tenancy, member=False, library_id="lib-3",
                    label="Someone else's", account_id="acc-third")
    with TestClient(_app(p, tenancy=tenancy)) as client:
        rows = client.get(f"{API_PREFIX}/libraries").json()
    assert [r["id"] for r in rows] == ["lib-2", "lib-test"]  # by label
    assert {r["id"]: r["role"] for r in rows} == \
        {"lib-2": "editor", "lib-test": "admin"}
    # ⚠ The role travels per ACCOUNT, so these two rows carry two
    # different owners. lib-3 is absent because its customer has no member
    # here — the switcher lists what you can reach, and reachability is
    # now ownership.
    assert {r["id"]: r["account_id"] for r in rows} == \
        {"lib-2": OTHER_ACCOUNT, "lib-test": TEST_ACCOUNT}


def test_creating_a_library_makes_the_caller_its_admin_and_it_is_usable_at_once():
    """The two halves of §4.3's step 2: the library exists, and the person who
    made it can immediately name it on a request."""
    p = StubPrincipal()
    tenancy = _tenancy(p)
    with TestClient(_app(p, tenancy=tenancy)) as client:
        created = client.post(f"{API_PREFIX}/libraries",
                              json={"label": "משפחת מלין"})
        assert created.status_code == 201, created.text
        new_id = created.json()["id"]
        assert created.json()["role"] == "admin"
        resolved = client.get(f"{API_PREFIX}/meta",
                              headers={deps.LIBRARY_HEADER: new_id})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["library"]["label"] == "משפחת מלין"
    # ⚠ NO membership is minted for the library, and that is the P3.7b
    # rule: it lands under the caller's existing account and inherits the
    # standing they already had. A grant per library is what was deleted.
    assert tenancy.membership(p.id, new_id) is None
    row = tenancy.get_library(new_id)
    assert row is not None and row.account_id == TEST_ACCOUNT
    assert tenancy.membership(p.id, TEST_ACCOUNT).role is Role.ADMIN



def test_only_an_admin_adds_a_library_to_an_account_others_belong_to():
    """§4.2 over the route that stopped being harmless when the boundary moved.

    Before P3.7b this minted a brand-new tenant with the caller as its admin,
    so leaving it open touched nobody. It now writes into an EXISTING customer:
    every member's switcher grows a row, and there is no DELETE to undo it. A
    viewer appending libraries to the account that pays for them is vandalism
    the product cannot reverse (P3.7b's data-integrity review reproduced it).
    """
    for role in (Role.VIEWER, Role.EDITOR):
        # The role is held on the account that owns the caller's OWN
        # default library — the one `_account()` resolves — and somebody
        # else administers it. This route takes no library header: it is
        # on the user axis, so the customer is chosen for it.
        p = StubPrincipal()
        tenancy = MemoryTenancyStore()
        tenancy.save_user(User(id=p.id))
        tenancy.save_user(User(id="usr-admin"))
        tenancy.save_account(Account(id=TEST_ACCOUNT))
        tenancy.save_membership(
            Membership("usr-admin", TEST_ACCOUNT, Role.ADMIN))
        tenancy.save_membership(Membership(p.id, TEST_ACCOUNT, role))
        tenancy.save_library(Library(id=p.library.id,
                                     account_id=TEST_ACCOUNT,
                                     label=p.library.label))
        with TestClient(_app(principal=p, tenancy=tenancy)) as c:
            r = c.post(f"{API_PREFIX}/libraries", json={"label": "שלי"})
            assert r.status_code == 403, (role, r.status_code, r.text)
        # …and nothing was appended to the customer paying for it.
        assert [lib.id for lib in tenancy.list_libraries(TEST_ACCOUNT)] == [
            p.library.id
        ]


def test_a_library_goes_under_an_account_you_belong_to_never_your_defaults():
    """`_account`'s first branch reads the principal's OWN default library and
    uses its owner — which is only legitimate while the caller is a member of
    that owner. A principal whose default library belongs to a customer they
    have nothing to do with must NOT get a library written into it; they get a
    fresh account of their own instead.

    Dev-trusted principals make this unreachable today. It is pinned because
    it is the one line that decides whether `principal.library` can be used as
    a lever into somebody else's customer (P3.7b's data-integrity review)."""
    p = StubPrincipal()
    tenancy = MemoryTenancyStore()
    tenancy.save_user(User(id=p.id))
    tenancy.save_account(Account(id="acc-foreign"))
    tenancy.save_library(Library(id=p.library.id, account_id="acc-foreign",
                                 label=p.library.label))
    with TestClient(_app(principal=p, tenancy=tenancy)) as c:
        made = c.post(f"{API_PREFIX}/libraries", json={"label": "שלי"})
    assert made.status_code == 201, made.text
    assert made.json()["account_id"] != "acc-foreign"
    assert [lib.id for lib in tenancy.list_libraries("acc-foreign")] == \
        [p.library.id], "a library was written into a foreign customer"


def test_a_missing_library_and_a_foreign_one_cost_the_same_lookups():
    """404-never-403 on the TIMING axis, which the wire alone cannot carry.

    Every reply is byte-identical, so the only thing left to distinguish "no
    such library" from "somebody else's library" is how long the answer took.
    The obvious resolver — return early when the library is missing — costs
    one store call for a fictional id and two for a real one belonging to
    another customer, and the sqlite adapter opens a connection per operation.
    P3.7b's security review measured that as a clean 2×: 20 foreign ids and 20
    invented ones, interleaved, 200 samples each, and every single one
    classified correctly by response time with no overlap. Sweeping ids then
    enumerates another account's libraries through a door that says the same
    thing to all of them.

    Counted rather than timed, deliberately: a wall-clock assertion on a
    4-core laptop under an antivirus is a flake generator, and the count is
    the property — the timing was only its symptom."""
    calls: list[str] = []

    class Counting:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            attr = getattr(self._inner, name)
            if name not in ("get_library", "membership", "get_account"):
                return attr

            def counted(*args, **kwargs):
                calls.append(name)
                return attr(*args, **kwargs)
            return counted

    p = StubPrincipal()
    inner = _tenancy(p)
    inner.save_account(Account(id=OTHER_ACCOUNT))
    inner.save_library(Library(id="lib-theirs", account_id=OTHER_ACCOUNT,
                               label="של מישהו אחר"))

    shapes = {}
    for name, library_id in (("foreign", "lib-theirs"),
                             ("fictional", "lib-invented")):
        calls.clear()
        with TestClient(_app(principal=p, tenancy=Counting(inner))) as c:
            r = c.get(f"{API_PREFIX}/meta",
                      headers={deps.LIBRARY_HEADER: library_id})
        assert r.status_code == 404 and r.json() == {"detail": "no such library"}
        shapes[name] = list(calls)

    assert shapes["foreign"] == shapes["fictional"], (
        "a library that exists but is not yours takes a different number of "
        f"store lookups than one that does not exist: {shapes}"
    )


def test_a_library_goes_under_the_account_you_are_operating_as():
    """`_account`'s first branch, pinned where it can actually be wrong.

    A user may belong to several customers (P4.3's invites), and only one of
    them is the one they are demonstrably operating as: the owner of the
    library their own principal resolves to. Picking "the first account we
    happen to list" is a cross-tenant write the moment a second membership
    exists — and it survived the whole ring until this case (P3.7b's security
    review, mutation M6)."""
    p = StubPrincipal()
    tenancy = MemoryTenancyStore()
    tenancy.save_user(User(id=p.id))
    # Two accounts, ADMIN of both. "acc-aaa" sorts first; the principal's own
    # library belongs to the OTHER one, which is the answer.
    for account_id in ("acc-aaa", TEST_ACCOUNT):
        tenancy.save_account(Account(id=account_id))
        tenancy.save_membership(Membership(p.id, account_id, Role.ADMIN))
    tenancy.save_library(Library(id=p.library.id, account_id=TEST_ACCOUNT,
                                 label=p.library.label))
    with TestClient(_app(principal=p, tenancy=tenancy)) as c:
        made = c.post(f"{API_PREFIX}/libraries", json={"label": "שנייה"})
    assert made.status_code == 201, made.text
    assert made.json()["account_id"] == TEST_ACCOUNT, (
        "a library landed in a customer the caller was not operating as"
    )
    assert tenancy.list_libraries("acc-aaa") == ()

def test_a_library_created_with_a_blank_name_is_refused():
    """§4.3, and the deliberate asymmetry with a shelf (whose label is
    optional because an unnamed shelf is shown by its own photograph).

    Both spellings of blank answer the SAME way: the rule is the domain's, not
    a pydantic constraint that would make `""` a 422 and `"   "` a 400."""
    with TestClient(_app()) as client:
        assert client.post(f"{API_PREFIX}/libraries",
                           json={"label": "   "}).status_code == 400
        assert client.post(f"{API_PREFIX}/libraries",
                           json={"label": ""}).status_code == 400
        assert client.patch(f"{API_PREFIX}/libraries/lib-test",
                            json={"label": " "}).status_code == 400


def test_renaming_a_library_the_caller_does_not_belong_to_is_404():
    p = StubPrincipal()
    tenancy = _tenancy(p)
    _second_library(p, tenancy, member=False)
    with TestClient(_app(p, tenancy=tenancy)) as client:
        r = client.patch(f"{API_PREFIX}/libraries/lib-2", json={"label": "Mine"})
        mine = client.patch(f"{API_PREFIX}/libraries/lib-test",
                            json={"label": "הספרייה שלי"})
    assert r.status_code == 404, r.text
    assert mine.status_code == 200 and mine.json()["label"] == "הספרייה שלי"
    assert tenancy.get_library("lib-2").label == "Office", "a 404 still wrote"


def test_a_photo_is_reachable_from_an_img_tag_in_a_second_library():
    """⚠ The bug the switcher shipped with, found in live use the same day.

    An `<img src>` and a download `<a href>` are built by the BROWSER, which
    cannot be told to send `X-Booksnap-Library`. So every photo, every spine
    crop and both export links resolved against the caller's DEFAULT library
    — and in a second library they 404'd: a shelf photo that had just been
    read correctly rendered as an empty box.

    The query parameter is the escape hatch for exactly those requests. This
    asserts BOTH halves, because either alone is the bug: the photo is found
    with `?library=`, and it is NOT found without it.
    """
    p = StubPrincipal()
    tenancy = _tenancy(p)
    _second_library(p, tenancy)
    with _blobs() as blobs:
        c = TestClient(_app(p, blobs=blobs, tenancy=tenancy))
        key = c.post(f"{API_PREFIX}/images",
                     files={"file": ("shelf.png", _png(), "image/png")},
                     headers={deps.LIBRARY_HEADER: "lib-2"}).json()["key"]

        as_img = c.get(f"{API_PREFIX}/images/{key}/thumb?library=lib-2")
        assert as_img.status_code == 200, as_img.text

        # No reference at all: the DEFAULT library, which never had this
        # photo. This is what the browser was really sending.
        assert c.get(f"{API_PREFIX}/images/{key}/thumb").status_code == 404


def test_the_header_wins_over_a_stale_query_parameter():
    """The client's own `fetch()` always sets the header, and a URL can
    outlive a switch (a cached image src, a link someone kept). If the
    parameter could override the header, one stale URL would drag a whole
    request into the wrong library."""
    p = StubPrincipal()
    tenancy = _tenancy(p)
    _second_library(p, tenancy)
    with TestClient(_app(p, tenancy=tenancy)) as client:
        body = client.get(
            f"{API_PREFIX}/meta?library=lib-2",
            headers={deps.LIBRARY_HEADER: "lib-test"},
        ).json()
    assert body["library"]["id"] == "lib-test"


def test_meta_names_the_user_so_an_empty_switcher_can_be_explained():
    with TestClient(_app()) as client:
        assert client.get(f"{API_PREFIX}/meta").json()["user"]["id"] == "p-test"


# --- books: the P1.4 surface ---------------------------------------------

def test_a_write_through_the_api_reaches_the_real_store():
    """The bug this exists for: binding a port with ``lambda v=value: v`` gives
    the provider a defaulted PARAMETER, FastAPI treats it as a field to
    resolve, and pydantic DEEP-COPIES mutable defaults. Every endpoint then
    gets a copy of the store — reads look perfect and writes vanish. Nothing
    else in this file catches it, because every other assertion reads back
    through the same request-scoped copy.
    """
    store = MemoryBookStore()
    with TestClient(_app(store=store)) as client:
        created = client.post(f"{API_PREFIX}/books",
                              json={"title": "ספר", "author": "מחבר"}).json()
    assert store.get(TEST_LIBRARY, created["id"]) is not None, \
        "the API served a copy of the store; the write was discarded"


def test_lists_books_with_paging_and_a_total():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "גדר", "אבן", "בית")
    with TestClient(_app(store=store)) as client:
        body = client.get(f"{API_PREFIX}/books?limit=2").json()
    assert [b["title"] for b in body["items"]] == ["אבן", "בית"]
    assert body["total"] == 3 and body["limit"] == 2 and body["offset"] == 0


def test_list_rejects_an_unbounded_limit():
    """A client asking for everything must not be able to page the server out
    of memory by accident."""
    with TestClient(_app()) as client:
        assert client.get(f"{API_PREFIX}/books?limit=100000").status_code == 422


def test_list_filters_by_status():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    _seed(store, TEST_LIBRARY, "בית", status=Status.MANUAL)
    with TestClient(_app(store=store)) as client:
        assert [b["title"] for b in
                client.get(f"{API_PREFIX}/books?status=auto").json()["items"]] \
            == ["אבן"]
        assert [b["title"] for b in
                client.get(f"{API_PREFIX}/books?status=manual").json()["items"]] \
            == ["בית"]


def test_list_filters_by_author_key():
    """The author chip is a grouping over NORMALIZED strings (§5.1), so the
    key round-trips: a book's ``author_key`` is what you filter with, and a
    differently-spelled-but-equal name comes back with it."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן", "בית", author="ג'ראלד דארל")
    _seed(store, TEST_LIBRARY, "גדר", author="אסימוב")
    with TestClient(_app(store=store)) as client:
        key = client.get(f"{API_PREFIX}/books/b1").json()["author_key"]
        page = client.get(f"{API_PREFIX}/books", params={"author_key": key}).json()
    assert [b["title"] for b in page["items"]] == ["אבן", "בית"]
    assert page["total"] == 2


def test_search_ranks_by_relevance_and_ignores_the_sort_control():
    """Relevance IS the order when searching, so a `sort` arriving alongside
    `q` is ignored rather than rejected — a UI that keeps a sort control on
    screen while the user types must not start returning 400s mid-keystroke."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "מהעיר הדוממת", "עיר", "עיר הזמן")
    with TestClient(_app(store=store)) as client:
        body = client.get(f"{API_PREFIX}/books",
                          params={"q": "עיר", "sort": "title"}).json()
    assert body["items"][0]["title"] == "עיר", [b["title"] for b in body["items"]]
    assert body["total"] == 3


def test_an_empty_q_falls_back_to_listing_rather_than_returning_nothing():
    """A cleared search box shows the library again; it does not show zero
    books because `q=` was still on the URL."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן", "בית")
    with TestClient(_app(store=store)) as client:
        assert client.get(f"{API_PREFIX}/books", params={"q": ""}).json()["total"] == 2
        assert client.get(f"{API_PREFIX}/books", params={"q": "  "}).json()["total"] == 2
        assert client.get(f"{API_PREFIX}/books", params={"q": "זזז"}).json()["total"] == 0


def test_get_returns_the_book_with_its_copies():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        body = client.get(f"{API_PREFIX}/books/b1").json()
    assert body["copy_count"] == 1 and len(body["copies"]) == 1
    assert body["copies"][0]["shelf_id"] is None  # §1.1, until the map


def test_patch_marks_the_book_manual_and_persists():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        body = client.patch(f"{API_PREFIX}/books/b1",
                            json={"title": "אבן מתוקנת"}).json()
    assert body["title"] == "אבן מתוקנת"
    assert body["status"] == "manual", "an edit did not outrank the auto claim"
    assert store.get(TEST_LIBRARY, "b1").title == "אבן מתוקנת"


def test_patch_with_no_fields_is_a_400_not_a_silent_no_op():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        assert client.patch(f"{API_PREFIX}/books/b1", json={}).status_code == 400


def test_renaming_onto_a_book_you_already_own_is_a_409():
    """A real case — fixing a misread title to one you own. Resolving it is a
    decision (merge? keep both?), so the API refuses rather than defaulting."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן", "בית")
    with TestClient(_app(store=store)) as client:
        r = client.patch(f"{API_PREFIX}/books/b2", json={"title": "אבן"})
    assert r.status_code == 409
    assert store.get(TEST_LIBRARY, "b2").title == "בית", "the refused edit stuck"


def test_manual_add_lands_as_manual_with_one_copy():
    with TestClient(_app()) as client:
        r = client.post(f"{API_PREFIX}/books",
                        json={"title": "  ספר ידני  ", "author": " מחבר "})
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "ספר ידני", "whitespace was not trimmed"
    assert body["status"] == "manual" and body["copy_count"] == 1
    assert body["added_at"] == "2026-08-07T12:00:00+00:00"


def test_manual_add_of_a_book_you_own_is_a_409():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        r = client.post(f"{API_PREFIX}/books",
                        json={"title": "אבן", "author": "פול קארני"})
    assert r.status_code == 409


def test_delete_removes_from_the_library_and_is_not_idempotent_about_it():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        assert client.delete(f"{API_PREFIX}/books/b1").status_code == 204
        assert client.delete(f"{API_PREFIX}/books/b1").status_code == 404
    assert store.count(TEST_LIBRARY) == 0


# --- copies (P1.7) ---------------------------------------------------------

def test_add_copy_creates_a_second_manual_copy():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        r = client.post(f"{API_PREFIX}/books/b1/copies",
                        json={"label": "כריכה רכה", "tags": [" מתנה ", ""],
                             "condition": " טוב "})
    assert r.status_code == 201
    body = r.json()
    assert body["copy_count"] == 2
    new = next(c for c in body["copies"] if c["label"] == "כריכה רכה")
    assert new["status"] == "manual"
    assert new["tags"] == ["מתנה"], "blank tags should be dropped, others trimmed"
    assert new["condition"] == "טוב"
    original = next(c for c in body["copies"] if c["id"] != new["id"])
    assert original["status"] == "auto", "the original copy must be untouched"


def test_patch_copy_edits_metadata_without_touching_status():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        r = client.patch(f"{API_PREFIX}/books/b1/copies/c1",
                         json={"condition": "קרוע"})
    assert r.status_code == 200
    copy = r.json()["copies"][0]
    assert copy["condition"] == "קרוע"
    assert copy["status"] == "auto", "metadata edit must not mark it manual"


def test_lend_then_return_a_copy():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        lent = client.post(f"{API_PREFIX}/books/b1/copies/c1/lend",
                           json={"lent_to": "דנה", "due_at": "2026-09-01"})
        assert lent.status_code == 200
        lending = lent.json()["copies"][0]["lending"]
        assert lending == {"lent_to": "דנה", "lent_at": "2026-08-07T12:00:00+00:00",
                           "due_at": "2026-09-01", "returned_at": None,
                           "is_out": True}

        returned = client.post(f"{API_PREFIX}/books/b1/copies/c1/return")
    assert returned.status_code == 200
    lending = returned.json()["copies"][0]["lending"]
    assert lending["is_out"] is False
    assert lending["returned_at"] == "2026-08-07T12:00:00+00:00"
    assert lending["lent_to"] == "דנה", "the loan history must not be cleared"


def test_lending_an_already_out_copy_is_a_409_naming_the_borrower():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        client.post(f"{API_PREFIX}/books/b1/copies/c1/lend",
                    json={"lent_to": "דנה"})
        r = client.post(f"{API_PREFIX}/books/b1/copies/c1/lend",
                        json={"lent_to": "יוסי"})
    assert r.status_code == 409
    assert "דנה" in r.json()["detail"]


def test_returning_a_copy_that_was_never_lent_is_a_409():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        r = client.post(f"{API_PREFIX}/books/b1/copies/c1/return")
    assert r.status_code == 409


def test_a_copy_action_on_an_unknown_copy_id_is_404():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        assert client.patch(f"{API_PREFIX}/books/b1/copies/nope",
                            json={"condition": "x"}).status_code == 404
        assert client.post(f"{API_PREFIX}/books/b1/copies/nope/lend",
                           json={"lent_to": "דנה"}).status_code == 404
        assert client.post(
            f"{API_PREFIX}/books/b1/copies/nope/return").status_code == 404


def test_a_copy_action_on_a_book_in_another_library_is_404():
    """§4.2, same as every other book route: foreign reads as absent."""
    other = LibraryRef("lib-other", "Other")
    store = MemoryBookStore()
    store.save(other, new_book(id="b9", library_id=other.id, title="סוד",
                               copy_id="c9"))
    with TestClient(_app(store=store)) as client:
        assert client.post(f"{API_PREFIX}/books/b9/copies",
                           json={}).status_code == 404
        assert client.post(f"{API_PREFIX}/books/b9/copies/c9/lend",
                           json={"lent_to": "דנה"}).status_code == 404


def test_list_filters_by_lent_out():
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן", "בית")
    with TestClient(_app(store=store)) as client:
        client.post(f"{API_PREFIX}/books/b1/copies/c1/lend",
                    json={"lent_to": "דנה"})
        r = client.get(f"{API_PREFIX}/books?lent_out=true")
    assert [b["id"] for b in r.json()["items"]] == ["b1"]


def test_export_is_reachable_and_not_swallowed_by_the_id_route():
    """/books/export is declared BEFORE /books/{book_id}. Registered the other
    way round, "export" arrives as a book id and 404s — invisible until
    someone clicks Export."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        assert client.get(f"{API_PREFIX}/books/export").status_code == 200


def test_csv_export_carries_a_bom_so_excel_reads_hebrew():
    """Without it Excel shows mojibake, and "my export is broken" becomes
    indistinguishable from "your data is broken"."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן", "בית")
    with TestClient(_app(store=store)) as client:
        r = client.get(f"{API_PREFIX}/books/export?format=csv")
    assert r.status_code == 200
    assert r.content.startswith(b"\xef\xbb\xbf")
    assert "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("title,author,status")
    assert "אבן" in text and "בית" in text


def test_export_is_the_whole_library_not_a_page():
    """An export that stops at page 1 is worse than no export — it looks
    complete."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, *[f"ספר {i:03d}" for i in range(1, 121)])
    with TestClient(_app(store=store)) as client:
        rows = client.get(f"{API_PREFIX}/books/export?format=csv") \
            .content.decode("utf-8-sig").strip().splitlines()
        data = client.get(f"{API_PREFIX}/books/export?format=json").json()
    assert len(rows) == 121, "header + 120 books"
    assert len(data["books"]) == 120


def test_the_download_is_named_for_the_library_and_the_day():
    """An export lands in a Downloads folder next to everyone else's files,
    and it is a SNAPSHOT — the same generic name twice becomes
    "booksnap-library (1).csv" and neither file says what it holds or when."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "אבן")
    with TestClient(_app(store=store)) as client:
        for fmt in ("csv", "json"):
            cd = client.get(f"{API_PREFIX}/books/export?format={fmt}") \
                .headers["content-disposition"]
            assert f"books-Test-library-2026-08-07.{fmt}" in cd, cd


def test_a_hebrew_library_name_survives_the_download_header():
    """A bare `filename=` is ASCII-only, so a Hebrew library name would arrive
    mangled or be dropped. RFC 6266's `filename*` carries the real one; the
    ASCII fallback keeps the DATE rather than degrading to a generic name."""
    hebrew = LibraryRef(id="lib-he", label="הספרייה שלי")
    store = MemoryBookStore()
    _seed(store, hebrew, "אבן")
    with TestClient(_app(principal=StubPrincipal(library=hebrew),
                         store=store)) as client:
        cd = client.get(f"{API_PREFIX}/books/export").headers[
            "content-disposition"]
    assert "filename*=UTF-8''" in cd
    assert quote("הספרייה-שלי") in cd, cd
    assert 'filename="books-2026-08-07.csv"' in cd, cd


def test_export_rejects_an_unknown_format():
    with TestClient(_app()) as client:
        assert client.get(
            f"{API_PREFIX}/books/export?format=pdf").status_code == 422


def test_a_book_in_another_library_is_404_not_403():
    """§4.2 / P3.3: don't leak existence. The store already answers 'absent',
    so the route cannot leak it even by accident."""
    store = MemoryBookStore()
    other = LibraryRef("lib-other", "Other")
    store.save(other, new_book(id="b9", library_id=other.id, title="סוד",
                               copy_id="c9"))
    with TestClient(_app(store=store)) as client:
        assert client.get(f"{API_PREFIX}/books/b9").status_code == 404
        assert client.patch(f"{API_PREFIX}/books/b9",
                            json={"title": "x"}).status_code == 404
        assert client.delete(f"{API_PREFIX}/books/b9").status_code == 404
    assert store.get(other, "b9") is not None, "a foreign book was modified"


def test_unbound_principal_fails_loudly():
    """An app built without an identity adapter must error, not serve a
    default library. Silent defaults are how cross-tenant leaks start."""
    from fastapi import FastAPI
    from fastapi import Depends

    app = FastAPI()

    @app.get("/x")
    def x(lib: LibraryRef = Depends(deps.current_library)):
        return {"id": lib.id}

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/x")
    assert r.status_code == 500, r.status_code


def test_unknown_route_is_404():
    with TestClient(_app()) as client:
        assert client.get(f"{API_PREFIX}/nope").status_code == 404


# --- meta-tests over every route -----------------------------------------

def test_every_api_route_is_versioned():
    routes = _api_routes(_app())
    assert routes, "no API routes found — the meta-tests would pass vacuously"
    bad = [p for p, _ in routes if not p.startswith(API_PREFIX + "/")]
    assert not bad, f"unversioned API routes: {bad} (H3)"


def test_openapi_paths_are_all_under_v1():
    """The same rule read off the published contract rather than the router —
    it is the schema that clients and the TS generator actually see."""
    # Not pooled: `.openapi()` memoises the document on the app object, and a
    # recycled app carrying that cache would hand a later test a schema it did
    # not build.
    schema = _app(recycle=False).openapi()
    bad = [p for p in schema["paths"] if not p.startswith(API_PREFIX + "/")]
    assert not bad, f"schema paths outside {API_PREFIX}: {bad} (H3)"


def _dependency_calls(route: APIRoute) -> set:
    """Every callable in a route's dependency tree, flattened."""
    seen = set()
    stack = [route.dependant]
    while stack:
        d = stack.pop()
        if d.call is not None:
            seen.add(d.call)
        stack.extend(d.dependencies)
    return seen


# The ONLY routes allowed to skip `current_library` (P3.1). They are how a
# caller learns which libraries it may name, so requiring them to resolve one
# first is circular: a client with no valid selection — a fresh browser, a
# membership just removed — could never recover. They are user-scoped
# instead, which the second half of the meta-test below asserts, so "exempt"
# never means "unscoped".
#
# A closed list, deliberately: adding a route here is an edit to a test, which
# is the point at which someone has to justify it.
#
# ⚠ Keyed by (METHOD, path), not path alone — P3.2's review caught the sharper
# version of the same hole: a future `DELETE /libraries/{library_id}` (the
# deliberately-absent delete-library route) or P4.3's member routes at these
# paths would inherit a path-only exemption silently and could ship unpoliced
# with every meta-test green.
_USER_SCOPED = {
    ("GET", f"{API_PREFIX}/libraries"),
    ("POST", f"{API_PREFIX}/libraries"),
    ("PATCH", f"{API_PREFIX}/libraries/{{library_id}}"),
}


def _exempt(path: str, route: APIRoute) -> bool:
    return all((m, path) in _USER_SCOPED for m in route.methods)


def test_every_api_route_resolves_its_library_from_the_principal():
    routes = _api_routes(_app())
    assert routes, "no API routes found — this meta-test would pass vacuously"
    bad = [p for p, r in routes
           if not _exempt(p, r)
           and deps.current_library not in _dependency_calls(r)]
    assert not bad, (
        f"routes not library-scoped: {bad} — every route resolves its library "
        f"through deps.current_library (H2)"
    )


def test_every_api_route_declares_exactly_one_policy_capability():
    """P3.2's meta-test, promised by this file's own docstring since P3.1: a
    route with NO policy declaration FAILS rather than defaulting to open.

    Exactly one, not at least one: two `require(...)` dependencies on a route
    would enforce the STRICTER intersection today and read as either-or to the
    next person — a disagreement between what the code does and what it says.

    The user-scoped routes are exempt from the LIBRARY-capability axis
    (same closed list, same circularity argument) — but not from policy:
    the rename route consults the same matrix directly, which
    `test_renaming_a_library_is_admin_only` proves over HTTP.
    """
    from app.api.policy import CAPABILITY_ATTR

    routes = _api_routes(_app())
    assert routes, "no API routes found — this meta-test would pass vacuously"
    bad = []
    for path, route in routes:
        if _exempt(path, route):
            continue
        declared = [getattr(c, CAPABILITY_ATTR) for c in _dependency_calls(route)
                    if hasattr(c, CAPABILITY_ATTR)]
        if len(declared) != 1:
            bad.append((path, declared))
    assert not bad, (
        f"routes without exactly one policy capability: {bad} — declare it "
        "with Depends(require(Capability.X)) (P3.2)"
    )


def _viewer_of_second_library(role: Role = Role.VIEWER):
    """A principal whose OWN library is lib-test but who holds `role` in
    lib-2 — requests carrying the lib-2 header exercise the matrix for real,
    because the dev-trusted own-library shortcut cannot apply there."""
    p = StubPrincipal()
    tenancy = _tenancy(p)
    # A SECOND account, not a second library of the first: a role is held per
    # account since P3.7b, so lib-2 under TEST_ACCOUNT would inherit ADMIN and
    # the matrix would never be exercised.
    tenancy.save_account(Account(id=OTHER_ACCOUNT))
    tenancy.save_membership(Membership(p.id, OTHER_ACCOUNT, role))
    tenancy.save_library(Library(id="lib-2", account_id=OTHER_ACCOUNT,
                                 label="ההורים"))
    return p, tenancy


def test_a_viewer_browses_but_may_not_edit_capture_or_see_photos():
    """§4.2 over real HTTP, including §12.2 #1's settled cell: the catalog
    answers, the photographs and every write refuse with 403 — not 404,
    because the caller IS a member and the library's existence is not the
    secret (§4.2 protects OTHER households' libraries; this is their own)."""
    p, tenancy = _viewer_of_second_library()
    with TestClient(_app(principal=p, tenancy=tenancy)) as c:
        h = {deps.LIBRARY_HEADER: "lib-2"}
        assert c.get(f"{API_PREFIX}/books", headers=h).status_code == 200
        assert c.get(f"{API_PREFIX}/shelves", headers=h).status_code == 200
        denied = [
            ("post", f"{API_PREFIX}/books",
             dict(json={"title": "ספר", "author": ""})),
            ("post", f"{API_PREFIX}/images",
             dict(files={"file": ("a.png", _png(), "image/png")})),
            ("post", f"{API_PREFIX}/shelves", dict(json={"label": "מדף"})),
        ]
        for method, url, kw in denied:
            r = getattr(c, method)(url, headers=h, **kw)
            assert r.status_code == 403, (method, url, r.status_code)
        # §12.2 #1's cell: photo bytes AND metadata are Editor+. The 403
        # comes from the dependency, BEFORE any store lookup — deliberately,
        # so a viewer cannot even probe which keys exist.
        key = "0" * 64 + ".jpg"
        for tail in ("", "/full", "/thumb"):
            r = c.get(f"{API_PREFIX}/images/{key}{tail}", headers=h)
            assert r.status_code == 403, (tail, "a viewer saw a photograph")


def test_an_editor_captures_but_only_an_admin_deletes_photos():
    """The one place §4.2 splits editor from admin on an existing route:
    "delete photos" sits in the admin column, because deleting a photo
    destroys the evidence every read of it points at."""
    p, tenancy = _viewer_of_second_library(role=Role.EDITOR)
    with _blobs() as blobs:
        with TestClient(_app(principal=p, tenancy=tenancy, blobs=blobs)) as c:
            h = {deps.LIBRARY_HEADER: "lib-2"}
            up = c.post(f"{API_PREFIX}/images", headers=h,
                        files={"file": ("a.png", _png(), "image/png")})
            assert up.status_code == 201, "an editor uploads photos (§4.2)"
            key = up.json()["key"]
            assert c.get(f"{API_PREFIX}/images/{key}/thumb",
                         headers=h).status_code == 200
            r = c.delete(f"{API_PREFIX}/images/{key}", headers=h)
            assert r.status_code == 403, "an editor deleted a photo (§4.2)"
            tenancy.save_membership(Membership(p.id, OTHER_ACCOUNT, Role.ADMIN))
            r = c.delete(f"{API_PREFIX}/images/{key}", headers=h)
            assert r.status_code == 204


def test_a_membership_row_on_your_own_library_outranks_the_dev_trusted_fallback():
    """`_role` consults the membership row FIRST and falls back to ADMIN only
    when no row exists for the principal's own library. Reordering those two
    branches would silently grant ADMIN to anyone whose own-library row says
    less — invisible today (the bootstrap writes ADMIN) and a landmine the
    day P4.3 lets an admin demote someone. Pinned by planting a VIEWER row
    on the ACCOUNT that owns the principal's own library and watching a
    write refuse."""
    p = StubPrincipal()
    tenancy = _tenancy(p)   # seeds ADMIN…
    tenancy.save_membership(Membership(p.id, TEST_ACCOUNT, Role.VIEWER))
    with TestClient(_app(principal=p, tenancy=tenancy)) as c:
        r = c.post(f"{API_PREFIX}/books", json={"title": "ס", "author": ""})
        assert r.status_code == 403, (
            "a stored viewer role on the caller's own library was ignored — "
            "the dev-trusted ADMIN fallback must lose to a real row"
        )


def test_renaming_a_library_is_admin_only():
    """The user-scoped routes are exempt from `require()`'s transport, not
    from the matrix — the rename consults the same POLICY table directly."""
    p, tenancy = _viewer_of_second_library(role=Role.EDITOR)
    with TestClient(_app(principal=p, tenancy=tenancy)) as c:
        r = c.patch(f"{API_PREFIX}/libraries/lib-2", json={"label": "חדש"})
        assert r.status_code == 403
        tenancy.save_membership(Membership(p.id, OTHER_ACCOUNT, Role.ADMIN))
        r = c.patch(f"{API_PREFIX}/libraries/lib-2", json={"label": "חדש"})
        assert r.status_code == 200
        assert r.json()["label"] == "חדש"


def test_a_foreign_library_is_still_404_never_403_now_that_policy_exists():
    """§4.2's ordering, pinned: existence is decided BEFORE capability. A 403
    for a library the caller does not belong to would confirm another
    household's collection exists — the resolver answers 404 first, and the
    policy check must never run for it."""
    p = StubPrincipal()
    tenancy = _tenancy(p)
    # Exists, owned by a customer the caller has nothing to do with.
    tenancy.save_account(Account(id=OTHER_ACCOUNT))
    tenancy.save_library(Library(id="lib-other", account_id=OTHER_ACCOUNT,
                                 label="זרים"))
    with TestClient(_app(principal=p, tenancy=tenancy)) as c:
        for lib in ("lib-other", "lib-fictional"):
            r = c.post(f"{API_PREFIX}/books", json={"title": "ס", "author": ""},
                       headers={deps.LIBRARY_HEADER: lib})
            assert r.status_code == 404, (lib, r.status_code)


def test_the_user_scoped_routes_are_still_scoped_by_something():
    """The exemption is from the LIBRARY axis, not from tenancy. A route that
    resolved neither a library nor a user would serve everyone's data —
    and it would pass the test above simply by being on the list."""
    routes = {(m, p): r for p, r in _api_routes(_app()) for m in r.methods}
    for method, path in _USER_SCOPED:
        assert (method, path) in routes, \
            f"{method} {path} is exempted but does not exist"
        assert deps.get_principal in _dependency_calls(routes[(method, path)]), \
            f"{method} {path} resolves neither a library nor a user"


def test_library_resolution_has_exactly_one_implementation():
    """H2 says 'exactly one function'. Assert it structurally, so a second
    resolver added for convenience is a test failure and not a discovery at
    pillar 4.

    ⚠ This used to count occurrences of the string `principal.library`. P3.1
    made the resolver read it twice (the no-header default, and the
    header-names-my-own-library short circuit), so the string count stopped
    meaning anything — what the rule was always about is that no OTHER
    function decides which library a request operates on.
    """
    import ast
    import inspect

    src = inspect.getsource(deps)
    assert src.count("def current_library") == 1
    tree = ast.parse(src)
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or fn.name == "current_library":
            continue
        reads = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Attribute) and n.attr == "library"]
        assert not reads, (
            f"{fn.name}() in app/api/deps.py resolves a library too — H2 says "
            "exactly one function does"
        )


def test_the_library_meta_resolves_is_always_one_the_switcher_lists():
    """The invariant `list_libraries` deliberately does NOT patch over: the
    resolver serves the principal's default library without a store lookup,
    and the switcher lists store rows, so a missing membership would show the
    user a library the switcher says they do not have."""
    with TestClient(_app()) as client:
        current = client.get(f"{API_PREFIX}/meta").json()["library"]["id"]
        listed = [row["id"] for row in
                  client.get(f"{API_PREFIX}/libraries").json()]
    assert current in listed, (
        f"{current} is resolvable but unlisted — app/main.py's bootstrap is "
        "what keeps these two in step"
    )


def test_no_module_level_mutable_state_in_api():
    """H2/§1.3: the tuning server's module-global job dict is exactly what a
    second tenant breaks. Assert the new api layer has no module-level dict,
    list or set — the shape that bug takes."""
    import ast

    offenders = []
    for f in sorted((REPO_ROOT / "app").rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in tree.body:  # module level only
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if isinstance(value, (ast.Dict, ast.List, ast.Set, ast.DictComp,
                                  ast.ListComp, ast.SetComp)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [t.id for t in targets if isinstance(t, ast.Name)]
                # Exempt by convention, because neither is the failure mode
                # this test exists for (a per-request cache or registry):
                #   SHOUTING_CASE — constants, not written to at runtime;
                #   __dunder__    — module protocol, e.g. __all__.
                def _exempt(n: str) -> bool:
                    return n.isupper() or (n.startswith("__") and n.endswith("__"))

                if any(not _exempt(n) for n in names):
                    offenders.append(
                        f"{f.relative_to(REPO_ROOT).as_posix()}:{node.lineno} {names}"
                    )
    assert not offenders, "module-level mutable state: " + "; ".join(offenders)


# --- shelves and captures (P2.2) -----------------------------------------

def test_a_photo_with_no_shelf_still_gets_one():
    """The binding, and the item's whole point. A capture with no shelf is a
    read with nothing to reconcile against (§5.6), so "assign it later" is not
    a state the model offers — the photo lands on a fresh UNNAMED shelf, and
    *Unassigned* on screen means not yet named.

    The response carries the shelf as well as the capture: when the shelf was
    auto-created the client has no other way to learn its id.
    """
    c = TestClient(_app())
    r = c.post(f"{API_PREFIX}/captures", json={"image_id": "IMG_6082"})
    assert r.status_code == 201, r.text
    body = r.json()

    assert body["shelf_created"] is True
    assert body["shelf"]["label"] == "", "an auto-created shelf was named"
    assert body["shelf"]["depth_count"] == 1
    assert body["capture"]["shelf_id"] == body["shelf"]["id"]
    assert body["capture"]["depth"] == 1
    assert body["capture"]["image_id"] == "IMG_6082"

    listed = c.get(f"{API_PREFIX}/shelves").json()
    assert [s["id"] for s in listed] == [body["shelf"]["id"]]
    assert listed[0]["capture_count"] == 1


def test_a_photo_can_name_an_existing_shelf_and_appends_after_the_last():
    """Several captures of one shelf are ordered (§5.3), and the order is
    computed rather than asked for: intake is "photograph it left to right",
    so a caller supplying its own number is two clients waiting to disagree."""
    c = TestClient(_app())
    shelf = c.post(f"{API_PREFIX}/shelves", json={"label": "סלון"}).json()

    first = c.post(f"{API_PREFIX}/captures",
                   json={"shelf_id": shelf["id"], "image_id": "a"}).json()
    second = c.post(f"{API_PREFIX}/captures",
                    json={"shelf_id": shelf["id"], "image_id": "b"}).json()

    assert first["shelf_created"] is False
    assert [first["capture"]["order"], second["capture"]["order"]] == [0, 1]
    got = c.get(f"{API_PREFIX}/shelves/{shelf['id']}/captures").json()
    assert [x["image_id"] for x in got] == ["a", "b"]


def test_a_photo_cannot_be_filed_at_a_row_that_was_never_declared():
    """§5.7: depth is declared, never detected. A 409 naming the declared
    depth, not a silent clamp to 1 — filing a photo at a row that does not
    exist gives reconciliation a location with no counterpart in the room."""
    c = TestClient(_app())
    shelf = c.post(f"{API_PREFIX}/shelves", json={}).json()

    r = c.post(f"{API_PREFIX}/captures",
               json={"shelf_id": shelf["id"], "depth": 2})
    assert r.status_code == 409, r.text
    assert "2" in r.json()["detail"]

    deeper = c.post(f"{API_PREFIX}/shelves/{shelf['id']}/depths").json()
    assert deeper["depth_count"] == 2
    ok = c.post(f"{API_PREFIX}/captures",
                json={"shelf_id": shelf["id"], "depth": 2})
    assert ok.status_code == 201, ok.text


def test_rebinding_a_photo_moves_it_and_gives_it_a_fresh_position():
    """The inline assignment the intake UI performs. A photo moved to another
    shelf keeps no memory of where it sat on the old one — an inherited order
    would collide with whatever already occupies that slot."""
    c = TestClient(_app())
    auto = c.post(f"{API_PREFIX}/captures", json={"image_id": "a"}).json()
    target = c.post(f"{API_PREFIX}/shelves", json={"label": "מטבח"}).json()
    c.post(f"{API_PREFIX}/captures",
           json={"shelf_id": target["id"], "image_id": "resident"})

    moved = c.patch(f"{API_PREFIX}/captures/{auto['capture']['id']}",
                    json={"shelf_id": target["id"]})
    assert moved.status_code == 200, moved.text
    assert moved.json()["capture"]["shelf_id"] == target["id"]
    assert moved.json()["capture"]["order"] == 1, "it collided with the resident"

    # The shelf it left is now empty, and therefore deletable.
    assert c.delete(f"{API_PREFIX}/shelves/{auto['shelf']['id']}"
                    ).status_code == 204


def test_naming_a_shelf_is_optional_in_both_directions():
    """Identity is free (owner's call): a shelf may be created unnamed, named
    later, and un-named again. `""` is a legal value, not a missing one."""
    c = TestClient(_app())
    shelf = c.post(f"{API_PREFIX}/shelves", json={}).json()
    assert shelf["label"] == ""

    named = c.patch(f"{API_PREFIX}/shelves/{shelf['id']}",
                    json={"label": "סלון, כוננית 2"}).json()
    assert named["label"] == "סלון, כוננית 2"

    cleared = c.patch(f"{API_PREFIX}/shelves/{shelf['id']}",
                      json={"label": ""}).json()
    assert cleared["label"] == "", "clearing a label was treated as absent"


def test_a_shelf_with_photos_cannot_be_deleted():
    """§5.6 at the HTTP edge: 409, not a cascade. Its captures are the record
    a re-read diffs against, and destroying them on a misclick is exactly the
    destructive direction the whole design refuses."""
    c = TestClient(_app())
    made = c.post(f"{API_PREFIX}/captures", json={"image_id": "a"}).json()
    shelf_id = made["shelf"]["id"]

    r = c.delete(f"{API_PREFIX}/shelves/{shelf_id}")
    assert r.status_code == 409, r.text
    assert c.get(f"{API_PREFIX}/shelves/{shelf_id}").status_code == 200

    assert c.delete(f"{API_PREFIX}/captures/{made['capture']['id']}"
                    ).status_code == 204
    assert c.delete(f"{API_PREFIX}/shelves/{shelf_id}").status_code == 204


def test_the_wishlist_is_absent_from_the_shelf_list_unless_asked_for():
    c = TestClient(_app())
    c.post(f"{API_PREFIX}/shelves", json={"label": "סלון"})
    wish = c.post(f"{API_PREFIX}/shelves",
                  json={"label": "משאלות", "virtual": True}).json()

    assert wish["id"] not in [s["id"] for s in
                             c.get(f"{API_PREFIX}/shelves").json()]
    assert wish["id"] in [
        s["id"] for s in
        c.get(f"{API_PREFIX}/shelves", params={"include_virtual": True}).json()
    ]
    # And it never gains a row behind — it is not furniture.
    assert c.post(f"{API_PREFIX}/shelves/{wish['id']}/depths"
                  ).status_code == 409


def test_a_shelf_in_another_library_is_404_not_403():
    """§4.2: absent and forbidden are the same answer, so the API cannot leak
    which shelf ids exist in someone else's library."""
    shared = MemoryShelfStore()
    mine = TestClient(_app(shelves=shared))
    theirs = TestClient(_app(
        StubPrincipal(LibraryRef("lib-other", "Other"), "p-other"),
        shelves=shared,
    ))
    made = mine.post(f"{API_PREFIX}/captures", json={"image_id": "a"}).json()
    shelf_id, cap_id = made["shelf"]["id"], made["capture"]["id"]

    assert theirs.get(f"{API_PREFIX}/shelves/{shelf_id}").status_code == 404
    assert theirs.get(f"{API_PREFIX}/captures/{cap_id}").status_code == 404
    assert theirs.delete(f"{API_PREFIX}/shelves/{shelf_id}").status_code == 404
    assert theirs.get(f"{API_PREFIX}/shelves").json() == []
    # Filing a photo onto a foreign shelf is the same answer, not a 403.
    assert theirs.post(f"{API_PREFIX}/captures",
                       json={"shelf_id": shelf_id}).status_code == 404
    assert mine.get(f"{API_PREFIX}/shelves/{shelf_id}").status_code == 200


# --- images (P2.3) --------------------------------------------------------

def test_a_photo_round_trips_and_comes_back_decodable():
    """The item in one test: bytes in, bytes out, still an image. Dimensions
    come back too, so the review grid can reserve an aspect ratio before the
    picture arrives instead of reflowing on every tile."""
    from PIL import Image

    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        r = c.post(f"{API_PREFIX}/images",
                   files={"file": ("IMG_6082.png", _png((40, 30)), "image/png")})
        assert r.status_code == 201, r.text
        meta = r.json()
        assert (meta["width"], meta["height"]) == (40, 30)
        assert meta["content_type"] == "image/png"
        assert meta["filename"] == "IMG_6082.png"

        full = c.get(f"{API_PREFIX}/images/{meta['key']}/full")
        assert full.status_code == 200
        assert Image.open(io.BytesIO(full.content)).size == (40, 30)

        thumb = c.get(f"{API_PREFIX}/images/{meta['key']}/thumb")
        assert thumb.status_code == 200
        assert thumb.headers["content-type"] == "image/jpeg"
        assert Image.open(io.BytesIO(thumb.content)).size[0] <= 480


def test_uploading_the_same_photo_twice_stores_it_once():
    """§12.3 #13. Re-uploading after a browser refresh is the NORMAL case with
    a camera roll, not an edge one — so the second attempt must cost a hash
    rather than a duplicate, and hand back the same key."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        data = _png()
        first = c.post(f"{API_PREFIX}/images",
                       files={"file": ("a.png", data, "image/png")}).json()
        again = c.post(f"{API_PREFIX}/images",
                       files={"file": ("b.png", data, "image/png")}).json()

        assert first["key"] == again["key"]
        stored = list((Path(blobs.root)).rglob("*.png"))
        assert len(stored) == 1, f"stored twice: {stored}"
        # The filename follows the LATEST upload — same photo, but this time
        # the name may be the better one.
        assert c.get(f"{API_PREFIX}/images/{first['key']}"
                     ).json()["filename"] == "b.png"


def test_a_rotated_phone_photo_is_stored_upright():
    """Phone photos carry an EXIF rotation flag. `cv2.imread` honours it and
    PIL does not unless asked, so left alone the engine would read an upright
    shelf while the review grid showed it on its side — and the person
    reviewing would reasonably conclude the reader was broken.

    Normalising at STORE time is what makes those two agree, and it is also why
    the same photo uploaded upright and rotated must not store twice: identical
    pixels, one key.
    """
    from PIL import Image

    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        # orientation 6 = rotate 90°: a 40x30 image displays as 30x40.
        r = c.post(f"{API_PREFIX}/images",
                   files={"file": ("p.jpg", _jpeg((40, 30), orientation=6),
                                   "image/jpeg")})
        meta = r.json()
        assert (meta["width"], meta["height"]) == (30, 40), \
            "EXIF orientation was not applied at store time"

        served = Image.open(io.BytesIO(
            c.get(f"{API_PREFIX}/images/{meta['key']}/full").content))
        assert served.size == (30, 40)
        assert served.getexif().get(0x0112) in (None, 1), \
            "the stored bytes still carry a rotation flag"


def test_a_file_that_is_not_an_image_is_refused_by_decoding_it():
    """Never by trusting the filename or the declared content type — both are
    the client's own claim, and a store that believes them will serve whatever
    was really uploaded back to a browser under an image content type."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        r = c.post(f"{API_PREFIX}/images",
                   files={"file": ("shelf.jpg", b"#!/bin/sh\nrm -rf /",
                                   "image/jpeg")})
        assert r.status_code == 415, r.text


def test_a_key_cannot_escape_the_library_directory():
    """The key arrives in a URL. `../` in a path segment is how a store that
    just joins strings ends up serving somebody's private key file, so a key is
    validated as `<64 hex>.<ext>` rather than trusted."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        for evil in ("..%2f..%2fproduct.db", "....%2f%2fetc%2fpasswd.jpg"):
            r = c.get(f"{API_PREFIX}/images/{evil}/full")
            assert r.status_code == 404, (evil, r.status_code)


def test_a_photo_in_another_library_is_404_not_403():
    """§4.2 again, and here it also means one tenant cannot read another's
    photos by guessing a hash they happen to know."""
    with _blobs() as blobs:
        mine = TestClient(_app(blobs=blobs))
        theirs = TestClient(_app(
            StubPrincipal(LibraryRef("lib-other", "Other"), "p-other"),
            blobs=blobs,
        ))
        key = mine.post(f"{API_PREFIX}/images",
                        files={"file": ("a.png", _png(), "image/png")}
                        ).json()["key"]

        assert theirs.get(f"{API_PREFIX}/images/{key}").status_code == 404
        assert theirs.get(f"{API_PREFIX}/images/{key}/full").status_code == 404
        assert theirs.get(f"{API_PREFIX}/images/{key}/thumb").status_code == 404
        assert theirs.delete(f"{API_PREFIX}/images/{key}").status_code == 404
        assert mine.get(f"{API_PREFIX}/images/{key}/full").status_code == 200


def test_a_missing_thumbnail_is_re_derived_rather_than_reported_absent():
    """A variant is a CACHE. On screen "no thumbnail yet" and "this photo is
    gone" look identical, and only one of them is a real problem — so a
    deleted rendition must cost a re-render, not a broken tile."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        key = c.post(f"{API_PREFIX}/images",
                     files={"file": ("a.png", _png(), "image/png")}
                     ).json()["key"]
        cached = list(Path(blobs.root).rglob("*~thumb.jpg"))
        assert cached, "no thumbnail was cached at upload"
        for f in cached:
            f.unlink()

        assert c.get(f"{API_PREFIX}/images/{key}/thumb").status_code == 200
        assert list(Path(blobs.root).rglob("*~thumb.jpg")), "not re-cached"


def test_deleting_a_photo_takes_its_renditions_with_it():
    """Variants are a cache OF this original. A stale rendition surviving a
    delete means a wrong picture on a screen, which is worse than the directory
    scan that prevents it."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        key = c.post(f"{API_PREFIX}/images",
                     files={"file": ("a.png", _png(), "image/png")}
                     ).json()["key"]

        assert c.delete(f"{API_PREFIX}/images/{key}").status_code == 204
        assert list(Path(blobs.root).rglob("*~thumb.jpg")) == []
        assert c.get(f"{API_PREFIX}/images/{key}/full").status_code == 404
        assert c.delete(f"{API_PREFIX}/images/{key}").status_code == 404


# --- reads (P2.4) ----------------------------------------------------------
#
# StubReader/SlowStubReader implement app.ports.reader.Reader without
# booksnap, cv2 or tesseract — H4 ring 3's rule: this ring never invokes the
# real engine. QueuedJobRunner IS real (it is fast and pure-Python); only
# the engine is stubbed.

class StubReader:
    """Returns exactly the claims it is holding, ignoring `mode`. `_claims`
    is mutable so a test can set it up AFTER learning a real capture id from
    the API, then let the (already-submitted-later) job pick it up."""

    def __init__(self, claims: list[ReadClaim] | None = None,
                 unavailable: str | None = None):
        self._claims = claims or []
        # Every mode is available to a stub — it needs no credential, which is
        # exactly why the preflight lives on the port and not in the route.
        # A test that wants the refusal sets this.
        self._unavailable = unavailable

    def read(self, library, requests, *, mode, progress=None, should_stop=None):
        if progress:
            progress({"stage": "done", "total": len(requests)})
        return list(self._claims)

    def unavailable(self, mode: str) -> str | None:
        return self._unavailable

    def code_version(self) -> dict:
        return {"sha": "stub", "branch": "test", "dirty": False}

    def config_snapshot(self) -> dict:
        return {"stub": True}


class SlowStubReader:
    """Produces one claim at a time with a short pause between each, checking
    `should_stop` before every one — enough real time for a test to call the
    stop endpoint mid-read and see it actually take effect, without waiting
    anywhere near a real engine's ~10s/spine."""

    def __init__(self, capture_id: str, steps: int = 200, step_s: float = 0.01):
        self._capture_id = capture_id
        self._steps = steps
        self._step_s = step_s

    def read(self, library, requests, *, mode, progress=None, should_stop=None):
        out = []
        for i in range(self._steps):
            if should_stop and should_stop():
                break
            out.append(ReadClaim(spine_id=f"sp{i}", capture_id=self._capture_id,
                                 title=f"claim {i}", tier="auto"))
            time.sleep(self._step_s)
        return out

    def unavailable(self, mode: str) -> str | None:
        return None

    def code_version(self) -> dict:
        return {"sha": "stub", "dirty": False}

    def config_snapshot(self) -> dict:
        return {}


def _wait_until_settled(client, shelf_id: str, read_id: str, *, timeout: float = 2.0):
    """Poll GET .../reads/{id} until its status leaves 'running'. The job
    runs on a real background thread even with a stub engine, so a test has
    to synchronise on it somehow — this is that somehow."""
    deadline = time.monotonic() + timeout
    body = None
    while time.monotonic() < deadline:
        body = client.get(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.01)
    raise AssertionError(f"read did not settle within {timeout}s: {body}")


def test_two_concurrent_reads_in_two_libraries_do_not_observe_each_other():
    """P3.4's named test case, over real HTTP: one user, two libraries,
    one QueuedJobRunner. Each read reports its own library's progress,
    stopping one leaves the other running, and the tenant key the router
    hands the runner is the LIBRARY id — the fairness axis — pinned with a
    spy, because dropping `tenant=` in reads.py would silently collapse
    every library into one queue and no adapter-ring test could see it."""
    import threading

    p = StubPrincipal()
    tenancy = _tenancy(p)
    tenancy.save_library(Library(id="lib-2", account_id=TEST_ACCOUNT,
                                 label="שניה"))

    release = {TEST_LIBRARY.id: threading.Event(), "lib-2": threading.Event()}

    class GatedReader:
        """Blocks per-library until the test releases it, then produces one
        claim naming its own library — so a leak would be visible in the
        claims themselves, not only in timing."""

        def read(self, library, requests, *, mode, progress=None,
                 should_stop=None):
            if progress:
                progress({"lib": library.id})
            deadline = time.monotonic() + 5
            while (not release[library.id].is_set()
                   and not (should_stop and should_stop())):
                if time.monotonic() > deadline:
                    raise AssertionError("gate never released")
                time.sleep(0.01)
            return [ReadClaim(spine_id="sp1",
                              capture_id=requests[0].capture_id,
                              title=f"ספר {library.id}", tier="auto")]

        def unavailable(self, mode):
            return None

        def code_version(self):
            return {}

        def config_snapshot(self):
            return {}

    class SpyRunner(QueuedJobRunner):
        def __init__(self):
            super().__init__(workers=2)
            self.tenants = []

        def submit(self, job_id, fn, *, tenant="", retries=0):
            self.tenants.append(tenant)
            super().submit(job_id, fn, tenant=tenant, retries=retries)

    spy = SpyRunner()
    with _blobs() as blobs:
        c = TestClient(_app(principal=p, tenancy=tenancy, blobs=blobs,
                            reader=GatedReader(), jobs=spy))
        h2 = {deps.LIBRARY_HEADER: "lib-2"}

        def setup(headers):
            key = c.post(f"{API_PREFIX}/images", headers=headers,
                         files={"file": ("a.png", _png(), "image/png")}
                         ).json()["key"]
            made = c.post(f"{API_PREFIX}/captures", headers=headers,
                          json={"image_id": key}).json()
            return made["shelf"]["id"]

        shelf_a, shelf_b = setup({}), setup(h2)
        read_a = c.post(f"{API_PREFIX}/shelves/{shelf_a}/reads",
                        json={"depth": 1, "mode": "spines"}).json()["id"]
        read_b = c.post(f"{API_PREFIX}/shelves/{shelf_b}/reads", headers=h2,
                        json={"depth": 1, "mode": "spines"}).json()["id"]
        assert spy.tenants == [TEST_LIBRARY.id, "lib-2"], (
            "the runner's fairness key must be the library id (P3.4)"
        )

        def poll(shelf, read, headers):
            return c.get(f"{API_PREFIX}/shelves/{shelf}/reads/{read}",
                         headers=headers).json()

        deadline = time.monotonic() + 5
        while True:
            a, b = poll(shelf_a, read_a, {}), poll(shelf_b, read_b, h2)
            if a.get("progress") and b.get("progress"):
                break
            assert time.monotonic() < deadline, (a, b)
            time.sleep(0.01)
        assert a["progress"] == {"lib": TEST_LIBRARY.id}
        assert b["progress"] == {"lib": "lib-2"}, \
            "one library's read reported the other's progress"

        c.post(f"{API_PREFIX}/shelves/{shelf_a}/reads/{read_a}/stop")
        a = _wait_until_settled(c, shelf_a, read_a)
        assert a["status"] == "stopped"
        assert poll(shelf_b, read_b, h2)["status"] == "running", \
            "stopping one library's read touched the other's"

        release["lib-2"].set()
        deadline = time.monotonic() + 5
        while True:
            b = poll(shelf_b, read_b, h2)
            if b["status"] != "running":
                break
            assert time.monotonic() < deadline, b
            time.sleep(0.01)
        assert b["status"] == "done"
        assert [cl["title"] for cl in b["claims"]] == ["ספר lib-2"]


def _seed_reads(store, library: LibraryRef, n: int, started_at: str) -> None:
    from app.domain import Read

    base = len(store.list_all_reads(library))
    for i in range(n):
        store.save_read(library, Read(
            id=f"seeded-{base + i}", library_id=library.id, shelf_id="sh-old",
            depth=1, capture_ids=("c",), mode="spines", started_at=started_at,
        ))


def test_the_run_rate_cap_blocks_a_retry_loop_and_only_this_library():
    """P3.6 (§1.2): one number against a stuck client, never against family.
    The cap counts a rolling hour PER LIBRARY — a burst in one must not
    freeze another — and reads older than the window never count, or the cap
    would turn into a lifetime quota."""
    from app.api.routers.reads import RUN_RATE_CAP_PER_HOUR

    p = StubPrincipal()
    tenancy = _tenancy(p)
    tenancy.save_library(Library(id="lib-2", account_id=TEST_ACCOUNT,
                                 label="שניה"))
    reads_store = MemoryReadStore()
    with _blobs() as blobs:
        c = TestClient(_app(principal=p, tenancy=tenancy, blobs=blobs,
                            reads=reads_store, reader=StubReader()))
        h2 = {deps.LIBRARY_HEADER: "lib-2"}

        def shelf_with_photo(headers):
            key = c.post(f"{API_PREFIX}/images", headers=headers,
                         files={"file": ("a.png", _png(), "image/png")}
                         ).json()["key"]
            return c.post(f"{API_PREFIX}/captures", headers=headers,
                          json={"image_id": key}).json()["shelf"]["id"]

        shelf_a, shelf_b = shelf_with_photo({}), shelf_with_photo(h2)

        # StubClock's "now" is 12:00; fill the window 30 minutes back.
        _seed_reads(reads_store, TEST_LIBRARY, RUN_RATE_CAP_PER_HOUR,
                    "2026-08-07T11:30:00+00:00")
        r = c.post(f"{API_PREFIX}/shelves/{shelf_a}/reads",
                   json={"depth": 1, "mode": "spines"})
        assert r.status_code == 429, r.text
        assert str(RUN_RATE_CAP_PER_HOUR) in r.json()["detail"]

        # The OTHER library is untouched by this library's burst.
        r2 = c.post(f"{API_PREFIX}/shelves/{shelf_b}/reads", headers=h2,
                    json={"depth": 1, "mode": "spines"})
        assert r2.status_code == 202, (
            "one library's retry loop froze another library's read"
        )


def test_reads_older_than_the_window_do_not_count_toward_the_cap():
    from app.api.routers.reads import RUN_RATE_CAP_PER_HOUR

    reads_store = MemoryReadStore()
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reads=reads_store,
                            reader=StubReader()))
        key = c.post(f"{API_PREFIX}/images",
                     files={"file": ("a.png", _png(), "image/png")}
                     ).json()["key"]
        shelf = c.post(f"{API_PREFIX}/captures",
                       json={"image_id": key}).json()["shelf"]["id"]
        _seed_reads(reads_store, TEST_LIBRARY, RUN_RATE_CAP_PER_HOUR * 2,
                    "2026-08-07T09:00:00+00:00")   # three hours before "now"
        r = c.post(f"{API_PREFIX}/shelves/{shelf}/reads",
                   json={"depth": 1, "mode": "spines"})
        assert r.status_code == 202, (
            "reads outside the rolling hour counted — the cap became a "
            "lifetime quota"
        )


def test_a_read_stopped_before_it_looked_archives_no_not_seen_summary():
    """P3.4 makes stop-while-queued routine, and a stopped read with zero
    claims never looked at anything: a diff summary over it would archive
    "N not seen" forever for a read that read nothing. Same treatment as
    `failed` — no snapshot (the books were never at risk either way; §5.6's
    never-auto-remove holds upstream)."""
    import threading

    release = threading.Event()

    class GateOrStopReader:
        def read(self, library, requests, *, mode, progress=None,
                 should_stop=None):
            deadline = time.monotonic() + 5
            while not release.is_set() and not (should_stop and should_stop()):
                if time.monotonic() > deadline:
                    raise AssertionError("never released")
                time.sleep(0.01)
            if should_stop and should_stop():
                return []
            return [ReadClaim(spine_id="sp1",
                              capture_id=requests[0].capture_id,
                              title="ספר אמיתי", tier="auto")]

        def unavailable(self, mode):
            return None

        def code_version(self):
            return {}

        def config_snapshot(self):
            return {}

    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=GateOrStopReader(),
                            jobs=QueuedJobRunner(workers=1)))

        def shelf_with_photo(colour):
            key = c.post(f"{API_PREFIX}/images",
                         files={"file": ("a.png", _png(colour=colour),
                                         "image/png")}).json()["key"]
            return c.post(f"{API_PREFIX}/captures",
                          json={"image_id": key}).json()["shelf"]["id"]

        shelf_a = shelf_with_photo((10, 10, 10))
        shelf_b = shelf_with_photo((20, 20, 20))
        read_a = c.post(f"{API_PREFIX}/shelves/{shelf_a}/reads",
                        json={"depth": 1, "mode": "spines"}).json()["id"]
        read_b = c.post(f"{API_PREFIX}/shelves/{shelf_b}/reads",
                        json={"depth": 1, "mode": "spines"}).json()["id"]
        # B waits behind A on the single worker; stop it while queued.
        c.post(f"{API_PREFIX}/shelves/{shelf_b}/reads/{read_b}/stop")
        release.set()

        a = _wait_until_settled(c, shelf_a, read_a)
        b = _wait_until_settled(c, shelf_b, read_b)
        assert a["status"] == "done" and a["diff_summary"] is not None
        assert b["status"] == "stopped"
        assert b["claims"] == []
        assert b["diff_summary"] is None, (
            "a read that never looked archived a not-seen summary"
        )


def test_starting_a_read_needs_captures_at_that_depth():
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        shelf = c.post(f"{API_PREFIX}/shelves", json={"label": "סלון"}).json()
        r = c.post(f"{API_PREFIX}/shelves/{shelf['id']}/reads", json={"depth": 1})
    assert r.status_code == 409, r.text


def test_starting_a_read_needs_uploaded_photos_not_just_captures():
    """A shelf can have a capture before it has a photo (P2.2's recorded
    gap). Refusing this loudly is clearer than letting the job run and
    silently produce zero claims."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        made = c.post(f"{API_PREFIX}/captures", json={}).json()   # no image_id
        r = c.post(f"{API_PREFIX}/shelves/{made['shelf']['id']}/reads",
                   json={"depth": 1})
    assert r.status_code == 409, r.text


def test_a_read_at_an_undeclared_depth_is_409():
    """§5.7: depth is declared, never detected — the same rule captures
    enforce, reached through this door too."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        shelf = c.post(f"{API_PREFIX}/shelves", json={}).json()
        r = c.post(f"{API_PREFIX}/shelves/{shelf['id']}/reads", json={"depth": 2})
    assert r.status_code == 409, r.text
    assert "2" in r.json()["detail"]


def test_a_read_runs_via_a_stub_reader_and_produces_claims():
    """The whole flow: upload a photo, bind it to a shelf via a capture,
    start a read, poll until it settles, and see the claims the (stub)
    engine produced — including a crop round-tripped through BlobStore, the
    same way a real spine crop would be."""
    with _blobs() as blobs:
        reader = StubReader()
        c = TestClient(_app(blobs=blobs, reader=reader))

        img_key = c.post(f"{API_PREFIX}/images",
                         files={"file": ("a.png", _png(), "image/png")}
                         ).json()["key"]
        made = c.post(f"{API_PREFIX}/captures", json={"image_id": img_key}).json()
        shelf_id, cap_id = made["shelf"]["id"], made["capture"]["id"]

        # Set up now that the real capture id is known — the job reads
        # `reader._claims` only once the background thread actually runs,
        # which is after this line.
        reader._claims = [
            ReadClaim(spine_id="sp1", capture_id=cap_id, text="קריאה גולמית",
                     title="מלכי הכופרים", author="פול קארני", tier="auto",
                     score=91.0, crop=_png((10, 40)), box=(1, 2, 3, 4),
                     alternatives=[
                         ReadAlternative(title="ספינות מן המערב",
                                        author="פול קארני", score=61.2),
                     ]),
            ReadClaim(spine_id="sp2", capture_id=cap_id, tier="unmatched"),
        ]

        started = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1, "mode": "spines"})
        assert started.status_code == 202, started.text
        assert started.json()["status"] == "running"
        read_id = started.json()["id"]

        body = _wait_until_settled(c, shelf_id, read_id)
        assert body["status"] == "done"
        assert body["error"] is None
        assert body["capture_ids"] == [cap_id]
        assert body["code_version"] == {"sha": "stub", "branch": "test",
                                        "dirty": False}
        assert len(body["claims"]) == 2

        auto = next(cl for cl in body["claims"] if cl["tier"] == "auto")
        assert auto["title"] == "מלכי הכופרים"
        assert auto["box"] == [1, 2, 3, 4]
        assert auto["crop_key"], "the crop was not stored/keyed"
        assert c.get(f"{API_PREFIX}/images/{auto['crop_key']}/full"
                     ).status_code == 200
        # P2.7's "why?" data rides on the claim itself (see the module
        # docstring's cost reasoning) — GET .../reads/{id} is its only route.
        assert auto["alternatives"] == [
            {"title": "ספינות מן המערב", "author": "פול קארני", "score": 61.2,
             "reason": ""},
        ]

        unmatched = next(cl for cl in body["claims"] if cl["tier"] == "unmatched")
        assert unmatched["crop_key"] is None
        assert unmatched["alternatives"] == []

        # The list endpoint is a SUMMARY — status and a count, no claims.
        listed = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads").json()
        assert [r["id"] for r in listed] == [read_id]
        assert listed[0]["claim_count"] == 2
        assert "claims" not in listed[0], "the summary must not embed claims"


def test_a_read_can_be_stopped_and_keeps_its_partial_claims():
    """§ app.domain.read: a stopped read is a REAL partial result. Stopping
    early must leave SOME claims (proving the partial result was kept) and
    FEWER than the full run would have produced (proving the stop actually
    took effect rather than the job racing to completion anyway)."""
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        setup = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store))
        img_key = setup.post(f"{API_PREFIX}/images",
                             files={"file": ("a.png", _png(), "image/png")}
                             ).json()["key"]
        made = setup.post(f"{API_PREFIX}/captures", json={"image_id": img_key}).json()
        shelf_id, cap_id = made["shelf"]["id"], made["capture"]["id"]

        reader = SlowStubReader(capture_id=cap_id, steps=200, step_s=0.01)
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                            reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]

        # Let the worker produce a handful of claims (~5 at 10ms/step), then
        # stop it — long before its 200 simulated steps would finish alone.
        time.sleep(0.05)
        stopped = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/stop")
        assert stopped.status_code == 202, stopped.text

        body = _wait_until_settled(c, shelf_id, read_id, timeout=3.0)
        assert body["status"] == "stopped"
        assert body["error"] is None
        assert 0 < len(body["claims"]) < 200, (
            "expected a partial result — neither none (the stop lost the "
            "evidence) nor the full 200 (the stop had no effect)"
        )


def test_a_read_id_reached_through_the_wrong_shelf_is_404():
    """A real read id, but not this shelf's — must read as absent, not
    silently serve one shelf's evidence at another shelf's address."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        img_key = c.post(f"{API_PREFIX}/images",
                         files={"file": ("a.png", _png(), "image/png")}
                         ).json()["key"]
        made = c.post(f"{API_PREFIX}/captures", json={"image_id": img_key}).json()
        shelf_id = made["shelf"]["id"]
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        other = c.post(f"{API_PREFIX}/shelves", json={"label": "אחר"}).json()
        assert c.get(f"{API_PREFIX}/shelves/{other['id']}/reads/{read_id}"
                     ).status_code == 404


def test_a_read_in_another_library_is_404_not_403():
    """§4.2, same as every other aggregate: absent and forbidden are the
    same answer."""
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        mine = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                               reader=StubReader()))
        img_key = mine.post(f"{API_PREFIX}/images",
                            files={"file": ("a.png", _png(), "image/png")}
                            ).json()["key"]
        made = mine.post(f"{API_PREFIX}/captures", json={"image_id": img_key}).json()
        shelf_id = made["shelf"]["id"]
        read_id = mine.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                            json={"depth": 1}).json()["id"]
        _wait_until_settled(mine, shelf_id, read_id)

        theirs = TestClient(_app(
            StubPrincipal(LibraryRef("lib-other", "Other"), "p-other"),
            blobs=blobs, shelves=shelves, reads=reads_store, reader=StubReader(),
        ))
        assert theirs.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}"
                          ).status_code == 404
        assert theirs.get(f"{API_PREFIX}/shelves/{shelf_id}/reads").status_code == 404
        assert theirs.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                           json={"depth": 1}).status_code == 404
        assert mine.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}"
                        ).status_code == 200


def test_reads_are_listed_per_shelf_most_recent_first():
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                            reader=StubReader()))
        img_key = c.post(f"{API_PREFIX}/images",
                         files={"file": ("a.png", _png(), "image/png")}
                         ).json()["key"]
        made = c.post(f"{API_PREFIX}/captures", json={"image_id": img_key}).json()
        shelf_id = made["shelf"]["id"]

        first = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                       json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, first)
        second = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                        json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, second)

        listed = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads").json()
        assert [r["id"] for r in listed] == [second, first]


def test_a_capture_with_no_photo_is_skipped_not_fatal():
    """Two captures at one depth, one with a photo and one without (P2.2's
    recorded gap): the read still runs on the one that has evidence, rather
    than refusing the whole depth because of the other."""
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store))
        shelf = c.post(f"{API_PREFIX}/shelves", json={}).json()
        img_key = c.post(f"{API_PREFIX}/images",
                         files={"file": ("a.png", _png(), "image/png")}
                         ).json()["key"]
        with_photo = c.post(f"{API_PREFIX}/captures",
                            json={"shelf_id": shelf["id"], "image_id": img_key}
                            ).json()["capture"]
        c.post(f"{API_PREFIX}/captures", json={"shelf_id": shelf["id"]})  # no photo

        reader = StubReader([ReadClaim(spine_id="sp1",
                                       capture_id=with_photo["id"], tier="auto")])
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                            reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf['id']}/reads",
                         json={"depth": 1}).json()["id"]
        body = _wait_until_settled(c, shelf["id"], read_id)
        assert body["status"] == "done"
        assert len(body["claims"]) == 1
        assert body["claims"][0]["capture_id"] == with_photo["id"]


def test_a_capture_can_carry_the_key_of_an_uploaded_photo():
    """The join P2.3 exists for: upload returns a key, and the capture that
    files the photo onto a shelf references it. Two calls, deliberately — the
    owner drops twelve photos and decides shelf and depth while looking at the
    thumbnails."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        key = c.post(f"{API_PREFIX}/images",
                     files={"file": ("IMG_6082.png", _png(), "image/png")}
                     ).json()["key"]

        made = c.post(f"{API_PREFIX}/captures", json={"image_id": key}).json()
        assert made["capture"]["image_id"] == key
        assert made["shelf_created"] is True
        # And the bytes are reachable from what the capture carries.
        assert c.get(f"{API_PREFIX}/images/{made['capture']['image_id']}/thumb"
                     ).status_code == 200


# --- reconciliation (P2.5) --------------------------------------------------

def _read_shelf_and_capture(c, *, image_key: str | None = None):
    """Common setup: a shelf, one uploaded photo, one capture at depth 1."""
    key = image_key or c.post(
        f"{API_PREFIX}/images",
        files={"file": ("a.png", _png(), "image/png")},
    ).json()["key"]
    made = c.post(f"{API_PREFIX}/captures", json={"image_id": key}).json()
    return made["shelf"]["id"], made["capture"]["id"]


def test_diff_reports_added_unchanged_and_not_seen():
    """GET .../diff RECOMPUTES live (its own contract, `diff_for`'s docstring)
    — and since P2.9, a settled read has already applied itself server-side
    before this GET ever runs (see `test_a_settled_read_applies_its_diff_
    with_no_client_call_at_all` below), so "ספר חדש" already stands at this
    (shelf, depth) by the time this test asks. That is WHY it shows up
    `unchanged` here rather than `added` — not a weaker assertion, a
    consequence of the diff being live rather than a fixed record of the
    moment the read finished (that fixed record is `Read.diff_summary`,
    checked separately)."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        # A book already on this shelf, unclaimed by this read -> not_seen.
        store.save(TEST_LIBRARY, new_book(
            id="b-missing", library_id=TEST_LIBRARY.id, title="לא נקרא",
            author="", copy_id="c-missing", shelf_id=shelf_id, depth=1,
        ))
        # A book already here that this read DOES claim -> unchanged.
        store.save(TEST_LIBRARY, new_book(
            id="b-here", library_id=TEST_LIBRARY.id, title="כבר כאן",
            author="מחבר", copy_id="c-here", shelf_id=shelf_id, depth=1,
        ))

        reader = StubReader([
            ReadClaim(spine_id="sp1", capture_id=cap_id, title="כבר כאן",
                     author="מחבר", tier="auto", score=91.0),
            ReadClaim(spine_id="sp2", capture_id=cap_id, title="ספר חדש",
                     author="סופר", tier="auto", score=88.0),
        ])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        assert not diff["added"], "nothing is added without an answer (2026-08-09)"
        # A book already standing here: reconfirmed silently, no question.
        assert {o["existing_book"]["title"] for o in diff["unchanged"]} == {"כבר כאן"}
        # A book the library has never seen: a question, not an addition.
        assert [o["claim"]["title"] for o in diff["needs_decision"]] == ["ספר חדש"]
        assert len(diff["not_seen"]) == 1
        assert diff["not_seen"][0]["book"]["id"] == "b-missing"
        # b-missing + b-here only — GET is read-only, and the unapproved
        # finding has created nothing. Calling it twice must not change this.
        assert store.count(TEST_LIBRARY) == 2
        again = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        assert store.count(TEST_LIBRARY) == 2
        assert {o["existing_book"]["title"] for o in again["unchanged"]} == {"כבר כאן"}


def test_diff_asks_for_a_book_claimed_on_another_shelf():
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        store.save(TEST_LIBRARY, new_book(
            id="b-elsewhere", library_id=TEST_LIBRARY.id, title="ספר אחר",
            author="מחבר", copy_id="c-elsewhere", shelf_id="some-other-shelf",
            depth=1,
        ))
        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר אחר", author="מחבר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        assert not diff["added"] and not diff["unchanged"]
        assert len(diff["needs_decision"]) == 1
        assert diff["needs_decision"][0]["reason"] == "ambiguous_location"
        assert diff["needs_decision"][0]["existing_book"]["id"] == "b-elsewhere"


# --- P2.9: a settled read applies itself, server-side, with no client -------
#
# The bug this section guards against, from live phone use: upload -> press
# Run -> switch app -> come back. The read had finished; nothing had been
# added, because the ONLY thing that ever called POST .../apply was the
# browser's own poll loop noticing the read settle — and a backgrounded
# mobile tab does not reliably keep running that loop (§5.6's own inversion,
# "a read is an event that UPDATES the list", was being violated by the
# implementation). The fix moves the apply into `_job` itself, right where
# P2.8 already computes the settle-time diff for its snapshot.

class RaisingBookStore:
    """Wraps a real `BookStore` but makes `.save()` explode — the tool for
    proving that a failed AUTOMATIC apply does not take the read down with
    it. Every other method (`.list`, `.get`, `.count`, ...) is forwarded
    untouched via `__getattr__`, so the job's own claim-processing (which
    never calls `.save()` — only `apply_diff` does) is unaffected."""

    def __init__(self, inner):
        self._inner = inner

    def save(self, library, book):
        raise RuntimeError("boom: simulated apply-time storage failure")

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_a_settled_read_applies_its_diff_with_no_client_call_at_all():
    """THE regression test for P2.9's bug: reproduces "no client ever calls
    apply" by never calling it — not even the usual `POST .../apply` this
    file's other tests make out of habit. If this fails, the fix regressed
    back to depending on a client that might not be there.

    ⚠ What the automatic apply WRITES changed on 2026-08-09: a book the
    reader has never seen before is no longer created here (nothing enters
    the library unapproved — see `app.domain.reconcile`). So this uses the
    bucket that still writes unconditionally, `unchanged`: a book already
    standing at this (shelf, depth) must have this read's sighting appended
    with no client in the loop. The P2.9 guarantee is unchanged — the read
    reconciles and persists itself — only the set of things it may persist
    without asking is narrower."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)
        store.save(TEST_LIBRARY, new_book(
            id="b-here", library_id=TEST_LIBRARY.id, title="ספר חדש",
            author="סופר", copy_id="c-here", shelf_id=shelf_id, depth=1,
        ))

        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר חדש", author="סופר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        # No GET .../diff, no POST .../apply — the read settling is the only
        # thing that happened.
        got = store.get(TEST_LIBRARY, "b-here")
        sighting = got.copies[0].provenance[-1].sighting
        assert sighting == (read_id, "sp1"), (
            "the sighting must carry THIS read's own (run_id, spine_id), the "
            "same provenance an explicit client apply would have written"
        )


def test_a_settled_read_adds_no_book_the_owner_has_not_approved():
    """The other half of the same guarantee, and the owner's own bug report
    (2026-08-09): a read that finds fourteen books it has never seen before
    must put NONE of them in the library until a human says yes. Before this,
    the automatic apply above created them all."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר חדש", author="סופר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        assert store.count(TEST_LIBRARY) == 0, (
            "an AUTO-tier claim entered the library without being approved"
        )
        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        pending = diff["needs_decision"]
        assert [o["reason"] for o in pending] == ["new_book_unconfirmed"]

        # ...and approving it is what creates it, at APPROVED — a human said
        # yes, which outranks the AUTO rung a read alone produces.
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
               json={"answers": [{"claim_id": pending[0]["claim"]["id"],
                                  "kind": "confirm"}]})
        assert store.count(TEST_LIBRARY) == 1
        assert store.list(TEST_LIBRARY).items[0].status is Status.APPROVED


def test_the_automatic_apply_never_auto_resolves_a_needs_decision_claim():
    """§5.4's central rule, re-asserted at the exact new call site: settling
    automatically must NEVER stand in for a human's answer. An
    `ambiguous_location` claim is opened in the duplicates queue (same as an
    explicit no-answer apply would do) rather than resolved one way or the
    other, and a `review_tier_new_book` claim (a bare REVIEW-tier read, no
    prior record anywhere) is left open rather than promoted to a real book."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        duplicates = MemoryDuplicateQueue()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, duplicates=duplicates,
                            reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        store.save(TEST_LIBRARY, new_book(
            id="b-elsewhere", library_id=TEST_LIBRARY.id, title="ספר אחר",
            author="מחבר", copy_id="c-elsewhere", shelf_id="some-other-shelf",
            depth=1,
        ))
        reader = StubReader([
            ReadClaim(spine_id="sp1", capture_id=cap_id, title="ספר אחר",
                     author="מחבר", tier="auto", score=90.0),
            ReadClaim(spine_id="sp2", capture_id=cap_id, title="ספר חדש ולא ברור",
                     author="", tier="review", score=55.0),
        ])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, duplicates=duplicates, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        # Nothing new was CREATED — only the pre-existing book still has its
        # one original copy, and no book exists for the REVIEW-tier claim.
        assert store.count(TEST_LIBRARY) == 1
        assert store.get(TEST_LIBRARY, "b-elsewhere").copy_count == 1

        # The ambiguous claim is durably queued, exactly as an explicit
        # no-answer `POST .../apply` would have left it (P2.6, §5.4).
        open_qs = duplicates.list_open_questions(TEST_LIBRARY)
        assert len(open_qs) == 1
        assert open_qs[0].book_key == store.get(TEST_LIBRARY, "b-elsewhere").key

        # Both claims are still open on a live GET .../diff.
        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        reasons = {o["reason"] for o in diff["needs_decision"]}
        assert reasons == {"ambiguous_location", "new_book_unconfirmed"}


def test_the_diff_summary_snapshot_is_captured_before_the_automatic_apply_runs():
    """ORDERING, and the one bug a "freshen the summary" refactor would
    introduce: `_job` summarises the diff it already has and must never
    recompute one after applying. A second reconcile() would see the write
    the apply just made and describe it as having changed nothing.

    Uses a standing ALREADY_LISTED decision so the automatic apply has
    something to write without a human in the loop (since 2026-08-09 a new
    book does not qualify — it waits for approval). Before the apply the
    claim is `corrected`; recompute after it and the same claim reads
    `unchanged`, which is exactly the repaint this pins."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        decisions = MemoryDecisionStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, decisions=decisions,
                            reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)
        # The same book, standing on ANOTHER shelf, plus the human answer
        # that says "it is the same copy, it moved here".
        elsewhere = new_book(id="b-elsewhere", library_id=TEST_LIBRARY.id,
                             title="ספר חדש", author="סופר", copy_id="c-1",
                             shelf_id="other-shelf", depth=1)
        store.save(TEST_LIBRARY, elsewhere)
        decisions.save_decision(TEST_LIBRARY, Decision(
            library_id=TEST_LIBRARY.id, shelf_id=shelf_id, depth=1,
            book_key=elsewhere.key, kind=DecisionKind.ALREADY_LISTED,
            copy_id="c-1",
        ))

        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר חדש", author="סופר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, decisions=decisions, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        body = _wait_until_settled(c, shelf_id, read_id)

        # By now the copy HAS been relinked (the automatic apply ran) — but
        # the archived snapshot must still say "corrected", the truth at the
        # moment reconcile() looked, before that apply touched anything.
        assert store.get(TEST_LIBRARY, "b-elsewhere").copies[0].shelf_id == shelf_id
        assert body["diff_summary"] == {
            "added": 0, "corrected": 1, "unchanged": 0, "needs_decision": 0,
            "not_seen": 0, "rejected": 0, "ignored": 0,
        }
        live = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        assert not live["corrected"] and len(live["unchanged"]) == 1, (
            "the LIVE diff is expected to have moved on — that is precisely "
            "why the snapshot may not be recomputed from it"
        )


def test_a_failed_read_applies_nothing():
    """A read whose engine blew up mid-way has an arbitrary partial claim
    list — §5.5/§5.6 already say that is not evidence worth summarising, and
    the same reasoning means it must not be applied either."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        class BlowingUpReader:
            def read(self, library, requests, *, mode, progress=None,
                     should_stop=None):
                raise RuntimeError("engine exploded")

            def unavailable(self, mode: str) -> str | None:
                return None

            def code_version(self) -> dict:
                return {}

            def config_snapshot(self) -> dict:
                return {}

        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=BlowingUpReader()))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        body = _wait_until_settled(c, shelf_id, read_id)

        assert body["status"] == "failed"
        assert body["diff_summary"] is None
        assert store.count(TEST_LIBRARY) == 0


def test_the_automatic_apply_is_idempotent_against_a_later_client_apply_call():
    """The client's own `commitDiff` still calls `POST .../apply` on every
    settle (harmless-by-design, kept for the moment the server-side apply
    itself fails) — this proves "harmless" rather than assuming it:
    `Provenance.sighting` (`run_id`, `spine_id`) makes `observe()` idempotent,
    so the SAME claim reconciling twice must not create a second copy, a
    second sighting, or a second book."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר חדש", author="סופר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        # Approve the finding once — since 2026-08-09 that is what creates
        # the book, and it is also the write this test is about repeating.
        pending = c.get(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff"
        ).json()["needs_decision"][0]["claim"]["id"]
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
               json={"answers": [{"claim_id": pending, "kind": "confirm"}]})
        assert store.count(TEST_LIBRARY) == 1

        # The client's own apply, exactly as it fires today — twice, even,
        # since a flaky connection can retry it. And once more WITH the same
        # answer, the shape a double-clicked ✓ sends.
        for _ in range(2):
            r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
                      json={"answers": []})
            assert r.status_code == 200, r.text
        r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
                  json={"answers": [{"claim_id": pending, "kind": "confirm"}]})
        assert r.status_code in (200, 400), r.text

        assert store.count(TEST_LIBRARY) == 1, "a repeat apply must not add a second book"
        got = store.list(TEST_LIBRARY).items[0]
        assert got.copy_count == 1, "a repeat apply must not add a second copy"
        assert len(got.copies[0].provenance) == 1, (
            "the SAME (run_id, spine_id) sighting must not be recorded twice"
        )


def test_a_failed_automatic_apply_does_not_fail_the_read():
    """If the automatic apply itself blows up (a store hiccup, a shelf
    deleted in the instant between finishing and applying), the read is
    still a real record of a successful attempt — the claims and the P2.8
    snapshot survive; only the write-through is lost, and the client's own
    apply (still called on every settle) is the retry path for it. This is
    NOT a case that should ever surface as a `failed` read — that status
    means the ENGINE failed, and here it plainly did not."""
    with _blobs() as blobs:
        store = RaisingBookStore(MemoryBookStore())
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר חדש", author="סופר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        body = _wait_until_settled(c, shelf_id, read_id)

        assert body["status"] == "done", (
            "the read itself succeeded; only its automatic follow-up apply "
            "failed, and that must not relabel the read as failed"
        )
        assert len(body["claims"]) == 1, "the claim the engine found is kept"
        assert body["diff_summary"] == {
            "added": 0, "corrected": 0, "unchanged": 0, "needs_decision": 1,
            "not_seen": 0, "rejected": 0, "ignored": 0,
        }, "the summary, computed before the failed apply, must still be saved"


def test_apply_persists_added_and_unchanged_without_any_answers():
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר חדש", author="סופר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        applied = c.post(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
            json={"answers": []},
        )
        assert applied.status_code == 200, applied.text
        # A machine claim for an unknown book writes NOTHING without an answer
        # (2026-08-09) — it stays a question instead.
        assert store.count(TEST_LIBRARY) == 0
        assert [o["reason"] for o in applied.json()["needs_decision"]]             == ["new_book_unconfirmed"]


def test_apply_with_an_already_listed_answer_relinks_the_copy():
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        store.save(TEST_LIBRARY, new_book(
            id="b1", library_id=TEST_LIBRARY.id, title="ספר נודד",
            author="מחבר", copy_id="c1", shelf_id="old-shelf", depth=1,
        ))
        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר נודד", author="מחבר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        claim_id = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff"
                         ).json()["needs_decision"][0]["claim"]["id"]
        applied = c.post(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
            json={"answers": [{"claim_id": claim_id, "kind": "already_listed"}]},
        )
        assert applied.status_code == 200, applied.text
        assert not applied.json()["needs_decision"], "the answered claim is still open"
        assert store.get(TEST_LIBRARY, "b1").copies[0].shelf_id == shelf_id
        assert store.count(TEST_LIBRARY) == 1, "already-listed must not duplicate the book"


def test_apply_rejects_an_unknown_answer_kind():
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
                  json={"answers": [{"claim_id": "nope", "kind": "maybe"}]})
        assert r.status_code == 400, r.text


def test_apply_rejects_an_answer_for_a_claim_that_is_not_open():
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                            reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)
        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר", author="", tier="auto",
                                       score=90.0)])
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                            reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
                  json={"answers": [{"claim_id": "not-a-real-claim-id",
                                    "kind": "confirm"}]})
        assert r.status_code == 400, r.text


def test_diff_and_apply_refuse_a_still_running_read():
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        setup = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store))
        shelf_id, cap_id = _read_shelf_and_capture(setup)

        reader = SlowStubReader(capture_id=cap_id, steps=200, step_s=0.01)
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                            reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]

        assert c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff"
                     ).status_code == 409
        assert c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
                      json={"answers": []}).status_code == 409
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/stop")
        _wait_until_settled(c, shelf_id, read_id, timeout=3.0)


def test_diff_for_a_read_in_another_library_is_404_not_403():
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        mine = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                               reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(mine)
        read_id = mine.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                            json={"depth": 1}).json()["id"]
        _wait_until_settled(mine, shelf_id, read_id)

        theirs = TestClient(_app(
            StubPrincipal(LibraryRef("lib-other", "Other"), "p-other"),
            blobs=blobs, shelves=shelves, reads=reads_store, reader=StubReader(),
        ))
        assert theirs.get(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff"
        ).status_code == 404
        assert theirs.post(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
            json={"answers": []},
        ).status_code == 404


# --- the durable duplicates queue (P2.6, §5.4) ------------------------------

def _ambiguous_read(blobs):
    """A shelf/capture/read whose one claim collides with a book already
    confirmed on ANOTHER shelf — the real §5.4 ambiguous case, settled and
    ready for ``POST .../apply``. Mirrors `test_diff_asks_for_a_book_claimed_
    on_another_shelf`'s own setup; factored out because every test below
    needs it as its starting point, not its subject.

    Returns ``(store, shelves, reads_store, duplicates, client, shelf_id,
    read_id)``.
    """
    store = MemoryBookStore()
    shelves = MemoryShelfStore()
    reads_store = MemoryReadStore()
    duplicates = MemoryDuplicateQueue()
    c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                        blobs=blobs, duplicates=duplicates, reader=StubReader()))
    shelf_id, cap_id = _read_shelf_and_capture(c)

    store.save(TEST_LIBRARY, new_book(
        id="b-elsewhere", library_id=TEST_LIBRARY.id, title="ספר אחר",
        author="מחבר", copy_id="c-elsewhere", shelf_id="some-other-shelf",
        depth=1,
    ))
    reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                   title="ספר אחר", author="מחבר",
                                   tier="auto", score=90.0)])
    c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                        blobs=blobs, duplicates=duplicates, reader=reader))
    read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                     json={"depth": 1}).json()["id"]
    _wait_until_settled(c, shelf_id, read_id)
    return store, shelves, reads_store, duplicates, c, shelf_id, read_id


def test_a_skipped_ambiguous_claim_appears_in_the_duplicates_queue():
    with _blobs() as blobs:
        _, _, _, _, c, shelf_id, read_id = _ambiguous_read(blobs)
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
              json={"answers": []})

        got = c.get(f"{API_PREFIX}/duplicates").json()
        assert len(got) == 1
        q = got[0]
        assert q["shelf_id"] == shelf_id and q["depth"] == 1
        assert q["existing_book"]["id"] == "b-elsewhere"
        assert q["claim_title"] == "ספר אחר"
        assert q["prompt_kind"] == "three_way"
        assert q["default_copy_id"] == "c-elsewhere"


def test_the_books_duplicates_filter_returns_only_books_with_open_questions():
    with _blobs() as blobs:
        store, _, _, _, c, shelf_id, read_id = _ambiguous_read(blobs)
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
              json={"answers": []})
        store.save(TEST_LIBRARY, new_book(
            id="b-unrelated", library_id=TEST_LIBRARY.id, title="ספר שקט",
            author="", copy_id="c-unrelated",
        ))

        page = c.get(f"{API_PREFIX}/books", params={"duplicates": "true"}).json()
        assert [b["id"] for b in page["items"]] == ["b-elsewhere"]
        # Omitted entirely: every book, same as any other filter (§6).
        every = c.get(f"{API_PREFIX}/books").json()
        assert {b["id"] for b in every["items"]} == {"b-elsewhere", "b-unrelated"}


def test_answering_a_queued_question_relinks_and_closes_it():
    with _blobs() as blobs:
        store, _, _, _, c, shelf_id, read_id = _ambiguous_read(blobs)
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
              json={"answers": []})
        question_id = c.get(f"{API_PREFIX}/duplicates").json()[0]["id"]

        r = c.post(f"{API_PREFIX}/duplicates/{question_id}/answer",
                  json={"kind": "already_listed"})
        assert r.status_code == 200, r.text
        assert r.json()["copies"][0]["shelf_id"] == shelf_id
        assert store.count(TEST_LIBRARY) == 1, "already-listed must not duplicate the book"
        assert c.get(f"{API_PREFIX}/duplicates").json() == []


def test_skipping_a_queued_question_applies_the_safe_default():
    """§5.4, verbatim: 'default when the question is skipped or the run is
    never reviewed: already listed copy'. The end-to-end proof, over real
    HTTP: reversing the default (`app.domain.copy_resolution.DEFAULT_RESOLUTION`)
    to ANOTHER_COPY would make ``copy_count`` come back 2, not 1 — the
    phantom-copy regression §5.1/§5.4 both exist to rule out."""
    with _blobs() as blobs:
        _, _, _, _, c, shelf_id, read_id = _ambiguous_read(blobs)
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
              json={"answers": []})
        question_id = c.get(f"{API_PREFIX}/duplicates").json()[0]["id"]

        r = c.post(f"{API_PREFIX}/duplicates/{question_id}/skip")
        assert r.status_code == 200, r.text
        book = r.json()
        assert book["copy_count"] == 1
        assert book["copies"][0]["shelf_id"] == shelf_id, "the copy was not relinked"
        assert c.get(f"{API_PREFIX}/duplicates").json() == []


def test_answering_or_skipping_an_unknown_question_is_404():
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        r = c.post(f"{API_PREFIX}/duplicates/nope/answer",
                  json={"kind": "already_listed"})
        assert r.status_code == 404, r.text
        assert c.post(f"{API_PREFIX}/duplicates/nope/skip").status_code == 404


def test_a_question_whose_book_was_deleted_meanwhile_is_409_and_cleaned_up():
    """Defence in depth: the queue stores a POINTER, not a snapshot (same
    idiom as GET .../diff) — if the book it concerns is gone by the time a
    human answers, re-deriving the outcome finds nothing to answer, and the
    stale row must not be left to confuse the next listing."""
    with _blobs() as blobs:
        _, _, _, _, c, shelf_id, read_id = _ambiguous_read(blobs)
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
              json={"answers": []})
        question_id = c.get(f"{API_PREFIX}/duplicates").json()[0]["id"]

        assert c.delete(f"{API_PREFIX}/books/b-elsewhere").status_code == 204

        r = c.post(f"{API_PREFIX}/duplicates/{question_id}/answer",
                  json={"kind": "already_listed"})
        assert r.status_code == 409, r.text
        assert c.get(f"{API_PREFIX}/duplicates").json() == []


# --- P2.8: the shelf-detail screen ------------------------------------------

def test_shelf_overview_shows_no_staleness_signal_before_any_read_ever_happened():
    """The depth bar is always visible, even at `depth_count` 1 (§5.7) — and
    with nothing read yet at all, there is no fresher sibling to be stale
    against, so the soft line must stay quiet rather than flag the only row
    a shelf has."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        shelf = c.post(f"{API_PREFIX}/shelves", json={"label": "סלון"}).json()

        overview = c.get(f"{API_PREFIX}/shelves/{shelf['id']}/overview").json()
        assert overview["depths"] == [
            {"depth": 1, "last_read_at": None, "is_stale": False},
        ]
        assert overview["last_read_at"] is None


def test_shelf_overview_flags_a_row_stale_relative_to_its_read_sibling():
    """UI_PLAN §3's own example, ` "rows 2, 3 not read since 11.3.2026"` —
    staleness is relative to the shelf's OWN freshest row, never a clock."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/depths")  # now 2 rows deep
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)

        overview = c.get(f"{API_PREFIX}/shelves/{shelf_id}/overview").json()
        by_depth = {d["depth"]: d for d in overview["depths"]}
        assert by_depth[1]["last_read_at"] is not None
        assert by_depth[1]["is_stale"] is False
        assert by_depth[2]["last_read_at"] is None
        assert by_depth[2]["is_stale"] is True
        assert overview["last_read_at"] == by_depth[1]["last_read_at"]


def test_shelf_overview_for_an_absent_shelf_is_404():
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        assert c.get(f"{API_PREFIX}/shelves/nope/overview").status_code == 404


def test_shelf_books_lists_only_the_books_located_at_the_requested_depth():
    """§5.7 #1, at the API's own door: a shelf's books are per DEPTH, never
    a mixed list of two physical rows."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        c = TestClient(_app(store=store, shelves=shelves, blobs=blobs,
                            reader=StubReader()))
        shelf = c.post(f"{API_PREFIX}/shelves", json={"label": "סלון"}).json()
        c.post(f"{API_PREFIX}/shelves/{shelf['id']}/depths")  # 2 rows

        store.save(TEST_LIBRARY, new_book(
            id="b1", library_id=TEST_LIBRARY.id, title="קדמי", author="",
            copy_id="c1", shelf_id=shelf["id"], depth=1))
        store.save(TEST_LIBRARY, new_book(
            id="b2", library_id=TEST_LIBRARY.id, title="אחורי", author="",
            copy_id="c2", shelf_id=shelf["id"], depth=2))

        front = c.get(f"{API_PREFIX}/shelves/{shelf['id']}/books",
                      params={"depth": 1}).json()
        assert [b["id"] for b in front] == ["b1"]
        back = c.get(f"{API_PREFIX}/shelves/{shelf['id']}/books",
                     params={"depth": 2}).json()
        assert [b["id"] for b in back] == ["b2"]


def test_shelf_books_at_an_undeclared_depth_is_409():
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        shelf = c.post(f"{API_PREFIX}/shelves", json={}).json()
        r = c.get(f"{API_PREFIX}/shelves/{shelf['id']}/books", params={"depth": 2})
        assert r.status_code == 409, r.text


def test_shelf_books_for_an_absent_shelf_is_404():
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        assert c.get(f"{API_PREFIX}/shelves/nope/books").status_code == 404


def test_shelf_books_orders_by_the_engines_own_spine_index_when_available():
    """No true physical position is stored (see `_physical_order_key`'s own
    docstring); the best available proxy is the spine id's numeric suffix,
    numeric so spine 10 does not sort before spine 2, and a copy with no
    spine at all (a manual add) sorts last rather than first."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        c = TestClient(_app(store=store, blobs=blobs, reader=StubReader()))
        shelf = c.post(f"{API_PREFIX}/shelves", json={}).json()

        store.save(TEST_LIBRARY, new_book(
            id="b10", library_id=TEST_LIBRARY.id, title="עשירי", author="",
            copy_id="b10c", shelf_id=shelf["id"], depth=1,
            provenance=(Provenance(run_id="r1", spine_id="IMG_1_b0_s10",
                                   shelf_id=shelf["id"], depth=1),)))
        store.save(TEST_LIBRARY, new_book(
            id="b2", library_id=TEST_LIBRARY.id, title="שני", author="",
            copy_id="b2c", shelf_id=shelf["id"], depth=1,
            provenance=(Provenance(run_id="r1", spine_id="IMG_1_b0_s02",
                                   shelf_id=shelf["id"], depth=1),)))
        store.save(TEST_LIBRARY, new_book(
            id="bx", library_id=TEST_LIBRARY.id, title="בלי שדרה", author="",
            copy_id="bxc", shelf_id=shelf["id"], depth=1))  # no provenance

        got = c.get(f"{API_PREFIX}/shelves/{shelf['id']}/books",
                    params={"depth": 1}).json()
        assert [b["id"] for b in got] == ["b2", "b10", "bx"]


def test_shelf_books_reports_a_not_seen_streak_and_never_removes_the_book():
    """§5.6's central rule, exercised through the door a careless "cleanup"
    feature would most plausibly be added to: two re-reads in a row that do
    not reconfirm a book must grow its badge to 2, and MUST NOT touch the
    book itself — it is listed exactly as before, and still fetchable
    directly from the store the endpoint reads from."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        read_a = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                        json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_a)
        store.save(TEST_LIBRARY, new_book(
            id="b1", library_id=TEST_LIBRARY.id, title="ספר קבוע", author="",
            copy_id="c1", shelf_id=shelf_id, depth=1,
            provenance=(Provenance(run_id=read_a, spine_id="sp1",
                                   shelf_id=shelf_id, depth=1,
                                   captured_at="2026-08-01T00:00:00+00:00"),),
        ))

        # Two re-reads of the SAME (shelf, depth); the (stub) engine finds
        # nothing either time -- two consecutive misses.
        for _ in range(2):
            read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                             json={"depth": 1}).json()["id"]
            _wait_until_settled(c, shelf_id, read_id)

        books = c.get(f"{API_PREFIX}/shelves/{shelf_id}/books",
                      params={"depth": 1}).json()
        assert len(books) == 1, "the book was removed after being unseen twice"
        assert books[0]["id"] == "b1"
        assert books[0]["copies"][0]["not_seen_streak"] == 2
        assert store.get(TEST_LIBRARY, "b1") is not None, \
            "computing the badge must not have touched the store"


def test_a_finished_read_carries_a_diff_summary_and_it_is_archived_not_repainted():
    """§5.5's headline example, end to end: a read that added one book must
    say so — in its own GET, in the shelf's history list — and that count
    must survive `apply` unchanged, because the book it added being "already
    here" from now on is not the same statement as "this read added it"."""
    with _blobs() as blobs:
        store = MemoryBookStore()
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)

        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר חדש", tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_store,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        body = _wait_until_settled(c, shelf_id, read_id)
        # A read of a book the library has never seen now settles as a
        # QUESTION, not an addition (2026-08-09) — the snapshot records that
        # honestly rather than claiming an addition that never happened.
        assert body["diff_summary"] == {
            "added": 0, "corrected": 0, "unchanged": 0, "needs_decision": 1,
            "not_seen": 0, "rejected": 0, "ignored": 0,
        }

        listed = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads").json()
        assert listed[0]["diff_summary"]["needs_decision"] == 1

        pending = c.get(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff"
        ).json()["needs_decision"][0]["claim"]["id"]
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
              json={"answers": [{"claim_id": pending, "kind": "confirm"}]})
        after_apply = c.get(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}").json()
        assert after_apply["diff_summary"]["needs_decision"] == 1, (
            "the archived snapshot must not repaint itself once the question "
            "it asked has, correctly, been answered"
        )


def test_a_stopped_or_failed_read_summary_is_none_or_reflects_the_partial_claims():
    """A `failed` read has no reliable diff to freeze (its claims may be an
    arbitrary partial slice from whatever blew up); a `stopped` one is a
    real partial result (§ app.domain.read) and gets a real summary over
    whatever it did collect."""
    with _blobs() as blobs:
        shelves = MemoryShelfStore()
        reads_store = MemoryReadStore()
        setup = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store))
        img_key = setup.post(f"{API_PREFIX}/images",
                             files={"file": ("a.png", _png(), "image/png")}
                             ).json()["key"]
        made = setup.post(f"{API_PREFIX}/captures", json={"image_id": img_key}).json()
        shelf_id, cap_id = made["shelf"]["id"], made["capture"]["id"]

        reader = SlowStubReader(capture_id=cap_id, steps=200, step_s=0.01)
        c = TestClient(_app(blobs=blobs, shelves=shelves, reads=reads_store,
                            reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        time.sleep(0.05)
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/stop")
        body = _wait_until_settled(c, shelf_id, read_id, timeout=3.0)
        assert body["status"] == "stopped"
        assert body["diff_summary"] is not None
        # Every claim a stopped read did collect is real evidence and lands in
        # the snapshot — as a pending question each, since 2026-08-09, rather
        # than as an addition nobody approved.
        assert body["diff_summary"]["needs_decision"] == len(body["claims"])


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "run_all.py"), __file__]
    ))


# --- the default reading mode, and its preflight (2026-08-08) -------------

def test_a_read_defaults_to_the_llm_mode():
    """Owner's call. The measured gap is not close: the Tesseract path is
    ~10s/spine and tops out near 76% title-correct, and CLAUDE.md already
    records llmpage as the engine's own default.

    The project's deterministic-first rule is about not paying an LLM for work
    cheap code can do — it was never an argument for making the worse reader
    the one everybody meets first. Pinned because "restore the deterministic
    default" is exactly the kind of tidy-looking change that would quietly
    hand every new user the weaker engine.
    """
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        key = c.post(f"{API_PREFIX}/images",
                     files={"file": ("a.png", _png(), "image/png")}).json()["key"]
        made = c.post(f"{API_PREFIX}/captures", json={"image_id": key}).json()
        # A body with no `mode` at all — the default is what is under test.
        started = c.post(f"{API_PREFIX}/shelves/{made['shelf']['id']}/reads",
                         json={})
    assert started.status_code == 202, started.text
    assert started.json()["mode"] == "llmpage"


def test_a_mode_whose_credential_is_missing_is_refused_at_the_door():
    """A read runs in a WORKER THREAD. A missing key discovered there surfaces
    as a `failed` read with a traceback in a log nobody is watching, minutes
    after the click — and the owner is left guessing whether the photo, the
    shelf or the engine was the problem.

    The answer comes from the Reader, not from this route: which credential
    which engine needs is the adapter's knowledge, and encoding it in the API
    layer would couple the route to whichever adapter is bound — and would
    give this ring an environment it deliberately does not have.
    """
    with _blobs() as blobs:
        refuses = StubReader(unavailable="needs A_KEY — set it and restart")
        c = TestClient(_app(blobs=blobs, reader=refuses))
        key = c.post(f"{API_PREFIX}/images",
                     files={"file": ("a.png", _png(), "image/png")}).json()["key"]
        made = c.post(f"{API_PREFIX}/captures", json={"image_id": key}).json()
        r = c.post(f"{API_PREFIX}/shelves/{made['shelf']['id']}/reads",
                   json={"mode": "llmpage"})

    assert r.status_code == 409, r.text
    # The message must say what to DO, not merely what is absent — it is shown
    # to the owner, who cannot read a traceback.
    assert "set it and restart" in r.json()["detail"]


def test_the_real_reader_names_the_key_each_mode_needs():
    """The adapter is the one place that knows the mapping. Asserted directly
    because the API ring stubs the Reader, so nothing else exercises it — and
    a preflight that never fires is indistinguishable from no preflight."""
    import os as _os

    from app.adapters.booksnap_reader import BooksnapReader

    reader = BooksnapReader.__new__(BooksnapReader)   # no engine construction
    saved = {k: _os.environ.pop(k, None)
             for k in ("ANTHROPIC_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS")}
    try:
        assert "ANTHROPIC_API_KEY" in (reader.unavailable("llmpage") or "")
        assert "GOOGLE_APPLICATION_CREDENTIALS" in (
            reader.unavailable("fullpage") or "")
        # Tesseract needs nothing, and stays the answer when no key exists.
        assert reader.unavailable("spines") is None
        assert "unknown reading mode" in (reader.unavailable("nope") or "")
    finally:
        for k, v in saved.items():
            if v is not None:
                _os.environ[k] = v


# --- what phones actually send (2026-08-08) -------------------------------

def test_a_real_phone_photo_uploads():
    """The regression that shipped. Every one of the owner's real shelf photos
    is an MPO — a JPEG container with a second embedded frame — and the upload
    validator's whitelist only knew JPEG/PNG/WEBP, so every real upload 415'd
    while every test passed.

    The tests passed because `Image.new(...).save(format='JPEG')` produces
    plain JPEG. **A synthetic image is not a sample of the input domain.**
    """
    from PIL import Image

    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        data = _mpo()
        assert Image.open(io.BytesIO(data)).format == "MPO", "not a real MPO"

        r = c.post(f"{API_PREFIX}/images",
                   files={"file": ("IMG_6082.jpg", data, "image/jpeg")})
        assert r.status_code == 201, r.text
        meta = r.json()
        # Served as JPEG: frame 0 of an MPO is an ordinary JPEG, which is what
        # a browser and cv2 both read.
        assert meta["content_type"] == "image/jpeg"
        assert (meta["width"], meta["height"]) == (60, 40)

        assert c.get(f"{API_PREFIX}/images/{meta['key']}/full").status_code == 200
        thumb = c.get(f"{API_PREFIX}/images/{meta['key']}/thumb")
        assert thumb.status_code == 200
        assert Image.open(io.BytesIO(thumb.content)).format == "JPEG"


def test_a_rotated_phone_photo_that_is_an_mpo_is_stored_upright_as_jpeg():
    """The two phone realities together: MPO *and* an EXIF rotation flag. An
    MPO cannot be written back as an MPO from one transposed frame, so
    correcting orientation must re-encode as JPEG — and the earlier code would
    have thrown trying to save `format='MPO'`."""
    from PIL import Image

    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        r = c.post(f"{API_PREFIX}/images",
                   files={"file": ("p.jpg", _mpo((60, 40), orientation=6),
                                   "image/jpeg")})
        assert r.status_code == 201, r.text
        meta = r.json()
        assert (meta["width"], meta["height"]) == (40, 60), "not transposed"

        served = Image.open(io.BytesIO(
            c.get(f"{API_PREFIX}/images/{meta['key']}/full").content))
        assert served.format == "JPEG", "an MPO was re-saved as MPO"
        assert served.getexif().get(0x0112) in (None, 1)


def test_an_unsupported_format_says_what_to_change():
    """"Not a decodable image" is true and useless — the owner is holding a
    photo that plainly IS one. HEIC is the iPhone default whenever the camera
    is not on "Most Compatible", so the refusal names it and says what to do."""
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        r = c.post(f"{API_PREFIX}/images",
                   files={"file": ("IMG_1.heic", _heic_header(), "image/heic")})
        assert r.status_code == 415, r.text
        detail = r.json()["detail"]
        assert "HEIC" in detail
        assert "Most Compatible" in detail, "the message does not say what to do"


def test_the_owners_real_photos_upload_if_they_are_on_this_machine():
    """Self-skipping, like the spotchecks: `work/` is gitignored, so a fresh
    clone has no photos and this cannot be a hard gate. But on the machine that
    HAS them it is the only test that runs the real input domain through the
    real validator — which is the check whose absence let MPO ship broken.
    """
    real = sorted(Path(REPO_ROOT / "work" / "library").glob("*.jpeg"))[:3]
    if not real:
        return  # no local photo archive; the committed MPO test still ran

    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs))
        for path in real:
            r = c.post(f"{API_PREFIX}/images",
                       files={"file": (path.name, path.read_bytes(),
                                       "image/jpeg")})
            assert r.status_code == 201, f"{path.name}: {r.status_code} {r.text[:200]}"
            key = r.json()["key"]
            assert c.get(f"{API_PREFIX}/images/{key}/thumb").status_code == 200


# --- the image workspace (P2.10, §12.2 #10) ---------------------------------
#
# "An image is a durable object: clicking it opens its runs, each run lists its
# findings, and each finding can be approved / edited / removed." Everything
# below is that loop over HTTP — and, just as important, the proof that
# reaching a settled read's findings costs no second read.

def _settled_read(c, *, claims, store=None, shelves=None, reads=None,
                  blobs=None, approve_findings=True):
    """A shelf, a photo, and one finished read of it — the state the
    workspace opens onto."""
    shelf_id, cap_id = _read_shelf_and_capture(c)
    reader = StubReader([claim(cap_id) for claim in claims])
    c2 = TestClient(_app(store=store, shelves=shelves, reads=reads,
                         blobs=blobs, reader=reader))
    read_id = c2.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                      json={"depth": 1}).json()["id"]
    _wait_until_settled(c2, shelf_id, read_id)
    if approve_findings:
        # Since 2026-08-09 a machine claim is a QUESTION, not a book — the
        # workspace's approve/fix/remove loop only has something to act on
        # once a human has said yes, which is what these lines are.
        diff = c2.get(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        answers = [{"claim_id": o["claim"]["id"], "kind": "confirm"}
                   for o in diff["needs_decision"]
                   if o["reason"] == "new_book_unconfirmed"]
        if answers:
            c2.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
                    json={"answers": answers})
    return c2, shelf_id, cap_id, read_id


def _auto_claim(title="ספר חדש", spine="sp1"):
    return lambda cap_id: ReadClaim(spine_id=spine, capture_id=cap_id,
                                    title=title, author="סופר", tier="auto",
                                    score=90.0)


def test_a_photo_lists_the_runs_that_read_it():
    """§12.2 #10's "clicking it opens that image's runs" — and the reason it
    hangs off the capture: two reads of the same photo both list here."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim()], store=store, shelves=shelves,
            reads=reads_, blobs=blobs)
        second = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                        json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, second)

        r = c.get(f"{API_PREFIX}/captures/{cap_id}/reads")
        assert r.status_code == 200, r.text
        ids = [row["id"] for row in r.json()]
        assert set(ids) == {read_id, second}
        assert all(row["diff_summary"] is not None for row in r.json()), (
            "a history row with no counts cannot render §5.6's headline line"
        )


def test_a_photos_runs_are_404_for_a_capture_that_is_not_there():
    with _blobs() as blobs:
        c = TestClient(_app(blobs=blobs, reader=StubReader()))
        assert c.get(f"{API_PREFIX}/captures/nope/reads").status_code == 404


def test_opening_a_settled_reads_findings_starts_no_new_read():
    """The behaviour §12.2 #10 is explicitly about: *"a processed photo is
    never re-read just to see what it found"*. Reaching the findings is
    reads-of-the-photo + the read's own diff, and neither may start a job."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim()], store=store, shelves=shelves,
            reads=reads_, blobs=blobs)

        before = len(reads_.list_reads(TEST_LIBRARY, shelf_id))
        c.get(f"{API_PREFIX}/captures/{cap_id}/reads")
        findings = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff")
        assert findings.status_code == 200, findings.text
        assert len(reads_.list_reads(TEST_LIBRARY, shelf_id)) == before, (
            "opening a photo's findings started another read"
        )
        # Every finding names the capture it came from, which is what lets the
        # workspace show one photo's findings rather than the whole row's.
        outcomes = findings.json()["unchanged"] + findings.json()["added"]
        assert [o["claim"]["capture_id"] for o in outcomes] == [cap_id]


def test_approving_a_finding_raises_the_book_from_auto_to_approved():
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        # An AUTO-status book the read RE-FINDS rather than introduces: one
        # of P1.3's 251 imports, say. Since 2026-08-09 a newly-approved
        # finding is already `approved`, so this route's remaining job is
        # exactly this case — raising a record that predates the approval
        # rule and has never been looked at.
        shelf_id, cap_id = _read_shelf_and_capture(c)
        store.save(TEST_LIBRARY, new_book(
            id="b-legacy", library_id=TEST_LIBRARY.id, title="ספר ישן",
            author="סופר", copy_id="c-legacy", shelf_id=shelf_id, depth=1,
        ))
        reader = StubReader([ReadClaim(spine_id="sp1", capture_id=cap_id,
                                       title="ספר ישן", author="סופר",
                                       tier="auto", score=90.0)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)
        book = c.get(f"{API_PREFIX}/books").json()["items"][0]
        assert book["status"] == "auto"

        r = c.post(f"{API_PREFIX}/books/{book['id']}/approve")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
        # Idempotent, and never a demotion — `Status.merge`'s whole job.
        again = c.post(f"{API_PREFIX}/books/{book['id']}/approve")
        assert again.json()["status"] == "approved"


def test_editing_a_finding_marks_the_book_manual_and_keeps_it_on_the_shelf():
    """*Edit* is the ordinary book route (H3 — the workspace does not need a
    third way to write a title), but the thing worth pinning is that fixing a
    title from a photo does not unfile the book."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim(title="ספר חדשש")], store=store,
            shelves=shelves, reads=reads_, blobs=blobs)
        book = c.get(f"{API_PREFIX}/books").json()["items"][0]

        r = c.patch(f"{API_PREFIX}/books/{book['id']}", json={"title": "ספר חדש"})
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "ספר חדש" and r.json()["status"] == "manual"
        assert r.json()["copies"][0]["shelf_id"] == shelf_id


def test_retracting_a_finding_removes_the_phantom_and_suppresses_it_here():
    """The ✕, end to end: the auto-only book is gone from the library, the
    finding now reads `rejected` in the diff, and a re-read does not bring it
    back (§5.6)."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim()], store=store, shelves=shelves,
            reads=reads_, blobs=blobs)
        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        claim_id = (diff["unchanged"] + diff["added"])[0]["claim"]["id"]
        assert store.count(TEST_LIBRARY) == 1

        r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}"
                   f"/findings/{claim_id}/retract")
        assert r.status_code == 200, r.text
        assert store.count(TEST_LIBRARY) == 0
        assert [o["claim"]["id"] for o in r.json()["rejected"]] == [claim_id], (
            "the retracted finding must stay visible with a reason, not vanish"
        )

        # A second read of the same shelf must not re-add it.
        again = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                       json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, again)
        assert store.count(TEST_LIBRARY) == 0, "the retracted book came back"


def test_deleting_a_book_marks_its_finding_removed_and_keeps_it_that_way():
    """Owner, 2026-08-10, from live use: *"removing a book in the books tab
    should mark it as removed (strike through) in the image"*.

    Two halves of one write. Before this, deleting a book recorded nothing —
    so the finding reverted to an ordinary unanswered question (its ✓ back on
    screen, as if nobody had decided), AND the next read of that shelf put the
    book straight back, which is the §5.6 rule going unenforced for the
    plainest rejection the product has.
    """
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim()], store=store, shelves=shelves,
            reads=reads_, blobs=blobs)
        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        claim_id = (diff["unchanged"] + diff["added"])[0]["claim"]["id"]
        book_id = c.get(f"{API_PREFIX}/books").json()["items"][0]["id"]

        assert c.delete(f"{API_PREFIX}/books/{book_id}").status_code == 204

        after = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        assert [o["claim"]["id"] for o in after["rejected"]] == [claim_id], (
            "a deleted book's finding must read as REMOVED, not as a question "
            "nobody has answered"
        )
        assert not after["needs_decision"]

        # And the other half: a later read does not put it back (§5.6).
        again = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                       json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, again)
        assert store.count(TEST_LIBRARY) == 0, "the deleted book came back"


def test_undo_brings_a_deleted_books_finding_back_as_a_question():
    """↩ clears the standing decision and lets the read apply itself again —
    so the finding returns as the PENDING one it was, never as a book nobody
    approved (the rule that outranks every other path into the library)."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim()], store=store, shelves=shelves,
            reads=reads_, blobs=blobs)
        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        claim_id = (diff["unchanged"] + diff["added"])[0]["claim"]["id"]
        book_id = c.get(f"{API_PREFIX}/books").json()["items"][0]["id"]
        c.delete(f"{API_PREFIX}/books/{book_id}")

        r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}"
                   f"/findings/{claim_id}/restore")
        assert r.status_code == 200, r.text
        assert not r.json()["rejected"], "the suppression was not lifted"
        assert [o["claim"]["id"] for o in r.json()["needs_decision"]] == [claim_id]
        assert store.count(TEST_LIBRARY) == 0, \
            "undo must not re-enter a book nobody approved"


def test_deleting_an_unshelved_book_records_nothing_and_still_deletes():
    """P1.3's 251 imported books have no shelf. There is no row for a future
    read to re-find them on, so a deletion there has nothing to suppress —
    and must still delete."""
    store = MemoryBookStore()
    _seed(store, TEST_LIBRARY, "ספר בלי מדף")
    decisions = MemoryDecisionStore()
    with TestClient(_app(store=store, decisions=decisions)) as c:
        book_id = c.get(f"{API_PREFIX}/books").json()["items"][0]["id"]
        assert c.delete(f"{API_PREFIX}/books/{book_id}").status_code == 204
    assert store.count(TEST_LIBRARY) == 0
    assert decisions.list_decisions(TEST_LIBRARY, "", 1) == ()


def test_retracting_never_deletes_a_book_that_predates_this_read():
    """UI_PLAN §5's separation over HTTP: a book an EARLIER read (or P1.3's
    import) put in the library is taken off this shelf and the no is
    recorded — the record itself survives.

    Note what stopped protecting it on 2026-08-09: "a human approved it".
    Every confirmed finding is APPROVED now, so the rule asks who CREATED the
    record instead (`app.domain.retract`)."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)
        store.save(TEST_LIBRARY, new_book(
            id="b-older", library_id=TEST_LIBRARY.id, title="ספר חדש",
            author="סופר", copy_id="c-older", shelf_id=shelf_id, depth=1,
        ))
        book_id = "b-older"
        reader = StubReader([_auto_claim()(cap_id)])
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=reader))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        _wait_until_settled(c, shelf_id, read_id)
        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        claim_id = (diff["unchanged"] + diff["added"])[0]["claim"]["id"]

        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}"
               f"/findings/{claim_id}/retract")

        still = c.get(f"{API_PREFIX}/books/{book_id}")
        assert still.status_code == 200, "a book older than this read was deleted"
        assert still.json()["copies"][0]["shelf_id"] is None


def test_restoring_a_retracted_finding_puts_the_book_back():
    """The ↩. It re-applies the read rather than re-reading the photo — the
    library returns to exactly one book, not two."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim()], store=store, shelves=shelves,
            reads=reads_, blobs=blobs)
        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        claim_id = (diff["unchanged"] + diff["added"])[0]["claim"]["id"]
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}"
               f"/findings/{claim_id}/retract")
        assert store.count(TEST_LIBRARY) == 0

        r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}"
                   f"/findings/{claim_id}/restore")
        assert r.status_code == 200, r.text
        assert not r.json()["rejected"], "the suppression was not lifted"
        # ↩ un-suppresses the FINDING; it does not re-approve on the owner's
        # behalf (2026-08-09 — nothing enters the library unapproved, and an
        # undo is not an approval). One more ✓ puts the book back.
        assert store.count(TEST_LIBRARY) == 0
        assert [o["reason"] for o in r.json()["needs_decision"]]             == ["new_book_unconfirmed"]
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
               json={"answers": [{"claim_id": claim_id, "kind": "confirm"}]})
        assert store.count(TEST_LIBRARY) == 1


def test_restoring_a_finding_that_was_never_retracted_is_a_409():
    """Silently doing nothing would look identical to success."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim()], store=store, shelves=shelves,
            reads=reads_, blobs=blobs)
        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        claim_id = (diff["unchanged"] + diff["added"])[0]["claim"]["id"]

        r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}"
                   f"/findings/{claim_id}/restore")
        assert r.status_code == 409, r.text


def test_adding_a_book_to_a_photo_by_hand_files_it_immediately_at_manual():
    """*"The engine missed this book"* (owner 2026-08-09). It joins the
    photo's findings AND the library in one call — no approval step, because
    typing the title IS the approval (§5.1's ladder)."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim()], store=store, shelves=shelves,
            reads=reads_, blobs=blobs)
        before = store.count(TEST_LIBRARY)

        r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/findings",
                   json={"title": "ספר שהמנוע פספס", "author": "מחבר"})
        assert r.status_code == 201, r.text
        assert store.count(TEST_LIBRARY) == before + 1

        added = [b for b in store.list(TEST_LIBRARY).items
                 if b.title == "ספר שהמנוע פספס"][0]
        assert added.status is Status.MANUAL
        assert added.copies[0].shelf_id == shelf_id
        # It is a FINDING of this photo, not a book filed off to the side —
        # which is the whole reason it goes onto the read at all.
        titles = [o["claim"]["title"] for o in r.json()["added"] + r.json()["unchanged"]]
        assert "ספר שהמנוע פספס" in titles
        read = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}").json()
        assert [cl["tier"] for cl in read["claims"] if cl["title"] == "ספר שהמנוע פספס"] \
            == ["manual"]


def test_the_author_field_completes_against_the_library():
    """Retyping an author is how "דויד גרוסמן" and "דוד גרוסמן" become two
    people the author chip then treats as two shelves' worth of books (owner,
    2026-08-09). Matching is `app.domain.search`'s, so "the search mechanism"
    means ONE thing across this codebase."""
    store = MemoryBookStore()
    c = TestClient(_app(store=store))
    for n, (title, author) in enumerate([
        ("ספר א", "דוד גרוסמן"),
        ("ספר ב", "דוד גרוסמן"),   # same author, listed once
        ("ספר ג", "עמוס עוז"),
        ("ספר ד", ""),               # no author at all
    ]):
        store.save(TEST_LIBRARY, new_book(
            id=f"b{n}", library_id=TEST_LIBRARY.id, title=title, author=author,
            copy_id=f"c{n}"))

    everyone = c.get(f"{API_PREFIX}/books/authors").json()
    assert everyone == ["דוד גרוסמן", "עמוס עוז"], (
        "authors must be distinct, and a book with no author is not one"
    )

    narrowed = c.get(f"{API_PREFIX}/books/authors", params={"q": "גרוס"}).json()
    assert narrowed == ["דוד גרוסמן"]
    assert c.get(f"{API_PREFIX}/books/authors", params={"q": "זזז"}).json() == []


def test_the_author_list_is_spelled_the_way_the_owner_spells_it():
    """Normalisation is for MATCHING. An autocomplete that filled in the
    nikud-stripped, final-letter-folded form would quietly rewrite the
    library's own data one accepted suggestion at a time."""
    store = MemoryBookStore()
    c = TestClient(_app(store=store))
    store.save(TEST_LIBRARY, new_book(
        id="b1", library_id=TEST_LIBRARY.id, title="ספר",
        author="אפרים קישון", copy_id="c1"))

    assert c.get(f"{API_PREFIX}/books/authors", params={"q": "קיש"}).json()         == ["אפרים קישון"]


def test_adding_by_hand_first_asks_whether_this_read_already_found_it():
    """The expensive human error `booksnap/server.py:lookup` names: adding a
    book by hand that the run DID find and the eye skipped, on a forty-row
    shelf read right-to-left. Same question, same answer, one layer up."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim(title="מלכי הכופרים", spine="sp1"),
                       _auto_claim(title="ספינות מן המערב", spine="sp2")],
            store=store, shelves=shelves, reads=reads_, blobs=blobs)
        look = f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/findings/lookup"

        hits = c.get(look, params={"q": "מלכי"}).json()
        assert [h["title"] for h in hits] == ["מלכי הכופרים"]

        # P1.5's own rules, reused rather than re-approximated: a leading
        # particle in the QUERY is tolerated, and the stored text is never
        # stripped. A JS re-implementation is what this endpoint exists to
        # avoid having to keep in step.
        assert [h["title"] for h in c.get(look, params={"q": "כופרים"}).json()]             == ["מלכי הכופרים"]
        assert c.get(look, params={"q": "לא קיים"}).json() == []
        # Empty means "match nothing", never "match everything" — a blank box
        # is the caller's business, not a request for the whole read.
        assert c.get(look, params={"q": ""}).json() == []


def test_the_lookup_sees_findings_a_human_has_already_acted_on():
    """Including a REMOVED one. The book you retracted a moment ago is
    exactly the one you might be about to re-add by hand, and saying nothing
    would be the unhelpful half of honest."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim(title="מלכי הכופרים")], store=store,
            shelves=shelves, reads=reads_, blobs=blobs)
        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        claim_id = (diff["unchanged"] + diff["added"])[0]["claim"]["id"]
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}"
               f"/findings/{claim_id}/retract")

        hits = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}"
                     f"/findings/lookup", params={"q": "מלכי"}).json()
        assert [h["title"] for h in hits] == ["מלכי הכופרים"]


def test_two_hand_added_books_are_two_findings_not_one():
    """Each gets its own minted spine id. Sharing one would make
    `Provenance.sighting` identical for both, and `observe()`'s idempotency
    would swallow the second without a word."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim()], store=store, shelves=shelves,
            reads=reads_, blobs=blobs)

        for title in ("ראשון", "שני"):
            r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/findings",
                       json={"title": title})
            assert r.status_code == 201, r.text

        read = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}").json()
        manual = [cl for cl in read["claims"] if cl["tier"] == "manual"]
        assert len({cl["spine_id"] for cl in manual}) == 2
        assert {b.title for b in store.list(TEST_LIBRARY).items} >= {"ראשון", "שני"}


def test_a_volume_is_filed_next_to_the_part_it_was_split_from():
    """Otherwise the new volumes land at the bottom of the photo, away from
    the book they belong to (owner, 2026-08-09). The link is in the spine id
    — the same "structure in the string" the engine's own IMG_1234_b0_s07
    uses — so nothing needed a new column for a relationship only ordering
    cares about."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim(spine="sp1")], store=store, shelves=shelves,
            reads=reads_, blobs=blobs)

        for title in ("\u05db\u05e8\u05da \u05d1", "\u05db\u05e8\u05da \u05d2"):
            r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/findings",
                       json={"title": title, "after_spine_id": "sp1"})
            assert r.status_code == 201, r.text

        read = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}").json()
        parts = sorted(cl["spine_id"] for cl in read["claims"]
                       if cl["spine_id"].startswith("sp1~m"))
        assert parts == ["sp1~m1", "sp1~m2"], (
            "each part needs its OWN id, or Provenance.sighting collides and "
            "observe() swallows the second"
        )
        # Without a parent it is a standalone hand-add, not a part of anything.
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/findings",
               json={"title": "\u05dc\u05d1\u05d3"})
        read = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}").json()
        loose = [cl["spine_id"] for cl in read["claims"] if cl["title"] == "\u05dc\u05d1\u05d3"]
        assert loose and loose[0].startswith("manual-")


def test_a_book_cannot_be_added_by_hand_to_a_read_that_is_still_running():
    """The one guard that keeps `add_manual_claim` a narrow exception rather
    than a hole in "claims are never mutated after a read finishes"."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        shelf_id, cap_id = _read_shelf_and_capture(c)
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs,
                            reader=SlowStubReader(capture_id=cap_id, steps=200,
                                                  step_s=0.01)))
        read_id = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads",
                         json={"depth": 1}).json()["id"]
        try:
            r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/findings",
                       json={"title": "מוקדם מדי"})
            assert r.status_code == 409, r.text
        finally:
            c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/stop")
            _wait_until_settled(c, shelf_id, read_id, timeout=3.0)


def test_approving_every_pending_finding_in_one_call():
    """"Approve all auto", the POC's own bulk action, restored — and it is
    deliberately just N confirms through the ordinary apply route rather than
    an endpoint of its own."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim(title=f"ספר {n}", spine=f"sp{n}")
                       for n in range(1, 4)],
            store=store, shelves=shelves, reads=reads_, blobs=blobs,
            approve_findings=False)
        assert store.count(TEST_LIBRARY) == 0

        diff = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        answers = [{"claim_id": o["claim"]["id"], "kind": "confirm"}
                   for o in diff["needs_decision"]]
        assert len(answers) == 3
        r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
                   json={"answers": answers})

        assert r.status_code == 200, r.text
        assert store.count(TEST_LIBRARY) == 3
        assert not r.json()["needs_decision"]


def test_a_finding_can_be_approved_as_corrected_in_one_act():
    """✎ then ✓ is one human decision, so it is one call and one write. The
    CLAIM keeps the engine's own text — it is evidence of what was read."""
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim(title="מלכי הכופריט")], store=store,
            shelves=shelves, reads=reads_, blobs=blobs, approve_findings=False)
        pending = c.get(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff"
        ).json()["needs_decision"][0]["claim"]["id"]

        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
               json={"answers": [{"claim_id": pending, "kind": "confirm",
                                  "title": "מלכי הכופרים",
                                  "author": "פול קארני"}]})

        book = store.list(TEST_LIBRARY).items[0]
        assert book.title == "מלכי הכופרים" and book.author == "פול קארני"
        read = c.get(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}").json()
        assert read["claims"][0]["title"] == "מלכי הכופריט", (
            "the claim was rewritten; it records what the ENGINE read"
        )

        # ⚠ The half that was missing when this shipped, and the reason the
        # bug survived a green suite: nobody read the diff BACK. The book now
        # lives under a different key from the claim, so a keyed lookup alone
        # leaves the finding pending forever — and a second click would make a
        # second book.
        after = c.get(
            f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/diff").json()
        assert not after["needs_decision"], "the corrected finding stayed open"
        assert [o["existing_book"]["title"] for o in after["unchanged"]]             == ["מלכי הכופרים"]
        c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}/apply",
               json={"answers": []})
        assert store.count(TEST_LIBRARY) == 1, "re-applying made a second book"


def test_acting_on_a_finding_that_is_not_in_this_read_is_a_404():
    with _blobs() as blobs:
        store, shelves, reads_ = MemoryBookStore(), MemoryShelfStore(), MemoryReadStore()
        c = TestClient(_app(store=store, shelves=shelves, reads=reads_,
                            blobs=blobs, reader=StubReader()))
        c, shelf_id, cap_id, read_id = _settled_read(
            c, claims=[_auto_claim()], store=store, shelves=shelves,
            reads=reads_, blobs=blobs)
        r = c.post(f"{API_PREFIX}/shelves/{shelf_id}/reads/{read_id}"
                   f"/findings/nope/retract")
        assert r.status_code == 404, r.text
