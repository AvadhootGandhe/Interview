"""Offline, deterministic stand-in for Claude (FAKE_LLM=1, demos and end-to-end tests).

It reads the same prompts the real agents send and answers with the same JSON/text shapes, using
simple rules (answer length, keywords). It is not smart; it exists so the whole loop runs without a key.
"""
from __future__ import annotations

import json
import re

TERMS = (
    "redis", "kafka", "postgres", "mysql", "mongodb", "rabbitmq", "docker", "kubernetes", "grpc",
    "graphql", "cache", "sharding", "replication", "idempotency", "load balancer", "cdn", "oauth",
)


def _between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i == -1:
        return ""
    i += len(start)
    j = text.find(end, i)
    return text[i : j if j != -1 else len(text)].strip()


class DeterministicFakeLLM:
    async def complete(self, prompt: str, *, task: str | None = None, **_) -> str:
        handler = getattr(self, f"_{task}", None)
        if handler is None:
            raise ValueError(f"DeterministicFakeLLM has no handler for task {task!r}")
        return handler(prompt)

    # --- company profile ------------------------------------------------------
    def _company_profile(self, prompt: str) -> str:
        topics = re.findall(r"^- ([^:\n]+): [\d.]+%", prompt, flags=re.M)[:3]
        company = _between(prompt, "real interviewer at ", ".")
        return (
            f"{company or 'This company'} focuses on {', '.join(topics) or 'core engineering topics'}.\n"
            "Questions are practical and scenario-based, with an eye on trade-offs."
        )

    # --- planner --------------------------------------------------------------
    def _planner(self, prompt: str) -> str:
        from app.agents.planner import fallback_plan
        from app.services.retriever import Filters, PoolItem

        pack = json.loads(_between(prompt, "Context pack (JSON):\n", "\n\nReturn only JSON"))
        pool = [PoolItem(**p) for p in pack["pool"]]
        f = Filters(**pack.get("filters", {}))
        return fallback_plan(pool, f).model_dump_json()

    # --- evaluator ------------------------------------------------------------
    def _evaluator(self, prompt: str) -> str:
        thread = _between(prompt, "so far (the candidate's answers, and any follow-up questions asked):\n", "\n\nScore the")
        answers = [m.strip() for m in re.findall(r"^Candidate: (.*)$", thread, flags=re.M)]
        last = answers[-1] if answers else ""
        n = len(last.split())
        if n < 6 or re.search(r"don't know|no idea|not sure", last, re.I):
            score = 15 if n < 6 else 25
        elif n < 20:
            score = 50
        elif n < 45:
            score = 65 + (10 if len(answers) > 1 else 0)
        else:
            score = 88
        mentioned = [t for t in TERMS if re.search(rf"\b{re.escape(t)}\b", " ".join(answers), re.I)]
        weak = score < 70
        return json.dumps({
            "satisfaction": score,
            "scores": {"correctness": score, "depth": max(0, score - 5), "clarity": score, "communication": score},
            "covered_points": ["the basic idea"] if score >= 40 else [],
            "missing_points": ["the main trade-offs", "a concrete example"] if weak else [],
            "follow_up_focus": "the trade-offs and a concrete example" if weak else "",
            "mentioned_terms": mentioned,
            "red_flags": [],
        })

    # --- interviewer ----------------------------------------------------------
    def _interviewer(self, prompt: str) -> str:
        mode = (re.search(r"Task \((\w+)\)", prompt) or [None, "ask"])[1]
        role = _between(prompt, "Interview: ", ".")
        if mode == "greeting":
            return f"Hi, welcome. This is a {role}. Let's start with a few warm-up questions."
        if mode == "ask":
            seed = _between(prompt, "Seed question (keep its intent): ", "\n")
            bridge = _between(prompt, "Bridge note: ", "\n")
            lead = f"Since you brought that up ({bridge.replace('candidate mentioned ', '')}), " if bridge else "Okay. "
            return f"{lead}{seed}"
        if mode == "follow_up":
            focus = _between(prompt, "Follow-up focus: ", "\n")
            return f"Could you say a bit more about {focus or 'that'}?"
        if mode == "transition":
            return "Thanks, that helps. Let's move on."
        return "Thank you, that was a good conversation. Your written feedback is ready for you."

    # --- reporter -------------------------------------------------------------
    def _reporter(self, prompt: str) -> str:
        covered = re.findall(r"covered: ([^\n]+)", prompt)
        missed = re.findall(r"missed: ([^\n]+)", prompt)
        pick = lambda xs, default: [x for x in dict.fromkeys(i.strip() for x in xs for i in x.split(";")) if x and x != "nothing noted"][:3] or [default]  # noqa: E731
        return json.dumps({
            "verdict": "A reasonable interview with clear areas to build on.",
            "strengths": pick(covered, "You stayed engaged throughout."),
            "gaps": pick(missed, "No major gaps found."),
            "next_steps": ["Practise explaining trade-offs out loud.", "Review the topics you scored lowest on."],
        })
