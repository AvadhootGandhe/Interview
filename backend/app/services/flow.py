"""Flow controller: pure rules (no LLM call, no I/O) that adjust the NEXT segment after each question.

    final score >= flow_harder_at  -> a harder pool question on the same theme (topic)
    final score <= flow_easier_at  -> an easier one
    a mentioned term matches an upcoming pool question -> move it up to next, with a bridge note

A bridge beats harder/easier. It never picks an already-asked question, never touches finished
segments, and leaves the plan unchanged when nothing fits. Only ids from the pool are used.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.agents.schemas import Evaluation, InterviewPlan, Segment
from app.config import settings
from app.services.retriever import STOP_WORDS, PoolItem

Search = Callable[[list[str], list[PoolItem]], list[PoolItem]]


@dataclass
class FlowDecision:
    plan: InterviewPlan  # a new plan; the input is never mutated
    segment: Segment | None  # the next segment, or None after the last one
    bridge: str | None = None
    reason: str = "unchanged"  # harder | easier | bridge | unchanged | end


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1 and w not in STOP_WORDS]


def keyword_search(terms: str | Sequence[str], pool: list[PoolItem]) -> list[PoolItem]:
    """In-memory stand-in for the FTS5 search: pool items ranked by how many query words they contain."""
    query = set(_words(" ".join([terms] if isinstance(terms, str) else terms)))
    scored = []
    for i, item in enumerate(pool):
        hits = len(query & set(_words(item.text)))
        if hits:
            scored.append((-hits, i, item))
    return [item for _, _, item in sorted(scored, key=lambda t: t[:2])]


def _clamp_difficulties(segments: list[Segment], start: int) -> None:
    """Keep neighbouring difficulties within max_difficulty_jump, from `start` on."""
    j = settings.max_difficulty_jump
    for i in range(max(1, start), len(segments)):
        prev = segments[i - 1].difficulty
        segments[i].difficulty = max(prev - j, min(prev + j, segments[i].difficulty))


def _segment_for(item: PoolItem, old: Segment, difficulty: int, link: str) -> Segment:
    return Segment(theme=old.theme, topic=item.topic, difficulty=min(5, max(1, difficulty)),
                   seed_question_id=item.id, link_from_previous=link)


def _display(term: str) -> str:
    term = term.strip()
    return term.capitalize() if term.islower() else term


def next_segment(
    plan: InterviewPlan,
    position: int,
    history: Sequence[str],
    last_eval: Evaluation,
    final_score: int,
    pool: list[PoolItem],
    search: Search | None = None,
) -> FlowDecision:
    """Decide the segment after `position`. `history` holds the ids already asked."""
    search = search or keyword_search
    nxt = position + 1
    if nxt >= len(plan.segments):
        return FlowDecision(plan, None, None, "end")

    new = plan.model_copy(deep=True)
    segs = new.segments
    by_id = {p.id: p for p in pool}
    asked = set(history)
    current = segs[nxt]
    current_item = by_id.get(current.seed_question_id)

    def swap_in(item: PoolItem, difficulty: int, link: str) -> None:
        """Make `item` the next segment; if it was planned later, that slot gets the old next question."""
        later = next((i for i in range(nxt + 1, len(segs)) if segs[i].seed_question_id == item.id), None)
        if later is not None:
            segs[later] = segs[later].model_copy(
                update={"seed_question_id": current.seed_question_id, "topic": current.topic,
                        "theme": current.theme, "difficulty": current.difficulty}
            )
        segs[nxt] = _segment_for(item, current, difficulty, link)
        _clamp_difficulties(segs, nxt)

    # 1. Bridge: something the candidate said matches an upcoming question.
    upcoming = [by_id[s.seed_question_id] for s in segs[nxt:] if s.seed_question_id in by_id
                and s.seed_question_id not in asked]
    for term in last_eval.mentioned_terms:
        hits = search([term], upcoming)
        if hits:
            bridge = f"candidate mentioned {_display(term)}"
            hit = hits[0]
            if hit.id == current.seed_question_id:
                segs[nxt].link_from_previous = bridge
            else:
                swap_in(hit, hit.difficulty if hit.difficulty else current.difficulty, bridge)
            return FlowDecision(new, segs[nxt], bridge, "bridge")

    # 2. Harder / easier on the same theme, from questions not asked and not already planned elsewhere.
    if current_item is not None and (final_score >= settings.flow_harder_at or final_score <= settings.flow_easier_at):
        harder = final_score >= settings.flow_harder_at
        planned_later = {s.seed_question_id for s in segs[nxt + 1:]}
        candidates = [
            p for p in pool
            if p.topic == current.topic and p.id not in asked and p.id not in planned_later
            and p.id != current_item.id
            and (p.difficulty > current_item.difficulty if harder else p.difficulty < current_item.difficulty)
        ]
        if candidates:
            pick = min(candidates, key=lambda p: abs(p.difficulty - current_item.difficulty))
            shift = 1 if harder else -1
            swap_in(pick, current.difficulty + shift, current.link_from_previous)
            return FlowDecision(new, segs[nxt], None, "harder" if harder else "easier")

    return FlowDecision(plan, plan.segments[nxt], None, "unchanged")
