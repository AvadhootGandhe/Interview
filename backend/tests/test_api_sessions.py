"""Phase 3: create session -> answer in text -> ... -> report, through the FastAPI TestClient."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import sessions as sessions_api
from app.db.session import get_db, make_engine
from app.main import app
from tests.conftest import RoutedLLM
from tests.factories import eval_json

BODY = {"profile": "Backend", "level": "SDE-2/3", "company": "Amazon"}


@pytest.fixture
def client(db_url, tmp_path, monkeypatch):
    engine = make_engine(db_url)
    llm = RoutedLLM({"evaluate": lambda prompt, **kw: eval_json(88)})

    def override_db():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[sessions_api.get_llm] = lambda: llm
    app.dependency_overrides[sessions_api.get_generator] = lambda: None
    monkeypatch.setattr(sessions_api.settings, "followup_log_path", str(tmp_path / "f.jsonl"))
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def test_full_interview_to_report(client):
    r = client.post("/sessions", json=BODY)
    assert r.status_code == 200, r.text
    start = r.json()
    sid, total = start["session_id"], start["total_questions"]
    assert start["state"] == "asking" and start["text"] and start["kind"] == "ask" and 4 <= total <= 6

    last = start
    for i in range(total):
        r = client.post(f"/sessions/{sid}/answer", json={"text": "A thorough answer about trade-offs."})
        assert r.status_code == 200, r.text
        last = r.json()
        assert last["done"] == (i == total - 1)
    assert last["kind"] == "closing" and last["state"] == "done"

    report = client.get(f"/sessions/{sid}/report")
    assert report.status_code == 200
    data = report.json()
    assert data["overall_score"] == 88 and len(data["questions"]) == total
    assert data["strengths"] and data["gaps"] and data["verdict"]
    assert data["questions"][0]["thread"][0]["role"] == "interviewer"


def test_end_endpoint_closes_early(client):
    sid = client.post("/sessions", json=BODY).json()["session_id"]
    client.post(f"/sessions/{sid}/answer", json={"text": "answer"})
    r = client.post(f"/sessions/{sid}/end")
    assert r.status_code == 200 and r.json()["done"]
    assert len(client.get(f"/sessions/{sid}/report").json()["questions"]) == 1


def test_error_responses(client):
    assert client.post("/sessions", json={**BODY, "profile": "Astronaut"}).status_code == 422
    assert client.post("/sessions/nope/answer", json={"text": "hi"}).status_code == 404
    assert client.get("/sessions/nope/report").status_code == 404
    sid = client.post("/sessions", json=BODY).json()["session_id"]
    assert client.get(f"/sessions/{sid}/report").status_code == 409  # not finished yet
    assert client.post(f"/sessions/{sid}/answer", json={"text": ""}).status_code == 422
    client.post(f"/sessions/{sid}/end")
    assert client.post(f"/sessions/{sid}/answer", json={"text": "late"}).status_code == 409


def test_session_requires_an_api_key_unless_fake_llm(monkeypatch):
    from app.llm import factory

    monkeypatch.setattr(factory.settings, "anthropic_api_key", "")
    monkeypatch.setattr(factory.settings, "fake_llm", False)
    factory.get_llm.cache_clear()
    with pytest.raises(Exception, match="ANTHROPIC_API_KEY"):
        factory.get_llm()
    factory.get_llm.cache_clear()
