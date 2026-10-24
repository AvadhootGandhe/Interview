"""Phase 3: eval data is well formed, run_evals computes its metrics, text_interview runs end to end.

Everything here runs on the offline fake LLM. The real G3/G9 numbers need ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from helpers import ScriptedLLM, eval_json
from sqlalchemy import select

from app.db.models import Level, Profile
from app.llm.fake_llm import DeterministicFakeLLM
from scripts import run_evals, text_interview

EVALS = Path(__file__).resolve().parents[1] / "evals"


def rows(name):
    return [json.loads(line) for line in (EVALS / name).read_text().splitlines() if line.strip()]


def test_answers_eval_set_is_labeled_across_levels():
    data = rows("answers.jsonl")
    assert 28 <= len(data) <= 40
    assert {r["label"] for r in data} == {"strong", "partial", "weak", "off_topic"}
    assert {r["level"] for r in data} == {"Fresher", "SDE-1", "SDE-1/2", "SDE-2/3", "Architect/Principal"}
    assert all({"id", "level", "question", "answer", "label", "satisfaction", "should_follow_up"} <= set(r) for r in data)
    assert len({r["id"] for r in data}) == len(data)
    by = {l: [r["satisfaction"] for r in data if r["label"] == l] for l in {r["label"] for r in data}}
    assert min(by["strong"]) > max(by["partial"]) >= min(by["partial"]) > max(by["weak"]) > max(by["off_topic"])
    assert all(r["should_follow_up"] == (r["label"] != "strong") for r in data)


def test_sessions_eval_set_covers_companies_profiles_and_levels(db):
    data = rows("sessions.jsonl")
    assert len(data) == 10
    profiles = set(db.scalars(select(Profile.name)))
    levels = set(db.scalars(select(Level.name)))
    for s in data:
        assert s["profile"] in profiles and s["level"] in levels and s["script"]
    assert len({s["company"] for s in data}) >= 4 and len({s["level"] for s in data}) >= 4
    assert any(s["topic"] for s in data) and any(step.get("mention") for s in data for step in s["script"])


async def test_answer_metrics_g3_agreement_and_follow_up_accuracy():
    data = [
        {"id": "x1", "level": "SDE-1", "question": "Q?", "answer": "a", "label": "strong", "satisfaction": 90, "should_follow_up": False},
        {"id": "x2", "level": "SDE-1", "question": "Q?", "answer": "b", "label": "weak", "satisfaction": 25, "should_follow_up": True},
        {"id": "x3", "level": "SDE-1", "question": "Q?", "answer": "c", "label": "partial", "satisfaction": 60, "should_follow_up": True},
        {"id": "x4", "level": "SDE-1", "question": "Q?", "answer": "d", "label": "weak", "satisfaction": 25, "should_follow_up": True},
    ]
    llm = ScriptedLLM(evaluator=[eval_json(85), eval_json(80), eval_json(65), eval_json(30)])
    m = await run_evals.eval_answers(llm, data)
    # |85-90|<=10 ok, |80-25| no, |65-60| ok, |30-25| ok
    assert m["n"] == 4 and m["g3_agreement"] == 0.75
    # follow-up expected for x2, x3, x4; actual (satisfaction < 70): x3, x4 (80 is not) -> x1 ok, x2 wrong, x3 ok, x4 ok
    assert m["followup_accuracy"] == 0.75
    assert m["by_label"]["weak"]["n"] == 2


async def test_fake_answer_eval_runs_on_the_real_file():
    m = await run_evals.eval_answers(DeterministicFakeLLM(), rows("answers.jsonl"))
    assert m["n"] == len(rows("answers.jsonl")) and 0 <= m["g3_agreement"] <= 1


async def test_flow_metrics_on_all_scripted_sessions_with_the_fake(db, train_log):
    m = await run_evals.eval_flow(db, DeterministicFakeLLM(), rows("sessions.jsonl"), judge=None)
    assert m["n"] == 10
    assert m["plan_valid_after_fallback"] == 1.0  # the fallback always validates
    assert 0 <= m["plan_first_try"] <= 1
    assert m["abrupt_jumps_avg"] >= 0 and m["coherence_avg"] is None and m["company_relevance_avg"] is None
    assert all(s["questions"] >= 1 for s in m["sessions"])


async def test_flow_judges_are_averaged_when_given(db, train_log):
    judge = ScriptedLLM(judge=[json.dumps({"score": 4, "reason": "ok"}), json.dumps({"score": 5, "reason": "ok"})] * 3)
    data = rows("sessions.jsonl")[:3]
    m = await run_evals.eval_flow(db, DeterministicFakeLLM(), data, judge=judge)
    assert m["coherence_avg"] == 4.0 and m["company_relevance_avg"] == 5.0


def test_checks_report_pass_and_fail():
    ok = run_evals.check_answers({"g3_agreement": 0.85, "followup_accuracy": 0.92})
    bad = run_evals.check_answers({"g3_agreement": 0.5, "followup_accuracy": 0.92})
    assert all(ok.values()) and not bad["g3_agreement >= 0.8"]
    flow = run_evals.check_flow({"plan_first_try": 0.95, "plan_valid_after_fallback": 1.0, "abrupt_jumps_avg": 0.5,
                                 "coherence_avg": 4.2, "company_relevance_avg": 3.0})
    assert not flow["company_relevance_avg >= 4.0"] and flow["abrupt_jumps_avg <= 1"]


def test_text_interview_runs_end_to_end_with_scripted_input(db_url, train_log, capsys):
    answers = iter(["I am not sure.", "A cache stores hot data in memory to avoid slow reads from the database, "
                    "and I would add a TTL and an eviction policy such as LRU to keep it fresh and bounded."] * 20)
    code = text_interview.main(
        ["--profile", "Backend", "--level", "SDE-2/3", "--fake", "--db", db_url],
        input_fn=lambda prompt="": next(answers),
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Interviewer:" in out and "Report" in out and "Overall" in out
