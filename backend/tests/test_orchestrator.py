import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.agents.orchestrator import Orchestrator
from app.agents.question_generator import GeneratorUnavailable
from app.db.models import Base
from app.services.retriever import Filters
from scripts.ingest import ingest

ROOT = Path(__file__).resolve().parents[2]
ALIASES = Path(__file__).resolve().parents[1] / "data" / "company_aliases.json"
F = Filters(profile="Backend", level="SDE-2/3", company="Amazon")


def ev(sat, terms=(), focus="What about failure modes?", missing=("failure modes",)):
    return json.dumps({
        "satisfaction": sat,
        "scores": {"correctness": sat, "depth": sat, "clarity": sat, "communication": sat},
        "covered_points": ["basics"], "missing_points": list(missing), "follow_up_focus": focus,
        "mentioned_terms": list(terms), "red_flags": []})


class ScriptedLLM:
    """Routes by prompt content so each agent gets a deterministic reply."""

    def __init__(self, evals):
        self.evals, self.calls = list(evals), []

    async def complete(self, prompt, **kw):
        self.calls.append(prompt)
        if "planning a spoken" in prompt:
            return "{}"  # force the deterministic fallback plan
        if "scoring a spoken answer" in prompt:
            return self.evals.pop(0)
        if "summarising how" in prompt:
            return "They focus on scale."
        if "Mode: follow_up" in prompt:
            return "Could you say more about failure modes?"
        if "Mode: greeting" in prompt:
            return "Hello, welcome. Ready to begin?"
        if "Mode: closing" in prompt:
            return "Thanks, that was great. Your report is ready."
        return "Let's move on. Here is the next question?"


class NoGen:
    async def generate(self, *a, **k):
        raise GeneratorUnavailable("off")


@pytest.fixture
def engine(tmp_path):
    # File-backed like production: the retriever opens its own connection while a session is mid-transaction.
    eng = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(eng)
    ingest(ROOT / "data" / "sample_questions.json", eng, ALIASES)
    return eng


def make(engine, evals, tmp_path):
    llm = ScriptedLLM(evals)
    return Orchestrator(engine, llm, NoGen(), followup_log=tmp_path / "followups.jsonl"), llm


def scalar(engine, sql, **p):
    with engine.connect() as c:
        return c.execute(text(sql), p).scalar()


async def test_start_retrieves_plans_saves_plan_and_greets(engine, tmp_path):
    orch, llm = make(engine, [], tmp_path)
    started = await orch.start(F, seed=1)
    assert started.messages[0] == "Hello, welcome. Ready to begin?"
    assert len(started.messages) == 2  # greeting + first question
    assert scalar(engine, "select count(*) from plans where session_id=:s", s=started.session_id) == 1
    assert scalar(engine, "select state from sessions where id=:s", s=started.session_id) == "active"
    assert any("planning a spoken" in c for c in llm.calls)


async def test_weak_answer_triggers_follow_up_and_logs_it(engine, tmp_path):
    orch, _ = make(engine, [ev(40)], tmp_path)
    sid = (await orch.start(F, seed=1)).session_id
    reply = await orch.answer(sid, "I don't know, maybe a cache?")
    assert reply.kind == "follow_up" and reply.messages == ["Could you say more about failure modes?"]
    assert scalar(engine, "select current_index from sessions where id=:s", s=sid) == 0
    lines = (tmp_path / "followups.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["answer"] == "I don't know, maybe a cache?"


async def test_strong_answer_moves_to_next_segment(engine, tmp_path):
    orch, _ = make(engine, [ev(85)], tmp_path)
    sid = (await orch.start(F, seed=1)).session_id
    reply = await orch.answer(sid, "A thorough answer.")
    assert reply.kind == "ask"
    assert scalar(engine, "select current_index from sessions where id=:s", s=sid) == 1
    assert scalar(engine, "select final_score from evaluations where session_id=:s", s=sid) == 85


async def test_follow_up_cap_then_moves_on_with_penalty(engine, tmp_path):
    orch, _ = make(engine, [ev(40), ev(45), ev(50)], tmp_path)
    sid = (await orch.start(F, seed=1)).session_id
    assert (await orch.answer(sid, "a")).kind == "follow_up"
    assert (await orch.answer(sid, "b")).kind == "follow_up"
    third = await orch.answer(sid, "c")
    assert third.kind == "ask"  # cap of 2 follow-ups reached
    assert scalar(engine, "select final_score from evaluations where session_id=:s and final_score is not null",
                  s=sid) == 50 - 2 * 5
    assert scalar(engine, "select followups_used from sessions where id=:s", s=sid) == 0  # reset for next question


async def test_finishes_after_last_question_with_closing(engine, tmp_path):
    orch, _ = make(engine, [ev(90)] * 10, tmp_path)
    sid = (await orch.start(F, seed=1)).session_id
    reply = None
    for _ in range(10):
        reply = await orch.answer(sid, "great answer")
        if reply.state == "done":
            break
    assert reply.state == "done" and reply.kind == "closing"
    assert reply.messages == ["Thanks, that was great. Your report is ready."]
    assert scalar(engine, "select state from sessions where id=:s", s=sid) == "done"
    n = scalar(engine, "select count(*) from evaluations where session_id=:s and final_score is not null", s=sid)
    assert 4 <= n <= 6


async def test_answer_after_done_is_rejected(engine, tmp_path):
    orch, _ = make(engine, [], tmp_path)
    sid = (await orch.start(F, seed=1)).session_id
    await orch.end(sid)
    with pytest.raises(ValueError):
        await orch.answer(sid, "late")


async def test_state_survives_restart(engine, tmp_path):
    orch, _ = make(engine, [ev(40)], tmp_path)
    sid = (await orch.start(F, seed=1)).session_id
    await orch.answer(sid, "weak")
    fresh, _ = make(engine, [ev(90)], tmp_path)  # brand new instance, same DB
    reply = await fresh.answer(sid, "much better answer")
    assert reply.kind == "ask"
    assert scalar(engine, "select current_index from sessions where id=:s", s=sid) == 1


async def test_flow_bridge_changes_next_question_and_versions_plan(engine, tmp_path):
    orch, _ = make(engine, [ev(70, terms=["kafka"])], tmp_path)
    sid = (await orch.start(F, seed=1)).session_id
    await orch.answer(sid, "I would put Kafka in front.")
    versions = scalar(engine, "select count(*) from plans where session_id=:s", s=sid)
    assert versions >= 1


async def test_end_early_closes_session(engine, tmp_path):
    orch, _ = make(engine, [], tmp_path)
    sid = (await orch.start(F, seed=1)).session_id
    reply = await orch.end(sid)
    assert reply.state == "done" and reply.kind == "closing"
