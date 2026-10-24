from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.db.models import Base
from app.services.company_profile import get_company_profile
from scripts.ingest import ingest
from tests.conftest import FakeLLM

ROOT = Path(__file__).resolve().parents[2]
ALIASES = Path(__file__).resolve().parents[1] / "data" / "company_aliases.json"


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    ingest(ROOT / "data" / "sample_questions.json", eng, ALIASES)
    return eng


def hand_counts(sample, company, profile, level):
    """Distinct questions per topic for one company/profile/level, straight from the raw JSON."""
    c = Counter()
    for topic, body in sample[company][profile][level].items():
        c[topic] = len({q["slug"] for q in body["questions"]})
    return c


async def test_topic_mix_matches_hand_computed_and_sums_to_100(engine, sample_questions):
    prof = await get_company_profile(engine, FakeLLM(["Focus text."]), "Amazon", "Backend", "SDE-2/3")
    counts = hand_counts(sample_questions, "Amazon", "Backend", "SDE-2/3")
    total = sum(counts.values())
    assert set(prof.topic_mix) == set(counts)
    assert sum(prof.topic_mix.values()) == 100
    for topic, pct in prof.topic_mix.items():
        assert abs(pct - 100 * counts[topic] / total) <= 1


async def test_summary_generated_once_then_cached(engine):
    llm = FakeLLM(["They probe scale and failure modes."])
    first = await get_company_profile(engine, llm, "Amazon", "Backend", "SDE-2/3")
    second = await get_company_profile(engine, llm, "Amazon", "Backend", "SDE-2/3")
    assert first.summary == second.summary == "They probe scale and failure modes."
    assert len(llm.calls) == 1
    with engine.connect() as c:
        assert c.execute(text("select count(*) from company_profiles")).scalar() == 1


async def test_prompt_contains_sample_questions(engine):
    llm = FakeLLM(["x"])
    await get_company_profile(engine, llm, "Amazon", "Backend", "SDE-2/3")
    assert "Amazon" in llm.calls[0]["prompt"] and "?" in llm.calls[0]["prompt"]


@pytest.mark.parametrize("company", [None, "General", "No Such Co"])
async def test_general_or_unknown_company_is_neutral_without_llm(engine, company):
    llm = FakeLLM(["should not be used"])
    prof = await get_company_profile(engine, llm, company, "Backend", "SDE-2/3")
    assert prof.summary == "" and prof.topic_mix == {}
    assert llm.calls == []


async def test_llm_failure_degrades_to_mix_only_and_is_not_cached(engine):
    class Boom(FakeLLM):
        async def complete(self, prompt, **kw):
            raise RuntimeError("api down")

    prof = await get_company_profile(engine, Boom(), "Amazon", "Backend", "SDE-2/3")
    assert prof.summary == "" and prof.topic_mix
    llm = FakeLLM(["Recovered."])
    assert (await get_company_profile(engine, llm, "Amazon", "Backend", "SDE-2/3")).summary == "Recovered."
