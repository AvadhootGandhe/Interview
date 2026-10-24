"""Phase 3 eval harness: data files are well formed and the metric code is correct (no API key needed)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.base import Msg
from app.config import settings
from app.llm.fake import DemoLLM
from scripts import run_evals

EVALS = Path(__file__).parents[1] / "evals"
LABEL_RANGES = {"strong": (80, 100), "partial": (45, 79), "weak": (10, 44), "off_topic": (0, 15)}


def rows(name):
    return [json.loads(l) for l in (EVALS / name).read_text().splitlines() if l.strip()]


def test_answers_file_is_balanced_and_consistent():
    data = rows("answers.jsonl")
    assert 28 <= len(data) <= 36
    assert {r["label"] for r in data} == set(LABEL_RANGES)
    assert {r["level"] for r in data} == set(settings.level_difficulty)
    assert len({r["id"] for r in data}) == len(data)
    for r in data:
        assert {"id", "profile", "level", "topic", "question", "answer", "label", "score"} <= set(r)
        lo, hi = LABEL_RANGES[r["label"]]
        assert lo <= r["score"] <= hi, r["id"]
        assert r["question"].strip() and r["answer"].strip()


def test_sessions_file_is_well_formed():
    data = rows("sessions.jsonl")
    assert 10 <= len(data) <= 14
    assert len({r["id"] for r in data}) == len(data)
    assert {r["company"] for r in data} >= {"Amazon", "Google", "Stripe", None}
    for r in data:
        assert r["persona"] in {"strong", "mixed", "weak"}
        assert r["profile"] and r["level"] in settings.level_difficulty
        assert isinstance(r.get("mentions", []), list)


def test_g3_counts_answers_within_ten_points():
    results = [{"label_score": 80, "predicted": 88}, {"label_score": 40, "predicted": 51},
               {"label_score": 20, "predicted": 12}, {"label_score": 90, "predicted": 70}]
    g3 = run_evals.g3_summary(results)
    assert g3["within_10"] == 2 and g3["total"] == 4 and g3["rate"] == 0.5 and not g3["passed"]
    assert run_evals.g3_summary([{"label_score": 50, "predicted": 59}])["passed"]


def test_abrupt_jumps_ignore_same_and_related_topics_and_bridges():
    topics = ["Caching", "Caching", "Redis Caching", "Kubernetes", "Message Queues"]
    assert run_evals.abrupt_jumps(topics, bridged=[False] * 5) == 2
    assert run_evals.abrupt_jumps(topics, bridged=[False, False, False, True, False]) == 1
    assert run_evals.abrupt_jumps(["A topic"], []) == 0


def test_flow_summary_applies_the_goal_thresholds():
    good = {"plan_valid": True, "first_try": True, "coherence": 4.5, "company_relevance": 4.2, "abrupt": 1, "bridged": 1}
    bad = {"plan_valid": True, "first_try": False, "coherence": 3.0, "company_relevance": 3.0, "abrupt": 3, "bridged": 0}
    s = run_evals.flow_summary([good, good])
    assert s["passed"] and s["plan_valid_rate"] == 1.0
    assert not run_evals.flow_summary([good, bad])["passed"]


async def test_answer_eval_runs_end_to_end_with_the_demo_llm():
    out = await run_evals.run_answers(DemoLLM(), limit=6)
    assert out["total"] == 6 and 0 <= out["rate"] <= 1


async def test_flow_eval_runs_end_to_end_with_the_demo_llm(db, tmp_path):
    out = await run_evals.run_flow(DemoLLM(), db, limit=3, followup_log=tmp_path / "f.jsonl")
    assert out["sessions"] == 3 and out["plan_valid_rate"] == 1.0
    assert set(out) >= {"coherence", "company_relevance", "abrupt_per_interview", "passed"}
