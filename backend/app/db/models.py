from sqlalchemy import (
    DDL, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event, func,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    is_general = Column(Integer, nullable=False, default=0)


class Profile(Base):
    __tablename__ = "profiles"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)


class Level(Base):
    __tablename__ = "levels"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    rank = Column(Integer, nullable=False)


class Topic(Base):
    __tablename__ = "topics"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    category = Column(String, nullable=False)  # technical | behavioral | dsa


class Question(Base):
    __tablename__ = "questions"
    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, nullable=False)
    ext_id = Column(String, nullable=False)
    text = Column(Text, nullable=False)


class QuestionMap(Base):
    __tablename__ = "question_map"
    id = Column(Integer, primary_key=True)
    question_id = Column(ForeignKey("questions.id"), nullable=False)
    company_id = Column(ForeignKey("companies.id"), nullable=False)
    profile_id = Column(ForeignKey("profiles.id"), nullable=False)
    level_id = Column(ForeignKey("levels.id"), nullable=False)
    topic_id = Column(ForeignKey("topics.id"), nullable=False)
    __table_args__ = (
        UniqueConstraint("question_id", "company_id", "profile_id", "level_id", "topic_id"),
        Index("ix_map_company_profile_level", "company_id", "profile_id", "level_id"),
        Index("ix_map_profile_level_topic", "profile_id", "level_id", "topic_id"),
        Index("ix_map_question", "question_id"),
    )


class CompanyProfile(Base):
    __tablename__ = "company_profiles"
    id = Column(Integer, primary_key=True)
    company_id = Column(ForeignKey("companies.id"), nullable=False)
    profile_id = Column(ForeignKey("profiles.id"), nullable=False)
    level_id = Column(ForeignKey("levels.id"))
    topic_mix_json = Column(Text, nullable=False)
    summary = Column(Text)
    updated_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("company_id", "profile_id", "level_id"),)


class InterviewSession(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True)
    profile = Column(String, nullable=False)
    level = Column(String)
    company = Column(String)
    topic = Column(String)
    state = Column(String, nullable=False, default="active")  # active | done
    current_index = Column(Integer, nullable=False, default=0)
    followups_used = Column(Integer, nullable=False, default=0)
    pool_json = Column(Text, nullable=False, default="[]")
    company_summary = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, server_default=func.now())


class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True)
    session_id = Column(ForeignKey("sessions.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    plan_json = Column(Text, nullable=False)
    bridge = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class Turn(Base):
    __tablename__ = "turns"
    id = Column(Integer, primary_key=True)
    session_id = Column(ForeignKey("sessions.id"), nullable=False, index=True)
    segment_index = Column(Integer, nullable=False)
    kind = Column(String, nullable=False)  # greeting | ask | follow_up | answer | closing
    role = Column(String, nullable=False)  # interviewer | candidate
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class Evaluation(Base):
    __tablename__ = "evaluations"
    id = Column(Integer, primary_key=True)
    session_id = Column(ForeignKey("sessions.id"), nullable=False, index=True)
    segment_index = Column(Integer, nullable=False)
    attempt = Column(Integer, nullable=False)
    satisfaction = Column(Integer, nullable=False)
    final_score = Column(Integer)  # set on the attempt that closed the question
    data_json = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


# FTS5 keyword index over question text; rowid == questions.id.
event.listen(
    Base.metadata,
    "after_create",
    DDL("CREATE VIRTUAL TABLE IF NOT EXISTS questions_fts USING fts5(text)"),
)
