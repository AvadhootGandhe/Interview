"""Phase 2: streaming ingest of the question dataset into SQLite."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select, text

from app.db.models import Company, Level, Profile, Question, QuestionMap, Topic
from app.db.session import make_engine
from scripts.ingest import canonical_company, ingest, parse_question_id, topic_category

XOR_SLUG = "xor-of-all-pairwise-bitwise-and-values-d1743"
ALIASES = {"AI21 Labs": "AI21"}


def _expected(sample_path):
    """Count the sample independently of the ingest code."""
    data = json.loads(sample_path.read_text())
    maps, slugs, topics = set(), set(), set()
    for company, profiles in data.items():
        company = "General" if company.startswith("(") else ALIASES.get(company, company)
        for profile, levels in profiles.items():
            for level, tops in levels.items():
                for topic, block in tops.items():
                    topics.add(topic)
                    for q in block["questions"]:
                        slugs.add(q["slug"])
                        maps.add((company, profile, level, topic, q["slug"]))
    return maps, slugs, topics


def _count(session, model):
    return session.scalar(select(func.count()).select_from(model))


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'ingest.db'}")
    yield eng
    eng.dispose()


def test_row_counts_match_the_sample(engine, sample_questions_path):
    from sqlalchemy.orm import Session

    stats = ingest(sample_questions_path, engine, batch_size=50)
    maps, slugs, topics = _expected(sample_questions_path)
    with Session(engine) as s:
        assert _count(s, Question) == len(slugs) == 1924
        assert _count(s, QuestionMap) == len(maps)
        assert _count(s, Profile) == 8
        assert _count(s, Level) == 5
        assert _count(s, Topic) == len(topics)
        assert s.execute(text("SELECT count(*) FROM questions_fts")).scalar() == 1924
    assert stats["questions"] == 1924
    assert stats["mappings"] == len(maps)


def test_junk_company_keys_merge_into_one_general_company(db):
    names = set(db.scalars(select(Company.name)))
    assert names == {"General", "AI21", "Amazon", "Google", "Stripe"}
    general = db.scalar(select(Company).where(Company.name == "General"))
    assert general.is_general is True
    assert db.scalar(select(func.count()).where(Company.is_general.is_(True))) == 1
    assert db.scalar(select(func.count()).where(QuestionMap.company_id == general.id)) > 0


def test_aliases_are_merged(db, sample_questions_path):
    maps, _, _ = _expected(sample_questions_path)
    ai21 = db.scalar(select(Company).where(Company.name == "AI21"))
    assert db.scalar(select(Company).where(Company.name == "AI21 Labs")) is None
    got = db.scalar(select(func.count()).where(QuestionMap.company_id == ai21.id))
    assert got == sum(1 for m in maps if m[0] == "AI21")


@pytest.mark.parametrize(
    "raw, canonical",
    [
        ("(base list empty)", "General"),
        ("(none provided)", "General"),
        ("<<<FIELD:companies>>>", "General"),
        ("", "General"),
        ("AI21 Labs", "AI21"),
        ("37signals/Basecamp", "37signals"),
        ("Amazon", "Amazon"),
    ],
)
def test_canonical_company(raw, canonical):
    assert canonical_company(raw) == canonical


def test_question_ids_are_parsed_from_the_slug_suffix(db):
    assert parse_question_id(XOR_SLUG) == "d1743"
    slug = "tell-me-about-a-time-you-strongly-disagreed-with-your-tech-lead-on-an--21834"
    assert parse_question_id(slug) == "21834"
    assert db.get(Question, "21834").slug == slug
    assert db.get(Question, "d1743").slug == XOR_SLUG


def test_duplicate_slugs_are_stored_once(db):
    assert db.scalar(select(func.count()).where(Question.slug == XOR_SLUG)) == 1
    # ...but every (company, profile, level, topic) it appears under is mapped.
    assert db.scalar(select(func.count()).where(QuestionMap.question_id == "d1743")) > 1


def test_reingest_is_idempotent(engine, sample_questions_path):
    from sqlalchemy.orm import Session

    ingest(sample_questions_path, engine)
    with Session(engine) as s:
        before = [_count(s, m) for m in (Company, Profile, Level, Topic, Question, QuestionMap)]
    ingest(sample_questions_path, engine)
    with Session(engine) as s:
        after = [_count(s, m) for m in (Company, Profile, Level, Topic, Question, QuestionMap)]
        assert s.execute(text("SELECT count(*) FROM questions_fts")).scalar() == 1924
    assert before == after


def test_levels_carry_a_difficulty_rank(db):
    ranks = {lv.name: lv.rank for lv in db.scalars(select(Level))}
    assert ranks == {"Fresher": 1, "SDE-1": 2, "SDE-1/2": 3, "SDE-2/3": 4, "Architect/Principal": 5}


@pytest.mark.parametrize(
    "topic, category",
    [
        ("Data Structures & Algorithms", "dsa"),
        ("Time & Space Complexity", "dsa"),
        ("Behavioral & Leadership Principles (STAR)", "behavioral"),
        ("Cross-team Technical Leadership & Influence", "behavioral"),
        ("Kafka", "technical"),
        ("System Design", "technical"),
    ],
)
def test_topic_categories(topic, category, db):
    assert topic_category(topic) == category
    stored = db.scalar(select(Topic).where(Topic.name == topic))
    if stored is not None:
        assert stored.category == category
