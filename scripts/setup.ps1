# One-time local setup: backend venv + dependencies, frontend node_modules,
# and local .env files from the committed templates. Safe to re-run.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")

# ── Backend ─────────────────────────────────────────────────────────────────
$backend = Join-Path $root "backend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating backend virtual environment (.venv)..."
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { & py -3 -m venv (Join-Path $backend ".venv") }
    else { & python -m venv (Join-Path $backend ".venv") }
}
Write-Host "Installing backend dependencies (dev + web extras)..."
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -e "$backend[dev,web]"
if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed." }

if (-not (Test-Path (Join-Path $backend ".env"))) {
    Copy-Item (Join-Path $backend ".env.example") (Join-Path $backend ".env")
    Write-Host "Created backend/.env from template (no secrets; edit locally as needed)."
}

# ── Frontend ────────────────────────────────────────────────────────────────
$frontend = Join-Path $root "frontend"
Write-Host "Installing frontend dependencies (npm ci)..."
Push-Location $frontend
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }
} finally { Pop-Location }

if (-not (Test-Path (Join-Path $frontend ".env"))) {
    Copy-Item (Join-Path $frontend ".env.example") (Join-Path $frontend ".env")
    Write-Host "Created frontend/.env from template."
}

Write-Host ""
Write-Host "Setup complete. Start the demo with: .\scripts\start-demo.ps1"
