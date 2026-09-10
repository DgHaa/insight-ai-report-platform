from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app import models  # noqa: F401  导入所有 ORM 模型，注册到 Base.metadata
from app.core.config import settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 使用应用配置中的异步连接串（特殊字符 % 需转义）
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        # 确保 alembic_version 表 version_num 列宽足够容纳长 revision id
        # （项目 revision id 超过 alembic 默认的 VARCHAR(32)）。必须在此显式提交，
        # 否则连接 autobegin 后 alembic 会复用该事务且不再提交，导致迁移被回滚。
        from sqlalchemy import text

        table_exists = await connection.execute(
            text("SELECT to_regclass('alembic_version')")
        )
        if table_exists.scalar() is None:
            await connection.execute(
                text(
                    "CREATE TABLE alembic_version (version_num VARCHAR(128) NOT NULL)"
                )
            )
        else:
            await connection.execute(
                text(
                    "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"
                )
            )
        await connection.commit()

        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
