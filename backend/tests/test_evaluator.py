"""Phase 3: the evaluator scores an answer (structured JSON) against a level-specific rubric."""
from __future__ import annotations

import json

import pytest

from app.agents.base import Msg
from app.agents.evaluator import RUBRICS, EvalInput, EvaluationError, Evaluator
from app.agents.schemas import Evaluation
from app.config import settings
from tests.conftest import FakeLLM
from tests.factories import eval_json


def inp(level="SDE-2/3", thread=None):
    thread = thread or [Msg("interviewer", "How does an LRU cache evict?"),
                        Msg("candidate", "It drops the least recently used entry, tracked with a linked list.")]
    return EvalInput(question="How does an LRU cache evict?", thread=thread, profile="Backend",
                     level=level, topic="Caching")


async def test_parses_valid_structured_output():
    llm = FakeLLM([eval_json(82, missing=[], terms=["linked list"])])
    ev = await Evaluator(llm).run(inp())
    assert isinstance(ev, Evaluation)
    assert ev.satisfaction == 82 and ev.scores.depth == 82
    assert ev.mentioned_terms == ["linked list"] and ev.covered_points == ["core idea"]


async def test_accepts_json_wrapped_in_a_code_fence():
    llm = FakeLLM(["```json\n" + eval_json(60) + "\n```"])
    assert (await Evaluator(llm).run(inp())).satisfaction == 60


async def test_retries_once_on_invalid_output_then_succeeds():
    llm = FakeLLM(["I think the answer is good.", eval_json(75)])
    ev = await Evaluator(llm).run(inp())
    assert ev.satisfaction == 75 and len(llm.calls) == 2


async def test_out_of_range_score_counts_as_invalid():
    bad = json.loads(eval_json(50))
    bad["satisfaction"] = 140
    llm = FakeLLM([json.dumps(bad), eval_json(50)])
    assert (await Evaluator(llm).run(inp())).satisfaction == 50 and len(llm.calls) == 2


async def test_raises_after_two_invalid_outputs():
    llm = FakeLLM(["nope", "{}"])
    with pytest.raises(EvaluationError):
        await Evaluator(llm).run(inp())
    assert len(llm.calls) == 2


async def test_rubric_changes_with_level():
    assert RUBRICS["Fresher"] != RUBRICS["Architect/Principal"]
    for level in ("Fresher", "Architect/Principal"):
        llm = FakeLLM([eval_json(70)])
        await Evaluator(llm).run(inp(level=level))
        assert RUBRICS[level] in llm.calls[0]["prompt"]
    fresher, architect = FakeLLM([eval_json(70)]), FakeLLM([eval_json(70)])
    await Evaluator(fresher).run(inp("Fresher"))
    await Evaluator(architect).run(inp("Architect/Principal"))
    assert fresher.calls[0]["prompt"] != architect.calls[0]["prompt"]


async def test_whole_question_thread_is_sent():
    thread = [Msg("interviewer", "Explain LRU eviction."), Msg("candidate", "FIRST-ANSWER-TEXT"),
              Msg("interviewer", "What about thread safety?"), Msg("candidate", "SECOND-ANSWER-TEXT")]
    llm = FakeLLM([eval_json(70)])
    await Evaluator(llm).run(inp(thread=thread))
    prompt = llm.calls[0]["prompt"]
    for m in thread:
        assert m.text in prompt
    assert prompt.index("FIRST-ANSWER-TEXT") < prompt.index("What about thread safety?") < prompt.index("SECOND-ANSWER-TEXT")


async def test_call_uses_the_evaluator_model_and_a_schema():
    llm = FakeLLM([eval_json(70)])
    await Evaluator(llm).run(inp())
    call = llm.calls[0]
    assert call["task"] == "evaluate" and call["model"] == settings.evaluator_model
    assert call["schema"] is Evaluation
