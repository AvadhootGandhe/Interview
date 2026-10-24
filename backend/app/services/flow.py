"""Flow controller: adjusts the NEXT segment after a question is finished. Rules only.

- mentioned a term that matches an upcoming pool question -> pull that question forward, add a bridge
- final score >= harder_at  -> a harder pool question on the same topic (smallest step up)
- final score <= easier_at  -> an easier one (smallest step down)
- no matching alternative   -> the plan stays as it was

Everything chosen comes from the retrieved pool; nothing is generated here.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.agents.planner import InterviewPlan, Segment
from app.config import settings
from app.services.retriever import PoolItem

Search = Callable[[list[str], list[PoolItem]], list[PoolItem]]


@dataclass
class Outcome:
    """A finished question: its id and final score (last satisfaction minus follow-up penalties)."""

    question_id: str
    final_score: float
    mentioned_terms: list[str] = field(default_factory=list)


def _contains(text: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term.lower())}(?!\w)", text.lower()) is not None


def _default_search(terms: list[str], items: list[PoolItem]) -> list[PoolItem]:
    return [i for i in items if any(_contains(i.text, t) for t in terms)]


def _label(term: str) -> str:
    return term.capitalize() if term == term.lower() else term


def next_segment(
    plan: InterviewPlan,
    history: list[Outcome],
    last_eval,
    pool: list[PoolItem],
    search: Search | None = None,
) -> tuple[Segment | None, str | None]:
    """The segment to ask next and an optional bridge note. Pure: `plan` is never modified.

    `last_eval` needs a `mentioned_terms` list; the score comes from `history[-1]`.
    Use `apply_next` to write the result into a copy of the plan.
    """
    index = len(history)
    if index >= len(plan.segments):
        return None, None
    current = plan.segments[index]
    by_id = {p.id: p for p in pool}
    asked = {h.question_id for h in history}
    planned = {s.seed_question_id for s in plan.segments}
    score = history[-1].final_score if history else 50.0

    # 1. a term the candidate brought up matches an upcoming question
    terms = [t for t in (getattr(last_eval, "mentioned_terms", None) or []) if t and t.strip()]
    if terms:
        upcoming = [by_id[s.seed_question_id] for s in plan.segments[index:]
                    if s.seed_question_id in by_id and s.seed_question_id not in asked]
        hits = (search or _default_search)(terms, upcoming)
        if hits:
            hit = hits[0]
            term = next((t for t in terms if _contains(hit.text, t)), terms[0])
            bridge = f"candidate mentioned {_label(term)}"
            source = next(s for s in plan.segments[index:] if s.seed_question_id == hit.id)
            return source.model_copy(update={"bridge": bridge}), bridge

    # 2. harder / easier question on the same theme, from questions nobody has planned or asked
    cur = by_id.get(current.seed_question_id)
    ref = cur.difficulty if cur else current.difficulty
    free = [p for p in pool if p.id not in asked and p.id not in planned and p.topic == current.topic]
    pick = None
    if score >= settings.flow_harder_at:
        harder = [p for p in free if p.difficulty > ref]
        pick = min(harder, key=lambda p: p.difficulty, default=None)
    elif score <= settings.flow_easier_at:
        easier = [p for p in free if p.difficulty < ref]
        pick = max(easier, key=lambda p: p.difficulty, default=None)
    if pick:
        return current.model_copy(update={
            "seed_question_id": pick.id, "topic": pick.topic, "difficulty": pick.difficulty,
            "bridge": "",
        }), None
    return current, None


def apply_next(plan: InterviewPlan, index: int, segment: Segment) -> InterviewPlan:
    """A copy of `plan` whose segment `index` is `segment`.

    If `segment` was pulled forward from a later position, the two swap places so no question
    is asked twice. Nothing else changes.
    """
    segs = list(plan.segments)
    old = segs[index]
    partner = next((i for i in range(index + 1, len(segs)) if segs[i].seed_question_id == segment.seed_question_id), None)
    if partner is not None:
        segs[partner] = old.model_copy(update={"link_from_previous": segs[partner].link_from_previous, "bridge": ""})
    segs[index] = segment.model_copy(update={"link_from_previous": old.link_from_previous})
    return InterviewPlan(segments=segs)
