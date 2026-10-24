import json
import math
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.services.context_pack import ContextPack
from app.services.levels import LEVEL_RANK

PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "planner.md").read_text()
MIN_SEGMENTS, MAX_SEGMENTS, DEFAULT_SEGMENTS = 4, 6, 5
MAX_DIFFICULTY_JUMP = 2
TOPIC_SHARE = 0.6


class Segment(BaseModel):
    theme: str
    topic: str
    difficulty: int = Field(ge=1, le=5)
    seed_question_id: int
    link_from_previous: str = ""


class InterviewPlan(BaseModel):
    segments: list[Segment]


def _baseline(pack: ContextPack) -> int:
    return LEVEL_RANK.get(pack.filters.level or "", 3)


def validate_plan(plan: InterviewPlan, pack: ContextPack) -> list[str]:
    """Return a list of problems; empty means the plan is valid."""
    errors: list[str] = []
    segs = plan.segments
    pool = {p.id: p for p in pack.pool}
    if not MIN_SEGMENTS <= len(segs) <= MAX_SEGMENTS:
        errors.append(f"need {MIN_SEGMENTS}-{MAX_SEGMENTS} segments, got {len(segs)}")
    ids = [s.seed_question_id for s in segs]
    errors += [f"unknown question id {i}" for i in ids if i not in pool]
    if len(set(ids)) != len(ids):
        errors.append("repeated question")
    if segs and segs[0].difficulty > _baseline(pack):
        errors.append("first segment is harder than the level baseline")
    for a, b in zip(segs, segs[1:]):
        if b.difficulty - a.difficulty > MAX_DIFFICULTY_JUMP:
            errors.append("difficulty jumps too much")
    topic = pack.filters.topic
    if topic and segs:
        available = sum(p.topic == topic for p in pack.pool)
        needed = min(math.ceil(TOPIC_SHARE * len(segs)), available)
        if sum(s.topic == topic for s in segs) < needed:
            errors.append(f"too few segments on topic {topic}")
    return errors


def fallback_plan(pack: ContextPack, n: int = DEFAULT_SEGMENTS) -> InterviewPlan:
    """Deterministic plan: items closest to the level baseline, grouped by topic, easiest first."""
    base, topic = _baseline(pack), pack.filters.topic
    ranked = sorted(pack.pool, key=lambda p: (p.topic != topic, abs(p.difficulty - base), p.id))
    chosen = ranked[:n]
    order = {t: i for i, t in enumerate(dict.fromkeys(p.topic for p in chosen))}
    chosen.sort(key=lambda p: (order[p.topic], p.difficulty, p.id))
    easiest = min(range(len(chosen)), key=lambda i: chosen[i].difficulty) if chosen else 0
    if chosen and chosen[easiest].difficulty < chosen[0].difficulty:
        chosen.insert(0, chosen.pop(easiest))
    segments = []
    for i, p in enumerate(chosen):
        prev = chosen[i - 1] if i else None
        link = "" if prev is None else (
            "Staying on the same topic." if prev.topic == p.topic else f"Moving from {prev.topic} to {p.topic}.")
        segments.append(Segment(theme=p.topic, topic=p.topic, difficulty=p.difficulty,
                                seed_question_id=p.id, link_from_previous=link))
    return InterviewPlan(segments=segments)


def _parse(raw: str) -> InterviewPlan | None:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        return InterviewPlan.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        return None


async def plan_interview(llm, pack: ContextPack, n: int = DEFAULT_SEGMENTS) -> InterviewPlan:
    prompt = (PROMPT.replace("{n}", str(n)).replace("{baseline}", str(_baseline(pack)))
              .replace("{pack}", pack.to_prompt()))
    for _ in range(2):  # first try + one retry
        try:
            plan = _parse(await llm.complete(prompt, max_tokens=900))
        except Exception:
            plan = None
        if plan and not validate_plan(plan, pack):
            return plan
    return fallback_plan(pack, n)
