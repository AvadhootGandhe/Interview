"""Deterministic stand-ins used when FAKE_LLM=1 and in API tests: no network, no models."""
import json
import re

MIN_STRONG_CHARS = 60


class NoGenerator:
    async def generate(self, *a, **k):
        from app.agents.question_generator import GeneratorUnavailable
        raise GeneratorUnavailable("generator disabled")


class FakeInterviewLLM:
    """Routes by prompt content. Answers shorter than MIN_STRONG_CHARS score 40, longer ones 85."""

    async def complete(self, prompt: str, **kw) -> str:
        if "planning a spoken" in prompt:
            return "{}"  # invalid on purpose: the planner falls back to its deterministic plan
        if "scoring a spoken answer" in prompt:
            answers = re.findall(r"^Candidate: (.*)$", prompt, flags=re.MULTILINE)
            sat = 85 if len(answers[-1].strip()) >= MIN_STRONG_CHARS else 40
            return json.dumps({
                "satisfaction": sat,
                "scores": {"correctness": sat, "depth": sat, "clarity": sat, "communication": sat},
                "covered_points": ["core idea"], "missing_points": ["failure modes"],
                "follow_up_focus": "What could go wrong, and how would you handle it?",
                "mentioned_terms": [], "red_flags": []})
        if "summarising how" in prompt:
            return "They focus on scale and real-world trade-offs."
        if "writing interview feedback" in prompt:
            return json.dumps({"verdict": "A promising practice run.",
                               "strengths": ["Clear core ideas"], "gaps": ["Failure modes"]})
        if "Mode: greeting" in prompt:
            return "Hi, welcome. I'll ask a few questions, so whenever you're ready, let's begin."
        if "Mode: follow_up" in prompt:
            return "Could you go a bit deeper on what could go wrong?"
        if "Mode: closing" in prompt:
            return "Thanks, that was a good conversation. Your report is ready."
        seed = re.search(r"Question to ask \(keep its intent\): (.*)", prompt)
        return f"Okay, next. {seed.group(1)}" if seed else "Okay, next question."
