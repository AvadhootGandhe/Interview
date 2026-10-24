"""Phase 4 TTS: engine call, sentence splitting, wav output, cache. No model needed."""
from __future__ import annotations

import io
import wave

import pytest

from app.speech import tts


def tone(n: int = 2400, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * n)
    return buf.getvalue()


class FakeEngine:
    def __init__(self):
        self.calls: list[str] = []

    def synth_wav(self, text: str) -> bytes:
        self.calls.append(text)
        return tone()


def test_split_sentences():
    parts = tts.split_sentences("Tell me about yourself. What did you build? Great! Then we move on")
    assert parts == ["Tell me about yourself.", "What did you build?", "Great!", "Then we move on"]


def test_split_sentences_packs_long_text_and_never_returns_empty():
    text = " ".join(f"Sentence number {i} is here." for i in range(40))
    parts = tts.split_sentences(text, max_chars=200)
    assert all(p and len(p) <= 200 for p in parts)
    assert " ".join(parts) == text
    assert tts.split_sentences("  ") == []


def test_split_sentences_breaks_one_enormous_sentence():
    parts = tts.split_sentences("word " * 300, max_chars=100)
    assert len(parts) > 1 and all(len(p) <= 100 for p in parts)


async def test_text_goes_to_engine_and_url_points_to_a_wav(tmp_path):
    engine = FakeEngine()
    svc = tts.TextToSpeech(engine, cache_dir=tmp_path)
    url = await svc.synthesize("Hello there.")
    assert engine.calls == ["Hello there."]
    assert url.startswith("/audio/") and url.endswith(".wav")
    with wave.open(str(tmp_path / url.removeprefix("/audio/"))) as w:
        assert w.getnchannels() == 1 and w.getnframes() > 0


async def test_long_text_is_sent_sentence_by_sentence_and_joined(tmp_path):
    engine = FakeEngine()
    svc = tts.TextToSpeech(engine, cache_dir=tmp_path)
    url = await svc.synthesize("First one. Second one? Third one!")
    assert engine.calls == ["First one.", "Second one?", "Third one!"]
    with wave.open(str(tmp_path / url.removeprefix("/audio/"))) as w:
        assert w.getnframes() == 3 * 2400


async def test_cache_can_be_disabled_for_honest_benchmarks(tmp_path):
    engine = FakeEngine()
    svc = tts.TextToSpeech(engine, cache_dir=tmp_path, use_cache=False)
    await svc.synthesize("Same text.")
    await svc.synthesize("Same text.")
    assert engine.calls == ["Same text.", "Same text."]


async def test_cache_by_text_hash(tmp_path):
    engine = FakeEngine()
    svc = tts.TextToSpeech(engine, cache_dir=tmp_path)
    a = await svc.synthesize("Same text.")
    b = await svc.synthesize("Same text.")
    c = await svc.synthesize("Other text.")
    assert a == b != c
    assert engine.calls == ["Same text.", "Other text."]
    again = await tts.TextToSpeech(FakeEngine(), cache_dir=tmp_path).synthesize("Same text.")
    assert again == a


async def test_empty_text_raises(tmp_path):
    with pytest.raises(ValueError):
        await tts.TextToSpeech(FakeEngine(), cache_dir=tmp_path).synthesize("   ")
