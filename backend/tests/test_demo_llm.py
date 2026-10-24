"""The offline DemoLLM (FAKE_LLM=1) must drive a complete interview, and company profile uses the cheap model."""
from __future__ import annotations

import json

from app.agents.orchestrator import Orchestrator
from app.agents.schemas import Evaluation
from app.llm.fake import DemoLLM
from app.services.company_profile import CompanyProfileService


async def test_demo_llm_runs_a_full_interview(db, tmp_path):
    o = Orchestrator(db, DemoLLM(), followup_log=tmp_path / "f.jsonl")
    first = await o.start(__import__("app.services.retriever", fromlist=["Filters"]).Filters(
        profile="Backend", level="SDE-1", company="Google"))
    r = first
    for _ in range(40):
        if r.done:
            break
        r = await o.answer(first.session_id, "I would use a cache with an eviction policy and measure hit rate; "
                                             "the trade-off is staleness versus latency, so I add a TTL.")
    assert r.done
    assert (await o.report(first.session_id)).overall_score > 0


async def test_demo_evaluator_scores_longer_answers_higher_and_returns_valid_json():
    llm = DemoLLM()
    short = Evaluation.model_validate_json(await llm.complete("<answer>I don't know</answer>", task="evaluate"))
    long = Evaluation.model_validate_json(await llm.complete(
        "<answer>" + "it depends on the workload and the consistency we need " * 6 + "</answer>", task="evaluate"))
    assert short.satisfaction < 50 < long.satisfaction


async def test_company_profile_summary_uses_the_cheap_model(db):
    seen = {}

    class Spy:
        async def complete(self, prompt, **kw):
            seen.update(kw)
            return "Amazon asks about scale."

    await CompanyProfileService(db, Spy()).get("Amazon", "Backend", "SDE-2/3")
    from app.config import settings
    assert seen["model"] == settings.cheap_model and seen["task"] == "company_profile"
