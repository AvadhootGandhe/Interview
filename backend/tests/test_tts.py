import wave
from pathlib import Path

from app.speech.tts import Synthesizer, split_sentences


class FakeEngine:
    sample_rate = 24000

    def __init__(self):
        self.calls = []

    def synth(self, text: str) -> bytes:
        self.calls.append(text)
        return b"\x01\x00" * 240  # 10 ms of pcm16


def test_split_sentences_keeps_punctuation():
    assert split_sentences("Hello there. How are you? Fine!") == ["Hello there.", "How are you?", "Fine!"]
    assert split_sentences("  ") == []
    assert split_sentences("no punctuation") == ["no punctuation"]


async def test_synthesizes_each_sentence_into_one_wav(tmp_path):
    engine = FakeEngine()
    tts = Synthesizer(engine, tmp_path)
    url = await tts.synthesize("One. Two. Three.")
    assert engine.calls == ["One.", "Two.", "Three."]
    assert url.startswith("/audio/") and url.endswith(".wav")
    with wave.open(str(tmp_path / url.removeprefix("/audio/"))) as w:
        assert w.getframerate() == 24000 and w.getnchannels() == 1 and w.getnframes() == 3 * 240


async def test_same_text_is_cached(tmp_path):
    engine = FakeEngine()
    tts = Synthesizer(engine, tmp_path)
    assert await tts.synthesize("Hi there.") == await tts.synthesize("Hi there.")
    assert engine.calls == ["Hi there."]


async def test_empty_text_returns_none(tmp_path):
    assert await Synthesizer(FakeEngine(), tmp_path).synthesize("   ") is None


async def test_engine_failure_returns_none(tmp_path):
    class Boom(FakeEngine):
        def synth(self, text):
            raise RuntimeError("no model")

    assert await Synthesizer(Boom(), tmp_path).synthesize("Hello.") is None
