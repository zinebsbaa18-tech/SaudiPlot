"""Migration smoke test: alembic upgrade head matches the ORM metadata."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("alembic")
pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")
pytest.importorskip("httpx")  # fastapi.testclient needs it

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, inspect  # noqa: E402

from saudi_plot_api.database import Base  # noqa: E402
from saudi_plot_api.models import AnonymousSession, Project  # noqa: F401, E402

ROOT = Path(__file__).resolve().parents[1]


def _migrate(tmp_path: Path, monkeypatch) -> Path:
    db_path = tmp_path / "migration_smoke.db"
    monkeypatch.setenv("SPD_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "src" / "saudi_plot_api" / "migrations"))
    command.upgrade(config, "head")
    return db_path


def test_upgrade_head_creates_expected_schema(tmp_path, monkeypatch):
    db_path = _migrate(tmp_path, monkeypatch)
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    inspector = inspect(engine)

    tables = set(inspector.get_table_names())
    assert {"anonymous_sessions", "projects"} <= tables

    # Every ORM-declared column exists with matching nullability -- the
    # migration and the models cannot drift silently.
    for table in ("anonymous_sessions", "projects"):
        migrated = {col["name"]: col for col in inspector.get_columns(table)}
        declared = Base.metadata.tables[table]
        assert set(migrated) == {col.name for col in declared.columns}
        for col in declared.columns:
            assert migrated[col.name]["nullable"] == col.nullable, (table, col.name)

    unique = inspector.get_unique_constraints("anonymous_sessions")
    assert any(c["column_names"] == ["token_hash"] for c in unique)
    fks = inspector.get_foreign_keys("projects")
    assert any(fk["referred_table"] == "anonymous_sessions" for fk in fks)
    engine.dispose()


def test_migrated_database_serves_the_app(tmp_path, monkeypatch):
    """The API runs against a database created purely by alembic."""
    from fastapi.testclient import TestClient

    from saudi_plot_api.config import Settings
    from saudi_plot_api.main import create_app

    db_path = _migrate(tmp_path, monkeypatch)
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{db_path.as_posix()}",
        cookie_secure=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.post("/api/v1/sessions").status_code == 201
        created = client.post("/api/v1/projects", json={"current_step": "confirm-data"})
        assert created.status_code == 201
    app.state.engine.dispose()


# ── Codex round 1 regressions ───────────────────────────────────────────────


def test_migration_creates_missing_database_directory(tmp_path, monkeypatch):
    """Clean-checkout workflow: the sqlite directory may not exist yet."""
    db_path = tmp_path / "no" / "such" / "dir" / "app.db"
    monkeypatch.setenv("SPD_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "src" / "saudi_plot_api" / "migrations"))
    command.upgrade(config, "head")
    assert db_path.exists()


def test_migration_reads_dotenv_like_the_application(tmp_path, monkeypatch):
    """A URL configured only in .env must reach alembic, exactly as it
    reaches the application through Settings."""
    db_path = tmp_path / "dotenv_target.db"
    monkeypatch.delenv("SPD_DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        f"SPD_DATABASE_URL=sqlite:///{db_path.as_posix()}\n", encoding="utf-8"
    )
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "src" / "saudi_plot_api" / "migrations"))
    command.upgrade(config, "head")
    assert db_path.exists()
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    assert {"anonymous_sessions", "projects"} <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_migration_url_with_percent_characters(tmp_path, monkeypatch):
    """ConfigParser interpolation must not choke on '%' in the database URL
    (e.g. percent-encoded credentials in a future PostgreSQL URL)."""
    db_path = tmp_path / "p%40ss" / "app.db"
    monkeypatch.setenv("SPD_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "src" / "saudi_plot_api" / "migrations"))
    command.upgrade(config, "head")
    assert db_path.exists()


# ── Codex round 5 regressions ───────────────────────────────────────────────


def test_programmatic_migration_runner_needs_no_ini(tmp_path, monkeypatch):
    """Installed deployments migrate via python -m saudi_plot_api.migrate."""
    from saudi_plot_api import migrate

    db_path = tmp_path / "installed.db"
    monkeypatch.setenv("SPD_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.chdir(tmp_path)  # nowhere near the repo alembic.ini
    migrate.upgrade_to_head()
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    assert {"anonymous_sessions", "projects"} <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_wheel_ships_migration_assets(tmp_path):
    """A non-editable install must contain env.py, the mako template, and the
    versions -- otherwise the documented migration workflow breaks."""
    import subprocess
    import sys
    import zipfile

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(tmp_path),
            str(ROOT),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    (wheel_path,) = tmp_path.glob("*.whl")
    names = zipfile.ZipFile(wheel_path).namelist()
    assert "saudi_plot_api/migrations/env.py" in names
    assert "saudi_plot_api/migrations/script.py.mako" in names
    assert any(
        n.startswith("saudi_plot_api/migrations/versions/") and n.endswith(".py") for n in names
    )
