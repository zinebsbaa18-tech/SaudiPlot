"""ADR-WEB-001 dependency-direction guards.

The deterministic offline core (saudi_plot_design) must never import the web
adapter or any web dependency. These tests run in a core-only environment --
they need no web packages themselves.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = ROOT / "src" / "saudi_plot_design"

FORBIDDEN_IN_CORE = (
    "saudi_plot_api",
    "fastapi",
    "starlette",
    "uvicorn",
    "sqlalchemy",
    "alembic",
    "pydantic_settings",
    "multipart",
    "httpx",
)


def test_core_source_never_imports_web_code():
    hits = []
    for path in CORE_SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in FORBIDDEN_IN_CORE:
            for pattern in (f"import {name}", f"from {name}"):
                if pattern in text:
                    hits.append(f"{path.relative_to(ROOT)}: {pattern}")
    assert not hits, "core must not depend on the web adapter or web packages:\n" + "\n".join(hits)


def test_core_import_pulls_no_web_modules():
    """Importing the full core pipeline never loads web packages."""
    probe = (
        "import sys\n"
        "import saudi_plot_design.cli\n"
        "import saudi_plot_design.output\n"
        "loaded = [m for m in ('saudi_plot_api', 'fastapi', 'starlette', 'sqlalchemy',\n"
        "                      'alembic', 'httpx', 'uvicorn')\n"
        "          if m in sys.modules]\n"
        "assert not loaded, f'core import loaded web modules: {loaded}'\n"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
