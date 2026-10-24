"""Phase 3: the interview REST API (text answers) through the FastAPI TestClient."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from helpers import ScriptedLLM, eval_json
from sqlalchemy.orm import Session

from app.api.sessions import get_generator, get_llm
from app.db.session import get_db, make_engine
from app.main import app

BODY = {"profile": "Backend", "level": "SDE-2/3"}
LONG = "I would put a cache in front with a TTL and eviction, and measure the hit rate before tuning."


@pytest.fixture
def llm():
    return ScriptedLLM()


@pytest.fixture
def client(db_url, llm, train_log):
    engine = make_engine(db_url)

    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_generator] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def test_create_session_returns_greeting_and_first_question(client):
    res = client.post("/sessions", json=BODY)
    assert res.status_code == 200
    data = res.json()
    assert data["session_id"] and [m["kind"] for m in data["messages"]] == ["greeting", "ask"]
    assert data["text"] and 4 <= data["progress"]["total"] <= 6 and data["progress"]["current"] == 1


def test_full_interview_from_create_to_report(client, llm):
    llm.replies["evaluator"] = [eval_json(40), eval_json(80)] + [eval_json(85)] * 10
    created = client.post("/sessions", json={**BODY, "company": "Amazon", "user_id": "u1"}).json()
    sid, total = created["session_id"], created["progress"]["total"]

    first = client.post(f"/sessions/{sid}/answer", json={"text": "not sure"}).json()
    assert first["kind"] == "follow_up" and not first["done"] and first["evaluation"]["satisfaction"] == 40

    last, answers = first, 0
    while not last["done"]:
        last = client.post(f"/sessions/{sid}/answer", json={"text": LONG}).json()
        answers += 1
        assert answers <= total + 1
    assert last["kind"] == "closing"

    report = client.get(f"/sessions/{sid}/report")
    assert report.status_code == 200
    body = report.json()
    assert len(body["questions"]) == total
    assert 0 <= body["overall_score"] <= 100
    assert body["strengths"] and body["gaps"] and body["verdict"]
    assert body["questions"][0]["followups"] == 1 and body["questions"][0]["final_score"] == 75


def test_end_finishes_early_and_report_is_available(client):
    sid = client.post("/sessions", json=BODY).json()["session_id"]
    client.post(f"/sessions/{sid}/answer", json={"text": LONG})
    ended = client.post(f"/sessions/{sid}/end").json()
    assert ended["kind"] == "closing" and ended["done"]
    assert client.get(f"/sessions/{sid}/report").status_code == 200


def test_report_before_the_end_is_a_conflict(client):
    sid = client.post("/sessions", json=BODY).json()["session_id"]
    assert client.get(f"/sessions/{sid}/report").status_code == 409


def test_answering_a_finished_session_is_a_conflict(client):
    sid = client.post("/sessions", json=BODY).json()["session_id"]
    client.post(f"/sessions/{sid}/end")
    assert client.post(f"/sessions/{sid}/answer", json={"text": "hi"}).status_code == 409


def test_unknown_session_is_404(client):
    assert client.post("/sessions/nope/answer", json={"text": "hi"}).status_code == 404
    assert client.post("/sessions/nope/end").status_code == 404
    assert client.get("/sessions/nope/report").status_code == 404


def test_unknown_profile_is_422(client):
    assert client.post("/sessions", json={"profile": "Underwater Basket Weaving"}).status_code == 422
    assert client.post("/sessions", json={}).status_code == 422


def test_answer_needs_text(client):
    sid = client.post("/sessions", json=BODY).json()["session_id"]
    assert client.post(f"/sessions/{sid}/answer", json={}).status_code == 422


def test_evaluator_failure_is_a_retryable_502(client, llm):
    sid = client.post("/sessions", json=BODY).json()["session_id"]
    llm.replies["evaluator"] = ["bad", "bad", eval_json(85)]
    assert client.post(f"/sessions/{sid}/answer", json={"text": LONG}).status_code == 502
    assert client.post(f"/sessions/{sid}/answer", json={"text": LONG}).status_code == 200
