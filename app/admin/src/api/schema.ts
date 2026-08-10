/**
 * The API contract, as types — the ONE place this app crosses into `app/web`.
 *
 * ⚠ This is a **type-only** re-export of the client contract generated from
 * `app/api/openapi.json` (`python tools/api_contract.py --write`). Every type
 * below is erased at build time, so the two clients share a compiler
 * guarantee and no runtime code whatsoever.
 *
 * Why import rather than copy: a copied `schema.d.ts` is a second generated
 * artefact that `tools/api_contract.py --check` does not police, and it would
 * drift in silence — the same failure this repo has already recorded for the
 * stale `:8757` bundle and the stale Vite module graph. Importing means a
 * renamed DTO field breaks BOTH clients' builds on the same commit, which is
 * the entire point of D3's TypeScript decision.
 *
 * If this console is ever extracted to its own repository, the replacement is
 * one line: run `openapi-typescript ../api/openapi.json -o src/api/schema.d.ts`
 * and re-point the import below.
 */
import type { components, paths } from '../../../web/src/api/schema'

export type { components, paths }

type Schemas = components['schemas']

// --- tenancy ---------------------------------------------------------------

/** One library the CALLER is a member of, with the role they hold.
 *  ⚠ Not "every library in the system" — see `AccessPage` and the plan: the
 *  server has no route that lists libraries across accounts. */
export type LibraryDTO = Schemas['LibraryDTO']
export type MetaResponse = Schemas['MetaResponse']
export type AccountDTO = Schemas['AccountDTO']

// --- books -----------------------------------------------------------------

export type BookDTO = Schemas['BookDTO']
export type BookPageDTO = Schemas['BookPageDTO']
export type CopyDTO = Schemas['CopyDTO']
export type SightingDTO = Schemas['SightingDTO']
export type BookPatch = Schemas['BookPatch']
/** `auto | approved | manual` — §5.1's ladder, strongest claim wins. */
export type Status = Schemas['Status']
export type BookSort = Schemas['BookSort']

// --- shelves, reads, the duplicate queue ------------------------------------

export type ShelfDTO = Schemas['ShelfDTO']
export type ShelfOverviewDTO = Schemas['ShelfOverviewDTO']
export type ReadSummaryDTO = Schemas['ReadSummaryDTO']
export type DuplicateQuestionDTO = Schemas['DuplicateQuestionDTO']

/** Path keys, so a URL this app builds by hand can still be checked against
 *  the contract in a test rather than only at runtime. */
export type ApiPath = keyof paths
