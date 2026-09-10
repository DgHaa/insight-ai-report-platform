"""异步数据库引擎与会话管理（asyncpg 驱动 + SQLAlchemy 2.0 Async）。

连接池语义：
- pool_size = DB_POOL_MIN_SIZE（5）：池内常驻连接数（最小连接数）；
- max_overflow = DB_POOL_MAX_SIZE - DB_POOL_MIN_SIZE（15）：允许临时溢出的连接数；
- 总连接数上限 = pool_size + max_overflow = 20（最大连接数）。
"""
import asyncio
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_size=settings.DB_POOL_MIN_SIZE,
    max_overflow=settings.DB_POOL_MAX_SIZE - settings.DB_POOL_MIN_SIZE,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=1800,  # 连接回收周期 30 分钟，避免被网络设备静默断开
    pool_pre_ping=True,  # 取用前探测，避免拿到失效连接
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def warm_up_pool() -> int:
    """启动预热：并发建立 DB_POOL_MIN_SIZE 个连接并归还连接池，
    保证池内至少有 5 个可用连接处于就绪状态。"""
    target = settings.DB_POOL_MIN_SIZE

    async def _ping() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    await asyncio.gather(*(_ping() for _ in range(target)))
    return target


async def close_engine() -> None:
    """关闭引擎并释放所有连接（应用退出时调用）。"""
    await engine.dispose()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：提供数据库会话，异常时自动回滚。"""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
