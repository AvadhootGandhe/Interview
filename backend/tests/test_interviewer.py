"""Phase 3: the interviewer speaks in five modes; output is clean, short, speakable text."""
from __future__ import annotations

import pytest

from app.agents.interviewer import Interviewer, InterviewerInput, build_prompt, clean_speech, same_intent
from app.config import settings
from tests.conftest import FakeLLM
from tests.factories import item, segment

SEED = item("c2", "Caching", 3, "How does LRU eviction work in a cache?")
SEG = segment(SEED)


def inp(mode="ask", **kw):
    base = dict(mode=mode, profile="Backend", level="SDE-2/3", company="Amazon",
                company_summary="Amazon probes scale and failure modes with scenario questions.",
                segment=SEG, seed_text=SEED.text,
                similar=["What is a cache stampede?", "Compare write-through and write-back caches.",
                         "How do you size a cache?"],
                bridge=None, last_answer_summary="Covered: basic caching. Missed: eviction.")
    base.update(kw)
    return InterviewerInput(**base)


def test_each_mode_builds_its_own_prompt():
    prompts = {m: build_prompt(inp(m, follow_up_focus="thread safety", missing_points=["locking"]))
               for m in ("greeting", "ask", "follow_up", "transition", "closing")}
    assert len(set(prompts.values())) == 5
    for mode, prompt in prompts.items():
        assert f"Mode: {mode}" in prompt


def test_greeting_mentions_company_and_level():
    p = build_prompt(inp("greeting", segment=None, seed_text=""))
    assert "Amazon" in p and "SDE-2/3" in p and "Backend" in p


def test_ask_prompt_has_theme_seed_style_examples_company_and_last_answer():
    p = build_prompt(inp("ask", bridge="candidate mentioned Redis"))
    assert SEG.theme in p and SEED.text in p
    assert "What is a cache stampede?" in p and "How do you size a cache?" in p
    assert "Amazon probes scale" in p
    assert "candidate mentioned Redis" in p
    assert "Covered: basic caching" in p


def test_ask_prompt_has_no_bridge_section_without_a_bridge():
    assert "Bridge" not in build_prompt(inp("ask", bridge=None))


def test_only_three_style_examples_are_used():
    p = build_prompt(inp("ask", similar=[f"Style example {i}" for i in range(5)]))
    assert "Style example 2" in p and "Style example 3" not in p


def test_follow_up_prompt_has_focus_and_missing_points():
    p = build_prompt(inp("follow_up", follow_up_focus="thread safety", missing_points=["locking", "TTL"]))
    assert "thread safety" in p and "locking" in p and "TTL" in p


def test_transition_and_closing_prompts():
    assert "move on" in build_prompt(inp("transition")).lower() and SEED.text in build_prompt(inp("transition"))
    assert "close" in build_prompt(inp("closing", segment=None, seed_text="")).lower()


def test_clean_speech_strips_markdown_and_lists():
    raw = "**Great.** Let's talk caching:\n\n1. First, `LRU`\n- then eviction\n# Heading\nHow does it work?"
    out = clean_speech(raw)
    assert not any(c in out for c in "*`#") and "\n" not in out
    assert out.startswith("Great. Let's talk caching") and out.endswith("How does it work?")


def test_clean_speech_caps_length_at_a_sentence_boundary():
    raw = " ".join(f"Sentence number {i} is here." for i in range(30))
    out = clean_speech(raw)
    assert len(out.split()) <= 60 and out.endswith(".")


def test_clean_speech_hard_cuts_one_endless_sentence():
    assert len(clean_speech("word " * 200).split()) == 60


def test_same_intent_rule():
    assert same_intent(SEED.text, "Nice. So how does LRU eviction actually work in a cache?")
    assert not same_intent(SEED.text, "Tell me about your favourite programming language.")


async def test_ask_returns_the_cleaned_model_output_and_uses_interviewer_model():
    llm = FakeLLM(["**Alright.** Next up: how does LRU eviction work in a cache?"])
    out = await Interviewer(llm).run(inp("ask"))
    assert out == "Alright. Next up: how does LRU eviction work in a cache?"
    call = llm.calls[0]
    assert call["task"] == "interview" and call["model"] == settings.interviewer_model


async def test_drifting_question_falls_back_to_the_seed_via_the_judge():
    judged = []

    def judge(seed, spoken):
        judged.append((seed, spoken))
        return False

    llm = FakeLLM(["Tell me about your favourite programming language."])
    out = await Interviewer(llm, intent_check=judge).run(inp("ask"))
    assert judged and SEED.text in out  # the original question is asked verbatim


async def test_faithful_question_is_kept_when_the_judge_agrees():
    llm = FakeLLM(["Let's go deeper: how does LRU eviction work in a cache?"])
    out = await Interviewer(llm, intent_check=lambda s, o: True).run(inp("ask"))
    assert out.startswith("Let's go deeper")


async def test_follow_up_is_not_intent_checked_against_the_seed():
    llm = FakeLLM(["And how would you keep that thread safe?"])
    out = await Interviewer(llm, intent_check=lambda s, o: False).run(inp("follow_up", follow_up_focus="thread safety"))
    assert out == "And how would you keep that thread safe?"
