# fixtures/search — the Hebrew search measurement set (P1.5)

Committed so `tests/test_search.py` and `tools/search_eval.py` reproduce on a
fresh clone with no `work/` directory.

| File | What it is |
|---|---|
| `corpus.json` | the owner's real 251 `{title, author}` pairs, exported from `work/library.json`. Titles only — no ids, statuses, provenance or run data |
| `queries.json` | hand-written queries with their expectations, each carrying a `why` |

**Real titles, not synthetic ones.** A made-up corpus agrees with whatever the
implementation happens to do. The awkward cases here — three spellings of one
Jonathan Strange title, five volumes sharing `הצי האבוד`, a book called `עיר`
living beside `עיר הזמן` and `מהעיר הדוממת` — are the ones that actually
decide whether ranking works, and no one would have invented them.

**Every query records `why`.** A query whose purpose nobody remembers is the
first thing deleted when it fails. `test_the_fixture_still_covers_the_cases_it
_claims_to` asserts the set keeps covering particles, geresh, final letters,
mixed script, ranking and series disambiguation.

## Measured, 2026-08-07

`python tools/search_eval.py --compare`, 24 queries against 251 books:

| mechanism | P@1 | recall | results/query |
|---|---|---|---|
| **and + particles + rank** (shipped) | **1.00** | **1.00** | **2.8** |
| and + particles, alphabetical | 0.88 | 1.00 | 2.8 |
| and, no particle variants | 0.94 | 0.97 | 2.7 |
| OR terms | 1.00 | 1.00 | 6.8 |
| word-start matching only | 0.81 | 0.89 | 2.5 |

Read it as: relevance ranking buys +0.12 P@1, particle tolerance +0.06 P@1 and
+0.03 recall, and infix matching +0.19 P@1 over word-start-only. AND does *not*
beat OR on P@1 — ranking is strong enough either way — so its case is the
result SET: 2.4× fewer books per query, which on a list UI is the difference
between an answer and a haystack.

P@1 is the metric that matters. On a personal library the failure mode is never
"nothing found"; it is the right book at rank 9 behind its series siblings.
Recall is reported alongside because it is trivially maxed by matching
everything — which is exactly what the noise column exists to catch.

## Regenerating

```bash
python tools/import_legacy.py --export-fixture   # unrelated: fixtures/legacy
python tools/search_eval.py --compare            # re-measure
python tools/search_eval.py --explain "הצי האבוד תעוזה"
```

`corpus.json` is exported by hand from `work/library.json` (title + author
only). It is deliberately NOT auto-refreshed: the numbers above describe this
corpus, and silently changing it would change the numbers without changing the
code.
