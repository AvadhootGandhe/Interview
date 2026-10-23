"""Engine/session helpers and the FastAPI `get_db` dependency."""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import Base

# Porter stemming lets "eviction" match "evict" and "caching" match "cache".
FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS questions_fts "
    "USING fts5(question_id UNINDEXED, text, tokenize='porter unicode61')"
)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(FTS_DDL))


def make_engine(url: str) -> Engine:
    kwargs = {}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
    elif url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
    engine = create_engine(url, **kwargs)
    init_db(engine)
    return engine


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(make_engine(settings.database_url))


def get_db() -> Iterator[Session]:
    with _session_factory()() as session:
        yield session
