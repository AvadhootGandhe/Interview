"""Plain helpers shared by the Phase 3 tests (importable as `helpers`)."""
from __future__ import annotations

import json


def make_pool(spec: list[tuple[str, int]] | None = None) -> list:
    """Synthetic pool: (topic, difficulty) pairs -> PoolItems with ids q1, q2, ..."""
    from app.services.retriever import PoolItem

    spec = spec or [
        ("Caching", 1), ("Caching", 2), ("Caching", 4), ("Caching", 5),
        ("Databases", 1), ("Databases", 3), ("Databases", 4),
        ("Messaging", 2), ("Messaging", 3), ("Messaging", 5),
        ("APIs", 1), ("APIs", 2), ("APIs", 3), ("APIs", 4),
    ]
    return [
        PoolItem(id=f"q{i + 1}", topic=t, text=f"Question {i + 1} about {t.lower()} at difficulty {d}?", difficulty=d)
        for i, (t, d) in enumerate(spec)
    ]


class ScriptedLLM:
    """Per-task scripted replies (in order); any task without a script falls through to the offline fake.

    A reply may be an Exception instance, which is raised instead of returned.
    """

    def __init__(self, **by_task: list) -> None:
        from app.llm.fake_llm import DeterministicFakeLLM

        self.replies = {task: list(r) for task, r in by_task.items()}
        self.fake = DeterministicFakeLLM()
        self.calls: list[dict] = []

    async def complete(self, prompt: str, *, task: str | None = None, **kwargs) -> str:
        self.calls.append({"task": task, "prompt": prompt, **kwargs})
        queue = self.replies.get(task)
        if queue:
            reply = queue.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        return await self.fake.complete(prompt, task=task, **kwargs)

    def prompts(self, task: str) -> list[str]:
        return [c["prompt"] for c in self.calls if c["task"] == task]


def seg(qid: str, topic: str, d: int, link: str = "builds on the last answer", theme: str | None = None) -> dict:
    return {"theme": theme or topic, "topic": topic, "difficulty": d, "seed_question_id": qid,
            "link_from_previous": link}


def plan_json(*segs: dict) -> str:
    return json.dumps({"segments": list(segs)})


def eval_json(satisfaction: int, **over) -> str:
    base = {
        "satisfaction": satisfaction,
        "scores": {"correctness": satisfaction, "depth": satisfaction, "clarity": satisfaction,
                   "communication": satisfaction},
        "covered_points": ["basic idea"],
        "missing_points": ["trade-offs"] if satisfaction < 70 else [],
        "follow_up_focus": "the trade-offs" if satisfaction < 70 else "",
        "mentioned_terms": [],
        "red_flags": [],
    }
    base.update(over)
    return json.dumps(base)
