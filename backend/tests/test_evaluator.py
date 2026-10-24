import json

import pytest

from app.agents.evaluator import Evaluation, EvaluationError, evaluate

VALID = {
    "satisfaction": 62,
    "scores": {"correctness": 70, "depth": 50, "clarity": 65, "communication": 60},
    "covered_points": ["explains TTL"],
    "missing_points": ["eviction policy"],
    "follow_up_focus": "How would you choose an eviction policy?",
    "mentioned_terms": ["redis"],
    "red_flags": [],
}
THREAD = [("How would you design a cache?", "I would use Redis with a TTL.")]


async def test_valid_output_parses_into_model(fake_llm):
    fake_llm.replies = [json.dumps(VALID)]
    ev = await evaluate(fake_llm, "Backend", "SDE-2/3", THREAD)
    assert isinstance(ev, Evaluation) and ev.satisfaction == 62
    assert ev.scores.depth == 50 and ev.mentioned_terms == ["redis"]
    assert ev.missing_points == ["eviction policy"]


async def test_fenced_json_accepted(fake_llm):
    fake_llm.replies = ["```json\n" + json.dumps(VALID) + "\n```"]
    assert (await evaluate(fake_llm, "Backend", "SDE-2/3", THREAD)).satisfaction == 62


async def test_retries_once_on_invalid_then_succeeds(fake_llm):
    fake_llm.replies = ["garbage", json.dumps(VALID)]
    ev = await evaluate(fake_llm, "Backend", "SDE-2/3", THREAD)
    assert ev.satisfaction == 62 and len(fake_llm.calls) == 2


async def test_raises_after_second_invalid(fake_llm):
    fake_llm.replies = ["garbage", json.dumps({**VALID, "satisfaction": 150})]
    with pytest.raises(EvaluationError):
        await evaluate(fake_llm, "Backend", "SDE-2/3", THREAD)
    assert len(fake_llm.calls) == 2


async def test_rubric_changes_by_level(fake_llm):
    fake_llm.replies = [json.dumps(VALID), json.dumps(VALID)]
    await evaluate(fake_llm, "Backend", "Fresher", THREAD)
    await evaluate(fake_llm, "Backend", "Architect/Principal", THREAD)
    fresher, architect = fake_llm.calls[0]["prompt"], fake_llm.calls[1]["prompt"]
    assert fresher != architect
    assert "fundamentals" in fresher.lower() and "trade-offs" in architect.lower()


async def test_whole_thread_is_sent(fake_llm):
    fake_llm.replies = [json.dumps(VALID)]
    thread = THREAD + [("What about eviction?", "LRU, because recent items are hot.")]
    await evaluate(fake_llm, "Backend", "SDE-2/3", thread)
    prompt = fake_llm.calls[0]["prompt"]
    for part in ("How would you design a cache?", "I would use Redis with a TTL.",
                 "What about eviction?", "LRU, because recent items are hot."):
        assert part in prompt


async def test_empty_answer_still_evaluated_by_prompt(fake_llm):
    fake_llm.replies = [json.dumps({**VALID, "satisfaction": 0})]
    ev = await evaluate(fake_llm, "Backend", "SDE-1", [("Q?", "")])
    assert ev.satisfaction == 0
