# Start the backend API on http://localhost:8000 (migrations first).
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $root "backend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "backend/.venv not found - run .\scripts\setup.ps1 first." }
if (-not (Test-Path (Join-Path $backend ".env"))) {
    Copy-Item (Join-Path $backend ".env.example") (Join-Path $backend ".env")
    Write-Host "Created backend/.env from template."
}

Push-Location $backend
try {
    Write-Host "Applying database migrations..."
    & $venvPython -m saudi_plot_api.migrate
    if ($LASTEXITCODE -ne 0) { throw "Migrations failed." }
    Write-Host "Starting backend on http://localhost:8000 (docs: http://localhost:8000/docs)"
    & $venvPython -m uvicorn --factory saudi_plot_api.main:create_app --host 127.0.0.1 --port 8000
} finally { Pop-Location }
