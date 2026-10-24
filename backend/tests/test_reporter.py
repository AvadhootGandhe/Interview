"""Phase 3: the reporter gives honest end-of-interview feedback."""
from __future__ import annotations

import json

from app.agents.reporter import QuestionResult, Report, Reporter, ReportContext

NARRATIVE = {
    "verdict": "A solid interview with clear strengths in caching.",
    "strengths": ["Explains caching trade-offs clearly"],
    "gaps": ["Needs more depth on consistency"],
    "next_steps": ["Practice CAP theorem examples"],
}


def results() -> list[QuestionResult]:
    return [
        QuestionResult("q1", "Caching", "What is a cache?", final_score=90, followups=0,
                       covered_points=["eviction", "TTL"], missing_points=[]),
        QuestionResult("q2", "Databases", "Explain isolation levels.", final_score=55, followups=2,
                       covered_points=["dirty reads"], missing_points=["phantom reads", "snapshot isolation"]),
        QuestionResult("q3", "APIs", "Design pagination.", final_score=76, followups=1,
                       covered_points=["cursor pagination"], missing_points=["stable ordering"]),
    ]


def ctx(**kw) -> ReportContext:
    return ReportContext(profile="Backend", level="SDE-2/3", company="Amazon", topic=None,
                         questions=kw.pop("questions", results()), **kw)


async def test_report_has_overall_score_per_question_strengths_and_gaps(fake_llm):
    fake_llm.replies = [json.dumps(NARRATIVE)]
    report = await Reporter(fake_llm).run(ctx())
    assert isinstance(report, Report)
    assert report.overall_score == 74  # mean(90, 55, 76) = 73.67
    assert [q.question_id for q in report.questions] == ["q1", "q2", "q3"]
    assert report.questions[1].question == "Explain isolation levels."
    assert report.questions[1].final_score == 55 and report.questions[1].followups == 2
    assert report.strengths == NARRATIVE["strengths"] and report.gaps == NARRATIVE["gaps"]
    assert report.verdict == NARRATIVE["verdict"] and report.next_steps == NARRATIVE["next_steps"]


async def test_prompt_contains_every_question_and_its_points(fake_llm):
    fake_llm.replies = [json.dumps(NARRATIVE)]
    await Reporter(fake_llm).run(ctx())
    call = fake_llm.calls[0]
    assert call["task"] == "reporter"
    for text in ("What is a cache?", "phantom reads", "cursor pagination", "74"):
        assert text in call["prompt"]


async def test_falls_back_to_points_when_the_model_output_is_invalid(fake_llm):
    fake_llm.replies = ["not json", "still not json"]
    report = await Reporter(fake_llm).run(ctx())
    assert len(fake_llm.calls) == 2
    assert report.overall_score == 74
    assert report.strengths and report.gaps and report.verdict
    assert any("phantom reads" in g or "snapshot isolation" in g for g in report.gaps)
    assert any("eviction" in s or "TTL" in s for s in report.strengths)


async def test_an_interview_with_no_answers_reports_zero_without_calling_the_model(fake_llm):
    report = await Reporter(fake_llm).run(ctx(questions=[]))
    assert report.overall_score == 0 and report.questions == [] and fake_llm.calls == []
    assert report.verdict


async def test_scores_are_clamped_to_0_100(fake_llm):
    fake_llm.replies = [json.dumps(NARRATIVE)]
    qs = [QuestionResult("q1", "T", "Q?", final_score=-5, followups=2)]
    assert (await Reporter(fake_llm).run(ctx(questions=qs))).overall_score == 0
