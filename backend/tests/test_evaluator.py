"""Phase 3: the evaluator scores an answer (structured output) and asks for exactly what was missing."""
from __future__ import annotations

import json

import pytest
from helpers import eval_json

from app.agents.base import AgentOutputError
from app.agents.evaluator import EvalContext, Evaluation, Evaluator, ThreadTurn, rubric_for


def ctx(level="SDE-1", thread=None) -> EvalContext:
    return EvalContext(
        question="How does a database index speed up reads?",
        thread=thread or [ThreadTurn("candidate", "It keeps a sorted structure so lookups avoid full scans.")],
        level=level, profile="Backend", topic="Databases",
    )


async def test_parses_valid_structured_output(fake_llm):
    fake_llm.replies = [eval_json(
        62, covered_points=["sorted structure"], missing_points=["write cost"],
        follow_up_focus="the write overhead of indexes", mentioned_terms=["B-tree"], red_flags=[],
    )]
    ev = await Evaluator(fake_llm).run(ctx())
    assert isinstance(ev, Evaluation)
    assert ev.satisfaction == 62 and ev.scores.depth == 62
    assert ev.missing_points == ["write cost"] and ev.mentioned_terms == ["B-tree"]
    assert ev.follow_up_focus == "the write overhead of indexes"


async def test_requests_structured_output_for_the_evaluator_task(fake_llm):
    fake_llm.replies = [eval_json(80)]
    await Evaluator(fake_llm).run(ctx())
    call = fake_llm.calls[0]
    assert call["task"] == "evaluator"
    assert set(call["schema"]["properties"]) >= {
        "satisfaction", "scores", "covered_points", "missing_points",
        "follow_up_focus", "mentioned_terms", "red_flags",
    }


async def test_accepts_a_json_code_fence(fake_llm):
    fake_llm.replies = ["```json\n" + eval_json(75) + "\n```"]
    assert (await Evaluator(fake_llm).run(ctx())).satisfaction == 75


async def test_retries_once_on_invalid_output(fake_llm):
    fake_llm.replies = ["I think it was good!", eval_json(88)]
    ev = await Evaluator(fake_llm).run(ctx())
    assert ev.satisfaction == 88 and len(fake_llm.calls) == 2
    assert "invalid" in fake_llm.calls[1]["prompt"].lower()


async def test_out_of_range_score_counts_as_invalid(fake_llm):
    fake_llm.replies = [eval_json(140), eval_json(90)]
    assert (await Evaluator(fake_llm).run(ctx())).satisfaction == 90


async def test_raises_after_the_retry_fails(fake_llm):
    fake_llm.replies = ["nope", json.dumps({"satisfaction": "high"})]
    with pytest.raises(AgentOutputError):
        await Evaluator(fake_llm).run(ctx())
    assert len(fake_llm.calls) == 2


def test_rubric_changes_by_level():
    fresher, architect = rubric_for("Fresher"), rubric_for("Architect/Principal")
    assert fresher != architect
    assert "fundamentals" in fresher.lower() and "trade-off" in architect.lower()
    assert rubric_for(None) and rubric_for("Unknown level")  # always something sensible


async def test_prompt_uses_the_level_rubric(fake_llm):
    fake_llm.replies = [eval_json(70), eval_json(70)]
    ev = Evaluator(fake_llm)
    await ev.run(ctx("Fresher"))
    await ev.run(ctx("Architect/Principal"))
    assert rubric_for("Fresher") in fake_llm.calls[0]["prompt"]
    assert rubric_for("Architect/Principal") in fake_llm.calls[1]["prompt"]
    assert rubric_for("Architect/Principal") not in fake_llm.calls[0]["prompt"]


async def test_whole_question_thread_is_sent(fake_llm):
    thread = [
        ThreadTurn("candidate", "FIRST-ANSWER: an index is a sorted structure."),
        ThreadTurn("interviewer", "FOLLOWUP-Q: what does an index cost on writes?"),
        ThreadTurn("candidate", "SECOND-ANSWER: every insert must update the tree."),
    ]
    fake_llm.replies = [eval_json(78)]
    await Evaluator(fake_llm).run(ctx(thread=thread))
    prompt = fake_llm.calls[0]["prompt"]
    assert "How does a database index speed up reads?" in prompt
    for marker in ("FIRST-ANSWER", "FOLLOWUP-Q", "SECOND-ANSWER"):
        assert marker in prompt
    assert prompt.index("FIRST-ANSWER") < prompt.index("FOLLOWUP-Q") < prompt.index("SECOND-ANSWER")


async def test_prompt_asks_for_follow_up_focus_and_mentioned_terms(fake_llm):
    fake_llm.replies = [eval_json(70)]
    await Evaluator(fake_llm).run(ctx())
    prompt = fake_llm.calls[0]["prompt"]
    assert "follow_up_focus" in prompt and "mentioned_terms" in prompt
