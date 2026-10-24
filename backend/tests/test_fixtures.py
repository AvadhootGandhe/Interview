async def test_fake_llm_returns_queued_replies(fake_llm):
    fake_llm.replies = ["a", "b"]
    assert await fake_llm.complete("x") == "a"
    assert await fake_llm.complete("y") == "b"
    assert [c["prompt"] for c in fake_llm.calls] == ["x", "y"]


def test_sample_questions_loaded(sample_questions):
    assert sample_questions
