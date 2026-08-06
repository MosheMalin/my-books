# -*- coding: utf-8 -*-
"""E1 probe: can a cheap vision LLM read the shelves that Tesseract/Vision can't?

One whole-photo call per image (same granularity as `fullpage` mode), model
returns structured [{title, author}], scored against fixtures/ground_truth.json with the
project's own particle-tolerant scorer. This measures READING only — no NLI
retrieval, no matcher gates — i.e. the candidate-generation ceiling of an
llmpage mode.

Usage:  python tools/llm_read_probe.py [IMG_6082.jpeg IMG_7849.jpeg]
Needs ANTHROPIC_API_KEY in .env or the environment.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from PIL import Image

from booksnap.scoring import load_ground_truth, score_predictions

# model -> ($/MTok in, $/MTok out, max vision long edge in px)
MODELS = {
    "claude-haiku-4-5": (1.00, 5.00, 1568),
    "claude-sonnet-5": (3.00, 15.00, 2576),   # high-res vision tier
    "claude-opus-5": (5.00, 25.00, 2576),
}
MODEL = os.environ.get("PROBE_MODEL", "claude-haiku-4-5")

SCHEMA = {
    "type": "object",
    "properties": {
        "books": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "author": {"type": "string"},
                },
                "required": ["title", "author"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["books"],
    "additionalProperties": False,
}

PROMPT = (
    "This is a photograph of a bookshelf holding printed Hebrew (and occasionally "
    "English) books. Read the book spines and list every distinct book you can "
    "actually read: the title and, if printed and legible, the author, exactly as "
    "they appear on the spine. Rules: (1) only include a book if you can genuinely "
    "read its title on the spine — never guess or complete a title from your "
    "knowledge of what book it might be; (2) if the author is not visible, use an "
    "empty string; (3) publisher names and series names are not titles; "
    "(4) stylised or decorative lettering still counts if you can read it; "
    "(5) one entry per physical book."
)


def load_env() -> None:
    env = REPO / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def encode_image(img: Image.Image) -> tuple[str, dict]:
    max_edge = MODELS[MODEL][2]
    w, h = img.size
    if max(w, h) > max_edge:
        scale = max_edge / max(w, h)
        img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=88)
    data = base64.standard_b64encode(buf.getvalue()).decode()
    return data, {"sent": img.size, "kb": len(buf.getvalue()) // 1024}


def make_tiles(img: Image.Image, grid: str) -> list[Image.Image]:
    """Split into an RxC grid with 15% overlap so no spine is cut without a
    second chance; '1x1' means the whole image."""
    rows, cols = (int(x) for x in grid.split("x"))
    if rows == cols == 1:
        return [img]
    w, h = img.size
    tw, th = w / cols, h / rows
    ox, oy = tw * 0.15, th * 0.15
    out = []
    for r in range(rows):
        for c in range(cols):
            box = (max(0, round(c * tw - ox)), max(0, round(r * th - oy)),
                   min(w, round((c + 1) * tw + ox)), min(h, round((r + 1) * th + oy)))
            out.append(img.crop(box))
    return out


def read_image(client, img: Image.Image) -> tuple[list[dict], dict]:
    data, info = encode_image(img)
    t0 = time.time()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                {"type": "text", "text": PROMPT},
            ],
        }],
    )
    info["seconds"] = round(time.time() - t0, 1)
    info["input_tokens"] = resp.usage.input_tokens
    info["output_tokens"] = resp.usage.output_tokens
    info["stop_reason"] = resp.stop_reason
    pin, pout, _ = MODELS[MODEL]
    info["usd"] = round(resp.usage.input_tokens * pin / 1e6
                        + resp.usage.output_tokens * pout / 1e6, 5)
    text = next((b.text for b in resp.content if b.type == "text" and b.text), None)
    if text is None:
        return [], info
    try:
        return json.loads(text)["books"], info
    except (json.JSONDecodeError, KeyError):
        info["parse_error"] = text[:200]
        return [], info


def read_shelf(client, image_path: Path) -> tuple[list[dict], dict]:
    """Read one photo: optional rotation, optional tiling, union + dedupe."""
    from booksnap.catalog import normalize
    rotate = os.environ.get("PROBE_ROTATE", "none")   # cw | ccw | none
    grid = os.environ.get("PROBE_TILES", "1x1")
    img = Image.open(image_path)
    if rotate == "cw":
        img = img.transpose(Image.ROTATE_270)
    elif rotate == "ccw":
        img = img.transpose(Image.ROTATE_90)

    books: list[dict] = []
    seen: set[str] = set()
    agg = {"rotate": rotate, "grid": grid, "tiles": [], "seconds": 0.0,
           "input_tokens": 0, "output_tokens": 0, "usd": 0.0}
    for tile in make_tiles(img, grid):
        tb, info = read_image(client, tile)
        agg["tiles"].append(info)
        for k in ("seconds", "input_tokens", "output_tokens", "usd"):
            agg[k] = round(agg[k] + info[k], 5)
        for b in tb:
            key = normalize(b.get("title", ""))
            if key and key not in seen:
                seen.add(key)
                books.append(b)
    return books, agg


def main() -> None:
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set (env or .env)")
    import anthropic
    client = anthropic.Anthropic()

    gt = load_ground_truth()
    images = sys.argv[1:] or ["IMG_6082.jpeg", "IMG_7849.jpeg"]
    out_dir = REPO / "work" / "llm_probe"
    out_dir.mkdir(parents=True, exist_ok=True)

    total_usd = 0.0
    for name in images:
        path = REPO / "samples" / name
        books, info = read_shelf(client, path)
        total_usd += info["usd"]
        print(f"\n=== {name}  ({MODEL} rotate={info['rotate']} tiles={info['grid']}) ===")
        print(f"  {len(info['tiles'])} call(s), {info['seconds']}s, "
              f"{info['input_tokens']}in/{info['output_tokens']}out tokens = ${info['usd']}")
        for b in books:
            print(f"  {b['title']}  |  {b['author']}")

        record = {"model": MODEL, "image": name, "info": info, "books": books}
        if name in gt:
            score = score_predictions(books, gt[name], image=name)
            d = score.to_dict()
            record["score"] = d
            print(f"  -> read-rate: P {d['precision']} R {d['recall']} F1 {d['f1']} "
                  f"({len(d['correct'])}/{d['n_truth']} correct, "
                  f"{len(d['phantom'])} phantom)")
            if d["missed"]:
                print("  missed: " + " | ".join(d["missed"]))
            if d["phantom"]:
                print("  phantom: " + " | ".join(d["phantom"]))
        (out_dir / f"{Path(name).stem}.{MODEL}.r-{info['rotate']}.t-{info['grid']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\ntotal cost: ${round(total_usd, 5)}")


if __name__ == "__main__":
    main()


