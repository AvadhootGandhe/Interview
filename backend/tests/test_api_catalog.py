from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.main import create_app
from scripts.ingest import ingest

ROOT = Path(__file__).resolve().parents[2]
ALIASES = Path(__file__).resolve().parents[1] / "data" / "company_aliases.json"


@pytest.fixture(scope="module")
def client():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    ingest(ROOT / "data" / "sample_questions.json", eng, ALIASES)
    return TestClient(create_app(eng))


def test_company_search_finds_amazon(client):
    names = client.get("/catalog/companies", params={"q": "ama"}).json()
    assert "Amazon" in names


def test_company_search_excludes_general_and_is_case_insensitive(client):
    assert "General" not in client.get("/catalog/companies").json()
    assert client.get("/catalog/companies", params={"q": "AMAZ"}).json() == ["Amazon"]


def test_company_search_respects_limit(client):
    assert len(client.get("/catalog/companies", params={"limit": 2}).json()) == 2


def test_profiles_listed_sorted(client):
    profiles = client.get("/catalog/profiles").json()
    assert profiles == sorted(profiles) and "Backend" in profiles and len(profiles) == 8


def test_levels_ordered_by_rank(client):
    assert client.get("/catalog/levels").json() == ["Fresher", "SDE-1", "SDE-1/2", "SDE-2/3", "Architect/Principal"]


def test_topics_filtered_by_profile_and_company_sorted(client):
    topics = client.get("/catalog/topics", params={"profile": "Backend", "company": "Amazon"}).json()
    assert topics == sorted(topics) and "Kafka" in topics
    assert "Behavioral & Leadership Principles (STAR)" not in topics  # behavioral is a later track
    assert client.get("/catalog/topics", params={"profile": "Nope"}).json() == []
