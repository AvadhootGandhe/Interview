"""Orchestrator: the DB-backed interview state machine.

    start:  RETRIEVE (context pack) -> PLAN -> greeting + first question
    answer: EVALUATE -> follow-up (score < threshold, under the cap) or finish the question
            -> FLOW (rule-based) -> ask / transition for the next segment, or CLOSING -> done
    end:    close early.  report: the Reporter's output, stored once the interview is done.

Nothing lives in memory between calls: each call loads the session from SQLite, does its LLM work
without holding a write transaction, then saves everything in one commit.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import LLM, Msg
from app.agents.evaluator import EvalInput, Evaluator
from app.agents.interviewer import Interviewer, InterviewerInput
from app.agents.planner import Planner
from app.agents.reporter import QuestionRecord, Report, ReportInput, Reporter
from app.agents.schemas import Evaluation, InterviewPlan
from app.config import settings
from app.db.models import Evaluation as EvaluationRow
from app.db.models import InterviewSession, Plan, SessionState, Turn
from app.services.context_pack import build_context_pack
from app.services.flow import next_segment
from app.services.retriever import Filters, PoolItem, Retriever

REPO_ROOT = Path(__file__).resolve().parents[3]


class SessionClosed(Exception):
    """The interview is already over."""


class ReportNotReady(Exception):
    """The report exists only once the interview is done."""


class QuestionResult(BaseModel):
    question_id: str
    topic: str
    text: str
    score: int  # last satisfaction minus the follow-up penalty
    follow_ups: int
    evaluation: Evaluation | None = None


class InterviewState(BaseModel):
    pool: list[dict]
    company: str | None = None
    company_summary: str = ""
    idx: int = 0  # index of the segment being asked
    followups: int = 0  # follow-ups asked on the current question
    asked: list[str] = []
    results: list[QuestionResult] = []
    open_eval: Evaluation | None = None  # latest evaluation of the current (unfinished) question
    started_at: float = 0.0
    report: dict | None = None
    plan: InterviewPlan | None = None  # loaded from the plans table, not stored here

    def items(self) -> list[PoolItem]:
        return [PoolItem(**p) for p in self.pool]


@dataclass
class Reply:
    session_id: str
    text: str
    kind: str  # ask | follow_up | closing
    state: str  # asking | done
    done: bool
    question_index: int
    total_questions: int
    messages: list[dict]
    evaluation: Evaluation | None = None
    timings: dict[str, float] = field(default_factory=dict)  # stage -> ms (Server-Timing)


def _summary(ev: Evaluation) -> str:
    parts = []
    if ev.covered_points:
        parts.append("Covered: " + ", ".join(ev.covered_points[:3]) + ".")
    if ev.missing_points:
        parts.append("Missed: " + ", ".join(ev.missing_points[:3]) + ".")
    return " ".join(parts)


class Orchestrator:
    def __init__(
        self,
        db: Session,
        llm: LLM,
        generator=None,
        *,
        pack_builder=None,
        search=None,
        followup_log: Path | str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db = db
        self.llm = llm
        self.generator = generator
        self.pack_builder = pack_builder or build_context_pack
        self.search = search or Retriever(db).search
        self.followup_log = Path(followup_log or settings.followup_log_path or REPO_ROOT / "data" / "followup_train.jsonl")
        self.clock = clock
        self.interviewer = Interviewer(llm)
        self.timings: dict[str, float] = {}

    async def _say(self, inp: InterviewerInput) -> str:
        return await self._timed("interviewer", self.interviewer.run(inp))

    async def _timed(self, stage: str, coro):
        t0 = time.perf_counter()
        try:
            return await coro
        finally:
            self.timings[stage] = self.timings.get(stage, 0.0) + (time.perf_counter() - t0) * 1000

    # --- persistence -----------------------------------------------------------

    def _session(self, session_id: str) -> InterviewSession:
        row = self.db.get(InterviewSession, session_id)
        if row is None:
            raise KeyError(session_id)
        return row

    def load(self, session_id: str) -> InterviewState:
        self._session(session_id)
        row = self.db.get(SessionState, session_id)
        plan_row = self.db.scalar(select(Plan).where(Plan.session_id == session_id).order_by(Plan.id.desc()))
        state = InterviewState.model_validate_json(row.state_json)
        state.plan = InterviewPlan.model_validate_json(plan_row.plan_json)
        return state

    def _save(self, session_id: str, state: InterviewState, plan_changed: bool = False) -> None:
        if plan_changed:
            self.db.add(Plan(session_id=session_id, plan_json=state.plan.model_dump_json()))
        payload = state.model_dump_json(exclude={"plan"})
        row = self.db.get(SessionState, session_id)
        if row is None:
            self.db.add(SessionState(session_id=session_id, state_json=payload))
        else:
            row.state_json = payload

    def _turn(self, session_id: str, role: str, kind: str, text: str, question_id: str | None = None) -> Turn:
        turn = Turn(session_id=session_id, role=role, kind=kind, text=text, question_id=question_id)
        self.db.add(turn)
        return turn

    def _thread(self, session_id: str, question_id: str) -> list[Msg]:
        rows = self.db.scalars(
            select(Turn).where(Turn.session_id == session_id, Turn.question_id == question_id).order_by(Turn.id)
        )
        return [Msg(t.role, t.text) for t in rows]

    # --- helpers ---------------------------------------------------------------

    def _similar(self, state: InterviewState, seed: PoolItem) -> list[str]:
        others = [p for p in state.items() if p.id != seed.id and p.id not in state.asked]
        picks = self.search([seed.text], others)[: settings.style_examples]
        for p in others:  # pad with same-topic questions
            if len(picks) >= settings.style_examples:
                break
            if p.topic == seed.topic and p not in picks:
                picks.append(p)
        return [p.text for p in picks]

    def _ask_input(self, session: InterviewSession, state: InterviewState, mode: str, seed: PoolItem,
                   bridge: str | None, summary: str) -> InterviewerInput:
        seg = state.plan.segments[state.idx]
        return InterviewerInput(
            mode=mode, profile=session.profile or "technical", level=session.level or "",
            company=state.company, company_summary=state.company_summary, segment=seg, seed_text=seed.text,
            similar=self._similar(state, seed), bridge=bridge, last_answer_summary=summary,
        )

    def _closing_input(self, session: InterviewSession, state: InterviewState) -> InterviewerInput:
        return InterviewerInput(mode="closing", profile=session.profile or "technical", level=session.level or "",
                                company=state.company, company_summary=state.company_summary)

    def _reply(self, session: InterviewSession, state: InterviewState, kind: str, messages: list[dict],
               evaluation: Evaluation | None = None) -> Reply:
        return Reply(
            session_id=session.id, text=" ".join(m["text"] for m in messages), kind=kind, state=session.state,
            done=session.state == "done", question_index=min(state.idx, len(state.plan.segments) - 1),
            total_questions=len(state.plan.segments), messages=messages, evaluation=evaluation,
            timings=dict(self.timings),
        )

    def _log_followup(self, session: InterviewSession, seed: PoolItem, thread: list[Msg],
                      ev: Evaluation, follow_up: str) -> None:
        """Training data for LoRA v2: (context, answer, gaps) -> follow-up."""
        self.followup_log.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "session_id": session.id, "profile": session.profile, "level": session.level,
            "company": session.company, "topic": seed.topic, "question": seed.text,
            "thread": [{"role": m.role, "text": m.text} for m in thread],
            "satisfaction": ev.satisfaction, "missing_points": ev.missing_points,
            "follow_up_focus": ev.follow_up_focus, "follow_up": follow_up,
        }
        with self.followup_log.open("a") as f:
            f.write(json.dumps(row) + "\n")

    def _time_is_up(self, state: InterviewState) -> bool:
        limit = settings.interview_time_limit_s
        return bool(limit) and self.clock() - state.started_at > limit

    # --- public API --------------------------------------------------------------

    async def start(self, filters: Filters, user_id: str | None = None) -> Reply:
        pack = await self._timed("retrieve", self.pack_builder(
            self.db, filters, llm=self.llm, generator=self.generator, user_id=user_id))
        plan = await self._timed("plan", Planner(self.llm).run(pack))
        session = InterviewSession(
            id=uuid.uuid4().hex, user_id=user_id, profile=filters.profile, level=filters.level,
            company=filters.company, topic=filters.topic, state="asking",
        )
        company = None if pack.company_profile.is_general else pack.company_profile.company
        state = InterviewState(
            pool=[p.to_dict() for p in pack.pool], company=company, company_summary=pack.company_profile.summary,
            started_at=self.clock(), plan=plan,
        )
        seed = next(p for p in state.items() if p.id == plan.segments[0].seed_question_id)

        base = self._closing_input(session, state)
        # Independent of each other: run both Claude calls at once (saves one LLM round trip at start).
        greeting, question = await asyncio.gather(
            self._say(InterviewerInput(**{**base.__dict__, "mode": "greeting"})),
            self._say(self._ask_input(session, state, "ask", seed, None, "")),
        )

        self.db.add(session)
        self.db.flush()
        self._turn(session.id, "interviewer", "greeting", greeting)
        self._turn(session.id, "interviewer", "ask", question, seed.id)
        self._save(session.id, state, plan_changed=True)
        self.db.commit()
        return self._reply(session, state, "ask", [{"kind": "greeting", "text": greeting},
                                                   {"kind": "ask", "text": question}])

    async def answer(self, session_id: str, text: str) -> Reply:
        session = self._session(session_id)
        if session.state == "done":
            raise SessionClosed(session_id)
        state = self.load(session_id)
        pool = state.items()
        seg = state.plan.segments[state.idx]
        seed = next(p for p in pool if p.id == seg.seed_question_id)

        thread = self._thread(session_id, seed.id) + [Msg("candidate", text)]
        evaluation = await self._timed("evaluate", Evaluator(self.llm).run(EvalInput(
            question=seed.text, thread=thread, profile=session.profile, level=session.level, topic=seed.topic)))
        state.open_eval = evaluation
        sat = evaluation.satisfaction

        # Weak answer and follow-ups left: probe exactly what was missing.
        if sat < settings.satisfaction_threshold and state.followups < settings.max_followups:
            inp = self._ask_input(session, state, "follow_up", seed, None, _summary(evaluation))
            inp.follow_up_focus, inp.missing_points = evaluation.follow_up_focus, evaluation.missing_points
            follow_up = await self._say(inp)
            state.followups += 1
            self._persist_answer(session, seed, text, evaluation)
            self._turn(session_id, "interviewer", "follow_up", follow_up, seed.id)
            self._save(session_id, state)
            self.db.commit()
            self._log_followup(session, seed, thread, evaluation, follow_up)
            return self._reply(session, state, "follow_up", [{"kind": "follow_up", "text": follow_up}], evaluation)

        # The question is finished.
        final = max(0, sat - settings.followup_penalty * state.followups)
        state.results.append(QuestionResult(
            question_id=seed.id, topic=seed.topic, text=seed.text, score=final,
            follow_ups=state.followups, evaluation=evaluation))
        state.asked.append(seed.id)
        weak_finish = sat < settings.satisfaction_threshold
        summary = _summary(evaluation)
        state.followups, state.open_eval = 0, None

        last = state.idx + 1 >= len(state.plan.segments)
        if last or self._time_is_up(state):
            closing = await self._say(self._closing_input(session, state))
            self._persist_answer(session, seed, text, evaluation)
            self._turn(session_id, "interviewer", "closing", closing)
            session.state = "done"
            self._save(session_id, state)
            self.db.commit()
            return self._reply(session, state, "closing", [{"kind": "closing", "text": closing}], evaluation)

        t0 = time.perf_counter()
        decision = next_segment(state.plan, state.idx, state.asked, evaluation, final, pool, search=self.search)
        self.timings["flow"] = (time.perf_counter() - t0) * 1000
        plan_changed = decision.plan is not state.plan
        state.plan = decision.plan
        state.idx += 1
        nxt = next(p for p in pool if p.id == decision.segment.seed_question_id)
        mode = "transition" if weak_finish else "ask"
        question = await self._say(self._ask_input(session, state, mode, nxt, decision.bridge, summary))
        self._persist_answer(session, seed, text, evaluation)
        self._turn(session_id, "interviewer", "ask", question, nxt.id)
        self._save(session_id, state, plan_changed=plan_changed)
        self.db.commit()
        return self._reply(session, state, "ask", [{"kind": "ask", "text": question}], evaluation)

    def _persist_answer(self, session: InterviewSession, seed: PoolItem, text: str, ev: Evaluation) -> None:
        turn = self._turn(session.id, "candidate", "answer", text, seed.id)
        self.db.flush()
        self.db.add(EvaluationRow(turn_id=turn.id, satisfaction=ev.satisfaction, result_json=ev.model_dump_json()))

    async def end(self, session_id: str) -> Reply:
        session = self._session(session_id)
        if session.state == "done":
            raise SessionClosed(session_id)
        state = self.load(session_id)
        if state.open_eval is not None:  # a question was answered but still in follow-up: score what it got
            seed = next(p for p in state.items() if p.id == state.plan.segments[state.idx].seed_question_id)
            final = max(0, state.open_eval.satisfaction - settings.followup_penalty * state.followups)
            state.results.append(QuestionResult(
                question_id=seed.id, topic=seed.topic, text=seed.text, score=final,
                follow_ups=state.followups, evaluation=state.open_eval))
            state.open_eval = None
        closing = await self._say(self._closing_input(session, state))
        self._turn(session_id, "interviewer", "closing", closing)
        session.state = "done"
        self._save(session_id, state)
        self.db.commit()
        return self._reply(session, state, "closing", [{"kind": "closing", "text": closing}])

    async def report(self, session_id: str) -> Report:
        session = self._session(session_id)
        if session.state != "done":
            raise ReportNotReady(session_id)
        state = self.load(session_id)
        if state.report is not None:
            return Report.model_validate(state.report)
        records = [
            QuestionRecord(
                question_id=r.question_id, topic=r.topic, text=r.text, final_score=r.score, follow_ups=r.follow_ups,
                thread=self._thread(session_id, r.question_id), evaluation=r.evaluation)
            for r in state.results
        ]
        report = await Reporter(self.llm).run(ReportInput(
            profile=session.profile, level=session.level, company=state.company or session.company,
            topic=session.topic, questions=records))
        state.report = report.model_dump()
        self._save(session_id, state)
        self.db.commit()
        return report
