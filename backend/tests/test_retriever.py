"""Phase 2: retriever (SQLite filters + widening + FTS5) on the sample data."""
from __future__ import annotations

import re
from collections import Counter

import pytest

from app.config import settings
from app.db.models import InterviewSession, Turn
from app.services.retriever import STAGES, Filters, PoolItem, Retriever, level_difficulty

PROFILES = ["Backend", "DevOps", "Fullstack", "AI Engineer", "ML Engineer",
            "Database Developer", "Data Engineer", "AIOps"]
LEVELS = ["Fresher", "SDE-1", "SDE-1/2", "SDE-2/3", "Architect/Principal"]

COMBOS = [
    Filters(),
    Filters(profile="Backend"),
    Filters(level="SDE-2/3"),
    Filters(company="Amazon"),
    Filters(topic="Kafka"),
    Filters(profile="Backend", level="SDE-2/3"),
    Filters(profile="Backend", level="SDE-2/3", company="Amazon"),
    Filters(profile="Backend", level="SDE-2/3", company="Amazon", topic="Kafka"),
    Filters(profile="AI Engineer", level="Fresher", company="AI21 Labs"),
    Filters(profile="DevOps", company="Unknown Startup"),
    Filters(profile="Fullstack", company="General"),
]


@pytest.fixture
def retriever(db) -> Retriever:
    return Retriever(db)


def _ids(pool):
    return [p.id for p in pool]


# --- filters and pool shape --------------------------------------------------

@pytest.mark.parametrize("filters", COMBOS, ids=str)
def test_any_filter_combination_returns_a_pool_of_distinct_questions(retriever, filters):
    pool = retriever.build_pool(filters)
    assert 0 < len(pool) <= settings.pool_size == 40
    assert len(set(_ids(pool))) == len(pool)


@pytest.mark.parametrize("filters", COMBOS[:4] + COMBOS[5:7], ids=str)
def test_no_topic_means_several_topics_and_none_over_40_percent(retriever, filters):
    pool = retriever.build_pool(filters)
    counts = Counter(p.topic for p in pool)
    assert len(counts) >= 3
    assert max(counts.values()) <= settings.topic_max_share * len(pool)


def test_topic_matches_come_first_then_the_pool_widens(retriever):
    pool = retriever.build_pool(Filters(profile="Backend", topic="Kafka"))
    is_kafka = [p.topic == "Kafka" for p in pool]
    assert is_kafka[0] and is_kafka == sorted(is_kafka, reverse=True)


def test_no_topic_leaves_out_behavioral_topics(retriever):
    pool = retriever.build_pool(Filters(profile="Backend", level="SDE-2/3", company="Amazon"))
    assert "Behavioral & Leadership Principles (STAR)" not in {p.topic for p in pool}


def test_pool_items_carry_id_topic_text_source_difficulty(retriever):
    for item in retriever.build_pool(Filters(profile="Backend")):
        assert isinstance(item, PoolItem)
        assert item.id and item.topic and item.text
        assert item.source == "dataset"
        assert 1 <= item.difficulty <= 5


# --- difficulty --------------------------------------------------------------

@pytest.mark.parametrize("level, rank", list(zip(LEVELS, [1, 2, 3, 4, 5])))
def test_level_difficulty(level, rank):
    assert level_difficulty(level) == rank


@pytest.mark.parametrize("level, rank", [("Fresher", 1), ("Architect/Principal", 5)])
def test_difficulty_comes_from_the_level_the_question_came_from(retriever, level, rank):
    pool = retriever.build_pool(Filters(profile="Backend", level=level))
    level_matched = [p for p in pool if p.match in ("exact", "drop_company", "general")]
    assert level_matched and all(p.difficulty == rank for p in level_matched)


# --- widening ----------------------------------------------------------------

def test_widening_order_is_drop_company_then_general_then_drop_level():
    assert STAGES[:4] == ("exact", "drop_company", "general", "drop_level")


def test_pool_is_filled_in_widening_order(retriever):
    pool = retriever.build_pool(
        Filters(profile="Backend", level="SDE-1", company="Amazon", topic="Kafka"))
    order = [STAGES.index(p.match) for p in pool]
    assert order == sorted(order)
    assert pool[0].match == "exact" and pool[0].company_specific
    assert len(set(order)) > 1  # only 4 exact matches, so it widened


def test_sparse_filters_widen_to_other_levels(retriever):
    # AI21 has no Fresher questions at all.
    pool = retriever.build_pool(Filters(profile="AI Engineer", level="Fresher", company="AI21"))
    assert pool and not any(p.company_specific and p.match == "exact" for p in pool)


@pytest.mark.parametrize("profile", PROFILES)
def test_never_empty_when_the_profile_has_questions(retriever, profile):
    pool = retriever.build_pool(
        Filters(profile=profile, level="Fresher", company="AI21", topic="Snowflake"))
    assert pool


def test_unknown_company_counts_as_no_company(retriever):
    pool = retriever.build_pool(Filters(profile="Backend", company="Nope Inc"))
    assert pool and not any(p.company_specific for p in pool)


def test_unknown_profile_raises(retriever):
    with pytest.raises(ValueError):
        retriever.build_pool(Filters(profile="Astronaut"))


def test_company_with_matches_is_at_least_70_percent_company_specific(retriever):
    pool = retriever.build_pool(Filters(profile="Backend", level="SDE-2/3", company="Amazon"))
    share = sum(p.company_specific for p in pool) / len(pool)
    assert share >= settings.company_min_share


# --- recent sessions ---------------------------------------------------------

def test_excludes_questions_from_the_users_recent_sessions(db, retriever):
    filters = Filters(profile="Backend", level="SDE-2/3", company="Amazon")
    asked = _ids(retriever.build_pool(filters))[:10]
    db.add(InterviewSession(id="s1", user_id="u1", profile="Backend"))
    db.add_all(Turn(session_id="s1", question_id=qid, text="q") for qid in asked)
    db.commit()

    assert not set(asked) & set(_ids(retriever.build_pool(filters, user_id="u1")))
    # Another user is not affected (the whole company stage is available to them).
    other = retriever.build_pool(filters, user_id="u2")
    assert set(asked) <= set(_ids(other))


# --- FTS5 search -------------------------------------------------------------

@pytest.fixture
def big_pool(retriever):
    return retriever.build_pool(Filters(), size=5000)


def test_search_ranks_caching_questions_first(retriever, big_pool):
    hits = retriever.search("redis cache eviction", big_pool)
    assert hits
    top = hits[0].text.lower()
    assert sum(w in top for w in ("redis", "cach", "evict")) >= 2
    for hit in hits[:3]:
        assert re.search(r"redis|cach|evict", hit.text, re.I)


def test_search_kafka_finds_queue_and_streaming_questions(retriever, big_pool):
    hits = retriever.search("kafka", big_pool)
    assert hits and all("kafka" in h.text.lower() for h in hits)
    assert "Kafka" in {h.topic for h in hits}


def test_search_accepts_a_list_of_terms(retriever, big_pool):
    assert retriever.search(["Kafka"], big_pool)


def test_search_only_returns_pool_items(retriever):
    pool = retriever.build_pool(Filters(profile="Backend", level="SDE-2/3", company="Amazon"))
    hits = retriever.search("kafka consumer partition", pool)
    assert set(_ids(hits)) <= set(_ids(pool))


@pytest.mark.parametrize("terms", ["", "   ", "the and of", "is a to", '"*:()^', []])
def test_search_returns_empty_on_stop_words_or_empty_input(retriever, big_pool, terms):
    assert retriever.search(terms, big_pool) == []


def test_search_on_an_empty_pool(retriever):
    assert retriever.search("redis", []) == []
