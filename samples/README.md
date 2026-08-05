# Sample shelf photos

Four real shelf photos from the owner's library, used as regression fixtures.
The pipeline's measured results in CLAUDE.md are against these exact images.

| file | shelf | ~identifiable books |
|------|-------|--------------------|
| IMG_7849.jpeg | fantasy (Kearney, Snyder, Pearson, Martin) | ~14 |
| A5E6FC52-...jpeg | glass cabinet (mixed fiction) | ~11 |
| IMG_6082.jpeg | Durrell / Herriot nature writing | ~14 |
| B9E88456-...jpeg | two-group mixed shelf | ~17 |

Run the pipeline over them:
    python -m booksnap.cli --catalog sample_catalog.json --debug samples/*.jpeg

Debug segmentation overlays land in work/debug/.
