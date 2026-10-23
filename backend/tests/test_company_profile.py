"""Phase 2: company profile = topic mix (SQL) + cached focus summary (fake LLM)."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.db.models import CompanyProfile as CompanyProfileRow
from app.services.company_profile import NEUTRAL_SUMMARY, CompanyProfileService


@pytest.fixture
def expected_mix(fixtures_dir) -> dict[str, int]:
    return json.loads((fixtures_dir / "amazon_backend_topic_mix.json").read_text())


def test_topic_mix_matches_the_hand_computed_fixture(db, expected_mix):
    mix = CompanyProfileService(db, llm=None).topic_mix("Amazon", profile="Backend")
    assert {m["topic"]: m["count"] for m in mix} == expected_mix
    assert [m["count"] for m in mix] == sorted((m["count"] for m in mix), reverse=True)
    assert round(sum(m["percent"] for m in mix), 6) == 100


@pytest.mark.parametrize("profile, level", [(None, None), ("Backend", "SDE-2/3"), ("AI Engineer", None)])
def test_topic_mix_percentages_add_to_100(db, profile, level):
    mix = CompanyProfileService(db, llm=None).topic_mix("Amazon", profile=profile, level=level)
    assert mix and round(sum(m["percent"] for m in mix), 6) == 100


async def test_summary_is_generated_once_then_served_from_the_cache(db, fake_llm):
    fake_llm.replies = ["  Amazon asks about distributed systems.\nIt likes trade-offs.  "]
    service = CompanyProfileService(db, llm=fake_llm)

    first = await service.get("Amazon", profile="Backend", level="SDE-2/3")
    second = await service.get("Amazon", profile="Backend", level="SDE-2/3")

    assert len(fake_llm.calls) == 1
    assert first.summary == second.summary == "Amazon asks about distributed systems.\nIt likes trade-offs."
    assert first.company == "Amazon" and not first.is_general
    assert first.topic_mix == second.topic_mix and first.topic_mix
    prompt = fake_llm.calls[0]["prompt"]
    assert "Amazon" in prompt and "RabbitMQ" in prompt  # topic mix and sample questions go in
    assert db.scalar(select(func.count()).select_from(CompanyProfileRow)) == 1

    # A fresh service (e.g. after a restart) reads the DB cache too.
    again = await CompanyProfileService(db, llm=type(fake_llm)()).get("Amazon", "Backend", "SDE-2/3")
    assert again.summary == first.summary


async def test_summary_is_cached_per_profile_and_level(db, fake_llm):
    fake_llm.replies = ["one", "two"]
    service = CompanyProfileService(db, llm=fake_llm)
    await service.get("Amazon", profile="Backend", level="SDE-2/3")
    await service.get("Amazon", profile="Backend", level="Fresher")
    assert len(fake_llm.calls) == 2


@pytest.mark.parametrize("company", [None, "", "General", "(none provided)", "Unknown Startup"])
async def test_general_or_no_company_gives_a_neutral_profile_without_an_llm_call(db, fake_llm, company):
    profile = await CompanyProfileService(db, llm=fake_llm).get(company, profile="Backend")
    assert profile.is_general
    assert profile.summary == NEUTRAL_SUMMARY
    assert fake_llm.calls == []


async def test_llm_failure_falls_back_to_a_topic_summary_and_is_not_cached(db):
    class BrokenLLM:
        calls = 0

        async def complete(self, prompt, **kw):
            BrokenLLM.calls += 1
            raise RuntimeError("API down")

    service = CompanyProfileService(db, llm=BrokenLLM())
    profile = await service.get("Amazon", profile="Backend")
    assert "Amazon" in profile.summary and profile.summary != NEUTRAL_SUMMARY
    assert db.scalar(select(func.count()).select_from(CompanyProfileRow)) == 0
