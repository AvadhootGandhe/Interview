import pytest

from app.agents.interviewer import Interviewer, clean_speech
from app.agents.planner import Segment

SEG = Segment(theme="Caching", topic="Caching", difficulty=3, seed_question_id=1,
              link_from_previous="candidate mentioned Redis")
EXAMPLES = ["How does cache invalidation work?", "What is a cache stampede?", "Explain LRU vs LFU."]
SEED = "How would you design a read-through cache for a product catalog?"
COMPANY = "They favour scenario questions about scale."


def make(fake_llm, reply="Sure. Here is the question?"):
    fake_llm.replies = [reply]
    return Interviewer(fake_llm)


async def test_greeting_mentions_context(fake_llm):
    out = await make(fake_llm).greeting("Backend", "SDE-2/3", "Amazon")
    p = fake_llm.calls[0]["prompt"].lower()
    assert "greeting" in p and "amazon" in p and "backend" in p and out


async def test_ask_prompt_has_all_context(fake_llm):
    iv = make(fake_llm)
    await iv.ask(SEG, SEED, EXAMPLES, COMPANY, last_answer_summary="Used Redis with a TTL.")
    p = fake_llm.calls[0]["prompt"]
    assert SEG.theme in p and SEED in p and COMPANY in p
    assert all(e in p for e in EXAMPLES)
    assert "candidate mentioned Redis" in p and "Used Redis with a TTL." in p


async def test_ask_without_bridge_or_summary_omits_them(fake_llm):
    seg = SEG.model_copy(update={"link_from_previous": ""})
    iv = make(fake_llm)
    await iv.ask(seg, SEED, [], "", last_answer_summary="")
    p = fake_llm.calls[0]["prompt"]
    assert "Bridge:" not in p and "Last answer:" not in p


async def test_follow_up_prompt_has_focus_and_missing_points(fake_llm):
    iv = make(fake_llm)
    await iv.follow_up(SEED, "I'd just use Redis.", "How would you pick an eviction policy?",
                       ["eviction policy", "invalidation"])
    p = fake_llm.calls[0]["prompt"]
    assert "How would you pick an eviction policy?" in p
    assert "eviction policy" in p and "invalidation" in p and "I'd just use Redis." in p


async def test_closing_prompt(fake_llm):
    await make(fake_llm).closing("Backend")
    assert "closing" in fake_llm.calls[0]["prompt"].lower()


async def test_ask_keeps_seed_intent_via_judge(fake_llm):
    """A judge call checks the rephrase still asks the seed question; a mismatch falls back to the seed."""
    fake_llm.replies = ["Tell me about your favourite pizza?", "NO"]
    out = await Interviewer(fake_llm, check_intent=True).ask(SEG, SEED, [], "", "")
    assert out == SEED
    fake_llm.calls.clear()
    fake_llm.replies = ["How would you build a read-through cache for a catalog?", "YES"]
    out = await Interviewer(fake_llm, check_intent=True).ask(SEG, SEED, [], "", "")
    assert "read-through" in out and len(fake_llm.calls) == 2


@pytest.mark.parametrize("raw,expected", [
    ("**Great.** Let's go:\n- First point?\n- Second", "Great. Let's go: First point? Second"),
    ("`code` and # heading", "code and heading"),
    ("  plain text  ", "plain text"),
])
def test_clean_speech_strips_markdown(raw, expected):
    assert clean_speech(raw) == expected


def test_clean_speech_caps_length_at_sentence_boundary():
    text = " ".join(f"Sentence number {i} is here." for i in range(40))
    out = clean_speech(text)
    assert len(out.split()) <= 60 and out.endswith(".")
