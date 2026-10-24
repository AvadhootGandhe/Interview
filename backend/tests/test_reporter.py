"""Phase 3: the reporter gives an honest end-of-interview report."""
from __future__ import annotations

import json

from app.agents.base import Msg
from app.agents.reporter import QuestionRecord, ReportInput, Reporter
from app.config import settings
from tests.conftest import FakeLLM
from tests.factories import evaluation


def record(qid, score, follow_ups=0, sat=70):
    return QuestionRecord(
        question_id=qid, topic="Caching", text=f"Question {qid}?", final_score=score, follow_ups=follow_ups,
        thread=[Msg("interviewer", f"Question {qid}?"), Msg("candidate", "An answer.")],
        evaluation=evaluation(sat),
    )


def inp(records=None):
    return ReportInput(profile="Backend", level="SDE-2/3", company="Amazon", topic=None,
                       questions=records if records is not None else [record("a", 90), record("b", 60, 1), record("c", 30, 2)])


LLM_JSON = json.dumps({"verdict": "Solid fundamentals, thin on failure handling.",
                       "strengths": ["Clear caching basics"], "gaps": ["Failure modes", "Capacity planning"]})


async def test_report_has_overall_score_per_question_strengths_and_gaps():
    llm = FakeLLM([LLM_JSON])
    r = await Reporter(llm).run(inp())
    assert r.overall_score == 60  # mean of 90, 60, 30, computed in code, not by the model
    assert [q.question_id for q in r.questions] == ["a", "b", "c"]
    assert [q.final_score for q in r.questions] == [90, 60, 30]
    assert r.questions[2].follow_ups == 2 and r.questions[0].thread[1].text == "An answer."
    assert r.strengths == ["Clear caching basics"] and r.gaps == ["Failure modes", "Capacity planning"]
    assert r.verdict.startswith("Solid fundamentals")
    call = llm.calls[0]
    assert call["task"] == "report" and call["model"] == settings.reporter_model


async def test_prompt_lists_every_question_with_its_final_score():
    llm = FakeLLM([LLM_JSON])
    await Reporter(llm).run(inp())
    prompt = llm.calls[0]["prompt"]
    for qid in "abc":
        assert f"Question {qid}?" in prompt
    assert "90" in prompt and "failure handling" in prompt  # evaluator gaps are passed along


async def test_invalid_model_output_falls_back_to_a_report_built_from_the_evaluations():
    llm = FakeLLM(["oops", "still not json"])
    r = await Reporter(llm).run(inp())
    assert r.overall_score == 60 and len(llm.calls) == 2
    assert r.strengths and r.gaps and r.verdict


async def test_empty_interview_reports_zero_without_calling_the_model():
    llm = FakeLLM([])
    r = await Reporter(llm).run(inp([]))
    assert r.overall_score == 0 and r.questions == [] and llm.calls == []
