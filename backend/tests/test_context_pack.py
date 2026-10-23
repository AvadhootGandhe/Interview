"""Phase 2: the context pack the planner and interviewer receive."""
from __future__ import annotations

import copy
import json

import pytest

from app.agents.question_generator import GeneratorUnavailable, InvalidGeneration
from app.config import settings
from app.services.context_pack import LEVEL_EXPECTATIONS, build_context_pack, estimate_tokens
from app.services.retriever import Filters

AMAZON = Filters(profile="Backend", level="SDE-2/3", company="Amazon")


class FakeGenerator:
    """Stands in for QuestionGenerator (llama-server is not available in the cloud)."""

    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.calls: list[dict] = []
        self.fail_on = fail_on or set()

    async def generate(self, profile, level, topic, already_asked=None):
        self.calls.append({"profile": profile, "level": level, "topic": topic, "asked": already_asked})
        if topic in self.fail_on:
            raise InvalidGeneration("bad output")
        return f"How would you design a {topic} system at scale?"


class DownGenerator:
    calls = 0

    async def generate(self, *args, **kwargs):
        DownGenerator.calls += 1
        raise GeneratorUnavailable("llama-server is down")


async def _pack(db, fake_llm, filters=AMAZON, generator=None, **kw):
    fake_llm.replies = ["Amazon digs into distributed systems trade-offs."]
    return await build_context_pack(db, filters, llm=fake_llm, generator=generator, **kw)


async def test_pack_has_profile_level_expectations_and_pool(db, fake_llm):
    pack = await _pack(db, fake_llm, generator=FakeGenerator())
    assert pack.company_profile.company == "Amazon"
    assert pack.company_profile.summary.startswith("Amazon digs")
    assert pack.level_expectations == LEVEL_EXPECTATIONS["SDE-2/3"]
    assert pack.pool

    data = json.loads(pack.to_json())
    assert set(data) >= {"filters", "company_profile", "level_expectations", "pool"}
    assert set(data["pool"][0]) == {"id", "topic", "text", "source", "difficulty"}


async def test_pack_serializes_under_max_context_tokens(db, fake_llm):
    pack = await _pack(db, fake_llm, generator=FakeGenerator())
    assert estimate_tokens(pack.to_json()) <= settings.max_context_tokens


async def test_pool_is_trimmed_to_fit_a_small_budget(db, fake_llm):
    full = await _pack(db, fake_llm)
    small = copy.deepcopy(full)
    small.trim(900)
    assert estimate_tokens(small.to_json()) <= 900
    assert 0 < len(small.pool) < len(full.pool)
    # Trimming keeps the most specific (earliest) items.
    assert [p.id for p in small.pool] == [p.id for p in full.pool[: len(small.pool)]]


async def test_trimming_drops_dataset_items_before_generated_ones(db, fake_llm):
    pack = await _pack(db, fake_llm, generator=FakeGenerator(), max_tokens=900)
    assert estimate_tokens(pack.to_json()) <= 900
    assert sum(p.source == "generated" for p in pack.pool) == settings.generated_per_pack


def test_estimate_tokens_is_chars_over_4():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


async def test_generated_items_come_from_the_generator(db, fake_llm):
    generator = FakeGenerator()
    pack = await _pack(db, fake_llm, generator=generator)
    generated = [p for p in pack.pool if p.source == "generated"]

    assert len(generated) == len(generator.calls) == settings.generated_per_pack
    dataset_topics = {p.topic for p in pack.pool if p.source == "dataset"}
    for call, item in zip(generator.calls, generated):
        assert (call["profile"], call["level"]) == ("Backend", "SDE-2/3")
        assert call["topic"] in dataset_topics and item.topic == call["topic"]
        assert call["asked"]  # dedupes against the dataset questions
        assert item.difficulty == 4
    assert len({p.id for p in pack.pool}) == len(pack.pool)


async def test_topic_filter_means_generated_items_are_on_that_topic(db, fake_llm):
    generator = FakeGenerator()
    await _pack(db, fake_llm, Filters(profile="Backend", level="SDE-1", topic="Kafka"), generator)
    assert {c["topic"] for c in generator.calls} == {"Kafka"}


async def test_generator_down_gives_a_dataset_only_pack(db, fake_llm):
    DownGenerator.calls = 0
    pack = await _pack(db, fake_llm, generator=DownGenerator())
    assert pack.pool and all(p.source == "dataset" for p in pack.pool)
    assert DownGenerator.calls == 1  # stops asking once it knows the server is down
    assert estimate_tokens(pack.to_json()) <= settings.max_context_tokens


async def test_invalid_generations_are_skipped(db, fake_llm):
    class FirstOneInvalid(FakeGenerator):
        async def generate(self, profile, level, topic, already_asked=None):
            if not self.calls:
                self.fail_on.add(topic)
            return await super().generate(profile, level, topic, already_asked)

    generator = FirstOneInvalid()
    pack = await _pack(db, fake_llm, generator=generator)
    generated = [p for p in pack.pool if p.source == "generated"]
    assert len(generator.calls) == settings.generated_per_pack
    assert len(generated) == settings.generated_per_pack - 1
    assert generator.calls[0]["topic"] not in {p.topic for p in generated}


async def test_no_profile_or_level_skips_generation(db, fake_llm):
    generator = FakeGenerator()
    pack = await _pack(db, fake_llm, Filters(company="Amazon"), generator)
    assert generator.calls == [] and pack.pool


@pytest.mark.parametrize("max_tokens", [None, 900])
async def test_company_with_matches_is_at_least_70_percent_company_specific(db, fake_llm, max_tokens):
    kw = {"max_tokens": max_tokens} if max_tokens else {}
    pack = await _pack(db, fake_llm, generator=FakeGenerator(), **kw)
    dataset = [p for p in pack.pool if p.source == "dataset"]
    assert sum(p.company_specific for p in dataset) / len(dataset) >= 0.7


async def test_no_company_gives_a_neutral_profile_and_no_llm_call(db, fake_llm):
    pack = await build_context_pack(db, Filters(profile="Backend", level="Fresher"), llm=fake_llm)
    assert pack.company_profile.is_general
    assert fake_llm.calls == []
    assert pack.level_expectations == LEVEL_EXPECTATIONS["Fresher"]
