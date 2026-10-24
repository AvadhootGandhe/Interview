from fastapi import FastAPI
from sqlalchemy.engine import Engine

from app.api import catalog
from app.db.session import make_engine


def create_app(engine: Engine | None = None) -> FastAPI:
    app = FastAPI(title="AI Mock Interview")
    app.state.engine = engine or make_engine()
    app.include_router(catalog.router)
    return app


def app_factory() -> FastAPI:
    return create_app()
