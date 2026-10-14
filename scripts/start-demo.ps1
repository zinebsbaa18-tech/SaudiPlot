# Start backend and frontend together, each in its own window. No secrets are
# read or written here; each service loads its own gitignored .env.
$ErrorActionPreference = "Stop"
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "start-backend.ps1")
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "start-frontend.ps1")
Write-Host "Backend starting on  http://localhost:8000  (docs: http://localhost:8000/docs)"
Write-Host "Frontend starting on http://localhost:5173"
