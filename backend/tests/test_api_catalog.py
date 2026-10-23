"""Phase 2: GET /catalog/* through the FastAPI TestClient."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db, make_engine
from app.main import app


@pytest.fixture
def client(db_url):
    engine = make_engine(db_url)

    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def test_company_search_finds_amazon(client):
    res = client.get("/catalog/companies", params={"q": "ama"})
    assert res.status_code == 200
    assert res.json() == ["Amazon"]


def test_company_search_is_case_insensitive(client):
    assert client.get("/catalog/companies", params={"q": "AI2"}).json() == ["AI21"]


def test_companies_are_sorted_without_general_junk_or_aliases(client):
    assert client.get("/catalog/companies").json() == ["AI21", "Amazon", "Google", "Stripe"]


def test_profiles_are_listed_and_sorted(client):
    assert client.get("/catalog/profiles").json() == sorted([
        "AI Engineer", "AIOps", "Backend", "Data Engineer", "Database Developer",
        "DevOps", "Fullstack", "ML Engineer",
    ])


def test_levels_are_sorted_by_seniority(client):
    assert client.get("/catalog/levels").json() == [
        "Fresher", "SDE-1", "SDE-1/2", "SDE-2/3", "Architect/Principal",
    ]


def test_topics_are_listed_sorted_and_technical_only(client):
    topics = client.get("/catalog/topics").json()
    assert topics == sorted(topics, key=str.lower)
    assert "Kafka" in topics and "Data Structures & Algorithms" in topics
    assert "Behavioral & Leadership Principles (STAR)" not in topics


def test_topics_can_be_filtered_by_profile(client):
    backend = client.get("/catalog/topics", params={"profile": "Backend"}).json()
    everything = client.get("/catalog/topics").json()
    assert "Kafka" in backend
    assert len(backend) < len(everything)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
