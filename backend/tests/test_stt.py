"""Phase 4 STT: conversion command, engine interface and silence handling. No model needed."""
from __future__ import annotations

import io
import struct
import wave

import pytest

from app.speech import stt


def make_wav(samples: list[int], rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


LOUD = make_wav([8000, -8000] * 4000)
SILENT = make_wav([0] * 16000)


class FakeEngine:
    def __init__(self, text="hello world"):
        self.text = text
        self.paths: list[str] = []

    def transcribe_file(self, path: str) -> str:
        self.paths.append(path)
        return self.text


def passthrough(audio: bytes) -> bytes:
    return audio


def test_ffmpeg_command_is_16khz_mono_wav():
    cmd = stt.ffmpeg_command("in.webm", "out.wav")
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-i") + 1] == "in.webm"
    assert cmd[cmd.index("-ar") + 1] == "16000"
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[-1] == "out.wav"
    assert "wav" in cmd or "pcm_s16le" in cmd


def test_ffmpeg_binary_is_configurable():
    assert stt.ffmpeg_command("a", "b", ffmpeg="/opt/homebrew/bin/ffmpeg")[0] == "/opt/homebrew/bin/ffmpeg"


async def test_engine_is_called_with_a_wav_file_and_text_returned():
    engine = FakeEngine("  I would use a cache.  ")
    out = await stt.SpeechToText(engine, convert=passthrough).transcribe(LOUD)
    assert out == "I would use a cache."
    assert len(engine.paths) == 1 and engine.paths[0].endswith(".wav")


async def test_convert_is_applied_before_engine():
    seen = []

    def convert(audio: bytes) -> bytes:
        seen.append(audio)
        return LOUD

    engine = FakeEngine()
    await stt.SpeechToText(engine, convert=convert).transcribe(b"webm-bytes")
    assert seen == [b"webm-bytes"] and len(engine.paths) == 1


@pytest.mark.parametrize("audio", [b"", None])
async def test_empty_audio_returns_empty_without_calling_engine(audio):
    engine = FakeEngine()
    assert await stt.SpeechToText(engine, convert=passthrough).transcribe(audio) == ""
    assert engine.paths == []


async def test_silent_audio_returns_empty_without_calling_engine():
    engine = FakeEngine("Thank you.")  # whisper hallucinates on silence; we must not ask it
    assert await stt.SpeechToText(engine, convert=passthrough).transcribe(SILENT) == ""
    assert engine.paths == []


async def test_conversion_failure_returns_empty():
    def broken(audio: bytes) -> bytes:
        raise stt.AudioConversionError("bad data")

    engine = FakeEngine()
    assert await stt.SpeechToText(engine, convert=broken).transcribe(b"garbage") == ""
    assert engine.paths == []


def test_is_silent_helper():
    assert stt.is_silent(SILENT)
    assert not stt.is_silent(LOUD)
    assert stt.is_silent(b"not a wav")


def test_convert_with_missing_ffmpeg_raises(monkeypatch):
    monkeypatch.setattr(stt, "FFMPEG", "definitely-not-ffmpeg-binary")
    with pytest.raises(stt.AudioConversionError):
        stt.convert_to_wav16k(b"abc")
