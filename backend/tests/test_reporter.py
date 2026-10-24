import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.agents.orchestrator import Orchestrator
from app.agents.reporter import Report, build_report
from app.db.models import Base
from app.services.retriever import Filters
from scripts.ingest import ingest
from tests.test_orchestrator import F, NoGen, ScriptedLLM, ev

ROOT = Path(__file__).resolve().parents[2]
ALIASES = Path(__file__).resolve().parents[1] / "data" / "company_aliases.json"

SUMMARY = json.dumps({"verdict": "Solid fundamentals, light on failure modes.",
                      "strengths": ["Clear structure"], "gaps": ["Failure modes"]})


class ReportLLM(ScriptedLLM):
    def __init__(self, evals, report=SUMMARY):
        super().__init__(evals)
        self.report = report

    async def complete(self, prompt, **kw):
        if "writing interview feedback" in prompt:
            self.calls.append(prompt)
            if isinstance(self.report, Exception):
                raise self.report
            return self.report
        return await super().complete(prompt, **kw)


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'r.db'}")
    Base.metadata.create_all(eng)
    ingest(ROOT / "data" / "sample_questions.json", eng, ALIASES)
    return eng


async def finished_session(engine, tmp_path, llm):
    orch = Orchestrator(engine, llm, NoGen(), followup_log=tmp_path / "f.jsonl")
    sid = (await orch.start(F, seed=1)).session_id
    for _ in range(12):
        if (await orch.answer(sid, "my answer")).state == "done":
            break
    return sid


async def test_report_has_overall_per_question_strengths_gaps_and_thread(engine, tmp_path):
    llm = ReportLLM([ev(40), ev(80)] + [ev(90)] * 10)
    sid = await finished_session(engine, tmp_path, llm)
    report = await build_report(engine, llm, sid)
    assert isinstance(report, Report)
    assert 0 <= report.overall_score <= 100
    assert 4 <= len(report.questions) <= 6
    assert report.verdict.startswith("Solid") and report.strengths == ["Clear structure"]
    assert report.gaps == ["Failure modes"]
    first = report.questions[0]
    assert first.followups == 1 and first.score == 80 - 5
    assert [t.role for t in first.thread][:2] == ["interviewer", "candidate"]
    assert any(t.kind == "follow_up" for t in first.thread)


async def test_overall_is_mean_of_question_scores(engine, tmp_path):
    llm = ReportLLM([ev(90)] * 10)
    report = await build_report(engine, llm, await finished_session(engine, tmp_path, llm))
    assert report.overall_score == round(sum(q.score for q in report.questions) / len(report.questions))


async def test_llm_failure_falls_back_to_evaluation_points(engine, tmp_path):
    llm = ReportLLM([ev(90)] * 10, report=RuntimeError("down"))
    report = await build_report(engine, llm, await finished_session(engine, tmp_path, llm))
    assert report.strengths and report.gaps and report.verdict


async def test_unfinished_session_still_reports_answered_questions(engine, tmp_path):
    llm = ReportLLM([ev(85)])
    orch = Orchestrator(engine, llm, NoGen(), followup_log=tmp_path / "f.jsonl")
    sid = (await orch.start(F, seed=1)).session_id
    await orch.answer(sid, "one answer")
    await orch.end(sid)
    report = await build_report(engine, llm, sid)
    assert len(report.questions) == 1 and report.overall_score == 85
