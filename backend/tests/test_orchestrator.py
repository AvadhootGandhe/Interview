"""Phase 3: the DB-backed interview state machine (retrieve -> plan -> ask -> evaluate -> flow)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from helpers import ScriptedLLM, eval_json
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentOutputError
from app.agents.orchestrator import Orchestrator, SessionClosed, SessionNotFinished, SessionNotFound
from app.config import settings
from app.db.models import Evaluation, InterviewSession, Plan, Turn
from app.services.retriever import Filters

FILTERS = Filters(profile="Backend", level="SDE-2/3")
LONG = "I would use a cache with a TTL and eviction, and measure hit rates before tuning it."


def orch(db, llm, **kw) -> Orchestrator:
    return Orchestrator(db, llm, **kw)


async def started(db, llm, filters=FILTERS):
    o = orch(db, llm)
    result = await o.start(filters)
    return o, result


def kinds(db, sid) -> list[str]:
    return [t.kind for t in db.scalars(select(Turn).where(Turn.session_id == sid).order_by(Turn.id))]


async def test_start_retrieves_plans_saves_the_plan_and_greets(db, train_log):
    llm = ScriptedLLM()
    o, r = await started(db, llm)
    assert [m.kind for m in r.messages] == ["greeting", "ask"]
    assert r.text == " ".join(m.text for m in r.messages)
    assert r.progress == {"current": 1, "total": r.progress["total"]} and 4 <= r.progress["total"] <= 6

    session = db.get(InterviewSession, r.session_id)
    assert session.state == "active" and session.profile == "Backend" and session.level == "SDE-2/3"
    plan_rows = db.scalars(select(Plan).where(Plan.session_id == r.session_id)).all()
    assert len(plan_rows) == 1
    doc = json.loads(plan_rows[0].plan_json)
    assert len(doc["plan"]["segments"]) == r.progress["total"]
    pool_ids = {p["id"] for p in doc["pool"]}
    assert all(s["seed_question_id"] in pool_ids for s in doc["plan"]["segments"])
    assert kinds(db, r.session_id) == ["greeting", "ask"]
    assert "planner" in {c["task"] for c in llm.calls}


async def test_ask_prompt_gets_style_examples_and_company_context(db, train_log):
    llm = ScriptedLLM()
    o, r = await started(db, llm, Filters(profile="Backend", level="SDE-2/3", company="Amazon"))
    ask = llm.prompts("interviewer")[-1]
    assert "Task (ask)" in ask and "Similar questions" in ask
    assert ask.count("\n- ") == 3  # exactly three style examples
    assert "How this company interviews:" in ask
    seed = o.snapshot(r.session_id)["current_question"]["text"]
    assert seed in ask


async def test_low_satisfaction_triggers_a_follow_up(db, train_log):
    llm = ScriptedLLM(evaluator=[eval_json(40, follow_up_focus="consistency across replicas")])
    o, r = await started(db, llm)
    t = await o.answer(r.session_id, "Um, you just store it.")
    assert t.kind == "follow_up" and not t.done
    assert t.evaluation.satisfaction == 40
    assert "consistency across replicas" in llm.prompts("interviewer")[-1]
    assert kinds(db, r.session_id) == ["greeting", "ask", "answer", "follow_up"]
    assert db.scalars(select(Evaluation)).all()[0].satisfaction == 40
    assert o.snapshot(r.session_id)["followups"] == 1


async def test_high_satisfaction_moves_on_and_applies_the_flow_controller(db, train_log, monkeypatch):
    import app.agents.orchestrator as module

    calls = []
    real = module.next_segment

    def spy(plan, history, last_eval, pool, search=None):
        calls.append([(h.question_id, h.final_score) for h in history])
        return real(plan, history, last_eval, pool, search=search)

    monkeypatch.setattr(module, "next_segment", spy)
    llm = ScriptedLLM(evaluator=[eval_json(85)])
    o, r = await started(db, llm)
    first = o.snapshot(r.session_id)["current_question"]["id"]
    t = await o.answer(r.session_id, LONG)
    assert t.kind == "ask" and t.progress["current"] == 2
    assert calls == [[(first, 85)]]
    assert o.snapshot(r.session_id)["current_question"]["id"] != first
    assert kinds(db, r.session_id) == ["greeting", "ask", "answer", "ask"]


async def test_follow_up_cap_is_respected_then_it_moves_on(db, train_log):
    llm = ScriptedLLM(evaluator=[eval_json(40)] * 3)
    o, r = await started(db, llm)
    a = await o.answer(r.session_id, "no idea")
    b = await o.answer(r.session_id, "still not sure")
    c = await o.answer(r.session_id, "I really do not know")
    assert [a.kind, b.kind, c.kind] == ["follow_up", "follow_up", "ask"]  # settings.max_followups == 2
    snap = o.snapshot(r.session_id)
    assert snap["followups"] == 0 and snap["finals"][0]["followups"] == 2


async def test_final_score_applies_the_follow_up_penalty(db, train_log):
    llm = ScriptedLLM(evaluator=[eval_json(40), eval_json(80)])
    o, r = await started(db, llm)
    await o.answer(r.session_id, "not sure")
    t = await o.answer(r.session_id, LONG)
    assert t.kind == "ask"
    final = o.snapshot(r.session_id)["finals"][0]
    assert final["satisfaction"] == 80 and final["final"] == 80 - settings.followup_penalty


async def test_penalty_never_goes_below_zero(db, train_log):
    llm = ScriptedLLM(evaluator=[eval_json(10), eval_json(10), eval_json(2)])
    o, r = await started(db, llm)
    for _ in range(3):
        await o.answer(r.session_id, "dunno")
    assert o.snapshot(r.session_id)["finals"][0]["final"] == 0


async def test_after_the_last_question_it_closes_and_the_state_is_done(db, train_log):
    llm = ScriptedLLM(evaluator=[eval_json(85)] * 10)
    o, r = await started(db, llm)
    total, last = r.progress["total"], None
    for _ in range(total):
        last = await o.answer(r.session_id, LONG)
    assert last.kind == "closing" and last.done
    assert db.get(InterviewSession, r.session_id).state == "done"
    assert kinds(db, r.session_id)[-1] == "closing"
    assert len(o.snapshot(r.session_id)["finals"]) == total
    with pytest.raises(SessionClosed):
        await o.answer(r.session_id, "one more thing")


async def test_state_survives_a_restart(db, db_url, train_log):
    from app.db.session import make_engine

    llm = ScriptedLLM(evaluator=[eval_json(40), eval_json(80)])
    o, r = await started(db, llm)
    await o.answer(r.session_id, "not sure")  # -> follow-up, 1 used

    engine = make_engine(db_url)
    with Session(engine) as fresh:  # a new process: new session, new orchestrator, same database
        o2 = Orchestrator(fresh, llm)
        assert o2.snapshot(r.session_id)["followups"] == 1
        t = await o2.answer(r.session_id, LONG)
        assert t.kind == "ask" and t.progress["current"] == 2
        assert o2.snapshot(r.session_id)["finals"][0]["final"] == 75
    engine.dispose()


async def test_every_follow_up_is_logged_for_lora_v2(db, train_log):
    llm = ScriptedLLM(evaluator=[eval_json(40, missing_points=["replication"], follow_up_focus="replication"),
                                 eval_json(45, missing_points=["failover"], follow_up_focus="failover")])
    o, r = await started(db, llm)
    await o.answer(r.session_id, "It stores data.")
    await o.answer(r.session_id, "On disk.")
    lines = [json.loads(line) for line in train_log.read_text().splitlines()]
    assert len(lines) == 2
    first, second = lines
    assert {"profile", "level", "topic", "question", "thread", "missing_points", "follow_up_focus", "follow_up"} <= set(first)
    assert first["profile"] == "Backend" and first["follow_up_focus"] == "replication"
    assert first["missing_points"] == ["replication"]
    assert first["thread"][-1] == {"role": "candidate", "text": "It stores data."}
    assert len(second["thread"]) == 4  # question, answer, first follow-up, second answer
    assert first["follow_up"]


async def test_a_mentioned_term_leads_to_a_bridged_question(db, train_log):
    import re

    llm = ScriptedLLM()
    o = orch(db, llm)
    r = await o.start(FILTERS)
    snap = o.snapshot(r.session_id)
    pool = {p["id"]: p["text"].lower() for p in snap["pool"]}
    texts = [pool[s["seed_question_id"]] for s in snap["plan"]["segments"]]
    candidates = [
        w for w in set(re.findall(r"[a-z]{7,}", texts[2]))
        if not any(w in t for i, t in enumerate(texts) if i != 2)
    ]
    if not candidates:
        pytest.skip("no distinctive word in the sampled third question")
    llm.replies["evaluator"] = [eval_json(75, mentioned_terms=[candidates[0]])]
    await o.answer(r.session_id, LONG)
    assert "candidate mentioned" in llm.prompts("interviewer")[-1]
    assert o.snapshot(r.session_id)["plan"]["segments"][1]["bridge"].startswith("candidate mentioned")


async def test_next_ask_prompt_summarises_the_last_answer(db, train_log):
    llm = ScriptedLLM(evaluator=[eval_json(85, covered_points=["TTL and eviction"], missing_points=[])])
    o, r = await started(db, llm)
    await o.answer(r.session_id, LONG)
    assert "TTL and eviction" in llm.prompts("interviewer")[-1]


async def test_time_limit_closes_the_interview(db, train_log, monkeypatch):
    monkeypatch.setattr(settings, "max_interview_minutes", 10)
    llm = ScriptedLLM(evaluator=[eval_json(40)])
    o, r = await started(db, llm)
    row = db.get(InterviewSession, r.session_id)
    row.created_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    db.commit()
    t = await o.answer(r.session_id, "not sure")
    assert t.kind == "closing" and t.done  # no follow-up once the time is up
    assert db.get(InterviewSession, r.session_id).state == "done"


async def test_end_closes_early_and_scores_the_answered_question(db, train_log):
    llm = ScriptedLLM(evaluator=[eval_json(40)])
    o, r = await started(db, llm)
    await o.answer(r.session_id, "not sure")  # follow-up pending
    t = await o.end(r.session_id)
    assert t.kind == "closing" and t.done
    finals = o.snapshot(r.session_id)["finals"]
    assert len(finals) == 1 and finals[0]["final"] == 40 - settings.followup_penalty
    assert (await o.end(r.session_id)).done  # ending twice is harmless


async def test_end_with_no_answers_scores_nothing(db, train_log):
    o, r = await started(db, ScriptedLLM())
    await o.end(r.session_id)
    assert o.snapshot(r.session_id)["finals"] == []


async def test_evaluator_failure_changes_nothing_so_the_answer_can_be_retried(db, train_log):
    llm = ScriptedLLM(evaluator=["bad", "bad", eval_json(85)])
    o, r = await started(db, llm)
    before = kinds(db, r.session_id)
    with pytest.raises(AgentOutputError):
        await o.answer(r.session_id, LONG)
    assert kinds(db, r.session_id) == before
    t = await o.answer(r.session_id, LONG)
    assert t.kind == "ask"


async def test_report_after_done_is_cached(db, train_log):
    llm = ScriptedLLM(evaluator=[eval_json(85)] * 10)
    o, r = await started(db, llm)
    with pytest.raises(SessionNotFinished):
        await o.report(r.session_id)
    for _ in range(r.progress["total"]):
        await o.answer(r.session_id, LONG)
    report = await o.report(r.session_id)
    assert report.overall_score == 85 and len(report.questions) == r.progress["total"]
    calls = len(llm.calls)
    again = await orch(db, llm).report(r.session_id)
    assert again == report and len(llm.calls) == calls  # served from the saved copy


async def test_unknown_session_and_unknown_filters(db, train_log):
    o = orch(db, ScriptedLLM())
    with pytest.raises(SessionNotFound):
        await o.answer("nope", "hi")
    with pytest.raises(ValueError):
        await o.start(Filters(profile="Underwater Basket Weaving"))


async def test_a_topic_session_stays_on_topic(db, train_log):
    o = orch(db, ScriptedLLM())
    r = await o.start(Filters(profile="Backend", level="SDE-2/3", topic="MongoDB"))
    plan = o.snapshot(r.session_id)["plan"]["segments"]
    assert sum(s["topic"] == "MongoDB" for s in plan) / len(plan) >= 0.6
