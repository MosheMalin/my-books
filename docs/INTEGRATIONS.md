# Integrations & deployment guide

This answers three practical questions: how to plug in Google Cloud Vision, how
the real NLI catalog helps, and what you run on your server. Everything here is
already coded and tested offline — you add credentials on your side.

## TL;DR division of labor

| Piece | Who does it | Why |
|-------|-------------|-----|
| Write the NLI + Vision adapters | done (in this package) | logic, testable offline |
| Hold the NLI API key / Google service-account key | **you, on your server** | live credentials must never pass through a chat, and my sandbox can't reach these APIs anyway |
| Verify the plumbing before spending | done | `tests/test_integrations.py` runs with mocked APIs, no key, no cost |

## 1. Google Cloud Vision fallback

**Should you hand me a token? No.** A Google service-account key is a live
credential that can incur charges; it belongs in a file on your server,
referenced by an environment variable, and should never be pasted into a chat.
My sandbox also can't reach `vision.googleapis.com`, so a key would be useless
here regardless. The adapter is written against the documented API and is
credential-agnostic — the Google client reads your key from the environment;
booksnap never touches the secret.

**Correction (Aug 2026):** earlier revisions of this file said to create a
service account and download a JSON key. Per
https://docs.cloud.google.com/vision/docs/authentication that is not the
recommended path, and **Cloud Vision does not support simple API keys at all**.
It uses **Application Default Credentials (ADC)**. For a developer machine the
supported flow needs no key file — nothing downloadable to leak:

1. Create a Google Cloud project and **enable billing** on it.
2. Install the Google Cloud CLI, then:
   ```
   gcloud init
   gcloud auth application-default login          # browser login, once
   gcloud config set project PROJECT_ID
   gcloud auth application-default set-quota-project PROJECT_ID
   gcloud services enable vision.googleapis.com
   ```
3. `pip install google-cloud-vision`

ADC writes credentials to `%APPDATA%\gcloud\application_default_credentials.json`
(Windows) and the client library finds them with no environment variable and no
code change. `GOOGLE_APPLICATION_CREDENTIALS` is only needed if you
deliberately choose the downloaded-key route instead.

Wire it in:

```python
from google.cloud import vision
from booksnap import Pipeline, NLICatalog, GoogleVisionFallback

fb = GoogleVisionFallback(vision.ImageAnnotatorClient(), image_ctor=vision.Image)
pipe = Pipeline(catalog=NLICatalog(), fallback=fb)
records = pipe.run(["shelf1.jpg", ...], use_fallback=True)
```

Cost: first 1,000 images/month free, then ~$1.50/1,000. A few-thousand-book
library is a one-time cost of a few dollars, and only the spines that fail
deterministic OCR are ever sent.

Prefer structured output? `ClaudeVisionFallback(send)` returns `{title,
author}` directly (you supply `send`, a callable wrapping the Anthropic client
+ a strict-JSON prompt), skipping the matching step for what it resolves.

## 2. The real catalog — why it genuinely helps (a corrected explanation)

An earlier claim of mine — "a bigger catalog is automatically better" — was
imprecise, and you were right to push on it. A bigger flat list also adds
*noise*: more entries mean more chances for garbled OCR to fuzzy-hit the wrong
book. Size alone is not the win.

The real win is that **NLI is a search engine, not a flat list**. The flow
changes from "fuzzy-match against everything" to:

```
garbled OCR  ->  NLI search API  ->  5-15 real candidates  ->  our matcher ranks
```

NLI does the retrieval — turning "הכוערם קארני" into a short list that includes
*מלכי הכופרים / פול קארני* — and our token-gated matcher only has to pick the
best of a handful, not scan millions. That is qualitatively better than
matching against my 57-entry hand-typed stand-in, and it covers essentially
every book legally published in Israel (legal-deposit law → the NLI/ULI catalog
is ~9M records).

Verified facts (checked, not assumed):
- Search endpoint: `https://api.nli.org.il/openlibrary/search?api_key={KEY}&query=...`
- Field-scoped, boolean query grammar (title/creator, contains/exact, AND/OR),
  JSON output.
- A key is **required** — sign up free at https://api2.nli.org.il/signup/ .

**Corrections (tested live against the real endpoint, Aug 2026):**
- There is **no usable `guest` key.** `api_key=guest` returns
  `403 {"error":{"code":"API_KEY_INVALID","message":"An invalid api_key was
  supplied. Get one at https://api2.nli.org.il:443"}}`. The earlier claim in
  this file that a guest key works for trials was wrong.
- `api.nli.org.il` is behind **Cloudflare**, which 403s the stdlib default
  `Python-urllib/3.x` User-Agent with an HTML challenge before the request
  reaches the API. `nli_catalog._default_transport` now sends a browser UA;
  with it, the endpoint returns proper JSON. So the transport is confirmed
  working end-to-end — the only missing piece is a real key.
- **OpenLibrary is not a viable Hebrew catalog**: searched live for four real
  Hebrew titles (including a well-known Durrell translation) — **0 hits each**.
- Google Books API rate-limits (HTTP 429) unauthenticated requests, so its
  Hebrew coverage could not be measured without a key. Untested, not endorsed.

Is NLI-search + local matcher better than Google-Vision + local matcher on
precision? That's an open empirical question I can't settle without API access —
but NLI is free and authoritative, so it's worth running as the primary catalog
with Vision as the OCR fallback. They're complementary, not either/or:
Vision fixes unreadable OCR; NLI resolves readable OCR to canonical records.

Setup:

```bash
export NLI_API_KEY=your_key      # or 'guest' for trials
```
```python
from booksnap import Pipeline, NLICatalog
pipe = Pipeline(catalog=NLICatalog(cache_dir="work/nli_cache"))
```
The adapter caches responses on disk (keyed by query), so a large photo batch
won't re-hit NLI for repeated strings and you stay well under rate limits.

Note: NLI's exact JSON field names can vary by record; the parser probes the
common title/creator keys defensively. On your first real run, dump one raw
response and confirm the field mapping in `nli_catalog.py::_parse` — it's the
one spot that may need a small tweak against live data.

## 3. "Install it for me" — what I did vs. what only you can do

I can't install onto your server (no access to it), and I can't run these APIs
from my sandbox (network-blocked). What I *did* do so you don't have to:

- Wrote both integrations as drop-in modules (`nli_catalog.py`, the two
  fallback classes in `fallback.py`).
- Made them dependency-light: NLI uses the Python stdlib for HTTP (no
  `requests` needed); the cloud SDKs are only touched if you actually inject a
  client.
- Wrote `tests/test_integrations.py` that exercises the full path — query
  building, response parsing, matcher hand-off, fallback re-matching — with
  **mocked** APIs, so you can run it right now with no key and no cost:

  ```bash
  python tests/test_integrations.py      # 6/6 offline
  ```

- Provided `setup.sh` for the one-time Tesseract + Hebrew-model + deps install.

So the only things left that genuinely require you: create the two keys, set two
environment variables, `pip install` the SDK(s) you choose. Everything else is
done and verified.
```
