# -*- coding: utf-8 -*-
"""Command-line entrypoint.

    python -m booksnap.cli --catalog sample_catalog.json --debug img1.jpg img2.jpg

Prints a per-spine summary and writes results.json to the work dir.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

from .pipeline import Pipeline
from .catalog import LocalCatalog
from .config import CONFIG


def main(argv=None):
    # Windows consoles default to a legacy codepage (e.g. cp1255) that can't
    # encode the Hebrew titles / check-mark glyphs this CLI prints.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="booksnap bookshelf cataloguer")
    ap.add_argument("images", nargs="+", help="shelf photo paths")
    ap.add_argument("--catalog", required=True, help="catalog JSON path")
    ap.add_argument("--debug", action="store_true",
                    help="write segmentation overlays to work/debug")
    ap.add_argument("--out", default=None, help="results JSON output path")
    args = ap.parse_args(argv)

    catalog = LocalCatalog.from_json(args.catalog)
    pipe = Pipeline(catalog=catalog, debug=args.debug)
    records = pipe.run(args.images)

    stats = {"AUTO": 0, "REVIEW": 0, "none": 0}
    by_image: dict[str, list] = {}
    for r in records:
        by_image.setdefault(r.spine.image, []).append(r)
    for image, recs in by_image.items():
        print(f"\n=== {image} — {len(recs)} spines ===")
        for r in recs:
            m = r.match
            if m and m.tier == "AUTO":
                stats["AUTO"] += 1
                print(f"  \u2713 AUTO   {m.title} \u2014 {m.author}")
            elif m:
                stats["REVIEW"] += 1
                print(f"  ? REVIEW {m.title} \u2014 {m.author}")
            else:
                stats["none"] += 1
                txt = (r.ocr.text if r.ocr else "")[:42]
                print(f"  \u2717 ------ {txt}")
    total = sum(stats.values())
    print(f"\nTOTALS ({total} spines): {stats}")

    out = args.out or (CONFIG.paths.work_dir / "results.json")
    Pipeline.save(records, out)
    print(f"results -> {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
