"""SQLAlchemy 2.0 models. `questions_fts` (FTS5) is created in `session.init_db`."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    is_general: Mapped[bool] = mapped_column(default=False)


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Level(Base):
    __tablename__ = "levels"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    rank: Mapped[int] = mapped_column(default=3)  # difficulty 1 (Fresher) .. 5 (Architect)


class Topic(Base):
    __tablename__ = "topics"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    category: Mapped[str] = mapped_column(String(20), default="technical")  # technical|behavioral|dsa


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # slug suffix, e.g. "21834" or "d1743"
    slug: Mapped[str] = mapped_column(String(300), unique=True)
    text: Mapped[str] = mapped_column(Text)


class QuestionMap(Base):
    __tablename__ = "question_map"
    __table_args__ = (
        UniqueConstraint("company_id", "profile_id", "level_id", "topic_id", "question_id"),
        Index("ix_map_profile_level_topic", "profile_id", "level_id", "topic_id"),
        Index("ix_map_company_profile_level", "company_id", "profile_id", "level_id"),
        Index("ix_map_question", "question_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"))
    level_id: Mapped[int] = mapped_column(ForeignKey("levels.id"))
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))


class CompanyProfile(Base):
    """Cached topic mix + focus summary per (company, profile, level)."""

    __tablename__ = "company_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id"))
    level_id: Mapped[int | None] = mapped_column(ForeignKey("levels.id"))
    topic_mix_json: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


# --- Interview state (filled in Phase 3) -------------------------------------

class InterviewSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    profile: Mapped[str | None] = mapped_column(String(100))
    level: Mapped[str | None] = mapped_column(String(100))
    company: Mapped[str | None] = mapped_column(String(200))
    topic: Mapped[str | None] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(30), default="created")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Turn(Base):
    __tablename__ = "turns"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    question_id: Mapped[str | None] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(20), default="interviewer")  # interviewer|candidate
    kind: Mapped[str] = mapped_column(String(20), default="ask")  # greeting|ask|follow_up|answer|closing
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Evaluation(Base):
    __tablename__ = "evaluations"
    id: Mapped[int] = mapped_column(primary_key=True)
    turn_id: Mapped[int] = mapped_column(ForeignKey("turns.id"), index=True)
    satisfaction: Mapped[int] = mapped_column(default=0)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    plan_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
