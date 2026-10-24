import asyncio
import hashlib
import re
import wave
from pathlib import Path


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.findall(r"[^.!?]+[.!?]*", text) if s.strip()]


class Synthesizer:
    """Text to speech. `engine.synth(text) -> pcm16 mono bytes` at `engine.sample_rate`; results are cached on disk."""

    def __init__(self, engine, cache_dir: Path):
        self.engine, self.cache_dir = engine, Path(cache_dir)

    async def synthesize(self, text: str) -> str | None:
        sentences = split_sentences(text)
        if not sentences:
            return None
        name = hashlib.sha256(text.strip().encode()).hexdigest()[:24] + ".wav"
        path = self.cache_dir / name
        if not path.exists():
            try:
                pcm = await asyncio.to_thread(lambda: b"".join(self.engine.synth(s) for s in sentences))
            except Exception:
                return None
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(self.engine.sample_rate)
                w.writeframes(pcm)
        return f"/audio/{name}"


class KokoroEngine:  # local-only: needs `pip install kokoro soundfile`
    sample_rate = 24000

    def __init__(self, voice: str = "af_heart"):
        from kokoro import KPipeline

        self.voice, self.pipeline = voice, KPipeline(lang_code="a")

    def synth(self, text: str) -> bytes:
        import numpy as np

        chunks = [np.asarray(audio) for _, _, audio in self.pipeline(text, voice=self.voice)]
        pcm = np.concatenate(chunks) if chunks else np.zeros(0)
        return (np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes()
