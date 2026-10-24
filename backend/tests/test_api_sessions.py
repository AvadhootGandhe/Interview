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


# ---- speech ---------------------------------------------------------------------------------
from tests.conftest import FakeSTT, FakeTTS  # noqa: E402


@pytest.fixture
def speech_client(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'sp.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    ingest(ROOT / "data" / "sample_questions.json", eng, ALIASES)
    stt = FakeSTT(STRONG)
    app = create_app(eng, llm=FakeInterviewLLM(), generator=NoGenerator(), followup_log=tmp_path / "f.jsonl",
                     stt=stt, tts=FakeTTS(), audio_dir=tmp_path / "audio")
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "fake.wav").write_bytes(b"RIFFdata")
    return TestClient(app), stt


def test_create_returns_audio_url_per_message(speech_client):
    client, _ = speech_client
    data = client.post("/sessions", json=BODY).json()
    assert data["audio_urls"] == ["/audio/fake.wav"] * len(data["messages"])


def test_audio_answer_is_transcribed_then_processed(speech_client):
    client, _ = speech_client
    sid = client.post("/sessions", json=BODY).json()["session_id"]
    r = client.post(f"/sessions/{sid}/audio", files={"audio": ("a.webm", b"bytes", "audio/webm")})
    assert r.status_code == 200
    data = r.json()
    assert data["transcript"] == STRONG and data["kind"] == "ask"
    assert data["audio_urls"] == ["/audio/fake.wav"]


def test_unintelligible_audio_gets_calm_422(speech_client):
    client, stt = speech_client
    stt.text = ""
    sid = client.post("/sessions", json=BODY).json()["session_id"]
    r = client.post(f"/sessions/{sid}/audio", files={"audio": ("a.webm", b"x", "audio/webm")})
    assert r.status_code == 422 and "hear" in r.json()["detail"].lower()


def test_audio_files_are_served(speech_client):
    client, _ = speech_client
    r = client.get("/audio/fake.wav")
    assert r.status_code == 200 and r.content == b"RIFFdata"
    assert client.get("/audio/missing.wav").status_code == 404


def test_audio_route_without_stt_is_501(client):
    sid = client.post("/sessions", json=BODY).json()["session_id"]
    r = client.post(f"/sessions/{sid}/audio", files={"audio": ("a.webm", b"x", "audio/webm")})
    assert r.status_code == 501
