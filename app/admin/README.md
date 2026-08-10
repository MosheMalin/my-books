# booksnap admin console (`app/admin/`)

The **SYSTEM administrator's** console — a second client, separate from the
household app in `app/web/`. It exists because tenant administration is a
different job for a different person, and putting those controls in the app
every household member opens means everyone carries buttons they must never
press.

⚠⚠ **There are two admin jobs and this is only one of them.**

| | sees | is a member of | invites people |
|---|---|---|---|
| **system admin** — this tool | every tenant | nothing | no (P4.3) |
| **account admin** — `Role.ADMIN` | one library | that library | no route yet (P4.3) |

A system admin is deliberately **not** a `Role`: `app.domain.tenancy.Role` says
who you are *within one library*, so a `SYSTEM_ADMIN` value would make every
membership row a place someone could grant themselves the world. It is a
property of the operator, carried by a shared token on a separate service.

Design decisions and the API audit behind them:
[`planning/ADMIN_CONSOLE_PLAN.md`](../../planning/ADMIN_CONSOLE_PLAN.md).

## Run it

The console talks to **two** services, and needs both:

| port | service | what for |
|---|---|---|
| 8758 | `app/staff_api/` — cross-tenant, **read-only** | everything the operator can SEE |
| 8757 | `app/main.py` — the ordinary product API | everything they can CHANGE, only inside their own libraries |

```bash
python -c "import uvicorn; uvicorn.run('app.main:app', host='0.0.0.0', port=8757)"
```

```bash
python -c "import uvicorn; uvicorn.run('app.staff_api.main:app', host='0.0.0.0', port=8758)"
```

⚠ **Set a staff token before exposing 8758.** The product API has no
authentication — a deliberate single-household trade until pillar 4 — and that
trade does NOT carry over to a service that returns every account and every
household's books. Put `BOOKSNAP_STAFF_TOKEN=<something long>` in `.env` (or
the environment) and the service refuses every request without it; the console
asks for it once and keeps it in that browser. With no token set the service
still serves, and says so in a banner you cannot miss.

Then, once per clone:

```bash
npm install --prefix app/admin
```

and to serve it:

```bash
npm --prefix app/admin run dev
```

It listens on **port 5174** (the product client keeps 5173, so both can run at
once) and binds `0.0.0.0`, so it is reachable **from a phone on the same
network** at `http://<this-machine's-LAN-ip>:5174`. Vite prints the address as
*Network:* when it starts; `ipconfig` finds it otherwise.

For a built bundle rather than the dev server:

```bash
npm --prefix app/admin run build
```

```bash
npm --prefix app/admin run preview
```

`preview` binds the same host and port. ⚠ Nothing mounts `app/admin/dist/`
behind FastAPI — unlike the product client, which `app/main.py` serves at `/`
— so the dev or preview server *is* how this app is reached.

## ⚠ There is no login

Anyone on the local network can open this and administer the library. That is
the same deliberate single-household trade `:8757` and `:5173` already make
until pillar 4 lands authentication — but it matters more here, so the Access
screen says it on screen too. Do not expose port 5174 beyond the LAN.

## What it does

| Screen | What it shows |
|---|---|
| **Overview** | System-wide totals — accounts, libraries, memberships, books, copies, shelves, photos, reads, duplicates, lent-out — and the same figures per library. |
| **Libraries** | Every library in the system. Rename and export where the operator is a member; read-only elsewhere. |
| **Library** | One library's numbers, its members and their roles, its shelves with last-read dates, and its recent reads. |
| **Books** | Every book in every tenant, server-paged and searchable by the product's own measured Hebrew rules. Approve / edit / delete, but only in the operator's own libraries. |
| **Users** | Every account in the system and the libraries each belongs to. |
| **Access** | The staff credential, the two admin jobs named apart, and what user management still needs from the backend. |

⚠ **Reading is cross-tenant; writing is not.** The staff service does not
write at all, and the product API resolves the caller's own membership and
404s for anything else (§4.2). So a book or a library outside the operator's
memberships shows its numbers and says it is read-only, rather than offering a
button that would fail on click.

⚠ **Users are reported, not profiled.** The Users screen shows identity and
membership and deliberately no per-person reading or capture activity — a feed
of what someone has been photographing in their own home is a different and
much larger power, and this product has no login, audit trail or consent story
to justify it yet.

**Not here, because no route exists in either service:** inviting or removing
users, changing roles, and deleting a library. Each is named on the Access
screen with what would unblock it. None is present as a disabled control — a
greyed-out button that never becomes clickable reads as a bug.

## Development

```bash
npm --prefix app/admin run typecheck
```

```bash
npm --prefix app/admin run test
```

```bash
python tests/run_all.py test_staff_api
```

51 client tests and 20 Python ones. They test what encodes a **decision** — the tenant reference on every
request, the §5.1 ladder behind "awaiting approval", the delete confirmation,
the absence of an invite control — not layout and not DTO plumbing. Each was
mutation-checked: reversing the rule fails a named test.

⚠ The ring mocks `fetch` and runs in jsdom, which computes no CSS cascade. A
green suite is not "the screen is right"; the product's own notes list several
layout bugs that were invisible to exactly this kind of test and had to be
caught in a browser.

Product-API types come from `app/web/src/api/schema.d.ts` by a **type-only**
import, so a renamed DTO breaks both clients' builds on the same commit.
Regenerate with `python tools/api_contract.py --write` as usual.

Staff-API types in `src/api/staff.ts` are hand-written and mirror
`app/staff_api/app.py`: that service is not part of the committed
`app/api/openapi.json` contract, and adding it there would mean editing that
artefact and the tool that checks it. Keep the two in step; a mismatch shows up
immediately as `undefined` in a table.
