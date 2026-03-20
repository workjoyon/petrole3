from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _fix_async_url(url: str) -> str:
    """Fix Neon.tech connection string for asyncpg compatibility.
    asyncpg uses 'ssl=require' not 'sslmode=require'."""
    if "asyncpg" in url and "sslmode=" in url:
        url = url.replace("?sslmode=require", "").replace("&sslmode=require", "")
        url = url.replace("?channel_binding=require", "").replace("&channel_binding=require", "")
        # Remove trailing ? if params were stripped
        url = url.rstrip("?").rstrip("&")
    return url


_connect_args = {}
if "neon.tech" in settings.DATABASE_URL or "sslmode" in settings.DATABASE_URL:
    import ssl as _ssl_module
    _ctx = _ssl_module.create_default_context()
    _connect_args = {"ssl": _ctx}

engine = create_async_engine(
    _fix_async_url(settings.DATABASE_URL),
    echo=settings.ENVIRONMENT == "development",
    connect_args=_connect_args,
)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
