from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.engine import Engine

from app.agents.orchestrator import Orchestrator
from app.api import catalog, sessions
from app.config import settings
from app.db.session import make_engine


def _default_llm_and_generator():
    if settings.fake_llm:
        from app.llm.fake_llm import FakeInterviewLLM, NoGenerator
        return FakeInterviewLLM(), NoGenerator()
    from app.agents.question_generator import QuestionGenerator
    from app.llm.claude_client import ClaudeClient
    from app.llm.local_client import LocalClient
    return ClaudeClient(), QuestionGenerator(LocalClient(settings.llama_server_url))


def create_app(engine: Engine | None = None, llm=None, generator=None,
               followup_log: Path | None = Path("data/followup_train.jsonl")) -> FastAPI:
    app = FastAPI(title="AI Mock Interview")
    app.state.engine = engine or make_engine()
    if llm is None or generator is None:
        default_llm, default_gen = _default_llm_and_generator()
        llm, generator = llm or default_llm, generator or default_gen
    app.state.llm = llm
    app.state.orchestrator = Orchestrator(app.state.engine, llm, generator, followup_log=followup_log)
    app.include_router(catalog.router)
    app.include_router(sessions.router)
    return app


def app_factory() -> FastAPI:
    return create_app()
