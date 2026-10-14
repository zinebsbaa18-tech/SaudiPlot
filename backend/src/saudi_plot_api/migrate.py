"""Programmatic Alembic runner for installed deployments.

A wheel or sdist install has no repository ``alembic.ini``; this module builds
the configuration from the packaged migration scripts instead, so

    python -m saudi_plot_api.migrate

upgrades the configured database (SPD_DATABASE_URL / .env / default) to head.
The source-checkout workflow (``alembic upgrade head`` with alembic.ini) keeps
working unchanged -- both paths run the same env.py, which resolves the URL
through Settings.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def build_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def upgrade_to_head() -> None:
    command.upgrade(build_config(), "head")


if __name__ == "__main__":
    upgrade_to_head()
