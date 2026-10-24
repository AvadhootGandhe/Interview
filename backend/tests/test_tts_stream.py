"""Latency: first sentence is synthesized first and returned at once; the rest renders in the background."""
from __future__ import annotations

import threading
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import audio
from app.speech import tts
from tests.test_tts import tone


class GatedEngine:
    """Sentence 1 is instant; later sentences wait for `gate`."""

    def __init__(self):
        self.calls: list[str] = []
        self.gate = threading.Event()

    def synth_wav(self, text: str) -> bytes:
        self.calls.append(text)
        if len(self.calls) > 1:
            assert self.gate.wait(5)
        return tone()


TEXT = "First one. Second one? Third one!"


async def test_returns_after_first_sentence_only(tmp_path):
    engine = GatedEngine()
    svc = tts.TextToSpeech(engine, cache_dir=tmp_path)
    clips = await svc.synthesize_stream(TEXT)
    assert len(clips.urls) == 3 and clips.full_url.startswith("/audio/")
    assert engine.calls == ["First one."]
    assert (tmp_path / clips.urls[0].removeprefix("/audio/")).exists()
    assert not (tmp_path / clips.urls[1].removeprefix("/audio/")).exists()
    engine.gate.set()
    await svc.wait_idle()
    names = [u.removeprefix("/audio/") for u in [*clips.urls, clips.full_url]]
    assert all((tmp_path / n).exists() for n in names)
    with wave.open(str(tmp_path / clips.full_url.removeprefix("/audio/"))) as w:
        assert w.getnframes() == 3 * 2400  # full clip = the three sentences joined
    assert engine.calls == ["First one.", "Second one?", "Third one!"]


async def test_single_sentence_has_one_clip_equal_to_full(tmp_path):
    svc = tts.TextToSpeech(GatedEngine(), cache_dir=tmp_path)
    clips = await svc.synthesize_stream("Just one sentence.")
    assert clips.urls == [clips.full_url]


async def test_full_url_matches_plain_synthesize(tmp_path):
    engine = GatedEngine()
    engine.gate.set()
    svc = tts.TextToSpeech(engine, cache_dir=tmp_path)
    clips = await svc.synthesize_stream(TEXT)
    await svc.wait_idle()
    assert await svc.synthesize(TEXT) == clips.full_url
    assert len(engine.calls) == 3  # served from cache, no re-synthesis


async def test_background_failure_is_tolerated_and_releases_waiters(tmp_path):
    class Boom(GatedEngine):
        def synth_wav(self, text):
            if self.calls:
                self.calls.append(text)
                raise RuntimeError("engine crashed")
            return super().synth_wav(text)

    svc = tts.TextToSpeech(Boom(), cache_dir=tmp_path)
    clips = await svc.synthesize_stream(TEXT)
    await svc.wait_idle()  # must not hang or raise
    assert not (tmp_path / clips.full_url.removeprefix("/audio/")).exists()
    assert tts.PENDING == {}


def test_audio_endpoint_waits_for_a_pending_clip(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "AUDIO_DIR", tmp_path)
    app = FastAPI()
    app.include_router(audio.router)
    ev = threading.Event()
    tts.PENDING["late.wav"] = ev

    def finish():
        (tmp_path / "late.wav").write_bytes(b"RIFFlate")
        ev.set()

    threading.Timer(0.3, finish).start()
    r = TestClient(app).get("/audio/late.wav")
    assert r.status_code == 200 and r.content == b"RIFFlate"
    tts.PENDING.pop("late.wav", None)


def test_audio_endpoint_404_when_pending_clip_never_appears(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "AUDIO_DIR", tmp_path)
    app = FastAPI()
    app.include_router(audio.router)
    ev = threading.Event()
    ev.set()  # renderer gave up
    tts.PENDING["gone.wav"] = ev
    assert TestClient(app).get("/audio/gone.wav").status_code == 404
    tts.PENDING.pop("gone.wav", None)
