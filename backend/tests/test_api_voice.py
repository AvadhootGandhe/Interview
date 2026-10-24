"""Phase 4: the voice loop through the API: audio in (STT), spoken interviewer out (TTS)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import sessions as sessions_api
from app.db.session import get_db, make_engine
from app.main import app
from app.speech import deps as speech_deps
from tests.conftest import FakeSTT, FakeTTS, RoutedLLM
from tests.factories import eval_json

BODY = {"profile": "Backend", "level": "SDE-2/3", "company": "Amazon"}
AUDIO = {"audio": ("answer.webm", b"\x1aE\xdf\xa3fake-webm", "audio/webm")}


class BrokenTTS:
    async def synthesize(self, text: str) -> str:
        raise RuntimeError("engine crashed")


class StreamTTS:
    """Has the streaming interface: first clip now, whole-text clip for backward compatibility."""

    async def synthesize_stream(self, text: str):
        from app.speech.tts import Clips

        n = len(text.split(". "))
        return Clips(urls=[f"/audio/c{i}.wav" for i in range(n)], full_url="/audio/full.wav")


@pytest.fixture
def env(db_url, tmp_path, monkeypatch):
    engine = make_engine(db_url)
    llm = RoutedLLM({"evaluate": lambda prompt, **kw: eval_json(88)})
    stt, tts = FakeSTT("I would use a queue and a cache."), FakeTTS()

    def override_db():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[sessions_api.get_llm] = lambda: llm
    app.dependency_overrides[sessions_api.get_generator] = lambda: None
    app.dependency_overrides[speech_deps.get_stt] = lambda: stt
    app.dependency_overrides[speech_deps.get_tts] = lambda: tts
    monkeypatch.setattr(sessions_api.settings, "followup_log_path", str(tmp_path / "f.jsonl"))
    yield type("Env", (), {"client": TestClient(app), "llm": llm, "stt": stt, "tts": tts})
    app.dependency_overrides.clear()
    engine.dispose()


def test_start_returns_audio_url_for_greeting_and_question(env):
    r = env.client.post("/sessions", json=BODY)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["audio_url"].startswith("/audio/")
    assert env.tts.calls == [data["text"]]  # one spoken utterance: greeting + first question
    assert "tts;dur=" in r.headers["server-timing"]


def test_audio_answer_is_transcribed_and_advances(env):
    sid = env.client.post("/sessions", json=BODY).json()["session_id"]
    r = env.client.post(f"/sessions/{sid}/answer", files=AUDIO)
    assert r.status_code == 200, r.text
    data = r.json()
    assert env.stt.calls == [b"\x1aE\xdf\xa3fake-webm"]
    assert data["transcript"] == "I would use a queue and a cache."
    assert data["audio_url"].startswith("/audio/") and data["question_index"] == 1
    assert data["messages"][0]["audio_url"] == data["audio_url"]
    timing = r.headers["server-timing"]
    for stage in ("stt", "evaluate", "flow", "interviewer", "tts", "total"):
        assert f"{stage};dur=" in timing


def test_text_answer_still_works_and_echoes_transcript(env):
    sid = env.client.post("/sessions", json=BODY).json()["session_id"]
    r = env.client.post(f"/sessions/{sid}/answer", json={"text": "typed answer"})
    assert r.status_code == 200
    assert r.json()["transcript"] == "typed answer"
    assert env.stt.calls == []


def test_silent_audio_is_calm_422_and_does_not_advance(env):
    sid = env.client.post("/sessions", json=BODY).json()["session_id"]
    env.stt.text = "   "
    r = env.client.post(f"/sessions/{sid}/answer", files=AUDIO)
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "no_speech" and "again" in body["detail"].lower()
    assert env.llm.calls_for("evaluate") == []
    ok = env.client.post(f"/sessions/{sid}/answer", json={"text": "now typed"})
    assert ok.status_code == 200 and ok.json()["question_index"] == 1


def test_empty_audio_upload_is_no_speech(env):
    sid = env.client.post("/sessions", json=BODY).json()["session_id"]
    r = env.client.post(f"/sessions/{sid}/answer", files={"audio": ("a.webm", b"", "audio/webm")})
    assert r.status_code == 422 and r.json()["code"] == "no_speech"


def test_multipart_without_audio_is_422(env):
    sid = env.client.post("/sessions", json=BODY).json()["session_id"]
    r = env.client.post(f"/sessions/{sid}/answer", data={"x": "y"}, files={"other": ("a", b"1")})
    assert r.status_code == 422


def test_tts_failure_keeps_text_and_nulls_audio(env):
    app.dependency_overrides[speech_deps.get_tts] = lambda: BrokenTTS()
    r = env.client.post("/sessions", json=BODY)
    assert r.status_code == 200
    data = r.json()
    assert data["audio_url"] is None and data["text"]
    sid = data["session_id"]
    r = env.client.post(f"/sessions/{sid}/answer", json={"text": "a"})
    assert r.status_code == 200 and r.json()["audio_url"] is None and r.json()["text"]


def test_speech_off_gives_null_audio_and_rejects_audio_answers(env):
    app.dependency_overrides[speech_deps.get_tts] = lambda: None
    app.dependency_overrides[speech_deps.get_stt] = lambda: None
    data = env.client.post("/sessions", json=BODY).json()
    assert data["audio_url"] is None
    r = env.client.post(f"/sessions/{data['session_id']}/answer", files=AUDIO)
    assert r.status_code == 503 and r.json()["code"] == "speech_unavailable"


def test_closing_reply_has_audio(env):
    sid = env.client.post("/sessions", json=BODY).json()["session_id"]
    r = env.client.post(f"/sessions/{sid}/end")
    assert r.status_code == 200 and r.json()["audio_url"].startswith("/audio/")


class TestEngineSelection:
    def test_modes(self, monkeypatch):
        s = speech_deps.settings
        monkeypatch.setattr(s, "fake_llm", False)
        monkeypatch.setattr(s, "speech", "auto")
        assert speech_deps.resolve_mode() == "real"
        monkeypatch.setattr(s, "fake_llm", True)
        assert speech_deps.resolve_mode() == "off"
        monkeypatch.setattr(s, "speech", "real")
        assert speech_deps.resolve_mode() == "real"
        monkeypatch.setattr(s, "speech", "fake")
        assert speech_deps.resolve_mode() == "fake"

    def test_off_builds_nothing_and_real_is_lazy(self, monkeypatch):
        monkeypatch.setattr(speech_deps.settings, "speech", "off")
        speech_deps.build_stt.cache_clear()
        assert speech_deps.get_stt() is None and speech_deps.get_tts() is None
        monkeypatch.setattr(speech_deps.settings, "speech", "real")
        speech_deps.build_stt.cache_clear()
        assert speech_deps.get_stt() is not None  # constructing must not import mlx
        speech_deps.build_stt.cache_clear()

    async def test_fake_engines(self, tmp_path):
        from app.speech.fake import FakeSpeechToText, FakeSpeechTTS

        assert await FakeSpeechToText().transcribe(b"") == ""
        assert await FakeSpeechToText().transcribe(b"abc")
        url = await FakeSpeechTTS(cache_dir=tmp_path).synthesize("hello there")
        assert (tmp_path / url.removeprefix("/audio/")).is_file()


def test_audio_urls_lists_per_sentence_clips_and_audio_url_stays_the_whole_text(env):
    app.dependency_overrides[speech_deps.get_tts] = lambda: StreamTTS()
    data = env.client.post("/sessions", json=BODY).json()
    assert len(data["audio_urls"]) >= 2
    assert data["audio_url"] == "/audio/full.wav"
    assert data["messages"][-1].get("audio_url") in (None, "/audio/full.wav")


def test_audio_urls_falls_back_to_single_clip_for_plain_tts(env):
    data = env.client.post("/sessions", json=BODY).json()
    assert data["audio_urls"] == [data["audio_url"]]


def test_no_speech_means_empty_audio_urls(env):
    app.dependency_overrides[speech_deps.get_tts] = lambda: None
    assert env.client.post("/sessions", json=BODY).json()["audio_urls"] == []
