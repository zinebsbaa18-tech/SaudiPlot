# Run the complete backend test suite.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $root "backend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "backend/.venv not found - run .\scripts\setup.ps1 first." }
Push-Location $backend
try {
    # --basetemp avoids a Windows shared-temp teardown quirk with pytest.
    & $venvPython -m pytest --basetemp "$env:TEMP\saudi-plot-pytest" @args
    exit $LASTEXITCODE
} finally { Pop-Location }
