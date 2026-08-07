# fixtures/legacy — a sample of today's `work/` shapes

Committed so `tests/test_legacy_import.py` runs on a fresh clone with no
`work/` directory at all (plan H6: "a committed fixtures/legacy/ sample of
today's work/ shapes, and a test asserting the import produces the expected
entities").

Regenerate with:

    python tools/import_legacy.py --export-fixture

**Sampled by SHAPE, not at random** — every distinct `source` shape the real
data contains appears here, because a fixture that misses one stops proving
anything about it. Currently 9 books, 3 run(s),
2 image(s), 17 decision(s).

Shapes covered:

| Shape | Why it is here |
|---|---|
| stale key | 30 of the owner's 251 keys predate the geresh fix in `normalize()`; the importer must RE-KEY rather than trust the file |
| `source.manual` + `owner-fb-<title>` spine id | a book typed in from the review screen |
| `source.manual` + `manual-<timestamp>` spine id | the same action, a different id format — `owner-fb-` alone would miss 9 of the 24 |
| `source.replaced` | a human picked from ranked alternatives; imported as `approved`, not `manual` |
| `status: auto` | absorbed from an AUTO claim, never looked at |
| `status: approved`, real spine id | the common case; its `<image_id>_b<n>_s<nn>` prefix is what dates the sighting |

Pruned from `store.json`: each run's `config` snapshot and per-image detail.
The importer never reads them, and they carry absolute paths from the owner's
machine. Everything the importer DOES read is verbatim.

The owner's own book titles. Not synthetic — a hand-written fixture would have
agreed with whatever the importer happened to do.
