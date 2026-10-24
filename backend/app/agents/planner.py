"""Planner: one Claude call turns the context pack into an ordered, validated InterviewPlan.

If the model output is invalid twice, a deterministic fallback plan is used. The fallback is built
from the pool alone and always passes `validate_plan`.
"""
from __future__ import annotations

import logging
import math

from app.agents.base import LLM, complete_validated, render
from app.agents.schemas import InterviewPlan, PlanDraft, Segment
from app.config import settings
from app.services.context_pack import ContextPack
from app.services.retriever import Filters, PoolItem, level_difficulty

log = logging.getLogger(__name__)
STAGES = ("Warm-up", "Core concepts", "Deeper scenario", "Stretch")


class PlanError(Exception):
    """No plan can be made (the pool is empty)."""


def segment_range(pool_size: int) -> tuple[int, int]:
    return min(settings.planner_min_segments, pool_size), min(settings.planner_max_segments, pool_size)


def _topic_need(filters: Filters, pool: list[PoolItem], n: int) -> tuple[str | None, int]:
    if not filters.topic:
        return None, 0
    topic = filters.topic.lower()
    available = sum(1 for p in pool if p.topic.lower() == topic)
    return topic, min(math.ceil(settings.topic_focus_share * n), available)


def validate_plan(plan: InterviewPlan | PlanDraft, pool: list[PoolItem], filters: Filters) -> list[str]:
    """Problems with the plan (empty list = valid)."""
    errors: list[str] = []
    by_id = {p.id: p for p in pool}
    segs = plan.segments
    lo, hi = segment_range(len(pool))
    if not lo <= len(segs) <= hi:
        errors.append(f"need {lo}-{hi} segments, got {len(segs)}")

    seen: set[str] = set()
    for s in segs:
        if s.seed_question_id not in by_id:
            errors.append(f"seed_question_id {s.seed_question_id!r} is not in the pool")
        elif s.seed_question_id in seen:
            errors.append(f"repeated question {s.seed_question_id!r}")
        seen.add(s.seed_question_id)

    baseline = level_difficulty(filters.level)
    if segs and segs[0].difficulty > baseline:
        errors.append(f"warm-up difficulty {segs[0].difficulty} is above the level baseline {baseline}")
    for a, b in zip(segs, segs[1:]):
        if abs(b.difficulty - a.difficulty) > settings.max_difficulty_jump:
            errors.append(f"difficulty jump {a.difficulty} -> {b.difficulty} is more than {settings.max_difficulty_jump}")
            break

    topic, need = _topic_need(filters, pool, len(segs))
    if topic:
        on_topic = sum(1 for s in segs if s.seed_question_id in by_id and by_id[s.seed_question_id].topic.lower() == topic)
        if on_topic < need:
            errors.append(f"only {on_topic} segments use topic {filters.topic!r}; need at least {need}")
    return errors


def _spread(items: list[PoolItem], k: int) -> list[PoolItem]:
    """k items spread evenly over the difficulty range."""
    items = sorted(items, key=lambda p: p.difficulty)
    if k >= len(items):
        return items
    if k == 1:
        return items[:1]
    picks = {round(i * (len(items) - 1) / (k - 1)) for i in range(k)}
    return [items[i] for i in sorted(picks)] if len(picks) == k else items[:k]


def fallback_plan(pool: list[PoolItem], filters: Filters) -> InterviewPlan:
    """Sort the pool by topic group, then difficulty, and pick a ramping, valid subset."""
    items = list({p.id: p for p in pool}.values())
    if not items:
        raise PlanError("the question pool is empty")
    n = min(5, len(items))
    topic, need = _topic_need(filters, items, n)

    # Few topics, so the interview stays on one theme and then moves once: the chosen (or largest)
    # topic first, then the next largest.
    by_topic: dict[str, list[PoolItem]] = {}
    for p in items:
        by_topic.setdefault(p.topic, []).append(p)
    ranked = sorted(by_topic.values(), key=lambda g: (g[0].topic.lower() != (topic or ""), -len(g), g[0].topic))
    first_share = need if topic else math.ceil(n / 2)
    chosen: list[PoolItem] = _spread(ranked[0], min(first_share, len(ranked[0])))
    if len(ranked) > 1:
        chosen += _spread(ranked[1], min(n - len(chosen), len(ranked[1])))
    if len(chosen) < n:  # small groups: top up from anything left
        chosen += _spread([p for p in items if p not in chosen], n - len(chosen))

    groups: dict[str, list[PoolItem]] = {}
    for p in chosen:
        groups.setdefault(p.topic, []).append(p)
    ordered_groups = sorted(
        groups.values(), key=lambda g: (min(p.difficulty for p in g), g[0].topic.lower() != (topic or ""))
    )
    ordered = [p for g in ordered_groups for p in sorted(g, key=lambda p: p.difficulty)]

    segments: list[Segment] = []
    prev: Segment | None = None
    for i, p in enumerate(ordered):
        d = p.difficulty if prev is None else max(prev.difficulty - settings.max_difficulty_jump,
                                                  min(p.difficulty, prev.difficulty + settings.max_difficulty_jump))
        if prev is None:
            d = min(d, level_difficulty(filters.level))
        stage = STAGES[min(len(STAGES) - 1, i * len(STAGES) // len(ordered))]
        link = "" if prev is None else (
            f"Staying with {p.topic}" if prev.topic == p.topic else f"Moving from {prev.topic} to {p.topic}"
        )
        prev = Segment(theme=f"{stage}: {p.topic}", topic=p.topic, difficulty=max(1, d),
                       seed_question_id=p.id, link_from_previous=link)
        segments.append(prev)
    return InterviewPlan(segments=segments, source="fallback", attempts=0)


class Planner:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def build_prompt(self, pack: ContextPack) -> str:
        f = pack.filters
        lo, hi = segment_range(len(pack.pool))
        topic, need = _topic_need(f, pack.pool, hi)
        return render(
            "planner",
            profile=f.profile or "any",
            level=f.level or "any level",
            company_line=f" interviewing at {f.company}" if f.company else "",
            pack=pack.to_json(),
            count_rule=f"Use between {lo} and {hi} segments." if lo != hi else f"Use exactly {hi} segment(s).",
            baseline=level_difficulty(f.level),
            max_jump=settings.max_difficulty_jump,
            topic_rule=(f"The candidate chose the topic {f.topic!r}: at least {round(settings.topic_focus_share * 100)}% "
                        "of segments use it and the others use closely related topics." if topic
                        else "No topic was chosen: cover several related topics, not one."),
        )

    async def run(self, pack: ContextPack) -> InterviewPlan:
        if not pack.pool:
            raise PlanError("the question pool is empty")
        by_id = {p.id: p for p in pack.pool}
        attempts = 1
        try:
            draft, attempts = await complete_validated(
                self.llm, self.build_prompt(pack), PlanDraft,
                check=lambda plan: validate_plan(plan, pack.pool, pack.filters),
                task="plan", model=settings.planner_model, effort=settings.planner_effort, max_tokens=2048,
            )
        except Exception as exc:  # invalid twice, or the API failed: never block the interview
            log.warning("planner fell back to the fixed plan: %s", exc)
            plan = fallback_plan(pack.pool, pack.filters)
            plan.attempts = 2 if isinstance(exc, ValueError) else 1
            return plan
        for s in draft.segments:  # the pool is the truth about a question's topic
            s.topic = by_id[s.seed_question_id].topic
        return InterviewPlan(segments=draft.segments, source="llm", attempts=attempts)
