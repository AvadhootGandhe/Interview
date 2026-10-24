from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.db.models import Base
from app.llm.fake_llm import FakeInterviewLLM, NoGenerator
from scripts.ingest import ingest
from scripts.run_evals import count_topic_jumps, load_answers, run_flow

ROOT = Path(__file__).resolve().parents[2]
SESSIONS = Path(__file__).resolve().parents[1] / "evals" / "sessions.jsonl"
ALIASES = Path(__file__).resolve().parents[1] / "data" / "company_aliases.json"


def test_count_topic_jumps():
    assert count_topic_jumps([]) == 0
    assert count_topic_jumps(["A", "A", "A"]) == 0
    assert count_topic_jumps(["A", "A", "B", "B", "C"]) == 2


def test_sessions_file_is_well_formed():
    rows = load_answers(SESSIONS)
    assert len(rows) >= 10 and len({r["id"] for r in rows}) == len(rows)
    assert all(r["profile"] and r["level"] and len(r["quality"]) >= 4 for r in rows)
    assert any(r["company"] for r in rows) and any(not r["company"] for r in rows)


class FixedJudge:
    async def complete(self, prompt, **kw):
        return "4"


class Candidate(FakeInterviewLLM):
    async def complete(self, prompt, **kw):
        if "You are role-playing a job candidate" in prompt:
            return "I would shard by tenant, add a write-through cache, and monitor replication lag and failure modes."
        return await super().complete(prompt, **kw)


async def test_run_flow_reports_g9_g10_metrics(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'f.db'}")
    Base.metadata.create_all(eng)
    ingest(ROOT / "data" / "sample_questions.json", eng, ALIASES)
    sessions = load_answers(SESSIONS)[:2]
    result = await run_flow(eng, Candidate(), NoGenerator(), FixedJudge(), sessions)
    assert result["n"] == 2
    assert result["plan_validity"] == 1.0
    assert result["flow_coherence"] == 4.0 and result["company_relevance"] == 4.0
    assert result["avg_topic_jumps"] >= 0
    assert set(result) >= {"passed", "avg_topic_jumps", "g10_company_pool_share"}
