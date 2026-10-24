"""Small builders shared by the Phase 3 tests."""
from __future__ import annotations

import json

from app.agents.schemas import Evaluation, InterviewPlan, Segment
from app.services.company_profile import CompanyProfile
from app.services.context_pack import ContextPack
from app.services.retriever import Filters, PoolItem


def item(id: str, topic: str = "Caching", difficulty: int = 3, text: str | None = None,
         source: str = "dataset") -> PoolItem:
    return PoolItem(id=id, topic=topic, text=text or f"Question {id} about {topic}?",
                    source=source, difficulty=difficulty)


def standard_pool() -> list[PoolItem]:
    return [
        item("c1", "Caching", 2, "What is a cache and why would you use one?"),
        item("c2", "Caching", 3, "How does LRU eviction work in a cache?"),
        item("c3", "Caching", 5, "Design a globally distributed cache with strong consistency."),
        item("m1", "Messaging", 2, "What is a message queue and when do you need one?"),
        item("m2", "Messaging", 4, "How do you guarantee exactly-once delivery with Kafka?"),
        item("r0", "Databases", 1, "What is a database index?"),
        item("r1", "Databases", 3, "How would you shard a relational database?"),
        item("r2", "Databases", 4, "Explain Redis persistence options, RDB and AOF."),
        item("a1", "API Design", 2, "What makes a REST API idempotent?"),
        item("a2", "API Design", 4, "How would you version a public API without breaking clients?"),
    ]


def segment(it: PoolItem, difficulty: int | None = None, link: str = "") -> Segment:
    return Segment(theme=f"{it.topic} basics", topic=it.topic, difficulty=difficulty or it.difficulty,
                   seed_question_id=it.id, link_from_previous=link)


def plan_of(pool: list[PoolItem], ids: list[str], difficulties: list[int] | None = None) -> InterviewPlan:
    by_id = {p.id: p for p in pool}
    ds = difficulties or [by_id[i].difficulty for i in ids]
    return InterviewPlan(segments=[segment(by_id[i], d) for i, d in zip(ids, ds)])


def pack_of(pool: list[PoolItem], level: str = "SDE-2/3", topic: str | None = None,
            company: str | None = None) -> ContextPack:
    return ContextPack(
        filters=Filters(profile="Backend", level=level, company=company, topic=topic),
        company_profile=CompanyProfile(company or "General", company is None, "Asks practical scenario questions."),
        level_expectations="Designs services; reasons about scale.",
        pool=pool,
    )


def eval_json(satisfaction: int, missing: list[str] | None = None, terms: list[str] | None = None,
              focus: str | None = None) -> str:
    missing = ["failure handling"] if missing is None else missing
    return json.dumps({
        "satisfaction": satisfaction,
        "scores": {"correctness": satisfaction, "depth": satisfaction, "clarity": satisfaction,
                   "communication": satisfaction},
        "covered_points": ["core idea"],
        "missing_points": missing,
        "follow_up_focus": focus if focus is not None else (missing[0] if missing else ""),
        "mentioned_terms": terms or [],
        "red_flags": [],
    })


def evaluation(satisfaction: int, terms: list[str] | None = None) -> Evaluation:
    return Evaluation.model_validate_json(eval_json(satisfaction, terms=terms))
