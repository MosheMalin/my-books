# booksnap — the product API and the built client, one image (P4.4).
#
# ⚠ ONE image serving BOTH, deliberately: `app/main.py` mounts the built
# client at "/" (see `WEB_DIST`), so in production there is no second web
# server and no CORS surface — the client and the API are same-origin, which
# is what makes the HttpOnly session cookie work without a single header.
# The staff service (:8758) is a SEPARATE process by design and gets its own
# service in compose; it never shares this container's port.
#
# Tesseract is installed because the free deterministic reading path is the
# graceful-degradation story (§10) — an image that can only run the paid
# engine is an image that stops working when a quota does.

# --- client build ----------------------------------------------------------
FROM node:24-bookworm-slim AS web
WORKDIR /src
# `app/ui` first: both clients install it through their own postinstall, and
# the copy order is what keeps a client-only edit off the ui layer's cache.
COPY app/ui/package.json app/ui/package-lock.json* app/ui/
RUN cd app/ui && npm ci --ignore-scripts
COPY app/ui app/ui
COPY app/web/package.json app/web/package-lock.json* app/web/
RUN cd app/web && npm ci
COPY app/web app/web
RUN cd app/web && npm run build

# --- runtime ---------------------------------------------------------------
FROM python:3.13-slim-bookworm AS runtime

# Hebrew OCR models included: the deterministic path is not optional
# (CLAUDE.md's philosophy, and §10's degradation answer).
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-heb libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY booksnap booksnap
COPY app app
COPY tools tools
COPY --from=web /src/app/web/dist app/web/dist

# Not root: the only thing this process should be able to write is its own
# state, which is a mounted volume.
RUN useradd --system --uid 10001 booksnap \
    && mkdir -p /data/work /data/blobs \
    && chown -R booksnap:booksnap /data
USER booksnap

ENV BOOKSNAP_WORK=/data/work \
    BOOKSNAP_DB=/data/work/product.db \
    BOOKSNAP_BLOBS=/data/blobs \
    PYTHONUNBUFFERED=1

EXPOSE 8757
# One worker: the job runner's state lives on the app instance (§1.3 — "the
# job runner holds its state on an INSTANCE, never a module global"), and a
# second worker would be a second queue with its own idea of what is running.
# Scaling past one household means a shared queue, not more workers.
# ⚠ --forwarded-allow-ips is the PROXY's network, never "*". With "*",
# uvicorn takes the LEFTMOST X-Forwarded-For — the caller's own value —
# so the per-source rate door is whatever an attacker types (measured:
# 120 sign-in links from one host, 0 refusals). Caddy replaces XFF by
# default so it is latent today, and it goes live the first time anyone
# adds `trusted_proxies` or a second load balancer. 172.16/12 is
# Docker's own bridge range: only the proxy beside us is believed.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8757", \
     "--workers", "1", "--proxy-headers", \
     "--forwarded-allow-ips", "172.16.0.0/12"]
