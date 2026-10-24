"""FastAPI dependencies for STT/TTS. Tests override `get_stt` / `get_tts`.

SPEECH=auto (default): real engines unless FAKE_LLM is set (then off). SPEECH=real|fake|off force it.
Engines are built lazily on first use; `None` means speech is off.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import settings


def resolve_mode() -> str:
    mode = (settings.speech or "auto").lower()
    if mode == "auto":
        return "off" if settings.fake_llm else "real"
    return mode if mode in ("real", "fake", "off") else "off"


@lru_cache
def build_stt(mode: str):
    if mode == "real":
        from app.speech.stt import SpeechToText
        return SpeechToText()
    if mode == "fake":
        from app.speech.fake import FakeSpeechToText
        return FakeSpeechToText()
    return None


@lru_cache
def build_tts(mode: str):
    if mode == "real":
        from app.speech.tts import TextToSpeech
        return TextToSpeech()
    if mode == "fake":
        from app.speech.fake import FakeSpeechTTS
        return FakeSpeechTTS()
    return None


def get_stt():
    return build_stt(resolve_mode())


def get_tts():
    return build_tts(resolve_mode())
