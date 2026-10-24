"""Phase 3: the interviewer speaks in five modes and always returns plain, speakable text."""
from __future__ import annotations

from app.agents.evaluator import ThreadTurn
from app.agents.interviewer import MODES, Interviewer, InterviewerContext, clean_speech

SEED = "How would you design a rate limiter for a public API?"
SUMMARY = "Amazon digs into scale, ownership and trade-offs."


def ctx(mode, **kw) -> InterviewerContext:
    base = dict(
        mode=mode, profile="Backend", level="SDE-2/3", company="Amazon", topic="APIs",
        company_summary=SUMMARY, theme="API protection", seed_question=SEED,
        examples=["EX-ONE: How do you throttle abusive clients?", "EX-TWO: Compare token and leaky bucket.",
                  "EX-THREE: How do you rate limit across regions?", "EX-FOUR: should not appear"],
    )
    base.update(kw)
    return InterviewerContext(**base)


async def run(fake_llm, c, reply="Okay, here is a question for you."):
    fake_llm.replies = [reply]
    text = await Interviewer(fake_llm).run(c)
    return text, fake_llm.calls[-1]["prompt"]


def test_there_are_five_modes():
    assert set(MODES) == {"greeting", "ask", "follow_up", "transition", "closing"}


async def test_greeting_prompt(fake_llm):
    _, prompt = await run(fake_llm, ctx("greeting", seed_question=""))
    assert "greeting" in prompt.lower()
    assert "Backend" in prompt and "SDE-2/3" in prompt and "Amazon" in prompt
    assert SUMMARY in prompt
    assert SEED not in prompt  # the greeting does not ask the first question


async def test_ask_prompt_has_everything_the_plan_promises(fake_llm):
    c = ctx("ask", bridge="candidate mentioned Redis",
            last_answer_summary="They explained caching with Redis but skipped eviction.")
    _, prompt = await run(fake_llm, c)
    assert "API protection" in prompt  # segment theme
    assert SEED in prompt
    for ex in ("EX-ONE", "EX-TWO", "EX-THREE"):
        assert ex in prompt
    assert "EX-FOUR" not in prompt  # exactly 3 style examples
    assert SUMMARY in prompt
    assert "candidate mentioned Redis" in prompt
    assert "skipped eviction" in prompt


async def test_ask_prompt_without_a_bridge_or_summary_has_neither(fake_llm):
    _, prompt = await run(fake_llm, ctx("ask"))
    assert "Bridge note" not in prompt and "last answer" not in prompt.lower()


async def test_ask_prompt_tells_the_model_to_keep_the_intent(fake_llm):
    _, prompt = await run(fake_llm, ctx("ask"))
    assert "same" in prompt.lower() and "intent" in prompt.lower()


async def test_follow_up_prompt_has_focus_missing_points_and_thread(fake_llm):
    c = ctx(
        "follow_up", follow_up_focus="how the limiter behaves across several servers",
        missing_points=["shared state", "clock skew"],
        thread=[ThreadTurn("interviewer", SEED), ThreadTurn("candidate", "I would count requests in memory.")],
    )
    _, prompt = await run(fake_llm, c)
    assert "how the limiter behaves across several servers" in prompt
    assert "shared state" in prompt and "clock skew" in prompt
    assert "I would count requests in memory." in prompt
    assert SEED in prompt


async def test_transition_prompt_is_a_short_acknowledgement(fake_llm):
    _, prompt = await run(fake_llm, ctx("transition", last_answer_summary="Solid answer on indexes."))
    assert "Solid answer on indexes." in prompt
    assert "do not ask a question" in prompt.lower()


async def test_closing_prompt(fake_llm):
    _, prompt = await run(fake_llm, ctx("closing", seed_question="", last_answer_summary="Strong on caching."))
    assert "closing" in prompt.lower() and "Strong on caching." in prompt


async def test_calls_use_the_interviewer_task_and_no_schema(fake_llm):
    await run(fake_llm, ctx("ask"))
    call = fake_llm.calls[-1]
    assert call["task"] == "interviewer" and call.get("schema") is None


async def test_output_is_cleaned_to_plain_speakable_text(fake_llm):
    raw = "**Great.** Let's move on:\n\n1. First, how would you design a rate limiter?\n- keep it simple\n`code`"
    text, _ = await run(fake_llm, ctx("ask"), reply=raw)
    assert "*" not in text and "`" not in text and "\n" not in text and "1." not in text
    assert text.startswith("Great. Let's move on")


def test_output_is_capped_at_about_60_words():
    long = " ".join(f"Sentence number {i} is here." for i in range(40))
    out = clean_speech(long)
    assert len(out.split()) <= 60
    assert out.endswith(".")  # cut at a sentence boundary
    no_stops = " ".join(["word"] * 200)
    assert len(clean_speech(no_stops).split()) <= 60


def test_clean_speech_strips_quotes_and_speaker_labels():
    assert clean_speech('Interviewer: "Tell me about caching."') == "Tell me about caching."
    assert clean_speech("### Heading\nText") == "Heading Text"


async def test_judge_keeps_a_rephrase_that_preserves_the_intent(fake_llm):
    seen = []

    async def judge(seed, spoken):
        seen.append((seed, spoken))
        return True

    fake_llm.replies = ["Nice. Walk me through how you'd throttle clients on a public API."]
    text = await Interviewer(fake_llm, judge=judge).run(ctx("ask"))
    assert text.startswith("Nice.") and seen[0][0] == SEED


async def test_judge_rejection_falls_back_to_the_seed_question(fake_llm):
    async def judge(seed, spoken):
        return False

    fake_llm.replies = ["Sure. Tell me about your favourite database."]
    text = await Interviewer(fake_llm, judge=judge).run(ctx("ask"))
    assert SEED in text and "favourite database" not in text


async def test_judge_only_applies_to_ask(fake_llm):
    async def judge(seed, spoken):
        raise AssertionError("not for greetings")

    fake_llm.replies = ["Hi there, welcome."]
    assert await Interviewer(fake_llm, judge=judge).run(ctx("greeting", seed_question="")) == "Hi there, welcome."
