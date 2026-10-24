"""DemoLLM: a deterministic, offline stand-in for Claude (FAKE_LLM=1, dry-run evals, test fallback).

It routes on the `task=` label and returns valid output for every agent, so a whole interview runs
with no API key. It is a plumbing fixture, not a model: its scores are crude word counts.
"""
from __future__ import annotations

import json
import re

TECH_TERMS = ["redis", "kafka", "postgres", "kubernetes", "docker", "terraform", "grpc", "rabbitmq",
              "mongodb", "elasticsearch", "idempotency", "sharding", "circuit breaker", "cdn"]


def _between(text: str, start: str, end: str) -> str:
    m = re.search(re.escape(start) + r"(.*?)" + re.escape(end), text, re.DOTALL)
    return m.group(1) if m else ""


def _line(prompt: str, label: str) -> str:
    m = re.search(rf"^{re.escape(label)}:\s*(.*)$", prompt, re.MULTILINE)
    return m.group(1).strip() if m else ""


class DemoLLM:
    async def complete(self, prompt: str, task: str | None = None, **kwargs) -> str:
        handler = getattr(self, f"_{task}", None)
        return handler(prompt) if handler else ""

    def _plan(self, prompt: str) -> str:
        from app.agents.planner import fallback_plan
        from app.services.retriever import Filters, PoolItem

        pack = json.loads(_between(prompt, "<context_pack>", "</context_pack>"))
        pool = [PoolItem(**p) for p in pack["pool"]]
        plan = fallback_plan(pool, Filters(**pack["filters"]))
        return json.dumps({"segments": [s.model_dump() for s in plan.segments]})

    def _evaluate(self, prompt: str) -> str:
        answer = _between(prompt, "<answer>", "</answer>").strip()
        words = len(answer.split())
        low = answer.lower()
        sat = 10 if "don't know" in low or "no idea" in low else (15 if words < 4 else min(92, 25 + 3 * words))
        terms = [t for t in TECH_TERMS if t in low]
        missing = [] if sat >= 85 else ["the main trade-offs and failure handling"]
        return json.dumps({
            "satisfaction": sat,
            "scores": {k: sat for k in ("correctness", "depth", "clarity", "communication")},
            "covered_points": ["the core idea"] if sat >= 30 else [],
            "missing_points": missing,
            "follow_up_focus": missing[0] if missing else "",
            "mentioned_terms": terms,
            "red_flags": [],
        })

    def _interview(self, prompt: str) -> str:
        mode = _line(prompt, "Mode")
        seed = _line(prompt, "Seed question")
        if mode == "greeting":
            return "Hi, I'm your mock interviewer. Let's get started."
        if mode == "closing":
            return "Thanks for your time. Your feedback report is ready."
        if mode == "follow_up":
            return f"Could you say more about {_line(prompt, 'Follow-up focus')}?"
        lead = "Okay, let's move on." if mode == "transition" else "Let's go to the next part."
        return f"{lead} {seed}"

    def _report(self, prompt: str) -> str:
        return json.dumps({"verdict": "A reasonable interview with room to grow.",
                           "strengths": ["Explained the core ideas clearly"],
                           "gaps": ["Go deeper on trade-offs and failure handling"]})

    def _company_profile(self, prompt: str) -> str:
        return "Asks practical, scenario-based questions.\nExpects clear trade-off reasoning."

    def _judge(self, prompt: str) -> str:
        return json.dumps({"score": 4, "reason": "demo judge"})

    def _candidate(self, prompt: str) -> str:
        persona = _line(prompt, "Persona")
        if persona.startswith("weak"):
            return "I'm not sure, I think it is something like that."
        base = ("I would start from the requirements, pick a simple design and measure it. The trade-off is "
                "consistency versus latency, so I add timeouts, retries with backoff and monitoring for failures.")
        return base + (" I would also use Redis here." if "redis" in prompt.lower() else "")
