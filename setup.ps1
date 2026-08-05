# One-time setup for Windows: Tesseract + Hebrew models + Python deps.
# Linux/macOS: use ./setup.sh instead.
$ErrorActionPreference = "Stop"

$tessPath = "C:\Program Files\Tesseract-OCR"
if (-not (Get-Command tesseract -ErrorAction SilentlyContinue)) {
    Write-Output "Installing Tesseract OCR via winget..."
    winget install --id UB-Mannheim.TesseractOCR -e --silent --accept-package-agreements --accept-source-agreements

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$tessPath*") {
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$tessPath", "User")
        Write-Output "Added $tessPath to User PATH (restart your shell to pick it up)"
    }
    $env:Path += ";$tessPath"
} else {
    Write-Output "Tesseract already on PATH, skipping install."
}

New-Item -ItemType Directory -Force -Path tessdata, tessfast | Out-Null
$BEST = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main"
$FAST = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main"
Invoke-WebRequest -Uri "$BEST/heb.traineddata" -OutFile "tessdata/heb.traineddata"
Invoke-WebRequest -Uri "$BEST/script/Hebrew.traineddata" -OutFile "tessdata/Hebrew.traineddata"
Invoke-WebRequest -Uri "$FAST/heb.traineddata" -OutFile "tessfast/heb.traineddata"

python -m pip install -r requirements.txt

Write-Output "Setup complete. Run: python -m booksnap.cli --catalog sample_catalog.json --debug shelf1.jpg"
