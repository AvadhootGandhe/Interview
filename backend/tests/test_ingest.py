import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.db.models import Base
from scripts.ingest import ingest

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample_questions.json"
ALIASES = Path(__file__).resolve().parents[1] / "data" / "company_aliases.json"


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return eng


def scalar(eng, sql, **p):
    with eng.connect() as c:
        return c.execute(text(sql), p).scalar()


def expected_unique_slugs(sample):
    return {q["slug"] for c in sample.values() for p in c.values() for l in p.values()
            for t in l.values() for q in t["questions"]}


def test_row_counts_match_sample(engine, sample_questions):
    ingest(SAMPLE, engine, ALIASES)
    assert scalar(engine, "select count(*) from questions") == len(expected_unique_slugs(sample_questions))
    assert scalar(engine, "select count(*) from profiles") == 8
    assert scalar(engine, "select count(*) from levels") == 5


def test_junk_companies_merge_into_general(engine):
    ingest(SAMPLE, engine, ALIASES)
    names = {r[0] for r in engine.connect().execute(text("select name from companies"))}
    assert "General" in names
    assert not any(n.startswith(("(", "<")) for n in names)
    assert scalar(engine, "select is_general from companies where name='General'") == 1


def test_aliases_are_merged(engine):
    ingest(SAMPLE, engine, ALIASES)
    names = {r[0] for r in engine.connect().execute(text("select name from companies"))}
    assert "AI21" in names and "AI21 Labs" not in names


def test_slug_suffix_parsed_as_ext_id(engine):
    ingest(SAMPLE, engine, ALIASES)
    assert scalar(engine, "select ext_id from questions where slug like '%-d1743'") == "d1743"
    assert scalar(engine, "select ext_id from questions where slug like '%-86840'") == "86840"


def test_duplicate_slugs_stored_once(engine):
    ingest(SAMPLE, engine, ALIASES)
    assert scalar(engine, "select count(*) from (select slug from questions group by slug having count(*)>1)") == 0


def test_level_rank_and_topic_category(engine):
    ingest(SAMPLE, engine, ALIASES)
    assert scalar(engine, "select rank from levels where name='Fresher'") == 1
    assert scalar(engine, "select rank from levels where name='Architect/Principal'") == 5
    assert scalar(engine, "select category from topics where name like 'Behavioral%'") == "behavioral"
    assert scalar(engine, "select category from topics where name='Data Structures & Algorithms'") == "dsa"


def test_fts_index_populated(engine):
    ingest(SAMPLE, engine, ALIASES)
    n = scalar(engine, "select count(*) from questions")
    assert scalar(engine, "select count(*) from questions_fts") == n
    assert scalar(engine, "select count(*) from questions_fts where questions_fts match 'positional'") >= 1


def test_ingest_is_idempotent(engine):
    ingest(SAMPLE, engine, ALIASES)
    snap = [scalar(engine, f"select count(*) from {t}") for t in
            ("companies", "questions", "question_map", "questions_fts")]
    ingest(SAMPLE, engine, ALIASES)
    assert snap == [scalar(engine, f"select count(*) from {t}") for t in
                    ("companies", "questions", "question_map", "questions_fts")]
