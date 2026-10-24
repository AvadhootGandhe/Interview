from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.agents.question_generator import GeneratorUnavailable
from app.db.models import Base
from app.services.context_pack import build_context_pack, estimate_tokens
from app.services.retriever import Filters
from scripts.ingest import ingest
from tests.conftest import FakeLLM

ROOT = Path(__file__).resolve().parents[2]
ALIASES = Path(__file__).resolve().parents[1] / "data" / "company_aliases.json"


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    ingest(ROOT / "data" / "sample_questions.json", eng, ALIASES)
    return eng


class FakeGenerator:
    def __init__(self):
        self.calls = []

    async def generate(self, profile, level, topic, asked=None):
        self.calls.append((profile, level, topic))
        return f"Generated question about {topic}?"


class DownGenerator:
    async def generate(self, *a, **k):
        raise GeneratorUnavailable("down")


F = Filters(profile="Backend", level="SDE-2/3", company="Amazon")


async def test_pack_has_profile_expectations_and_pool(engine):
    pack = await build_context_pack(engine, FakeLLM(["They love scale."]), FakeGenerator(), F, seed=1)
    assert pack.company_profile.summary == "They love scale."
    assert "scale" in pack.level_expectations.lower()
    assert pack.pool and len({p.id for p in pack.pool}) == len(pack.pool)
    text = pack.to_prompt()
    assert "Amazon" in text and "They love scale." in text and pack.pool[0].text in text


async def test_serialized_pack_fits_token_budget_by_trimming_pool(engine):
    pack = await build_context_pack(engine, FakeLLM(["s"]), FakeGenerator(), F, seed=1, max_tokens=500)
    assert estimate_tokens(pack.to_prompt()) <= 500
    assert 0 < len(pack.pool) < 40


async def test_default_budget_is_respected(engine):
    pack = await build_context_pack(engine, FakeLLM(["s" * 400]), FakeGenerator(), F, seed=1)
    assert estimate_tokens(pack.to_prompt()) <= 3000


async def test_generated_items_added_with_source_and_unique_ids(engine):
    gen = FakeGenerator()
    pack = await build_context_pack(engine, FakeLLM(["s"]), gen, F, seed=1)
    generated = [p for p in pack.pool if p.source == "generated"]
    assert 0 < len(generated) <= 3 and len(gen.calls) == len(generated)
    assert all(p.id < 0 for p in generated)
    assert len({p.id for p in pack.pool}) == len(pack.pool)
    assert all(c[:2] == ("Backend", "SDE-2/3") for c in gen.calls)


async def test_generator_down_gives_dataset_only_valid_pack(engine):
    pack = await build_context_pack(engine, FakeLLM(["s"]), DownGenerator(), F, seed=1)
    assert pack.pool and all(p.source == "dataset" for p in pack.pool)


async def test_company_pack_is_mostly_company_specific(engine):
    pack = await build_context_pack(engine, FakeLLM(["s"]), DownGenerator(), F, seed=1)
    assert sum(p.company_specific for p in pack.pool) / len(pack.pool) >= 0.7


async def test_no_company_gives_neutral_pack(engine):
    llm = FakeLLM(["unused"])
    pack = await build_context_pack(engine, llm, DownGenerator(), Filters(profile="Backend"), seed=1)
    assert pack.company_profile.summary == "" and llm.calls == []
    assert pack.pool
