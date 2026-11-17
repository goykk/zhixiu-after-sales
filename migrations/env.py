from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.db.base import Base, init_engine  # noqa: E402
import core.db.models  # noqa: E402,F401  # 注册全部表

try:
    import core.multimodal.uploads  # noqa: E402,F401
except ModuleNotFoundError:
    pass

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    from services.api.app.config import settings

    if settings.database_url:
        return settings.database_url
    return config.get_main_option("sqlalchemy.url") or "sqlite:///./data/app.db"


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = database_url()
    connectable = init_engine(url)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=url.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()