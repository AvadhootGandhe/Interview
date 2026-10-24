"""Pydantic models shared by the agents, the flow controller and the API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Segment(BaseModel):
    theme: str
    topic: str
    difficulty: int = Field(ge=1, le=5)
    seed_question_id: str
    link_from_previous: str = ""


class PlanDraft(BaseModel):
    """What the planner model returns."""

    segments: list[Segment] = Field(min_length=1, max_length=6)


class InterviewPlan(PlanDraft):
    source: Literal["llm", "fallback"] = "llm"
    attempts: int = 1  # model attempts used (1 = valid on the first try)


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
