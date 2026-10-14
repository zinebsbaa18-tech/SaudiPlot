#!/bin/bash
# Post-merge setup: install dependencies and run migrations.
# Runs from the repository root. Stdin is closed (non-interactive).
set -e

echo "=== Installing Python backend dependencies ==="
cd backend
# Install core package first (no rlPyCairo — needs cairo system lib not yet
# available via pkg-config; it is lazily imported so the app runs without it)
pip install -e "." -q
pip install fastapi uvicorn sqlalchemy alembic pydantic-settings \
    python-multipart httpx svglib reportlab cairosvg -q

echo "=== Running database migrations ==="
python -m saudi_plot_api.migrate

echo "=== Installing frontend dependencies ==="
cd ../frontend
npm install --prefer-offline

echo "=== Post-merge setup complete ==="
