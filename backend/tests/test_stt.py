import pytest

from app.speech.stt import Transcriber, build_ffmpeg_command


class FakeEngine:
    def __init__(self, text="hello world"):
        self.text, self.paths = text, []

    def transcribe_file(self, path: str) -> str:
        self.paths.append(path)
        return self.text


def ok_convert(src, dst):
    open(dst, "wb").write(b"RIFF")


def test_ffmpeg_command_is_16k_mono_wav():
    cmd = build_ffmpeg_command("in.webm", "out.wav")
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-ar") + 1] == "16000" and cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[cmd.index("-i") + 1] == "in.webm" and cmd[-1] == "out.wav"


async def test_transcribes_through_engine():
    engine = FakeEngine("  I would use a cache.  ")
    assert await Transcriber(engine, convert=ok_convert).transcribe(b"audio") == "I would use a cache."
    assert len(engine.paths) == 1 and engine.paths[0].endswith(".wav")


async def test_empty_audio_returns_empty_without_calling_engine():
    engine = FakeEngine()
    assert await Transcriber(engine, convert=ok_convert).transcribe(b"") == ""
    assert engine.paths == []


async def test_silence_hallucination_is_filtered():
    for text in ("", "   ", "you", "Thanks for watching!"):
        assert await Transcriber(FakeEngine(text), convert=ok_convert).transcribe(b"x") == ""


async def test_conversion_failure_does_not_crash():
    def broken(src, dst):
        raise RuntimeError("ffmpeg failed")

    assert await Transcriber(FakeEngine(), convert=broken).transcribe(b"junk") == ""


async def test_engine_failure_does_not_crash():
    class Boom(FakeEngine):
        def transcribe_file(self, path):
            raise RuntimeError("model missing")

    assert await Transcriber(Boom(), convert=ok_convert).transcribe(b"x") == ""
