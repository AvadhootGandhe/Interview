"""Phase 3: the planner turns the context pack into 4-6 ordered, validated segments."""
from __future__ import annotations

import pytest
from helpers import make_pool, plan_json, seg
from pydantic import ValidationError

from app.agents.planner import InterviewPlan, PlanInvalid, Planner, Segment, fallback_plan, validate_plan
from app.services.context_pack import build_context_pack
from app.services.retriever import Filters

FILTERS = Filters(profile="Backend", level="SDE-2/3", company="Amazon")
L = Filters(level="SDE-2/3")

GOOD = [seg("q1", "Caching", 1, ""), seg("q2", "Caching", 2), seg("q6", "Databases", 3),
        seg("q7", "Databases", 4), seg("q9", "Messaging", 3)]


def make(segs) -> InterviewPlan:
    return InterviewPlan.model_validate({"segments": segs})


def test_valid_plan_parses_into_model(pool):
    plan = InterviewPlan.model_validate_json(plan_json(*GOOD))
    s = plan.segments[0]
    assert (s.theme, s.topic, s.difficulty, s.seed_question_id) == ("Caching", "Caching", 1, "q1")
    assert validate_plan(plan, pool, L) == []


def test_segment_difficulty_must_be_1_to_5():
    with pytest.raises(ValidationError):
        Segment(theme="t", topic="t", difficulty=6, seed_question_id="q1", link_from_previous="")


def test_rejects_made_up_ids(pool):
    bad = [dict(s) for s in GOOD]
    bad[2]["seed_question_id"] = "q999"
    assert any("q999" in e for e in validate_plan(make(bad), pool, L))


def test_rejects_repeated_questions(pool):
    bad = [dict(s) for s in GOOD]
    bad[1]["seed_question_id"] = "q1"
    assert any("repeat" in e for e in validate_plan(make(bad), pool, L))


def test_segment_count_bounds(pool):
    few = make(GOOD[:3])
    many = make(GOOD + [seg("q10", "Messaging", 5), seg("q11", "APIs", 3)])
    for p in (few, many):
        assert any("segments" in e for e in validate_plan(p, pool, L))


def test_first_segment_is_a_warm_up(pool):
    bad = [dict(s) for s in GOOD]
    bad[0]["difficulty"] = 3  # SDE-1 baseline is 2; SDE-2/3 baseline is 4
    plan = make(bad)
    assert validate_plan(plan, pool, L) == []
    assert any("warm-up" in e for e in validate_plan(plan, pool, Filters(level="SDE-1")))


def test_difficulty_never_jumps_by_more_than_two(pool):
    bad = [dict(s) for s in GOOD]
    bad[1]["difficulty"] = 4  # 1 -> 4
    assert any("jump" in e for e in validate_plan(make(bad), pool, L))


def test_topic_given_needs_60_percent_on_topic(pool):
    filters = Filters(level="SDE-2/3", topic="Caching")
    assert any("topic" in e for e in validate_plan(make(GOOD), pool, filters))  # 2 of 5
    on_topic = [seg("q1", "Caching", 1, ""), seg("q2", "Caching", 2), seg("q3", "Caching", 4),
                seg("q6", "Databases", 3), seg("q7", "Databases", 4)]
    assert validate_plan(make(on_topic), pool, filters) == []


def test_fallback_plan_always_validates():
    specs = [
        [("A", 5)] + [("B", 5)] * 3,
        [("A", 5)] * 5,
        [("A", 1), ("A", 5), ("B", 2), ("B", 5), ("C", 3), ("C", 3), ("C", 3)],
        [("T", d % 5 + 1) for d in range(22)],
        [("A", d % 5 + 1) for d in range(6)] + [("B", 5)] * 30,
    ]
    for spec in specs:
        pool = make_pool(spec)
        for level in ("Fresher", "SDE-1", "SDE-2/3", "Architect/Principal", None):
            for topic in (None, "A", "T"):
                f = Filters(level=level, topic=topic)
                plan = fallback_plan(pool, f)
                assert validate_plan(plan, pool, f) == [], (spec, level, topic)
                assert 4 <= len(plan.segments) <= 6


def test_small_pool_gets_fewer_segments_only_if_pool_is_tiny():
    f = Filters(level="SDE-1")
    assert len(fallback_plan(make_pool([("A", 1), ("B", 2)]), f).segments) == 2
    assert len(fallback_plan(make_pool([("A", d) for d in (1, 2, 3, 4)]), f).segments) == 4
    assert 4 <= len(fallback_plan(make_pool([("A", d % 5 + 1) for d in range(22)]), f).segments) <= 6


def test_fallback_groups_topics_and_starts_easy(pool):
    plan = fallback_plan(pool, L)
    topics = [s.topic for s in plan.segments]
    closed = set()
    for prev, cur in zip(topics, topics[1:]):
        if cur != prev:
            closed.add(prev)
        assert cur not in closed  # grouped, never shuffled
    assert plan.segments[0].difficulty <= 4


async def test_planner_uses_valid_llm_plan_without_retry(pool, fake_llm):
    fake_llm.replies = [plan_json(*GOOD)]
    planner = Planner(fake_llm)
    plan = await planner.plan_for(pool, L)
    assert [s.seed_question_id for s in plan.segments] == ["q1", "q2", "q6", "q7", "q9"]
    assert len(fake_llm.calls) == 1 and not planner.used_fallback


async def test_planner_retries_once_then_accepts(pool, fake_llm):
    fake_llm.replies = ["not json at all", plan_json(*GOOD)]
    planner = Planner(fake_llm)
    plan = await planner.plan_for(pool, L)
    assert len(fake_llm.calls) == 2 and not planner.used_fallback
    assert "invalid" in fake_llm.calls[1]["prompt"].lower()
    assert len(plan.segments) == 5


async def test_planner_falls_back_after_two_invalid_outputs(pool, fake_llm):
    bad = [dict(s) for s in GOOD]
    bad[0]["seed_question_id"] = "q404"
    fake_llm.replies = [plan_json(*bad), plan_json(*bad)]
    planner = Planner(fake_llm)
    plan = await planner.plan_for(pool, L)
    assert len(fake_llm.calls) == 2 and planner.used_fallback
    assert validate_plan(plan, pool, L) == []


async def test_planner_falls_back_when_llm_errors(pool):
    class Boom:
        async def complete(self, prompt, **kw):
            raise RuntimeError("api down")

    planner = Planner(Boom())
    plan = await planner.plan_for(pool, Filters(level="SDE-1"))
    assert planner.used_fallback and validate_plan(plan, pool, Filters(level="SDE-1")) == []


async def test_planner_prompt_contains_full_context_pack(db, fake_llm):
    fake_llm.replies = ["Amazon asks about scale."]
    pack = await build_context_pack(db, FILTERS, llm=fake_llm)
    fake_llm.calls.clear()
    fake_llm.replies = ["garbage", "garbage"]
    plan = await Planner(fake_llm).run(pack)
    prompt = fake_llm.calls[0]["prompt"]
    assert pack.to_json() in prompt
    assert pack.level_expectations in prompt
    assert validate_plan(plan, pack.pool, FILTERS) == []


async def test_planner_passes_a_json_schema(pool, fake_llm):
    fake_llm.replies = [plan_json(*GOOD)]
    await Planner(fake_llm).plan_for(pool, L)
    assert fake_llm.calls[0]["task"] == "planner"
    assert "segments" in fake_llm.calls[0]["schema"]["properties"]


async def test_empty_pool_raises(fake_llm):
    with pytest.raises(PlanInvalid):
        await Planner(fake_llm).plan_for([], Filters())
