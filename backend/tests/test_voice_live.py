"""Live voice E2E (Mac only): hello.wav through real STT, fake LLM, real TTS, audio served."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

pytestmark = pytest.mark.local


def test_hello_wav_answer_gets_spoken_reply(db_url, fixtures_dir, tmp_path, monkeypatch):
    from app.api import audio as audio_api
    from app.api import sessions as sessions_api
    from app.db.session import get_db, make_engine
    from app.llm.fake import DemoLLM
    from app.main import app
    from app.speech import deps
    from app.speech.stt import SpeechToText
    from app.speech.tts import TextToSpeech

    monkeypatch.setattr(audio_api, "AUDIO_DIR", tmp_path)
    engine = make_engine(db_url)

    def override_db():
        with Session(engine) as s:
            yield s

    llm = DemoLLM()
    stt, tts = SpeechToText(), TextToSpeech(cache_dir=tmp_path)
    app.dependency_overrides.update({
        get_db: override_db, sessions_api.get_llm: lambda: llm, sessions_api.get_generator: lambda: None,
        deps.get_stt: lambda: stt, deps.get_tts: lambda: tts,
    })
    monkeypatch.setattr(sessions_api.settings, "followup_log_path", str(tmp_path / "f.jsonl"))
    try:
        c = TestClient(app)
        start = c.post("/sessions", json={"profile": "Backend", "level": "SDE-2/3"}).json()
        r = c.post(f"/sessions/{start['session_id']}/answer",
                   files={"audio": ("hello.wav", (fixtures_dir / "hello.wav").read_bytes(), "audio/wav")})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "hello" in data["transcript"].lower()
        served = c.get(data["audio_url"])
        assert served.status_code == 200 and len(served.content) > 1000
        print("\nServer-Timing:", r.headers["server-timing"])
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
