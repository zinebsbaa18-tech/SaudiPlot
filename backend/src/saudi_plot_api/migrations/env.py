"""Alembic environment for the web adapter database."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from saudi_plot_api.config import Settings
from saudi_plot_api.database import Base, create_database_engine
from saudi_plot_api.models import AnonymousSession, Project  # noqa: F401  (register tables)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Resolve the URL exactly like the application does (process environment, then
# .env, then the built-in default), so migrations always target the same
# database the application uses. The alembic.ini value is documentation only.
# "%" must be doubled: set_main_option goes through ConfigParser interpolation
# (get_main_option returns the original URL).
config.set_main_option("sqlalchemy.url", Settings().database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # The shared factory also creates a missing SQLite parent directory, so
    # `alembic upgrade head` works on a clean checkout (var/ is gitignored).
    connectable = create_database_engine(config.get_main_option("sqlalchemy.url"))
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
