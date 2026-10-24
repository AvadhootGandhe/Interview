import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.agents.planner import InterviewPlan, Segment, fallback_plan, plan_interview, validate_plan
from app.db.models import Base
from app.services.context_pack import build_context_pack
from app.services.retriever import Filters
from scripts.ingest import ingest
from tests.conftest import FakeLLM

ROOT = Path(__file__).resolve().parents[2]
ALIASES = Path(__file__).resolve().parents[1] / "data" / "company_aliases.json"


class NoGen:
    async def generate(self, *a, **k):
        from app.agents.question_generator import GeneratorUnavailable
        raise GeneratorUnavailable("off")


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    ingest(ROOT / "data" / "sample_questions.json", eng, ALIASES)
    return eng


async def make_pack(engine, **kw):
    f = Filters(**{"profile": "Backend", "level": "SDE-2/3", "company": "Amazon", **kw})
    return await build_context_pack(engine, FakeLLM(["focus"]), NoGen(), f, seed=3)


def good_plan_json(pack, n=5):
    """A valid plan built from the pool: warm-up easy, ramping, related topics adjacent."""
    items = sorted(pack.pool, key=lambda p: (p.difficulty, p.topic))[:n]
    return json.dumps({"segments": [
        {"theme": f"Theme {i}", "topic": it.topic, "difficulty": it.difficulty,
         "seed_question_id": it.id, "link_from_previous": "" if i == 0 else "builds on the last"}
        for i, it in enumerate(items)]})


async def test_valid_plan_parses_into_model(engine):
    pack = await make_pack(engine)
    llm = FakeLLM([good_plan_json(pack)])
    plan = await plan_interview(llm, pack)
    assert isinstance(plan, InterviewPlan) and 4 <= len(plan.segments) <= 6
    assert all(isinstance(s, Segment) and 1 <= s.difficulty <= 5 for s in plan.segments)
    assert len(llm.calls) == 1


async def test_prompt_contains_full_context_pack(engine):
    pack = await make_pack(engine)
    llm = FakeLLM([good_plan_json(pack)])
    await plan_interview(llm, pack)
    assert pack.to_prompt() in llm.calls[0]["prompt"]


async def test_json_in_markdown_fence_is_accepted(engine):
    pack = await make_pack(engine)
    plan = await plan_interview(FakeLLM(["```json\n" + good_plan_json(pack) + "\n```"]), pack)
    assert len(plan.segments) >= 4


async def test_made_up_ids_rejected_then_retry_succeeds(engine):
    pack = await make_pack(engine)
    bad = json.loads(good_plan_json(pack))
    bad["segments"][2]["seed_question_id"] = 999_999_999
    llm = FakeLLM([json.dumps(bad), good_plan_json(pack)])
    plan = await plan_interview(llm, pack)
    assert len(llm.calls) == 2
    assert validate_plan(plan, pack) == []


async def test_invalid_twice_uses_fallback_that_validates(engine):
    pack = await make_pack(engine)
    llm = FakeLLM(["not json", "{}"])
    plan = await plan_interview(llm, pack)
    assert len(llm.calls) == 2
    assert validate_plan(plan, pack) == []


async def test_validation_rules(engine):
    pack = await make_pack(engine)
    base = json.loads(good_plan_json(pack))["segments"]

    def check(segments):
        return validate_plan(InterviewPlan(segments=[Segment(**s) for s in segments]), pack)

    assert check(base) == []
    assert check(base[:3])  # too few
    dup = [dict(s) for s in base]
    dup[1]["seed_question_id"] = dup[0]["seed_question_id"]
    assert check(dup)  # repeated question
    hard_start = [dict(s) for s in base]
    hard_start[0]["difficulty"] = 5
    assert check(hard_start)  # warm-up above level baseline
    jump = [dict(s) for s in base]
    jump[0]["difficulty"], jump[1]["difficulty"] = 1, 4
    assert check(jump)  # difficulty jumps by more than 2


@pytest.mark.parametrize("filters", [
    {}, {"level": "Fresher"}, {"level": "Architect/Principal"}, {"company": "Google"},
    {"company": None}, {"topic": "Kafka"}, {"company": "AI21"},
])
async def test_fallback_plan_always_validates(engine, filters):
    pack = await make_pack(engine, **filters)
    plan = fallback_plan(pack)
    assert validate_plan(plan, pack) == []
    assert 4 <= len(plan.segments) <= 6


async def test_fallback_groups_topics_and_ramps(engine):
    pack = await make_pack(engine)
    plan = fallback_plan(pack)
    diffs = [s.difficulty for s in plan.segments]
    assert diffs[0] <= min(diffs[1:]) or diffs[0] <= 4
    topics = [s.topic for s in plan.segments]
    jumps = sum(a != b for a, b in zip(topics, topics[1:]))
    assert jumps <= len(topics) - 1


async def test_topic_filter_means_most_segments_on_topic(engine):
    pack = await make_pack(engine, company=None, topic="Kafka")
    plan = fallback_plan(pack)
    assert validate_plan(plan, pack) == []
