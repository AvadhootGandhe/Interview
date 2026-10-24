"""Latency: speech engines are warmed in the background at server start (G4)."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.speech import tts as tts_mod
from app.speech.warmup import warm_up_speech
from tests.test_tts import FakeEngine as FakeTTSEngine


class Warmable:
    def __init__(self, fail=False):
        self.fail, self.warmed = fail, 0

    def warm_up(self) -> None:
        self.warmed += 1
        if self.fail:
            raise RuntimeError("model missing")


async def test_warm_up_calls_each_engine():
    stt, tts = Warmable(), Warmable()
    await warm_up_speech(stt, tts)
    assert (stt.warmed, tts.warmed) == (1, 1)


async def test_warm_up_tolerates_failure_and_missing_engines():
    tts = Warmable()
    await warm_up_speech(Warmable(fail=True), tts)  # failing STT must not stop TTS or raise
    assert tts.warmed == 1
    await warm_up_speech(None, object())  # speech off / engine without warm_up


def test_text_to_speech_warm_up_synthesizes_a_short_phrase(tmp_path):
    engine = FakeTTSEngine()
    tts_mod.TextToSpeech(engine, cache_dir=tmp_path).warm_up()
    assert len(engine.calls) == 1
    assert list(tmp_path.iterdir()) == []  # warm-up leaves no cache file behind


def test_lifespan_starts_warm_up_in_background_and_health_is_immediate(monkeypatch):
    started, finished = [], []
    stt, tts = Warmable(), Warmable()

    async def slow_warm(s, t):
        started.append((s, t))
        await asyncio.sleep(0.5)
        finished.append(1)

    monkeypatch.setattr("app.main.warm_up_speech", slow_warm)
    monkeypatch.setattr("app.main.get_stt", lambda: stt)
    monkeypatch.setattr("app.main.get_tts", lambda: tts)
    with TestClient(app) as c:
        assert c.get("/health").json() == {"status": "ok"}
        assert finished == []  # health did not wait for warm-up
    assert started == [(stt, tts)]
