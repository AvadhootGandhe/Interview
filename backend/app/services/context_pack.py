from collections import Counter
from dataclasses import dataclass, field, replace

from sqlalchemy.engine import Engine

from app.agents.question_generator import GeneratorUnavailable
from app.config import settings
from app.services.company_profile import CompanyProfileData, get_company_profile
from app.services.levels import LEVEL_RANK, level_expectations
from app.services.retriever import Filters, PoolItem, build_pool


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


@dataclass
class ContextPack:
    filters: Filters
    company_profile: CompanyProfileData
    level_expectations: str
    pool: list[PoolItem] = field(default_factory=list)

    def to_prompt(self) -> str:
        f = self.filters
        lines = [f"Candidate: {f.profile}" + (f", {f.level}" if f.level else "")]
        if f.company:
            lines.append(f"Company: {f.company}")
        if self.company_profile.summary:
            lines.append(f"Company focus: {self.company_profile.summary}")
        if self.company_profile.topic_mix:
            mix = ", ".join(f"{t} {p}%" for t, p in list(self.company_profile.topic_mix.items())[:8])
            lines.append(f"Topic mix: {mix}")
        lines.append(f"Level expectations: {self.level_expectations}")
        lines.append("Question pool (id | topic | difficulty | source | text):")
        lines += [f"{p.id} | {p.topic} | {p.difficulty} | {p.source} | {p.text}" for p in self.pool]
        return "\n".join(lines)


async def _generate(generator, f: Filters, pool: list[PoolItem], n: int) -> list[PoolItem]:
    if n <= 0 or not f.level:
        return []
    topics = [f.topic] if f.topic else [t for t, _ in Counter(p.topic for p in pool).most_common(n)]
    asked = [p.text for p in pool]
    out: list[PoolItem] = []
    for topic in topics[:n]:
        try:
            q = await generator.generate(f.profile, f.level, topic, asked=asked)
        except GeneratorUnavailable:
            return out
        asked.append(q)
        out.append(PoolItem(-(len(out) + 1), topic, q, "generated", LEVEL_RANK.get(f.level, 3)))
    return out


async def build_context_pack(engine: Engine, llm, generator, filters: Filters, *, seed: int | None = None,
                             exclude_ids=frozenset(), size: int | None = None,
                             max_tokens: int | None = None) -> ContextPack:
    size = size or settings.pool_size
    max_tokens = max_tokens or settings.max_context_tokens
    pool = build_pool(engine, filters, size=size, seed=seed, exclude_ids=exclude_ids)
    profile = await get_company_profile(engine, llm, filters.company, filters.profile, filters.level)
    pack = ContextPack(filters, profile, level_expectations(filters.level),
                       pool + await _generate(generator, filters, pool, settings.generated_per_pack))
    while pack.pool and estimate_tokens(pack.to_prompt()) > max_tokens:
        pack.pool.pop()
    return pack
