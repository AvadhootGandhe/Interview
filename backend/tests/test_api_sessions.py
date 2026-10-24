from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.db.models import Base
from app.llm.fake_llm import FakeInterviewLLM, NoGenerator
from app.main import create_app
from scripts.ingest import ingest

ROOT = Path(__file__).resolve().parents[2]
ALIASES = Path(__file__).resolve().parents[1] / "data" / "company_aliases.json"
BODY = {"profile": "Backend", "level": "SDE-2/3", "company": "Amazon"}
STRONG = "I would shard by tenant, add a write-through cache, and monitor replication lag and failure modes carefully."


@pytest.fixture
def client(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'api.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    ingest(ROOT / "data" / "sample_questions.json", eng, ALIASES)
    app = create_app(eng, llm=FakeInterviewLLM(), generator=NoGenerator(), followup_log=tmp_path / "f.jsonl")
    return TestClient(app)


def test_create_session_returns_greeting_and_first_question(client):
    r = client.post("/sessions", json=BODY)
    assert r.status_code == 200
    data = r.json()
    assert data["session_id"] and len(data["messages"]) == 2


def test_weak_answer_gets_follow_up_then_strong_moves_on(client):
    sid = client.post("/sessions", json=BODY).json()["session_id"]
    weak = client.post(f"/sessions/{sid}/answer", json={"text": "dunno"}).json()
    assert weak["kind"] == "follow_up" and weak["state"] == "active"
    strong = client.post(f"/sessions/{sid}/answer", json={"text": STRONG}).json()
    assert strong["kind"] == "ask"


def test_full_interview_to_report(client):
    sid = client.post("/sessions", json=BODY).json()["session_id"]
    state = "active"
    for _ in range(12):
        state = client.post(f"/sessions/{sid}/answer", json={"text": STRONG}).json()["state"]
        if state == "done":
            break
    assert state == "done"
    report = client.get(f"/sessions/{sid}/report").json()
    assert 0 <= report["overall_score"] <= 100 and 4 <= len(report["questions"]) <= 6
    assert report["strengths"] and report["gaps"] and report["verdict"]


def test_end_early_then_answer_conflicts(client):
    sid = client.post("/sessions", json=BODY).json()["session_id"]
    assert client.post(f"/sessions/{sid}/end").json()["state"] == "done"
    assert client.post(f"/sessions/{sid}/answer", json={"text": "late"}).status_code == 409


def test_unknown_session_404(client):
    assert client.post("/sessions/nope/answer", json={"text": "x"}).status_code == 404
    assert client.get("/sessions/nope/report").status_code == 404


def test_unknown_profile_is_a_clean_422(client):
    r = client.post("/sessions", json={"profile": "Astronaut"})
    assert r.status_code == 422


def test_empty_answer_is_rejected(client):
    sid = client.post("/sessions", json=BODY).json()["session_id"]
    assert client.post(f"/sessions/{sid}/answer", json={"text": "  "}).status_code == 422
