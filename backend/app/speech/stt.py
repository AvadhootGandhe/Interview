import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

# Whisper tends to emit these on silence or noise.
SILENCE_HALLUCINATIONS = {"you", "thank you.", "thanks for watching!", "thanks for watching.", "bye."}


def build_ffmpeg_command(src: str, dst: str) -> list[str]:
    return ["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1", "-f", "wav", dst]


def ffmpeg_convert(src: str, dst: str) -> None:
    subprocess.run(build_ffmpeg_command(src, dst), check=True, capture_output=True, timeout=30)


class Transcriber:
    """Speech to text. `engine.transcribe_file(path) -> str` is the swappable model (mlx-whisper on the Mac)."""

    def __init__(self, engine, convert: Callable[[str, str], None] = ffmpeg_convert):
        self.engine, self.convert = engine, convert

    async def transcribe(self, audio: bytes) -> str:
        if not audio:
            return ""
        return await asyncio.to_thread(self._transcribe_sync, audio)

    def _transcribe_sync(self, audio: bytes) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "in.audio", Path(tmp) / "out.wav"
            src.write_bytes(audio)
            try:
                self.convert(str(src), str(dst))
                text = self.engine.transcribe_file(str(dst)).strip()
            except Exception:
                return ""
        return "" if text.lower() in SILENCE_HALLUCINATIONS else text


class MlxWhisperEngine:  # local-only: needs Apple silicon + `pip install mlx-whisper`
    def __init__(self, model: str = "mlx-community/whisper-base.en-mlx"):
        self.model = model

    def transcribe_file(self, path: str) -> str:
        import mlx_whisper

        return mlx_whisper.transcribe(path, path_or_hf_repo=self.model)["text"]
