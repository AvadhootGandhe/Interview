"""Text to speech: split into sentences, synthesize each, join into one cached wav.

`TextToSpeech.synthesize(text) -> "/audio/<hash>.wav"` matches the FakeTTS in tests/conftest.py.
Kokoro is imported lazily, so cloud tests never need it.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import logging
import re
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

AUDIO_DIR = Path(__file__).resolve().parents[2] / "audio_cache"  # git-ignored
VOICE = os.environ.get("TTS_VOICE", "af_heart")
USE_CACHE = os.environ.get("TTS_CACHE", "1") != "0"  # TTS_CACHE=0 for latency benchmarks (real replies never repeat)
SAMPLE_RATE = 24000
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


log = logging.getLogger(__name__)
PENDING: dict[str, threading.Event] = {}  # clip file name -> set when its rendering finished (or failed)


@dataclass
class Clips:
    urls: list[str]  # one clip per sentence, in speaking order; only urls[0] is guaranteed ready on return
    full_url: str  # the whole text as one clip (what `synthesize` returns); ready once the rest has rendered


class TTSEngine(Protocol):
    def synth_wav(self, text: str) -> bytes: ...


def split_sentences(text: str, max_chars: int = 300) -> list[str]:
    """Sentences, with oversized ones broken at word boundaries; each piece <= max_chars."""
    out: list[str] = []
    for sent in _SENTENCE_END.split(text.strip()):
        sent = sent.strip()
        while len(sent) > max_chars:
            cut = sent.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            out.append(sent[:cut].strip())
            sent = sent[cut:].strip()
        if sent:
            out.append(sent)
    return out


class KokoroEngine:
    def __init__(self, voice: str = VOICE) -> None:
        self.voice = voice
        self._pipeline = None

    def _get(self):
        if self._pipeline is None:
            from kokoro import KPipeline  # lazy: Mac-only dependency

            self._pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
        return self._pipeline

    def synth_wav(self, text: str) -> bytes:
        import numpy as np

        chunks = [np.asarray(audio, dtype="float32") for _, _, audio in self._get()(text, voice=self.voice) if audio is not None]
        pcm = (np.clip(np.concatenate(chunks), -1, 1) * 32767).astype("<i2") if chunks else np.zeros(0, "<i2")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())
        return buf.getvalue()


def _join_wavs(wavs: list[bytes]) -> bytes:
    buf = io.BytesIO()
    out = None
    for data in wavs:
        with wave.open(io.BytesIO(data)) as w:
            if out is None:
                out = wave.open(buf, "wb")
                out.setparams(w.getparams())
            out.writeframes(w.readframes(w.getnframes()))
    out.close()
    return buf.getvalue()


class TextToSpeech:
    def __init__(self, engine: TTSEngine | None = None, cache_dir: Path | None = None, voice: str = VOICE,
                 use_cache: bool = USE_CACHE) -> None:
        self.use_cache = use_cache
        self.engine = engine or KokoroEngine(voice)
        self.cache_dir = Path(cache_dir) if cache_dir else AUDIO_DIR
        self.voice = voice
        self._engine_lock = threading.Lock()  # the model is not thread-safe: one synthesis at a time
        self._threads: list[threading.Thread] = []

    def _name(self, text: str) -> str:
        return hashlib.sha256(f"{self.voice}\n{text}".encode()).hexdigest()[:32] + ".wav"

    def warm_up(self) -> None:
        """Load the model and run one short synthesis; nothing is cached."""
        self.engine.synth_wav("Hello, let's begin.")

    async def synthesize(self, text: str) -> str:
        text = " ".join(text.split())
        if not text:
            raise ValueError("cannot synthesize empty text")
        name = self._name(text)
        path = self.cache_dir / name
        if not (self.use_cache and path.exists()):
            await asyncio.to_thread(self._render, text, path)
        return f"/audio/{name}"

    def _synth(self, text: str) -> bytes:
        with self._engine_lock:
            return self.engine.synth_wav(text)

    def _write(self, path: Path, data: bytes) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def _render(self, text: str, path: Path) -> None:
        self._write(path, _join_wavs([self._synth(s) for s in split_sentences(text)]))

    def _render_clip(self, sentence: str, path: Path) -> None:
        if not (self.use_cache and path.exists()):
            self._write(path, self._synth(sentence))

    async def synthesize_stream(self, text: str) -> Clips:
        """Render the first sentence and return its clip at once; the rest (and the joined whole) render in the background.

        Time to first audio is then one short sentence, not the whole reply. Clips are cached per sentence.
        """
        text = " ".join(text.split())
        if not text:
            raise ValueError("cannot synthesize empty text")
        sentences = split_sentences(text)
        if len(sentences) <= 1:
            url = await self.synthesize(text)
            return Clips([url], url)
        whole = self._name(text)
        names = [self._name(sent) for sent in sentences]
        urls = [f"/audio/{n}" for n in names]
        full = Clips(urls, f"/audio/{whole}")
        if self.use_cache and (self.cache_dir / whole).exists():
            return full
        todo = [n for n in [*names[1:], whole] if n not in PENDING]
        for n in todo:
            PENDING[n] = threading.Event()
        try:
            await asyncio.to_thread(self._render_clip, sentences[0], self.cache_dir / names[0])
        except BaseException:
            self._release(todo)
            raise
        # A plain thread, not an event-loop task: it must outlive the request that started it.
        thread = threading.Thread(target=self._render_rest, args=(sentences[1:], names, whole, todo), daemon=True)
        self._threads = [t for t in self._threads if t.is_alive()] + [thread]
        thread.start()
        return full

    def _release(self, names: list[str]) -> None:
        for n in names:
            ev = PENDING.pop(n, None)
            if ev is not None:
                ev.set()

    def _render_rest(self, sentences: list[str], names: list[str], whole: str, todo: list[str]) -> None:
        try:
            for sent, name in zip(sentences, names[1:]):
                self._render_clip(sent, self.cache_dir / name)
                if name in todo:
                    self._release([name])
            parts = [(self.cache_dir / n).read_bytes() for n in names]
            self._write(self.cache_dir / whole, _join_wavs(parts))
        except Exception:  # noqa: BLE001
            log.warning("background TTS failed; remaining clips unavailable", exc_info=True)
        finally:
            self._release(todo)

    async def wait_idle(self) -> None:
        """Wait for background rendering to finish (tests, shutdown)."""
        for t in list(self._threads):
            await asyncio.to_thread(t.join)
