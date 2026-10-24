"""Orchestrator: the DB-backed interview state machine.

RETRIEVE -> PLAN -> greet + ask -> (answer -> EVALUATE -> follow-up | FLOW -> ask)* -> CLOSING -> done.

All state lives in the database (sessions, turns, evaluations and a JSON state document in `plans`),
so a new Orchestrator instance, even in a new process, continues an interview mid-way.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.evaluator import EvalContext, Evaluation, Evaluator, ThreadTurn
from app.agents.interviewer import Interviewer, InterviewerContext
from app.agents.planner import InterviewPlan, Planner
from app.agents.reporter import QuestionResult, Report, Reporter, ReportContext
from app.config import settings
from app.db.models import Evaluation as EvaluationRow
from app.db.models import InterviewSession, Plan, Turn
from app.services.context_pack import build_context_pack
from app.services.flow import Outcome, apply_next, next_segment
from app.services.retriever import Filters, PoolItem, Retriever

REPO_ROOT = Path(__file__).resolve().parents[3]


class SessionNotFound(Exception):
    pass


class SessionClosed(Exception):
    """The interview is already finished."""


class SessionNotFinished(Exception):
    """The report is only available once the interview is done."""


@dataclass
class Message:
    kind: str
    text: str


@dataclass
class StartResult:
    session_id: str
    messages: list[Message]
    progress: dict

    @property
    def text(self) -> str:
        return " ".join(m.text for m in self.messages)


@dataclass
class TurnResult:
    kind: str  # follow_up | ask | closing
    text: str
    done: bool
    progress: dict
    evaluation: Evaluation | None = None
    question_id: str | None = None


def _train_path() -> Path:
    return Path(settings.followup_train_path) if settings.followup_train_path else REPO_ROOT / "data" / "followup_train.jsonl"


def summarize_answer(answer: str, ev: Evaluation | None) -> str:
    """One line about the last answer, for the next question's transition."""
    if ev and (ev.covered_points or ev.missing_points):
        parts = []
        if ev.covered_points:
            parts.append("covered " + "; ".join(ev.covered_points[:3]))
        if ev.missing_points:
            parts.append("missed " + "; ".join(ev.missing_points[:2]))
        return "They " + ", ".join(parts) + "."
    text = " ".join(answer.split())
    return text[:140] + ("..." if len(text) > 140 else "")


class Orchestrator:
    def __init__(self, db: Session, llm, generator=None, judge=None, train_log: Path | None = None) -> None:
        self.db = db
        self.llm = llm
        self.generator = generator
        self.planner = Planner(llm)
        self.evaluator = Evaluator(llm)
        self.interviewer = Interviewer(llm, judge=judge)
        self.reporter = Reporter(llm)
        self.train_log = train_log

    # --- state helpers --------------------------------------------------------

    def _session(self, sid: str) -> InterviewSession:
        row = self.db.get(InterviewSession, sid)
        if row is None:
            raise SessionNotFound(sid)
        return row

    def _plan_row(self, sid: str) -> Plan:
        return self.db.scalars(select(Plan).where(Plan.session_id == sid).order_by(Plan.id.desc())).first()

    def _doc(self, sid: str) -> dict:
        return json.loads(self._plan_row(sid).plan_json)

    def _save(self, sid: str, doc: dict, new_version: bool = False) -> None:
        if new_version:
            self.db.add(Plan(session_id=sid, plan_json=json.dumps(doc)))
        else:
            self._plan_row(sid).plan_json = json.dumps(doc)

    def _turn(self, sid: str, role: str, kind: str, text: str, qid: str | None) -> Turn:
        t = Turn(session_id=sid, role=role, kind=kind, text=text, question_id=qid)
        self.db.add(t)
        self.db.flush()
        return t

    @staticmethod
    def _pool(doc: dict) -> list[PoolItem]:
        return [PoolItem(**p) for p in doc["pool"]]

    @staticmethod
    def _current(doc: dict) -> dict:
        return doc["plan"]["segments"][doc["cursor"]["index"]]

    def _question(self, doc: dict) -> PoolItem:
        qid = self._current(doc)["seed_question_id"]
        return next(p for p in self._pool(doc) if p.id == qid)

    def _thread(self, sid: str, qid: str) -> list[ThreadTurn]:
        rows = self.db.scalars(
            select(Turn).where(Turn.session_id == sid, Turn.question_id == qid).order_by(Turn.id)
        )
        return [ThreadTurn("candidate" if t.role == "candidate" else "interviewer", t.text) for t in rows]

    def _progress(self, doc: dict) -> dict:
        return {"current": doc["cursor"]["index"] + 1, "total": len(doc["plan"]["segments"])}

    def snapshot(self, sid: str) -> dict:
        self._session(sid)
        doc = self._doc(sid)
        q = self._question(doc)
        return {
            "state": self._session(sid).state, "plan": doc["plan"], "pool": doc["pool"],
            "index": doc["cursor"]["index"], "followups": doc["cursor"]["followups"],
            "finals": doc["cursor"]["finals"],
            "current_question": {"id": q.id, "text": q.text, "topic": q.topic},
        }

    def _ctx(self, doc: dict, mode: str, **kw) -> InterviewerContext:
        f = doc["filters"]
        return InterviewerContext(
            mode=mode, profile=f["profile"], level=f["level"], company=f["company"], topic=f["topic"],
            company_summary=doc["company_summary"], **kw,
        )

    def _examples(self, doc: dict, seed: PoolItem) -> list[str]:
        """Similar retrieved questions as style examples: FTS matches first, then same topic, then the rest."""
        pool = self._pool(doc)
        skip = {seed.id} | {s["seed_question_id"] for s in doc["plan"]["segments"][: doc["cursor"]["index"]]}
        rest = [p for p in pool if p.id not in skip]
        ranked = [p for p in Retriever(self.db).search(seed.text, rest)]
        ranked += [p for p in rest if p.topic == seed.topic and p not in ranked]
        ranked += [p for p in rest if p not in ranked]
        return [p.text for p in ranked[: settings.examples_per_ask]]

    async def _ask(self, sid: str, doc: dict, last_summary: str = "") -> Message:
        seg = self._current(doc)
        seed = self._question(doc)
        text = await self.interviewer.run(self._ctx(
            doc, "ask", theme=seg["theme"], seed_question=seed.text, examples=self._examples(doc, seed),
            bridge=seg.get("bridge") or None, last_answer_summary=last_summary,
        ))
        self._turn(sid, "interviewer", "ask", text, seed.id)
        return Message("ask", text)

    # --- public API -----------------------------------------------------------

    async def start(self, filters: Filters, user_id: str | None = None) -> StartResult:
        pack = await build_context_pack(self.db, filters, self.llm, self.generator, user_id=user_id)
        greeting_ctx = InterviewerContext(
            mode="greeting", profile=filters.profile, level=filters.level, company=filters.company,
            topic=filters.topic, company_summary=pack.company_profile.summary,
        )
        plan, greeting = await asyncio.gather(self.planner.run(pack), self.interviewer.run(greeting_ctx))

        sid = uuid4().hex
        self.db.add(InterviewSession(
            id=sid, user_id=user_id, profile=filters.profile, level=filters.level,
            company=filters.company, topic=filters.topic, state="active",
        ))
        self.db.flush()
        doc = {
            "filters": {"profile": filters.profile, "level": filters.level,
                        "company": filters.company, "topic": filters.topic},
            "company_summary": pack.company_profile.summary,
            "plan": plan.model_dump(),
            "pool": [p.to_dict() for p in pack.pool],
            "cursor": {"index": 0, "followups": 0, "finals": [], "terms": [], "last_eval": None},
        }
        self.db.add(Plan(session_id=sid, plan_json=json.dumps(doc)))
        self._turn(sid, "interviewer", "greeting", greeting, None)
        first = await self._ask(sid, doc)
        self.db.commit()
        return StartResult(sid, [Message("greeting", greeting), first], self._progress(doc))

    async def answer(self, sid: str, text: str) -> TurnResult:
        session = self._session(sid)
        if session.state == "done":
            raise SessionClosed(sid)
        doc = self._doc(sid)
        cur = doc["cursor"]
        seed = self._question(doc)
        text = text.strip()

        thread = self._thread(sid, seed.id) + [ThreadTurn("candidate", text)]
        # Evaluate first: if it fails nothing has been saved and the candidate can simply retry.
        ev = await self.evaluator.run(EvalContext(
            question=seed.text, thread=thread, level=session.level, profile=session.profile, topic=seed.topic,
        ))
        turn = self._turn(sid, "candidate", "answer", text, seed.id)
        self.db.add(EvaluationRow(turn_id=turn.id, satisfaction=ev.satisfaction, result_json=ev.model_dump_json()))
        cur["last_eval"] = ev.model_dump()
        cur["last_answer"] = text
        cur["terms"] = list(dict.fromkeys(cur["terms"] + ev.mentioned_terms))

        if self._over_time(session):
            return await self._close(sid, doc, session, ev, finalize_current=True)

        if ev.satisfaction < settings.satisfaction_threshold and cur["followups"] < settings.max_followups:
            cur["followups"] += 1
            reply = await self.interviewer.run(self._ctx(
                doc, "follow_up", seed_question=seed.text, follow_up_focus=ev.follow_up_focus,
                missing_points=ev.missing_points, thread=thread,
            ))
            self._turn(sid, "interviewer", "follow_up", reply, seed.id)
            self._log_follow_up(session, seed, thread, ev, reply)
            self._save(sid, doc)
            self.db.commit()
            return TurnResult("follow_up", reply, False, self._progress(doc), ev, seed.id)

        self._finalize(doc, seed, ev)
        if cur["index"] + 1 >= len(doc["plan"]["segments"]):
            return await self._close(sid, doc, session, ev, finalize_current=False)

        history = [Outcome(f["question_id"], f["final"], f["terms"]) for f in cur["finals"]]
        last = SimpleNamespace(mentioned_terms=history[-1].mentioned_terms)
        plan = InterviewPlan.model_validate(doc["plan"])
        retriever = Retriever(self.db)
        segment, _bridge = next_segment(plan, history, last, self._pool(doc), search=retriever.search)
        new_plan = apply_next(plan, cur["index"] + 1, segment)
        changed = new_plan.model_dump() != doc["plan"]
        doc["plan"] = new_plan.model_dump()
        cur["index"] += 1
        cur.update(followups=0, terms=[], last_eval=None)
        message = await self._ask(sid, doc, summarize_answer(text, ev))
        self._save(sid, doc, new_version=changed)
        self.db.commit()
        return TurnResult("ask", message.text, False, self._progress(doc), ev, self._question(doc).id)

    async def end(self, sid: str) -> TurnResult:
        session = self._session(sid)
        doc = self._doc(sid)
        if session.state == "done":
            closing = self.db.scalars(
                select(Turn).where(Turn.session_id == sid, Turn.kind == "closing").order_by(Turn.id.desc())
            ).first()
            return TurnResult("closing", closing.text if closing else "", True, self._progress(doc))
        return await self._close(sid, doc, session, None, finalize_current=True)

    async def report(self, sid: str) -> Report:
        session = self._session(sid)
        if session.state != "done":
            raise SessionNotFinished(sid)
        doc = self._doc(sid)
        if doc.get("report"):
            return Report.model_validate(doc["report"])
        results = [
            QuestionResult(
                question_id=f["question_id"], topic=f["topic"], question=f["question"], final_score=f["final"],
                followups=f["followups"], covered_points=f["covered"], missing_points=f["missing"],
            )
            for f in doc["cursor"]["finals"]
        ]
        report = await self.reporter.run(ReportContext(
            session.profile, session.level, session.company, session.topic, results
        ))
        doc["report"] = report.model_dump()
        self._save(sid, doc)
        self.db.commit()
        return report

    # --- internals --------------------------------------------------------------

    @staticmethod
    def _over_time(session: InterviewSession) -> bool:
        limit = settings.max_interview_minutes
        if not limit:
            return False
        started = session.created_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - started).total_seconds() > limit * 60

    @staticmethod
    def _finalize(doc: dict, seed: PoolItem, ev: Evaluation) -> None:
        """Final score = last satisfaction minus the penalty for each follow-up the question needed."""
        cur = doc["cursor"]
        final = max(0, ev.satisfaction - settings.followup_penalty * cur["followups"])
        cur["finals"].append({
            "question_id": seed.id, "topic": seed.topic, "question": seed.text,
            "satisfaction": ev.satisfaction, "followups": cur["followups"], "final": final,
            "covered": ev.covered_points, "missing": ev.missing_points, "terms": list(cur["terms"]),
        })

    async def _close(self, sid, doc, session, ev, finalize_current: bool) -> TurnResult:
        cur = doc["cursor"]
        seed = self._question(doc)
        answered = cur.get("last_eval") is not None
        if finalize_current and answered and not any(f["question_id"] == seed.id for f in cur["finals"]):
            self._finalize(doc, seed, Evaluation.model_validate(cur["last_eval"]))
        finals = sorted(cur["finals"], key=lambda f: f["final"])
        note = ""
        if finals:
            note = f"Strongest on {finals[-1]['topic']}; most to work on in {finals[0]['topic']}."
        text = await self.interviewer.run(self._ctx(doc, "closing", last_answer_summary=note))
        self._turn(sid, "interviewer", "closing", text, None)
        session.state = "done"
        self._save(sid, doc)
        self.db.commit()
        return TurnResult("closing", text, True, self._progress(doc), ev, None)

    def _log_follow_up(self, session, seed: PoolItem, thread: list[ThreadTurn], ev: Evaluation, reply: str) -> None:
        """Append the follow-up to data/followup_train.jsonl (training data for LoRA v2)."""
        line = {
            "profile": session.profile, "level": session.level, "company": session.company,
            "topic": seed.topic, "question": seed.text,
            "thread": [{"role": t.role, "text": t.text} for t in thread],
            "satisfaction": ev.satisfaction, "missing_points": ev.missing_points,
            "follow_up_focus": ev.follow_up_focus, "follow_up": reply,
        }
        path = self.train_log or _train_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(line) + "\n")
