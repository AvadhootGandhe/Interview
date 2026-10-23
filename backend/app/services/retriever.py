"""Retriever: SQLite filters + FTS5 -> a question pool for the planner and flow controller.

Widening order when the filters are too narrow (each stage only adds questions):
    exact         the chosen company, profile, level and topic
    drop_company  the same filters at any other real company
    general       the same filters in the General bucket
    drop_level    any company, any level (same profile and topic)
    drop_topic    any company, same profile and level, any topic
    profile_only  any company, level and topic of the profile
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass

from sqlalchemy import case, func, literal, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Company, InterviewSession, Level, Profile, Question, QuestionMap, Topic, Turn
from app.db.names import GENERAL, canonical_company

STAGES = ("exact", "drop_company", "general", "drop_level", "drop_topic", "profile_only")

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "for", "from", "how", "i", "in", "is",
    "it", "of", "on", "or", "that", "the", "this", "to", "was", "what", "when", "why", "with", "you",
}


@dataclass
class Filters:
    profile: str | None = None
    level: str | None = None
    company: str | None = None
    topic: str | None = None


@dataclass
class PoolItem:
    id: str
    topic: str
    text: str
    source: str = "dataset"  # dataset | generated
    difficulty: int = 3  # 1 (Fresher) .. 5 (Architect/Principal)
    company_specific: bool = False
    match: str = ""  # widening stage that found it

    def to_dict(self) -> dict:
        d = asdict(self)
        del d["company_specific"], d["match"]
        return d


def level_difficulty(level: str | None) -> int:
    return settings.level_difficulty.get(level or "", 3)


def fts_query(terms: str | list[str]) -> str | None:
    """Turn free text into a safe FTS5 OR-query of quoted words, or None if nothing is left."""
    if isinstance(terms, str):
        terms = [terms]
    words: list[str] = []
    for term in terms:
        for w in re.findall(r"[a-z0-9]+", term.lower()):
            if len(w) > 1 and w not in STOP_WORDS and w not in words:
                words.append(w)
    return " OR ".join(f'"{w}"' for w in words) or None


class Retriever:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- public API ----------------------------------------------------------

    def build_pool(
        self, filters: Filters, user_id: str | None = None, size: int | None = None
    ) -> list[PoolItem]:
        size = size or settings.pool_size
        ids = self._resolve(filters)
        recent = self._recent_question_ids(user_id)
        pool = self._fill(ids, recent, size)
        if not pool and recent:  # never empty: repeating beats asking nothing
            pool = self._fill(ids, set(), size)
        return pool

    def search(self, terms: str | list[str], pool: list[PoolItem]) -> list[PoolItem]:
        """Pool items whose text matches any of the terms, best (bm25) first."""
        query = fts_query(terms)
        if not query or not pool:
            return []
        by_id = {p.id: p for p in pool}
        rows = self.db.execute(
            text("SELECT question_id FROM questions_fts WHERE questions_fts MATCH :q "
                 "ORDER BY bm25(questions_fts)"),
            {"q": query},
        ).scalars()
        return [by_id[qid] for qid in rows if qid in by_id]

    # --- internals -----------------------------------------------------------

    def _id(self, model, name: str | None) -> int | None:
        if not name:
            return None
        found = self.db.scalar(select(model.id).where(func.lower(model.name) == name.strip().lower()))
        if found is None:
            raise ValueError(f"unknown {model.__tablename__[:-1]}: {name!r}")
        return found

    def _resolve(self, f: Filters) -> dict[str, int | None]:
        company_id = None
        if f.company and canonical_company(f.company) != GENERAL:
            company_id = self.db.scalar(
                select(Company.id).where(
                    func.lower(Company.name) == canonical_company(f.company).lower(),
                    Company.is_general.is_(False),
                )
            )  # an unknown company simply means "no company"
        return {
            "company": company_id,
            "profile": self._id(Profile, f.profile),
            "level": self._id(Level, f.level),
            "topic": self._id(Topic, f.topic),
        }

    def _recent_question_ids(self, user_id: str | None) -> set[str]:
        if not user_id:
            return set()
        recent = (
            select(InterviewSession.id)
            .where(InterviewSession.user_id == user_id)
            .order_by(InterviewSession.created_at.desc())
            .limit(settings.recent_sessions_excluded)
        )
        rows = self.db.scalars(
            select(Turn.question_id).where(Turn.session_id.in_(recent), Turn.question_id.is_not(None))
        )
        return set(rows)

    def _conditions(self, stage: str, ids: dict) -> list | None:
        """WHERE clauses for one stage, or None when the stage adds nothing new."""
        company, level, topic = ids["company"], ids["level"], ids["topic"]
        conds = [QuestionMap.profile_id == ids["profile"]] if ids["profile"] else []
        if stage in ("exact", "drop_company", "general", "drop_level") and topic:
            conds.append(QuestionMap.topic_id == topic)
        else:  # no topic chosen (or dropped): technical screening only
            conds.append(Topic.category != "behavioral")
        if stage in ("exact", "drop_company", "general", "drop_topic") and level:
            conds.append(QuestionMap.level_id == level)

        if stage == "exact":
            return conds + [QuestionMap.company_id == company] if company else None
        if stage == "drop_company":
            return conds + [Company.is_general.is_(False), QuestionMap.company_id != (company or -1)]
        if stage == "general":
            return conds + [Company.is_general.is_(True)]
        if stage == "drop_level":
            return conds if level else None
        if stage == "drop_topic":
            return conds if topic else None
        return conds if (level or topic) else None  # profile_only

    def _candidates(self, stage: str, ids: dict, size: int) -> list[PoolItem]:
        conds = self._conditions(stage, ids)
        if conds is None:
            return []
        company = ids["company"]
        is_company = func.max(case((QuestionMap.company_id == company, 1), else_=0)) if company else literal(0)
        stmt = (
            select(Question.id, Question.text, func.min(Topic.name), func.min(Level.rank), is_company)
            .join(QuestionMap, QuestionMap.question_id == Question.id)
            .join(Topic, Topic.id == QuestionMap.topic_id)
            .join(Level, Level.id == QuestionMap.level_id)
            .join(Company, Company.id == QuestionMap.company_id)
            .where(*conds)
            .group_by(Question.id)
            .order_by(func.random())
            .limit(max(settings.retriever_candidates_per_stage, 3 * size))
        )
        return [
            PoolItem(id=qid, topic=topic, text=txt, difficulty=rank, company_specific=bool(own), match=stage)
            for qid, txt, topic, rank, own in self.db.execute(stmt)
        ]

    def _fill(self, ids: dict, exclude: set[str], size: int) -> list[PoolItem]:
        pool: list[PoolItem] = []
        seen = set(exclude)
        per_topic: Counter[str] = Counter()
        limit = size
        for stage in STAGES:
            cap = limit if ids["topic"] else max(1, int(settings.topic_max_share * limit))
            for item in _round_robin(self._candidates(stage, ids, size)):
                if len(pool) >= limit:
                    return pool
                if item.id in seen or per_topic[item.topic] >= cap:
                    continue
                seen.add(item.id)
                per_topic[item.topic] += 1
                pool.append(item)
            if stage == "exact" and len(pool) >= settings.company_min_items:
                # G10: a company with real matches keeps >= 70% company-specific questions.
                limit = min(size, int(len(pool) / settings.company_min_share))
        return pool


def _round_robin(items: list[PoolItem]) -> list[PoolItem]:
    """Interleave topics so a capped pool still covers several of them."""
    groups: dict[str, list[PoolItem]] = defaultdict(list)
    for item in items:
        groups[item.topic].append(item)
    out: list[PoolItem] = []
    while groups:
        for topic in list(groups):
            out.append(groups[topic].pop(0))
            if not groups[topic]:
                del groups[topic]
    return out
