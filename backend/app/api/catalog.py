from fastapi import APIRouter, Query, Request
from sqlalchemy import text

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _rows(request: Request, sql: str, **params) -> list[str]:
    with request.app.state.engine.connect() as conn:
        return [r[0] for r in conn.execute(text(sql), params)]


@router.get("/companies")
def companies(request: Request, q: str = "", limit: int = Query(20, ge=1, le=100)) -> list[str]:
    return _rows(
        request,
        "select name from companies where is_general = 0 and name like :q "
        "order by (name like :prefix) desc, name limit :limit",
        q=f"%{q}%", prefix=f"{q}%", limit=limit)


@router.get("/profiles")
def profiles(request: Request) -> list[str]:
    return _rows(request, "select name from profiles order by name")


@router.get("/levels")
def levels(request: Request) -> list[str]:
    return _rows(request, "select name from levels order by rank")


@router.get("/topics")
def topics(request: Request, profile: str, company: str | None = None) -> list[str]:
    sql = """select distinct t.name from question_map m
        join topics t on t.id = m.topic_id
        join profiles p on p.id = m.profile_id
        join companies c on c.id = m.company_id
        where p.name = :profile and t.category != 'behavioral'"""
    if company:
        sql += " and c.name = :company"
    return _rows(request, sql + " order by t.name", profile=profile, company=company)
