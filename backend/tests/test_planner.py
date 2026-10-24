"""Phase 3: the planner turns a context pack into a validated, flowing InterviewPlan."""
from __future__ import annotations

import json

import pytest

from app.agents.planner import PlanError, Planner, fallback_plan, validate_plan
from app.agents.schemas import InterviewPlan
from app.config import settings
from app.services.retriever import Filters, Retriever
from tests.conftest import FakeLLM
from tests.factories import item, pack_of, standard_pool


def reply(segments: list[tuple[str, str, int, str]]) -> str:
    """segments: (seed id, topic, difficulty, link)."""
    return json.dumps({"segments": [
        {"theme": f"{t} theme", "topic": t, "difficulty": d, "seed_question_id": i, "link_from_previous": l}
        for i, t, d, l in segments
    ]})


GOOD = [("c1", "Caching", 2, ""), ("c2", "Caching", 3, "builds on caching basics"),
        ("m1", "Messaging", 3, "from caches to queues"), ("r1", "Databases", 4, "storage behind the queue"),
        ("c3", "Caching", 5, "back to caching at scale")]


async def test_valid_plan_parses_into_interview_plan():
    llm = FakeLLM([reply(GOOD)])
    plan = await Planner(llm).run(pack_of(standard_pool()))
    assert isinstance(plan, InterviewPlan)
    assert plan.source == "llm" and plan.attempts == 1
    assert 4 <= len(plan.segments) <= 6
    seg = plan.segments[1]
    assert (seg.theme, seg.topic, seg.difficulty, seg.seed_question_id) == ("Caching theme", "Caching", 3, "c2")
    assert seg.link_from_previous == "builds on caching basics"
    assert len(llm.calls) == 1


async def test_planner_prompt_contains_the_full_context_pack_and_uses_plan_model():
    pack = pack_of(standard_pool())
    llm = FakeLLM([reply(GOOD)])
    await Planner(llm).run(pack)
    call = llm.calls[0]
    assert pack.to_json() in call["prompt"]
    assert call["task"] == "plan" and call["model"] == settings.planner_model


def test_rejects_made_up_ids():
    pool = standard_pool()
    plan = InterviewPlan.model_validate_json(reply(GOOD[:3] + [("zzz", "Databases", 4, "x"), GOOD[4]]))
    errors = validate_plan(plan, pool, pack_of(pool).filters)
    assert any("zzz" in e for e in errors)


def test_rejects_repeated_questions():
    pool = standard_pool()
    plan = InterviewPlan.model_validate_json(reply(GOOD[:3] + [GOOD[1], GOOD[4]]))
    assert any("repeat" in e for e in validate_plan(plan, pool, pack_of(pool).filters))


def test_warmup_must_not_exceed_level_baseline():
    pool = standard_pool()
    bad = [("c1", "Caching", 3, "")] + GOOD[1:]
    errors = validate_plan(InterviewPlan.model_validate_json(reply(bad)), pool, pack_of(pool, level="Fresher").filters)
    assert any("warm-up" in e for e in errors)
    assert not validate_plan(InterviewPlan.model_validate_json(reply(GOOD)), pool, pack_of(pool).filters)


def test_difficulty_never_jumps_by_more_than_two():
    pool = standard_pool()
    bad = [GOOD[0], ("c3", "Caching", 5, "x"), GOOD[2], GOOD[3], GOOD[4]]
    errors = validate_plan(InterviewPlan.model_validate_json(reply(bad)), pool, pack_of(pool).filters)
    assert any("jump" in e for e in errors)


def test_segment_count_must_be_four_to_six_for_a_big_pool():
    pool = standard_pool()
    plan = InterviewPlan.model_validate_json(reply(GOOD[:3]))
    assert any("segments" in e for e in validate_plan(plan, pool, pack_of(pool).filters))


def test_more_than_six_segments_do_not_even_parse():
    seven = [(f"x{i}", "Caching", 2, "") for i in range(7)]
    with pytest.raises(Exception):
        InterviewPlan.model_validate_json(reply(seven))


def test_topic_given_needs_sixty_percent_of_segments_on_it():
    pool = standard_pool()
    pack = pack_of(pool, topic="Caching")
    mixed = [("c1", "Caching", 2, ""), ("m1", "Messaging", 2, ""), ("r1", "Databases", 3, ""),
             ("a2", "API Design", 4, ""), ("c2", "Caching", 3, "")]
    assert any("topic" in e for e in validate_plan(InterviewPlan.model_validate_json(reply(mixed)), pool, pack.filters))
    focused = [("c1", "Caching", 2, ""), ("c2", "Caching", 3, ""), ("c3", "Caching", 5, ""),
               ("m1", "Messaging", 3, ""), ("r1", "Databases", 3, "")]
    # 3 of 5 = 60%, difficulty 3 -> 5 is a jump of 2
    assert not validate_plan(InterviewPlan.model_validate_json(reply(focused)), pool, pack.filters)


async def test_invalid_output_retries_once_then_succeeds():
    bad = reply(GOOD[:3] + [("zzz", "Databases", 4, "x"), GOOD[4]])
    llm = FakeLLM([bad, reply(GOOD)])
    plan = await Planner(llm).run(pack_of(standard_pool()))
    assert plan.source == "llm" and plan.attempts == 2
    assert "zzz" in llm.calls[1]["prompt"]  # the retry tells the model what was wrong


async def test_two_invalid_outputs_fall_back_to_a_valid_plan():
    llm = FakeLLM(["not json", reply([("nope", "Caching", 1, "")])])
    pack = pack_of(standard_pool())
    plan = await Planner(llm).run(pack)
    assert plan.source == "fallback" and len(llm.calls) == 2
    assert not validate_plan(plan, pack.pool, pack.filters)


async def test_llm_error_falls_back_instead_of_failing_the_interview():
    class Boom:
        async def complete(self, prompt, **kw):
            raise RuntimeError("api down")

    pack = pack_of(standard_pool())
    plan = await Planner(Boom()).run(pack)
    assert plan.source == "fallback" and not validate_plan(plan, pack.pool, pack.filters)


@pytest.mark.parametrize("size", [1, 2, 3, 4, 5, 6, 10])
def test_fallback_handles_small_pools(size):
    pool = standard_pool()[:size]
    pack = pack_of(pool)
    plan = fallback_plan(pool, pack.filters)
    expected = size if size < 4 else None
    assert len(plan.segments) == expected if expected else 4 <= len(plan.segments) <= 6
    assert len({s.seed_question_id for s in plan.segments}) == len(plan.segments)
    assert not validate_plan(plan, pool, pack.filters)


def test_empty_pool_cannot_be_planned():
    with pytest.raises(PlanError):
        fallback_plan([], pack_of([]).filters)


def test_fallback_groups_related_topics_and_ramps_difficulty():
    pool = standard_pool()
    plan = fallback_plan(pool, pack_of(pool).filters)
    topics = [s.topic for s in plan.segments]
    changes = sum(1 for a, b in zip(topics, topics[1:]) if a != b)
    assert changes <= len(set(topics)) - 1  # each topic forms one contiguous run
    assert plan.segments[0].difficulty <= settings.level_difficulty["SDE-2/3"]


def test_fallback_with_topic_keeps_sixty_percent_on_it():
    pool = standard_pool()
    pack = pack_of(pool, topic="Caching")
    plan = fallback_plan(pool, pack.filters)
    on_topic = sum(1 for s in plan.segments if s.topic == "Caching")
    assert on_topic >= 3 and not validate_plan(plan, pool, pack.filters)


@pytest.mark.parametrize("filters", [
    Filters("Backend", "SDE-2/3", "Amazon", None),
    Filters("Backend", "Fresher", "Stripe", "Caching"),
    Filters("AI Engineer", "Architect/Principal", "AI21", None),   # tiny company: widened, small pool
    Filters("DevOps", "SDE-1", "Google", None),
    Filters("Data Engineer", "SDE-1/2", None, None),
    Filters("ML Engineer", "Fresher", "AI21", None),
    Filters("AIOps", "Architect/Principal", "NoSuchCo", None),
])
def test_fallback_is_always_valid_on_real_pools(db, filters):
    pool = Retriever(db).build_pool(filters)
    plan = fallback_plan(pool, filters)
    assert not validate_plan(plan, pool, filters)
    assert 1 <= len(plan.segments) <= 6
