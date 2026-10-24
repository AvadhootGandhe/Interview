"""DB-backed interview state machine: retrieve -> plan -> ask -> evaluate -> follow-up/flow -> close.

No in-memory session state: every call loads the session from the database, so a fresh instance
can continue any interview.
"""
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.agents.evaluator import Evaluation, evaluate
from app.agents.interviewer import Interviewer
from app.agents.planner import InterviewPlan, plan_interview
from app.config import settings
from app.db import models as m
from app.services.context_pack import build_context_pack
from app.services.flow import adjust_plan
from app.services.retriever import Filters, PoolItem, search

STYLE_EXAMPLES = 3


@dataclass
class Reply:
    messages: list[str]
    kind: str  # greeting | ask | follow_up | closing
    state: str  # active | done
    evaluation: Evaluation | None = None


@dataclass
class Started:
    session_id: str
    messages: list[str]


class Orchestrator:
    def __init__(self, engine: Engine, llm, generator, *, followup_log: Path | None = None,
                 threshold: int | None = None, max_followups: int | None = None,
                 penalty: int | None = None, num_questions: int | None = None):
        self.engine, self.llm, self.generator = engine, llm, generator
        self.interviewer = Interviewer(llm)
        self.followup_log = followup_log
        self.threshold = threshold if threshold is not None else settings.satisfaction_threshold
        self.max_followups = max_followups if max_followups is not None else settings.max_followups
        self.penalty = penalty if penalty is not None else settings.followup_penalty
        self.num_questions = num_questions or settings.num_questions

    # ---- start -------------------------------------------------------------------------------
    async def start(self, filters: Filters, seed: int | None = None) -> Started:
        pack = await build_context_pack(self.engine, self.llm, self.generator, filters, seed=seed)
        plan = await plan_interview(self.llm, pack, self.num_questions)
        sid = uuid.uuid4().hex
        company = filters.company
        greeting = await self.interviewer.greeting(filters.profile, filters.level or "", company)
        with Session(self.engine) as db:
            db.add(m.InterviewSession(
                id=sid, profile=filters.profile, level=filters.level, company=company, topic=filters.topic,
                pool_json=json.dumps([asdict(p) for p in pack.pool]),
                company_summary=pack.company_profile.summary))
            db.add(m.Plan(session_id=sid, version=1, plan_json=plan.model_dump_json()))
            db.add(m.Turn(session_id=sid, segment_index=0, kind="greeting", role="interviewer", text=greeting))
            db.commit()
            first = await self._ask(db, sid, 0, last_summary="")
            db.commit()
        return Started(sid, [greeting, first])

    # ---- answer ------------------------------------------------------------------------------
    async def answer(self, session_id: str, text: str) -> Reply:
        with Session(self.engine) as db:
            s = self._active(db, session_id)
            idx = s.current_index
            db.add(m.Turn(session_id=s.id, segment_index=idx, kind="answer", role="candidate", text=text))
            db.flush()
            thread = self._thread(db, s.id, idx)
            ev = await evaluate(self.llm, s.profile, s.level or "", thread)
            attempt = s.followups_used + 1

            if ev.satisfaction < self.threshold and s.followups_used < self.max_followups:
                question, answer = thread[-1]
                focus = ev.follow_up_focus or ", ".join(ev.missing_points)
                spoken = await self.interviewer.follow_up(
                    self._seed_text(db, s, idx), answer, focus, ev.missing_points, s.company)
                db.add(m.Evaluation(session_id=s.id, segment_index=idx, attempt=attempt,
                                    satisfaction=ev.satisfaction, data_json=ev.model_dump_json()))
                db.add(m.Turn(session_id=s.id, segment_index=idx, kind="follow_up", role="interviewer",
                              text=spoken))
                s.followups_used += 1
                self._log_followup(s, question, answer, focus, ev, spoken)
                db.commit()
                return Reply([spoken], "follow_up", "active", ev)

            final = max(0, ev.satisfaction - self.penalty * s.followups_used)
            db.add(m.Evaluation(session_id=s.id, segment_index=idx, attempt=attempt,
                                satisfaction=ev.satisfaction, final_score=final, data_json=ev.model_dump_json()))
            plan = self._plan(db, s.id)
            terms = self._mentioned_terms(db, s.id, idx)
            s.followups_used = 0

            if idx + 1 >= len(plan.segments):
                reply = await self._close(db, s, ev)
                db.commit()
                return reply

            pool = self._pool(s)
            asked = {seg.seed_question_id for seg in plan.segments[: idx + 1]}
            new_plan, bridge = adjust_plan(plan, idx, final, terms, pool, asked,
                                           lambda q, p: search(self.engine, q, p))
            if new_plan != plan:
                version = len(db.scalars(select(m.Plan).where(m.Plan.session_id == s.id)).all()) + 1
                db.add(m.Plan(session_id=s.id, version=version, plan_json=new_plan.model_dump_json(),
                              bridge=bridge))
            s.current_index = idx + 1
            db.flush()
            summary = "; ".join(ev.covered_points[:2]) or text[:120]
            spoken = await self._ask(db, s.id, idx + 1, last_summary=summary)
            db.commit()
            return Reply([spoken], "ask", "active", ev)

    async def end(self, session_id: str) -> Reply:
        with Session(self.engine) as db:
            s = self._active(db, session_id)
            reply = await self._close(db, s, None)
            db.commit()
            return reply

    # ---- helpers -----------------------------------------------------------------------------
    @staticmethod
    def _active(db: Session, session_id: str) -> m.InterviewSession:
        s = db.get(m.InterviewSession, session_id)
        if s is None:
            raise KeyError(session_id)
        if s.state != "active":
            raise ValueError("interview is already finished")
        return s

    @staticmethod
    def _plan(db: Session, session_id: str) -> InterviewPlan:
        row = db.scalars(select(m.Plan).where(m.Plan.session_id == session_id)
                         .order_by(m.Plan.version.desc())).first()
        return InterviewPlan.model_validate_json(row.plan_json)

    @staticmethod
    def _pool(s: m.InterviewSession) -> list[PoolItem]:
        return [PoolItem(**p) for p in json.loads(s.pool_json)]

    def _seed_text(self, db: Session, s: m.InterviewSession, idx: int) -> str:
        seg = self._plan(db, s.id).segments[idx]
        return next(p.text for p in self._pool(s) if p.id == seg.seed_question_id)

    @staticmethod
    def _thread(db: Session, session_id: str, idx: int) -> list[tuple[str, str]]:
        """[(interviewer question, candidate answer)] for the current segment, in order."""
        turns = db.scalars(select(m.Turn).where(m.Turn.session_id == session_id, m.Turn.segment_index == idx)
                           .order_by(m.Turn.id)).all()
        pairs: list[tuple[str, str]] = []
        question = ""
        for t in turns:
            if t.role == "interviewer" and t.kind in ("ask", "follow_up"):
                question = t.text
            elif t.role == "candidate":
                pairs.append((question, t.text))
        return pairs

    @staticmethod
    def _mentioned_terms(db: Session, session_id: str, idx: int) -> list[str]:
        rows = db.scalars(select(m.Evaluation).where(m.Evaluation.session_id == session_id,
                                                     m.Evaluation.segment_index == idx)).all()
        terms: list[str] = []
        for r in rows:
            terms += [t for t in json.loads(r.data_json).get("mentioned_terms", []) if t not in terms]
        return terms

    async def _ask(self, db: Session, session_id: str, idx: int, last_summary: str) -> str:
        s = db.get(m.InterviewSession, session_id)
        plan, pool = self._plan(db, session_id), self._pool(s)
        seg = plan.segments[idx]
        seed = next(p for p in pool if p.id == seg.seed_question_id)
        used = {x.seed_question_id for x in plan.segments}
        examples = [p.text for p in search(self.engine, seed.text, [p for p in pool if p.id != seed.id])]
        examples = (examples + [p.text for p in pool if p.topic == seed.topic and p.id not in used])[:STYLE_EXAMPLES]
        spoken = await self.interviewer.ask(seg, seed.text, examples, s.company_summary, last_summary, s.company)
        db.add(m.Turn(session_id=session_id, segment_index=idx, kind="ask", role="interviewer", text=spoken))
        return spoken

    async def _close(self, db: Session, s: m.InterviewSession, ev: Evaluation | None) -> Reply:
        spoken = await self.interviewer.closing(s.profile, s.company)
        db.add(m.Turn(session_id=s.id, segment_index=s.current_index, kind="closing", role="interviewer",
                      text=spoken))
        s.state = "done"
        return Reply([spoken], "closing", "done", ev)

    def _log_followup(self, s, question, answer, focus, ev: Evaluation, spoken) -> None:
        if not self.followup_log:
            return
        self.followup_log.parent.mkdir(parents=True, exist_ok=True)
        with self.followup_log.open("a") as f:
            f.write(json.dumps({"profile": s.profile, "level": s.level, "company": s.company,
                                "question": question, "answer": answer, "missing_points": ev.missing_points,
                                "focus": focus, "follow_up": spoken}) + "\n")
