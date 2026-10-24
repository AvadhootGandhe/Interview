import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.services.levels import level_rubric

PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "evaluator.md").read_text()


class Scores(BaseModel):
    correctness: int = Field(ge=0, le=100)
    depth: int = Field(ge=0, le=100)
    clarity: int = Field(ge=0, le=100)
    communication: int = Field(ge=0, le=100)


class Evaluation(BaseModel):
    satisfaction: int = Field(ge=0, le=100)
    scores: Scores
    covered_points: list[str] = []
    missing_points: list[str] = []
    follow_up_focus: str = ""
    mentioned_terms: list[str] = []
    red_flags: list[str] = []


class EvaluationError(Exception):
    pass


def _parse(raw: str) -> Evaluation | None:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        return Evaluation.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        return None


async def evaluate(llm, profile: str, level: str, thread: list[tuple[str, str]]) -> Evaluation:
    """Score a question thread: [(interviewer_question, candidate_answer), ...] with follow-ups in order."""
    rendered = "\n".join(f"Interviewer: {q}\nCandidate: {a or '(no answer)'}" for q, a in thread)
    prompt = (PROMPT.replace("{profile}", profile).replace("{level}", level or "unspecified")
              .replace("{rubric}", level_rubric(level)).replace("{thread}", rendered))
    for _ in range(2):  # first try + one retry
        try:
            ev = _parse(await llm.complete(prompt, max_tokens=700, temperature=0))
        except Exception:
            ev = None
        if ev:
            return ev
    raise EvaluationError("evaluator returned invalid output twice")
