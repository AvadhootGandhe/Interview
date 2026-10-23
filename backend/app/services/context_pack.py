"""Context pack: what the planner and interviewer know before the interview starts.

company profile + level expectations + question pool (dataset + fine-tuned generated),
kept under MAX_CONTEXT_TOKENS by trimming the least specific pool items first.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Protocol

from sqlalchemy.orm import Session

from app.agents.question_generator import GeneratorUnavailable, InvalidGeneration
from app.config import settings
from app.services.company_profile import LLM, CompanyProfile, CompanyProfileService
from app.services.retriever import Filters, PoolItem, Retriever, level_difficulty

LEVEL_EXPECTATIONS = {
    "Fresher": "Fresher: solid fundamentals and clear definitions; simple examples; no production experience expected.",
    "SDE-1": "SDE-1: correct fundamentals applied to small features; basic debugging and testing; guided design.",
    "SDE-1/2": "SDE-1/2: owns features end to end; explains trade-offs; handles common failure modes.",
    "SDE-2/3": "SDE-2/3: designs services; reasons about scale, reliability and cost; real production stories.",
    "Architect/Principal": (
        "Architect/Principal: system-wide design and trade-offs across teams; long-term strategy, "
        "risk and cost; influences without authority."
    ),
}
DEFAULT_EXPECTATIONS = "Any level: check fundamentals first, then go as deep as the answers allow."


class Generator(Protocol):
    async def generate(self, profile: str, level: str, topic: str, already_asked: list[str] | None = None) -> str: ...


def estimate_tokens(text: str) -> int:
    """Rough token count: about 4 characters per token."""
    return math.ceil(len(text) / 4)


@dataclass
class ContextPack:
    filters: Filters
    company_profile: CompanyProfile
    level_expectations: str
    pool: list[PoolItem] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps({
            "filters": asdict(self.filters),
            "company_profile": self.company_profile.to_dict(),
            "level_expectations": self.level_expectations,
            "pool": [p.to_dict() for p in self.pool],
        }, separators=(",", ":"))

    def trim(self, max_tokens: int) -> None:
        """Drop pool items until the pack fits: last dataset items first, generated ones last."""
        while self.pool and estimate_tokens(self.to_json()) > max_tokens:
            dataset = [i for i, p in enumerate(self.pool) if p.source == "dataset"]
            self.pool.pop(dataset[-1] if dataset else -1)


async def _generated_items(generator: Generator | None, filters: Filters, pool: list[PoolItem]) -> list[PoolItem]:
    if generator is None or not (filters.profile and filters.level):
        return []
    n = settings.generated_per_pack
    if filters.topic:
        topics = [filters.topic] * n
    else:
        topics = [t for t, _ in Counter(p.topic for p in pool).most_common(n)]
    asked = [p.text for p in pool]
    items: list[PoolItem] = []
    for topic in topics:
        try:
            text = await generator.generate(filters.profile, filters.level, topic, already_asked=asked)
        except GeneratorUnavailable:
            break  # server is down: the pack stays dataset-only
        except InvalidGeneration:
            continue
        asked.append(text)
        items.append(PoolItem(
            id=f"gen-{len(items) + 1}", topic=topic, text=text, source="generated",
            difficulty=level_difficulty(filters.level), match="generated",
        ))
    return items


async def build_context_pack(
    db: Session,
    filters: Filters,
    llm: LLM | None,
    generator: Generator | None = None,
    user_id: str | None = None,
    max_tokens: int | None = None,
) -> ContextPack:
    pool = Retriever(db).build_pool(filters, user_id=user_id)
    profile = await CompanyProfileService(db, llm).get(filters.company, filters.profile, filters.level)
    pack = ContextPack(
        filters=filters,
        company_profile=profile,
        level_expectations=LEVEL_EXPECTATIONS.get(filters.level or "", DEFAULT_EXPECTATIONS),
        pool=pool + await _generated_items(generator, filters, pool),
    )
    pack.trim(max_tokens or settings.max_context_tokens)
    return pack
