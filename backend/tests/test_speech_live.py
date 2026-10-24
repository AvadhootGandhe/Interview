"""Live speech tests (Mac only): real mlx-whisper and Kokoro."""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.local

HELLO = Path(__file__).parent / "fixtures" / "hello.wav"
HELLO_TEXT = "Hello, I would design the system with a message queue and a cache to handle the load."


def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", s.lower())


def wer(ref: list[str], hyp: list[str]) -> float:
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[-1] / len(ref)


async def test_transcribe_hello_wav_wer_under_15_percent():
    from app.speech.stt import SpeechToText

    out = await SpeechToText().transcribe(HELLO.read_bytes())
    score = wer(words(HELLO_TEXT), words(out))
    print(f"\nSTT: {out!r} WER={score:.3f}")
    assert score < 0.15


async def test_synthesize_one_sentence_under_1s_after_warmup(tmp_path):
    from app.speech.tts import TextToSpeech

    svc = TextToSpeech(cache_dir=tmp_path)
    await svc.synthesize("Warm up sentence for the model.")
    t0 = time.perf_counter()
    url = await svc.synthesize("Tell me about a system you designed.")
    dt = time.perf_counter() - t0
    print(f"\nTTS latency: {dt:.3f}s")
    assert (tmp_path / url.removeprefix("/audio/")).stat().st_size > 1000
    assert dt < 1.0
