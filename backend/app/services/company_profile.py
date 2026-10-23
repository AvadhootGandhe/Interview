"""Company profile: topic mix (SQL) + a 3-4 line focus/style summary (LLM, cached in the DB)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Company, CompanyProfile as CompanyProfileRow, Question, QuestionMap, Topic
from app.services.retriever import Filters, company_id, resolve

PROMPT = (Path(__file__).parents[1] / "prompts" / "company_profile.md").read_text()
NEUTRAL_SUMMARY = (
    "No specific company. Ask like a calm, fair senior engineer at a typical tech company: "
    "clear fundamentals first, then practical scenarios and trade-offs."
)


class LLM(Protocol):
    async def complete(self, prompt: str, **kwargs) -> str: ...


@dataclass
class CompanyProfile:
    company: str
    is_general: bool
    summary: str
    topic_mix: list[dict] = field(default_factory=list)  # [{topic, count, percent}]

    def to_dict(self) -> dict:
        return asdict(self)


def _percentages(counts: list[int]) -> list[float]:
    """One-decimal percentages that add up to exactly 100 (largest remainder)."""
    total = sum(counts)
    if not total:
        return []
    raw = [c * 1000 / total for c in counts]  # in tenths of a percent
    tenths = [int(r) for r in raw]
    by_remainder = sorted(range(len(raw)), key=lambda i: raw[i] - tenths[i], reverse=True)
    for i in by_remainder[: 1000 - sum(tenths)]:
        tenths[i] += 1
    return [t / 10 for t in tenths]


class CompanyProfileService:
    def __init__(self, db: Session, llm: LLM | None) -> None:
        self.db = db
        self.llm = llm

    def _where(self, company: str, profile: str | None, level: str | None) -> list:
        ids = resolve(self.db, Filters(profile=profile, level=level))
        conds = [QuestionMap.company_id == company_id(self.db, company)]
        if ids["profile"]:
            conds.append(QuestionMap.profile_id == ids["profile"])
        if ids["level"]:
            conds.append(QuestionMap.level_id == ids["level"])
        return conds

    def topic_mix(self, company: str, profile: str | None = None, level: str | None = None) -> list[dict]:
        count = func.count(func.distinct(QuestionMap.question_id))
        rows = self.db.execute(
            select(Topic.name, count)
            .join(QuestionMap, QuestionMap.topic_id == Topic.id)
            .where(*self._where(company, profile, level))
            .group_by(Topic.name)
            .order_by(count.desc(), Topic.name)
        ).all()
        percents = _percentages([c for _, c in rows])
        return [{"topic": t, "count": c, "percent": p} for (t, c), p in zip(rows, percents)]

    async def get(
        self, company: str | None, profile: str | None = None, level: str | None = None
    ) -> CompanyProfile:
        cid = company_id(self.db, company)
        if cid is None:
            return CompanyProfile(company="General", is_general=True, summary=NEUTRAL_SUMMARY)
        name = self.db.get(Company, cid).name
        ids = resolve(self.db, Filters(profile=profile, level=level))
        key = [
            CompanyProfileRow.company_id == cid,
            CompanyProfileRow.profile_id == ids["profile"],
            CompanyProfileRow.level_id == ids["level"],
        ]
        cached = self.db.scalar(select(CompanyProfileRow).where(*key))
        if cached:
            return CompanyProfile(name, False, cached.summary, json.loads(cached.topic_mix_json))

        mix = self.topic_mix(name, profile, level)
        try:
            summary = await self._summarize(name, profile, level, mix)
        except Exception:  # the profile is optional context; never block an interview on it
            top = ", ".join(m["topic"] for m in mix[:3])
            return CompanyProfile(name, False, f"{name} questions focus on {top}.", mix)
        self.db.add(CompanyProfileRow(
            company_id=cid, profile_id=ids["profile"], level_id=ids["level"],
            topic_mix_json=json.dumps(mix), summary=summary,
        ))
        self.db.commit()
        return CompanyProfile(name, False, summary, mix)

    async def _summarize(self, company: str, profile: str | None, level: str | None, mix: list[dict]) -> str:
        questions = self.db.scalars(
            select(Question.text)
            .join(QuestionMap, QuestionMap.question_id == Question.id)
            .where(*self._where(company, profile, level))
            .group_by(Question.id)
            .order_by(func.random())
            .limit(settings.profile_sample_questions)
        )
        scope = " ".join(x for x in (level, profile) if x)
        prompt = PROMPT.format(
            company=company,
            scope=f" for {scope} roles" if scope else "",
            topic_mix="\n".join(f"- {m['topic']}: {m['percent']}%" for m in mix[:15]),
            questions="\n".join(f"- {q}" for q in questions),
        )
        raw = await self.llm.complete(prompt, max_tokens=settings.profile_summary_max_tokens)
        lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]
        if not lines:
            raise ValueError("empty summary")
        return "\n".join(lines[:4])
