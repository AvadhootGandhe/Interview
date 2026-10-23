"""All tunable numbers live here. Override any of them from `.env`."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    llama_server_url: str = "http://127.0.0.1:8081"
    database_url: str = "sqlite:///./interview.db"
    fake_llm: bool = False

    # Question generator (must match how the LoRA was sampled in training)
    generator_temperature: float = 0.8
    generator_top_p: float = 0.9
    generator_n_predict: int = 100
    generator_max_chars: int = 400
    generator_timeout_s: float = 10.0

    # Interview flow (used from Phase 2-3)
    pool_size: int = 40
    satisfaction_threshold: int = 70
    max_followups: int = 2
    followup_penalty: int = 5


settings = Settings()
