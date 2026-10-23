"""🖥 Phase 2 "done when" on the full 914 MB dataset (local only, takes minutes)."""
from __future__ import annotations

import time

import pytest
from sqlalchemy.orm import Session

from app.db.session import make_engine
from app.services.retriever import Filters, Retriever
from scripts.ingest import ingest
from tests.conftest import REPO_ROOT

FULL = REPO_ROOT / "by_company_profile_level_topic.json"

pytestmark = pytest.mark.local


@pytest.fixture(scope="module")
def full_db(tmp_path_factory):
    if not FULL.exists():
        pytest.skip("full dataset not present")
    engine = make_engine(f"sqlite:///{tmp_path_factory.mktemp('full') / 'full.db'}")
    start = time.perf_counter()
    stats = ingest(FULL, engine)
    assert time.perf_counter() - start < 15 * 60
    assert 125_000 < stats["questions"] < 140_000
    assert 3_500_000 < stats["mappings"] < 4_200_000
    with Session(engine) as session:
        yield session


def test_amazon_ai_engineer_architect_agents_pool(full_db):
    pool = Retriever(full_db).build_pool(Filters(
        company="Amazon", profile="AI Engineer", level="Architect/Principal",
        topic="AI Agents & Tool Calling"))
    assert pool and pool[0].company_specific and pool[0].topic == "AI Agents & Tool Calling"


def test_fts_idempotency_under_50ms(full_db):
    retriever = Retriever(full_db)
    pool = retriever.build_pool(Filters(profile="Backend"), size=5000)
    start = time.perf_counter()
    hits = retriever.search("idempotency", pool)
    assert time.perf_counter() - start < 0.05
    assert hits and "idempot" in hits[0].text.lower()
