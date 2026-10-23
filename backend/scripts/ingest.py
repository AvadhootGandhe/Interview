"""Stream the question dataset into SQLite and build the FTS5 index.

    python -m scripts.ingest --source ../data/sample_questions.json [--db sqlite:///./interview.db]

The source is `company -> profile -> level -> topic -> {"questions": [{question, slug}]}`.
It is read one company at a time with ijson, so the 914 MB file never sits in RAM.
Re-running is safe: every insert ignores rows that already exist.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import ijson
from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.dialects.sqlite import insert

from app.config import settings
from app.db.models import Company, Level, Profile, Question, QuestionMap, Topic
from app.db.names import (  # noqa: F401  (re-exported for callers and tests)
    GENERAL,
    canonical_company,
    parse_question_id,
    topic_category,
)
from app.db.session import make_engine


class _Ids:
    """name -> id cache for the small lookup tables (insert on first sight)."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self.cache: dict[tuple[type, str], int] = {}

    def get(self, model: type, name: str, **extra) -> int:
        key = (model, name)
        if key not in self.cache:
            self.conn.execute(insert(model).values(name=name, **extra).on_conflict_do_nothing())
            self.cache[key] = self.conn.scalar(select(model.id).where(model.name == name))
        return self.cache[key]


def _flush(conn: Connection, questions: list[dict], maps: list[dict]) -> None:
    if questions:
        conn.execute(insert(Question).on_conflict_do_nothing(), questions)
    if maps:
        conn.execute(insert(QuestionMap).on_conflict_do_nothing(), maps)
    questions.clear()
    maps.clear()


def ingest(source: Path, engine: Engine, batch_size: int | None = None) -> dict[str, int]:
    batch_size = batch_size or settings.ingest_batch_size
    questions: list[dict] = []
    maps: list[dict] = []
    seen: set[str] = set()
    with engine.begin() as conn, open(source, "rb") as f:
        ids = _Ids(conn)
        for raw_company, profiles in ijson.kvitems(f, ""):
            name = canonical_company(raw_company)
            company_id = ids.get(Company, name, is_general=name == GENERAL)
            for profile, levels in profiles.items():
                profile_id = ids.get(Profile, profile)
                for level, topics in levels.items():
                    rank = settings.level_difficulty.get(level, 3)
                    level_id = ids.get(Level, level, rank=rank)
                    for topic, block in topics.items():
                        topic_id = ids.get(Topic, topic, category=topic_category(topic))
                        for q in block.get("questions", []):
                            qid = parse_question_id(q["slug"])
                            if qid not in seen:
                                seen.add(qid)
                                questions.append({"id": qid, "slug": q["slug"], "text": q["question"]})
                            maps.append({
                                "question_id": qid, "company_id": company_id, "profile_id": profile_id,
                                "level_id": level_id, "topic_id": topic_id,
                            })
                            if len(maps) >= batch_size:
                                _flush(conn, questions, maps)
        _flush(conn, questions, maps)
        conn.execute(text("DELETE FROM questions_fts"))
        conn.execute(text("INSERT INTO questions_fts (question_id, text) SELECT id, text FROM questions"))
        return {
            "questions": conn.scalar(select(func.count()).select_from(Question)),
            "mappings": conn.scalar(select(func.count()).select_from(QuestionMap)),
            "companies": conn.scalar(select(func.count()).select_from(Company)),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--db", default=settings.database_url)
    parser.add_argument("--batch-size", type=int, default=settings.ingest_batch_size)
    args = parser.parse_args()
    start = time.perf_counter()
    stats = ingest(args.source, make_engine(args.db), args.batch_size)
    print(f"{stats} in {time.perf_counter() - start:.1f}s")


if __name__ == "__main__":
    main()
