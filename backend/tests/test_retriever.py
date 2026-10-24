from pathlib import Path
from collections import Counter

import pytest
from sqlalchemy import create_engine

from app.db.models import Base
from app.services.retriever import Filters, PoolItem, build_pool, search
from scripts.ingest import ingest

ROOT = Path(__file__).resolve().parents[2]
ALIASES = Path(__file__).resolve().parents[1] / "data" / "company_aliases.json"


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    ingest(ROOT / "data" / "sample_questions.json", eng, ALIASES)
    return eng


def test_all_filters_optional_and_pool_is_distinct_and_bounded(engine):
    for f in [Filters(profile="Backend"),
              Filters(profile="Backend", level="SDE-2/3"),
              Filters(profile="Backend", level="SDE-2/3", company="Amazon"),
              Filters(profile="Backend", company="Google", topic="Kafka")]:
        pool = build_pool(engine, f, size=40, seed=1)
        assert 0 < len(pool) <= 40
        assert len({p.id for p in pool}) == len(pool)


def test_pool_items_carry_required_fields(engine):
    item = build_pool(engine, Filters(profile="Backend", level="Fresher", company="Amazon"), seed=1)[0]
    assert isinstance(item, PoolItem)
    assert item.id and item.topic and item.text
    assert item.source == "dataset"
    assert item.difficulty == 1


def test_difficulty_follows_level_rank(engine):
    pool = build_pool(engine, Filters(profile="Backend", level="Architect/Principal", company="Amazon"), size=10, seed=1)
    assert {p.difficulty for p in pool} == {5}


def test_no_topic_covers_several_topics_and_none_dominates(engine):
    pool = build_pool(engine, Filters(profile="Backend", level="SDE-2/3", company="Amazon"), size=40, seed=2)
    counts = Counter(p.topic for p in pool)
    assert len(counts) >= 4
    assert max(counts.values()) <= 0.4 * len(pool)


def test_topic_filter_respected_when_enough_questions(engine):
    pool = build_pool(engine, Filters(profile="Backend", topic="Kafka"), size=3, seed=1)
    assert pool and all(p.topic == "Kafka" for p in pool)


def test_company_specific_first(engine):
    pool = build_pool(engine, Filters(profile="Backend", level="SDE-2/3", company="Amazon"), seed=1)
    assert all(p.company_specific for p in pool[:20])
    assert sum(p.company_specific for p in pool) / len(pool) >= 0.7


def test_widens_when_sparse_and_never_empty(engine):
    # AI21 has very few questions; unknown company has none at all.
    for company in ("AI21", "No Such Co"):
        pool = build_pool(engine, Filters(profile="Backend", level="SDE-2/3", company=company, topic="Kafka"),
                          size=40, seed=1)
        assert len(pool) > 0
    pool = build_pool(engine, Filters(profile="Backend", level="SDE-2/3", company="AI21"), size=40, seed=1)
    assert len(pool) == 40


def test_unknown_profile_returns_empty_without_crashing(engine):
    assert build_pool(engine, Filters(profile="Nope"), seed=1) == []


def test_excludes_recent_question_ids(engine):
    f = Filters(profile="Backend", level="SDE-2/3", company="Amazon")
    first = build_pool(engine, f, seed=1)
    banned = {p.id for p in first[:10]}
    again = build_pool(engine, f, seed=1, exclude_ids=banned)
    assert not banned & {p.id for p in again}


def test_seed_makes_pool_deterministic(engine):
    f = Filters(profile="Backend")
    assert [p.id for p in build_pool(engine, f, seed=7)] == [p.id for p in build_pool(engine, f, seed=7)]


def _all_pool(engine):
    return build_pool(engine, Filters(profile="Backend"), size=400, seed=3)


def test_fts_ranks_matching_questions_first(engine):
    pool = _all_pool(engine)
    hits = search(engine, "redis cache eviction", pool)
    assert hits
    top = hits[0].text.lower()
    assert any(w in top for w in ("redis", "cache", "evict"))
    assert set(h.id for h in hits) <= {p.id for p in pool}


def test_fts_kafka_finds_streaming_questions(engine):
    hits = search(engine, "kafka", _all_pool(engine))
    assert hits and all("kafka" in h.text.lower() for h in hits)


@pytest.mark.parametrize("q", ["", "   ", "the a of", "!!! ???", 'a" OR "'])
def test_fts_empty_or_stopword_input_returns_empty(engine, q):
    assert search(engine, q, _all_pool(engine)) == []


@pytest.mark.parametrize("f", [
    Filters(profile="Backend", level="SDE-2/3", company="Amazon"),
    Filters(profile="Backend"),
    Filters(profile="Fullstack", company="Google"),
])
def test_pool_excludes_behavioral_topics(engine, f):
    for seed in range(5):
        assert not any(p.topic.startswith("Behavioral") for p in build_pool(engine, f, seed=seed))
