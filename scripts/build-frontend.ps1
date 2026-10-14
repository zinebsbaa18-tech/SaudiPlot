# Production build + lint for the frontend. Lint is checked against the
# approved frozen-frontend baseline (scripts/frontend-lint-baseline.json):
# the 13 known errors in the frozen UI are accepted, anything new fails.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$frontend = Join-Path $root "frontend"
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    throw "frontend/node_modules not found - run .\scripts\setup.ps1 first."
}
Push-Location $frontend
try {
    Write-Host "Building production bundle..."
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }

    Write-Host "Linting (against the approved frozen baseline)..."
    $report = Join-Path $env:TEMP "saudi-plot-eslint-report.json"
    npx eslint . -f json -o $report
    # eslint exits nonzero whenever errors exist; the baseline check decides.
    node (Join-Path $root "scripts\check-lint-baseline.mjs") $report (Join-Path $root "scripts\frontend-lint-baseline.json")
    exit $LASTEXITCODE
} finally { Pop-Location }
