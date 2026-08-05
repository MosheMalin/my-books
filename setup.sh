#!/usr/bin/env bash
# One-time setup: Tesseract + Hebrew models + Python deps.
set -e
apt-get install -y tesseract-ocr
mkdir -p tessdata tessfast
BEST=https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main
FAST=https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main
curl -sL -o tessdata/heb.traineddata      $BEST/heb.traineddata
curl -sL -o tessdata/Hebrew.traineddata   $BEST/script/Hebrew.traineddata
curl -sL -o tessfast/heb.traineddata      $FAST/heb.traineddata
pip install -r requirements.txt
echo "Setup complete. Run: python -m booksnap.cli --catalog sample_catalog.json --debug <images...>"
