"""Phase 3: the DB-backed interview state machine."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.agents.orchestrator import Orchestrator, ReportNotReady, SessionClosed
from app.agents.schemas import InterviewPlan
from app.config import settings
from app.db.models import Evaluation as EvaluationRow
from app.db.models import InterviewSession, Plan, Turn
from app.services.retriever import Filters
from tests.conftest import RoutedLLM
from app.services.flow import keyword_search
from tests.factories import eval_json, pack_of, plan_of, standard_pool

FILTERS = Filters(profile="Backend", level="SDE-2/3", company="Amazon")


def llm_with(*sats, terms=None, **routes):
    """An LLM whose evaluator returns the given satisfaction scores in order (the last repeats)."""
    queue = list(sats)

    def evaluate(prompt, **kw):
        sat = queue.pop(0) if len(queue) > 1 else queue[0]
        return eval_json(sat, terms=terms if sat == sats[0] else None)

    return RoutedLLM({"evaluate": evaluate, **routes})


def orch(db, llm, tmp_path, **kw):
    return Orchestrator(db, llm, followup_log=tmp_path / "followups.jsonl", **kw)


def fixed_pack(db, filters=FILTERS, llm=None, generator=None, user_id=None):
    async def build(*a, **k):
        return pack_of(standard_pool())
    return build


async def started(db, tmp_path, *sats, **kw):
    llm = llm_with(*sats)
    o = orch(db, llm, tmp_path, pack_builder=fixed_pack(db), **kw)
    first = await o.start(FILTERS)
    return o, llm, first


def turns(db, sid):
    return list(db.scalars(select(Turn).where(Turn.session_id == sid).order_by(Turn.id)))


async def test_start_retrieves_plans_saves_the_plan_and_greets(db, tmp_path):
    llm = llm_with(80)
    o = orch(db, llm, tmp_path)  # real retriever + context pack on the sample DB
    first = await o.start(FILTERS)
    assert first.state == "asking" and not first.done
    kinds = [t.kind for t in turns(db, first.session_id)]
    assert kinds == ["greeting", "ask"]
    assert first.text.startswith(turns(db, first.session_id)[0].text)

    plan_row = db.scalar(select(Plan).where(Plan.session_id == first.session_id))
    plan = InterviewPlan.model_validate_json(plan_row.plan_json)
    assert 4 <= len(plan.segments) <= 6 and first.total_questions == len(plan.segments)
    assert db.get(InterviewSession, first.session_id).state == "asking"
    # company profile summary used the cheap model
    assert llm.calls_for("company_profile")[0]["model"] == settings.cheap_model
    assert [c["task"] for c in llm.calls][:3] == ["company_profile", "plan", "interview"]


async def test_low_satisfaction_asks_a_follow_up_on_the_same_question(db, tmp_path):
    o, llm, first = await started(db, tmp_path, 40)
    r = await o.answer(first.session_id, "Um, caches are fast?")
    assert r.kind == "follow_up" and not r.done and r.question_index == 0
    assert "failure handling" in r.text  # the demo interviewer echoes the evaluator's focus
    assert llm.calls_for("interview")[-1]["prompt"].count("failure handling")
    assert [t.kind for t in turns(db, first.session_id)][-2:] == ["answer", "follow_up"]


async def test_high_satisfaction_moves_to_the_next_segment(db, tmp_path):
    o, llm, first = await started(db, tmp_path, 85)
    r = await o.answer(first.session_id, "A thorough answer.")
    assert r.kind == "ask" and r.question_index == 1
    ev = db.scalars(select(EvaluationRow)).all()
    assert len(ev) == 1 and ev[0].satisfaction == 85 and json.loads(ev[0].result_json)["missing_points"]


async def test_flow_controller_is_applied_and_bridge_reaches_the_interviewer(db, tmp_path):
    pool = standard_pool()
    plan = plan_of(pool, ["c1", "c2", "m1", "r2", "m2"])
    llm = llm_with(75, terms=["redis"], plan=plan.model_dump_json(include={"segments"}))
    o = orch(db, llm, tmp_path, pack_builder=fixed_pack(db), search=keyword_search)
    first = await o.start(FILTERS)
    r = await o.answer(first.session_id, "I'd put Redis in front of it.")
    state = o.load(first.session_id)
    assert r.kind == "ask" and r.question_index == 1
    assert [s.seed_question_id for s in state.plan.segments] == ["c1", "r2", "m1", "c2", "m2"]
    assert "candidate mentioned Redis" in llm.calls_for("interview")[-1]["prompt"]
    assert db.scalars(select(Plan).where(Plan.session_id == first.session_id)).all().__len__() == 2  # re-saved


async def test_follow_up_cap_then_moves_on_with_penalised_final_score(db, tmp_path):
    o, llm, first = await started(db, tmp_path, 40)
    sid = first.session_id
    kinds = [(await o.answer(sid, "meh")).kind for _ in range(3)]
    assert kinds == ["follow_up", "follow_up", "ask"]
    assert "Mode: transition" in llm.calls_for("interview")[-1]["prompt"]  # graceful move-on
    result = o.load(sid).results[0]
    assert result.follow_ups == settings.max_followups == 2
    assert result.score == 40 - 2 * settings.followup_penalty


async def test_interview_closes_after_the_last_question(db, tmp_path):
    o, llm, first = await started(db, tmp_path, 90)
    sid, n = first.session_id, first.total_questions
    replies = [await o.answer(sid, "great answer") for _ in range(n)]
    assert [r.kind for r in replies[:-1]] == ["ask"] * (n - 1)
    assert replies[-1].kind == "closing" and replies[-1].done and replies[-1].state == "done"
    assert db.get(InterviewSession, sid).state == "done"
    with pytest.raises(SessionClosed):
        await o.answer(sid, "one more")


async def test_state_survives_a_restart(db, tmp_path):
    o1, llm, first = await started(db, tmp_path, 85)
    sid = first.session_id
    await o1.answer(sid, "answer one")
    o2 = orch(db, llm, tmp_path, pack_builder=fixed_pack(db))  # a brand new instance
    r = await o2.answer(sid, "answer two")
    assert r.question_index == 2
    assert [x.score for x in o2.load(sid).results] == [85, 85]


async def test_every_follow_up_is_logged_for_lora_v2(db, tmp_path):
    o, llm, first = await started(db, tmp_path, 40)
    await o.answer(first.session_id, "not much")
    lines = (tmp_path / "followups.jsonl").read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["follow_up"] and row["missing_points"] == ["failure handling"]
    assert row["level"] == "SDE-2/3" and row["thread"][-1]["role"] == "candidate"
    assert row["question"]


async def test_time_limit_closes_after_the_current_question(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "interview_time_limit_s", 60)
    now = [1000.0]
    o, llm, first = await started(db, tmp_path, 90, clock=lambda: now[0])
    now[0] += 120
    r = await o.answer(first.session_id, "fine")
    assert r.kind == "closing" and r.done


async def test_end_closes_early_and_the_report_covers_answered_questions(db, tmp_path):
    o, llm, first = await started(db, tmp_path, 90)
    sid = first.session_id
    await o.answer(sid, "answer")
    r = await o.end(sid)
    assert r.kind == "closing" and r.done
    report = await o.report(sid)
    assert len(report.questions) == 1 and report.overall_score == 90
    assert (await o.report(sid)).overall_score == 90  # served from the stored copy
    assert len(llm.calls_for("report")) == 1


async def test_ending_mid_follow_up_still_scores_the_open_question(db, tmp_path):
    o, llm, first = await started(db, tmp_path, 40)
    await o.answer(first.session_id, "meh")  # follow-up asked, question still open
    await o.end(first.session_id)
    assert len((await o.report(first.session_id)).questions) == 1


async def test_report_before_the_interview_ends_is_refused(db, tmp_path):
    o, llm, first = await started(db, tmp_path, 90)
    with pytest.raises(ReportNotReady):
        await o.report(first.session_id)


async def test_unknown_session(db, tmp_path):
    o = orch(db, RoutedLLM(), tmp_path)
    with pytest.raises(KeyError):
        await o.answer("nope", "hi")


async def test_start_writes_greeting_and_first_question_concurrently(db, tmp_path):
    """Latency: the two interviewer calls at start do not depend on each other, so they overlap."""
    import asyncio

    state = {"now": 0, "peak": 0}
    inner = llm_with(80)

    class Slow:
        async def complete(self, prompt, **kw):
            if kw.get("task") != "interview":
                return await inner.complete(prompt, **kw)
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
            await asyncio.sleep(0.05)
            state["now"] -= 1
            return await inner.complete(prompt, **kw)

    o = orch(db, Slow(), tmp_path, pack_builder=fixed_pack(db))
    first = await o.start(FILTERS)
    assert state["peak"] == 2
    assert [m["kind"] for m in first.messages] == ["greeting", "ask"]
