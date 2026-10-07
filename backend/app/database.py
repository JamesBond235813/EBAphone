import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase

# Load the project-level environment before constructing the engine.  The
# previous import order let auth/payment read ``backend/.env`` while this
# module had already committed to its fallback MySQL URL, so deployments could
# silently connect to the wrong database unless DATABASE_URL was exported by
# the process manager itself.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_environment = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "production")).strip().lower()
_default_database_url = f"sqlite+aiosqlite:///{Path(__file__).resolve().parents[1] / 'ebaphone-dev.sqlite3'}"
DATABASE_URL = os.getenv("DATABASE_URL") or _default_database_url
if _environment in {"production", "prod"} and not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL must be explicitly configured in production")

engine = create_async_engine(DATABASE_URL, poolclass=NullPool, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with SessionLocal() as session:
        yield session
