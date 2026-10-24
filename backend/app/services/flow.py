"""Rule-based flow controller. Pure functions, no LLM call, so it adds no turn latency."""
from typing import Callable

from app.agents.planner import MAX_DIFFICULTY_JUMP, InterviewPlan, Segment
from app.services.retriever import PoolItem

HARDER_AT = 85
EASIER_AT = 50

SearchFn = Callable[[str, list[PoolItem]], list[PoolItem]]


def _segment_for(item: PoolItem, link: str = "") -> Segment:
    return Segment(theme=item.topic, topic=item.topic, difficulty=item.difficulty,
                   seed_question_id=item.id, link_from_previous=link)


def _within_jump(current: Segment, difficulty: int) -> bool:
    return difficulty - current.difficulty <= MAX_DIFFICULTY_JUMP


def _bridge_to_mentioned(plan, idx, terms, pool, asked, search_fn):
    """Swap in an unasked pool question that matches something the candidate just said."""
    if not terms:
        return None
    current, upcoming = plan.segments[idx], plan.segments[idx + 1:]
    upcoming_ids = {s.seed_question_id: i + idx + 1 for i, s in enumerate(upcoming)}
    hits = [h for h in search_fn(" ".join(terms), pool)
            if h.id not in asked and _within_jump(current, h.difficulty)]
    if not hits:
        return None
    hit = next((h for h in hits if h.id in upcoming_ids), hits[0])
    term = next((t for t in terms if t.lower() in hit.text.lower()), terms[0])
    bridge = f"candidate mentioned {term}"
    segments = list(plan.segments)
    nxt = idx + 1
    if hit.id in upcoming_ids:
        j = upcoming_ids[hit.id]
        segments[nxt], segments[j] = segments[j], segments[nxt]
        segments[nxt] = segments[nxt].model_copy(update={"link_from_previous": bridge})
    else:
        segments[nxt] = _segment_for(hit, bridge)
    return InterviewPlan(segments=segments), bridge


def _shift_difficulty(plan, idx, score, pool, asked):
    current, nxt = plan.segments[idx], plan.segments[idx + 1]
    in_plan = {s.seed_question_id for s in plan.segments}
    same_theme = [p for p in pool if p.topic == nxt.topic and p.id not in asked and p.id not in in_plan]
    if score >= HARDER_AT:
        options = sorted((p for p in same_theme
                          if p.difficulty > nxt.difficulty and _within_jump(current, p.difficulty)),
                         key=lambda p: (p.difficulty, p.id))
    else:
        options = sorted((p for p in same_theme if p.difficulty < nxt.difficulty),
                         key=lambda p: (-p.difficulty, p.id))
    if not options:
        return plan
    segments = list(plan.segments)
    segments[idx + 1] = _segment_for(options[0], nxt.link_from_previous)
    return InterviewPlan(segments=segments)


def adjust_plan(plan: InterviewPlan, current_index: int, final_score: int, mentioned_terms: list[str],
                pool: list[PoolItem], asked_ids: set[int], search_fn: SearchFn
                ) -> tuple[InterviewPlan, str | None]:
    """Adjust the next segment after question `current_index` is finished; returns (plan, bridge note)."""
    if current_index + 1 >= len(plan.segments):
        return plan, None
    bridged = _bridge_to_mentioned(plan, current_index, mentioned_terms, pool, asked_ids, search_fn)
    if bridged:
        return bridged
    if final_score >= HARDER_AT or final_score <= EASIER_AT:
        return _shift_difficulty(plan, current_index, final_score, pool, asked_ids), None
    return plan, None
