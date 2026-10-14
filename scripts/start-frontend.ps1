# Start the frontend dev server on http://localhost:5173.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$frontend = Join-Path $root "frontend"
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    throw "frontend/node_modules not found - run .\scripts\setup.ps1 first."
}
if (-not (Test-Path (Join-Path $frontend ".env"))) {
    Copy-Item (Join-Path $frontend ".env.example") (Join-Path $frontend ".env")
    Write-Host "Created frontend/.env from template."
}
Push-Location $frontend
try {
    Write-Host "Starting frontend on http://localhost:5173"
    npm run dev
} finally { Pop-Location }
