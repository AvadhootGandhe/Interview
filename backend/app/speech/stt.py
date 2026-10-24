"""Speech to text: any browser audio -> 16 kHz mono wav (ffmpeg) -> engine (mlx-whisper).

`SpeechToText.transcribe(bytes) -> str` matches the FakeSTT in tests/conftest.py.
mlx is imported lazily, so cloud tests never need it.
"""
from __future__ import annotations

import asyncio
import io
import os
import subprocess
import sys
import tempfile
import wave
from array import array
from typing import Callable, Protocol

FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "mlx-community/whisper-base.en-mlx")
SILENCE_RMS = 80  # int16 RMS below this counts as silence (whisper hallucinates on silence)


class AudioConversionError(Exception):
    pass


class STTEngine(Protocol):
    def transcribe_file(self, path: str) -> str: ...


def ffmpeg_command(src: str, dst: str, ffmpeg: str | None = None) -> list[str]:
    return [
        ffmpeg or FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", src, "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "-f", "wav", dst,
    ]


def convert_to_wav16k(audio: bytes) -> bytes:
    """Convert webm/ogg/mp4/wav bytes to 16 kHz mono wav bytes."""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "in.bin"), os.path.join(tmp, "out.wav")
        with open(src, "wb") as f:
            f.write(audio)
        try:
            proc = subprocess.run(ffmpeg_command(src, dst), capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise AudioConversionError(str(e)) from e
        if proc.returncode != 0 or not os.path.exists(dst):
            raise AudioConversionError(proc.stderr.decode(errors="replace")[-300:])
        with open(dst, "rb") as f:
            return f.read()


def is_silent(wav_bytes: bytes, threshold: int = SILENCE_RMS) -> bool:
    """True for silent, empty or unreadable wav data."""
    try:
        with wave.open(io.BytesIO(wav_bytes)) as w:
            frames = w.readframes(w.getnframes())
            width = w.getsampwidth()
    except (wave.Error, EOFError):
        return True
    if not frames or width != 2:
        return not frames
    samples = array("h")
    samples.frombytes(frames[: len(frames) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
    return rms < threshold


class MlxWhisperEngine:
    def __init__(self, model: str = WHISPER_MODEL) -> None:
        self.model = model

    def transcribe_file(self, path: str) -> str:
        import mlx_whisper  # lazy: Mac-only dependency

        result = mlx_whisper.transcribe(
            path, path_or_hf_repo=self.model, condition_on_previous_text=False, language="en"
        )
        return result.get("text", "")


class SpeechToText:
    def __init__(self, engine: STTEngine | None = None, convert: Callable[[bytes], bytes] | None = None) -> None:
        self.engine = engine or MlxWhisperEngine()
        self.convert = convert or convert_to_wav16k

    async def transcribe(self, audio: bytes | None) -> str:
        if not audio:
            return ""
        return await asyncio.to_thread(self._transcribe_sync, audio)

    def _transcribe_sync(self, audio: bytes) -> str:
        try:
            wav = self.convert(audio)
        except AudioConversionError:
            return ""
        if is_silent(wav):
            return ""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "answer.wav")
            with open(path, "wb") as f:
                f.write(wav)
            return (self.engine.transcribe_file(path) or "").strip()
