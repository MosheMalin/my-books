# `@booksnap/ui` — the shared client library

Two clients now exist: the product (`app/web`, the household's) and the
console (`app/admin`, the operator's). They were written under a "touch no
existing file" constraint, so the second one re-implemented what the first
already had — and the re-implementations had already started to drift.

This package is what they share, and only what they share.

## What belongs here

**A mechanism both apps need, or a rule both apps must not disagree about.**

| module | why it is shared |
|---|---|
| `SortControl` | the owner's own example. The console's re-invention lost the direction toggle *inside* the box and the reset-on-key-change rule |
| `vouchedFor` + the ladder's WORDS | VISION §5.1. The two apps had already disagreed about whether `manual` counts as vouched-for (the product shipped that bug) and about what `auto` is called in English. ⚠ `StatusBadge` itself is used by the console only: the product draws its own markup because `books.css` keys on `.b-auto`, so a straight swap would render its badges unstyled — and jsdom would not see it. Two renderers, one vocabulary, one rule |
| `styles/ui.css` → `.rtl-safe` | UI_PLAN §7.2. A **correctness** rule about Hebrew, not a theme; the two copies had drifted in their selectors |
| `i18n` | the provider, the `dir`/`lang` mirroring, the persistence. Not the string tables |
| `format` | `formatDate` had genuinely drifted: raw ISO in one app, `''` in the other |
| `useAsync` | the request-id guard. Dropping a superseded response is the rule; in a tenant-aware screen the race shows one library's books under another's name |
| `hash` | the `hashchange` subscription. Not the route tables |
| `testing/user` | `userEvent` with `delay: null` — measured 4× on the product's ring |

## What deliberately does not

- **Either app's vocabulary.** The product speaks about books and shelves, the
  console about accounts and totals. Shared strings cover shared *controls*
  only (`src/strings.ts` argues the line).
- **Either app's route table.** A union of both would let one app link to a
  screen it does not have.
- **Either app's palette.** The product is a reading surface, the console a
  dense table surface. Shared CSS draws from `--ui-*` and each app maps its
  own colours onto them — see the token contract below.
- **Anything that talks to a server.** The console reads a *different service*
  from the product (`planning/ADMIN_CONSOLE_PLAN.md`); a shared API client
  would be the one dependency that makes that separation meaningless.

## The one exception: `src/api/schema.d.ts`

The GENERATED contract types (`python tools/api_contract.py --write`) live
here, and they are not a UI component. They are here because **both clients
call `/api/v1`** — the console writes through it even though it reads from the
staff service — and the alternative was worse in both directions: a copy per
app is a second generated artefact the contract check does not police, and the
console importing the product's copy (what it did until now) is one client
depending on another's source tree.

⚠ It is a **subpath** import (`@booksnap/ui/api/schema`), deliberately absent
from `index.ts`. Types are erased at build time, so nothing runtime crosses;
keeping it off the barrel is what stops it reading as "the shared UI kit
knows about the API".

The staff service's types are NOT here. They are generated into
`app/admin/src/api/staff-schema.d.ts` — same pipeline, filed with the console,
because only one client speaks that protocol.

## How it is consumed

As **source**, through a path alias — never built, never published:

```ts
import { SortControl, useAsync } from '@booksnap/ui'
```

Each client sets the alias in its `vite.config.ts` and its `tsconfig.json`, and
sets:

```js
resolve: { dedupe: ['react', 'react-dom',
                    '@testing-library/dom', '@testing-library/react',
                    '@testing-library/user-event'] }
```

⚠ None of the five is optional, and the three that look like padding are the
ones that cost a debugging session. Without dedupe, Vite resolves a bare
import from THIS package's `node_modules` for shared files and from the app's
for app files:

- `react` — the familiar one: two copies break hooks, with an error message
  pointing nowhere near the cause;
- `@testing-library/*` — the subtle one. `@testing-library/dom` keeps its
  config in MODULE state and `@testing-library/react` writes React's `act`
  into it on import. A second, unconfigured copy leaves `userEvent` firing
  events OUTSIDE `act`, so React never flushes the effects — and the symptom
  is *a component that has not rendered its data yet*. It reads as a timing
  flake, not as a resolution problem.

A build step here would produce a second artefact to keep in sync, which is the
failure this repo has already recorded twice (the stale `:8757` bundle, the
stale Vite module graph). Consuming source means there is nothing to go stale.

## The token contract

`styles/ui.css` reads only `--ui-*` properties. Each app defines them in one
block in its own `tokens.css`, under `@booksnap/ui bridge`.

`src/tokens.test.ts` enforces it by reading both ends. It has to: **jsdom
computes no cascade**, so a missing mapping renders an invisible control
through a completely green client ring.

⚠ It also asserts each app *imports the sheet at all*, and imports it after its
tokens. That case exists because a review deleted
`import '@booksnap/ui/styles/ui.css'` from the product's `main.tsx` — turning
off `.rtl-safe` across the whole app and dropping the sort control's toggle out
of its box — and **every ring stayed green**. Checking the tokens without
checking the sheet is checking that the wiring has power while nobody plugged
anything in.

## Running it

```bash
npm install --prefix app/ui
npm --prefix app/ui run test
```

The gate runs it through `python tools/check.py --ui`, and staging anything
under `app/ui/` also runs BOTH clients' rings — a change here is a change to
two apps, and only they can prove it.
