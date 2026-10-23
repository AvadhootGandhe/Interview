"""GET /catalog/*: the names the setup screen offers (sorted, technical topics only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Company, Level, Profile, QuestionMap, Topic
from app.db.session import get_db

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _sorted(names) -> list[str]:
    return sorted(names, key=str.lower)


@router.get("/companies")
def companies(q: str = "", limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)) -> list[str]:
    stmt = select(Company.name).where(Company.is_general.is_(False))
    if q.strip():
        stmt = stmt.where(func.lower(Company.name).contains(q.strip().lower()))
    return _sorted(db.scalars(stmt.order_by(func.lower(Company.name)).limit(limit)))


@router.get("/profiles")
def profiles(db: Session = Depends(get_db)) -> list[str]:
    return _sorted(db.scalars(select(Profile.name)))


@router.get("/levels")
def levels(db: Session = Depends(get_db)) -> list[str]:
    return list(db.scalars(select(Level.name).order_by(Level.rank, Level.name)))


@router.get("/topics")
def topics(profile: str | None = None, db: Session = Depends(get_db)) -> list[str]:
    stmt = select(Topic.name).where(Topic.category != "behavioral")
    if profile:
        stmt = stmt.where(
            Topic.id.in_(
                select(QuestionMap.topic_id)
                .join(Profile, Profile.id == QuestionMap.profile_id)
                .where(func.lower(Profile.name) == profile.lower())
            )
        )
    return _sorted(db.scalars(stmt))
