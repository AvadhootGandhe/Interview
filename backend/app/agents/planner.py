"""Planner: context pack -> 4-6 ordered interview segments, validated against the pool.

The model proposes the plan; code checks it (ids exist, no repeats, warm-up first, gentle
difficulty ramp, topic focus). Invalid output is retried once, then replaced by a
deterministic fallback plan that always validates.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from statistics import mean

from pydantic import BaseModel, Field

from app.agents.base import complete_validated
from app.services.context_pack import ContextPack
from app.services.retriever import Filters, PoolItem, level_difficulty

log = logging.getLogger(__name__)

PROMPT = (Path(__file__).parents[1] / "prompts" / "planner.md").read_text()
MAX_SEGMENTS = 6
MAX_JUMP = 2
TOPIC_SHARE = 0.6


class Segment(BaseModel):
    theme: str
    topic: str
    difficulty: int = Field(ge=1, le=5)
    seed_question_id: str
    link_from_previous: str = ""
    bridge: str = ""  # set by the flow controller when the candidate's answer redirects the plan


class InterviewPlan(BaseModel):
    segments: list[Segment]


class PlanInvalid(Exception):
    """No plan can be made (for example, the pool is empty)."""


def segment_bounds(pool_size: int) -> tuple[int, int]:
    """4-6 segments; fewer only when the pool itself has fewer than 4 questions."""
    if pool_size >= 4:
        return 4, MAX_SEGMENTS
    return max(1, pool_size), max(1, pool_size)


def _same(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def _topic_needed(n: int, pool: list[PoolItem], topic: str | None) -> int:
    """Segments that must be on the chosen topic: 60%, or all the pool can offer."""
    if not topic:
        return 0
    available = sum(1 for p in pool if _same(p.topic, topic))
    return min(math.ceil(n * TOPIC_SHARE), available)


def validate_plan(plan: InterviewPlan, pool: list[PoolItem], filters: Filters) -> list[str]:
    """Human-readable problems; an empty list means the plan is valid."""
    errors: list[str] = []
    segs = plan.segments
    by_id = {p.id: p for p in pool}
    lo, hi = segment_bounds(len(pool))
    if not lo <= len(segs) <= hi:
        errors.append(f"need {lo}-{hi} segments, got {len(segs)}")

    seen: set[str] = set()
    for i, s in enumerate(segs, 1):
        if s.seed_question_id not in by_id:
            errors.append(f"segment {i}: seed_question_id {s.seed_question_id!r} is not in the pool")
        if s.seed_question_id in seen:
            errors.append(f"segment {i}: repeats question {s.seed_question_id!r}")
        seen.add(s.seed_question_id)

    baseline = level_difficulty(filters.level)
    if segs and segs[0].difficulty > baseline:
        errors.append(f"segment 1 must be a warm-up: difficulty {segs[0].difficulty} is above {baseline}")
    for i, (a, b) in enumerate(zip(segs, segs[1:]), 2):
        if abs(b.difficulty - a.difficulty) > MAX_JUMP:
            errors.append(f"segment {i}: difficulty jump {a.difficulty} -> {b.difficulty} is more than {MAX_JUMP}")

    need = _topic_needed(len(segs), pool, filters.topic)
    if need:
        on_topic = sum(1 for s in segs if s.seed_question_id in by_id and _same(by_id[s.seed_question_id].topic, filters.topic))
        if on_topic < need:
            errors.append(f"topic {filters.topic!r}: {on_topic} segments on it, need at least {need}")
    return errors


# --- deterministic fallback ---------------------------------------------------

def _spread(items: list[PoolItem], m: int) -> list[PoolItem]:
    """m items evenly spaced through a difficulty-sorted list (keeps the ramp)."""
    if m <= 0:
        return []
    if m >= len(items):
        return list(items)
    if m == 1:
        return [items[0]]
    return [items[round(i * (len(items) - 1) / (m - 1))] for i in range(m)]


def fallback_plan(pool: list[PoolItem], filters: Filters) -> InterviewPlan:
    """Pool sorted by topic group, then difficulty. Valid for any non-empty pool."""
    if not pool:
        raise PlanInvalid("the question pool is empty")
    n = min(5, len(pool)) if len(pool) >= 4 else len(pool)

    groups: dict[str, list[PoolItem]] = {}
    for p in sorted(pool, key=lambda p: (p.difficulty, p.id)):
        groups.setdefault(p.topic, []).append(p)
    order = sorted(groups, key=lambda t: (not _same(t, filters.topic), -len(groups[t]), t))

    picked: dict[str, list[PoolItem]] = {t: [] for t in order}
    taken: set[str] = set()

    def take(topic: str, m: int) -> None:
        rest = [p for p in groups[topic] if p.id not in taken]
        for p in _spread(rest, m):
            picked[topic].append(p)
            taken.add(p.id)

    total = lambda: len(taken)  # noqa: E731
    if filters.topic:
        first = next((t for t in order if _same(t, filters.topic)), None)
        if first:
            take(first, _topic_needed(n, pool, filters.topic))
    for cap in (2, n):  # first spread across topics, then fill from whatever is left
        for t in order:
            if total() >= n:
                break
            take(t, min(cap - len(picked[t]), n - total()))

    ordered = sorted(
        (t for t in order if picked[t]),
        key=lambda t: (not _same(t, filters.topic), mean(p.difficulty for p in picked[t])),
    )
    items = [p for t in ordered for p in sorted(picked[t], key=lambda p: (p.difficulty, p.id))]

    # The segment difficulty is the plan's own target: warm-up first, then a gentle ramp.
    difficulties: list[int] = []
    for i, p in enumerate(items):
        d = p.difficulty
        if i == 0:
            d = min(d, level_difficulty(filters.level))
        else:
            d = max(difficulties[-1] - MAX_JUMP, min(difficulties[-1] + MAX_JUMP, d))
        difficulties.append(max(1, min(5, d)))

    segments = []
    for i, (p, d) in enumerate(zip(items, difficulties)):
        if i == 0:
            link = ""
        elif p.topic != items[i - 1].topic:
            link = f"moves on from {items[i - 1].topic} to {p.topic}"
        else:
            link = f"goes deeper into {p.topic}"
        segments.append(Segment(theme=p.topic, topic=p.topic, difficulty=d, seed_question_id=p.id,
                                link_from_previous=link))
    return InterviewPlan(segments=segments)


# --- the agent ------------------------------------------------------------------

class Planner:
    def __init__(self, llm) -> None:
        self.llm = llm
        self.used_fallback = False

    async def run(self, pack: ContextPack) -> InterviewPlan:
        return await self.plan_for(
            pack.pool, pack.filters, context=pack.to_json(), expectations=pack.level_expectations
        )

    async def plan_for(
        self, pool: list[PoolItem], filters: Filters, context: str | None = None, expectations: str = ""
    ) -> InterviewPlan:
        if not pool:
            raise PlanInvalid("the question pool is empty")
        self.used_fallback = False
        lo, hi = segment_bounds(len(pool))
        target = min(5, hi) if len(pool) >= 4 else len(pool)
        if context is None:
            context = '{"pool":[' + ",".join(p_json(p) for p in pool) + "]}"
        topic_rule = (
            f"At least 60% of the segments must use the topic {filters.topic!r}; the others must be closely related topics."
            if filters.topic else "Cover several related topics; do not spend more than half the plan on one topic."
        )
        prompt = (
            PROMPT.replace("__EXPECTATIONS__", expectations or "Any level.")
            .replace("__TARGET__", str(target)).replace("__MIN__", str(lo))
            .replace("__BASELINE__", str(level_difficulty(filters.level)))
            .replace("__TOPIC_RULE__", topic_rule).replace("__CONTEXT__", context)
        )
        try:
            plan = await complete_validated(
                self.llm, prompt, InterviewPlan, task="planner",
                check=lambda p: validate_plan(p, pool, filters),
            )
        except Exception as exc:  # AgentOutputError after the retry, or any LLM transport error  # a bad or missing plan must never block an interview
            log.warning("planner fell back to the deterministic plan: %s", exc)
            self.used_fallback = True
            return fallback_plan(pool, filters)
        by_id = {p.id: p for p in pool}
        for s in plan.segments:  # the pool is the source of truth for topics
            s.topic = by_id[s.seed_question_id].topic
        return plan


def p_json(p: PoolItem) -> str:
    import json

    return json.dumps(p.to_dict(), separators=(",", ":"))
