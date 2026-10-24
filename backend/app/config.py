from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    database_url: str = "sqlite:///./data/app.db"
    llama_server_url: str = "http://localhost:8081"
    evaluator_model: str = "claude-sonnet-5-5"
    cheap_model: str = "claude-haiku-5-5"
    fake_llm: bool = False
    speech_enabled: bool = False  # local-only: mlx-whisper + Kokoro

    pool_size: int = 40
    max_context_tokens: int = 3000
    generated_per_pack: int = 3
    satisfaction_threshold: int = 70
    max_followups: int = 2
    followup_penalty: int = 5
    num_questions: int = 5


settings = Settings()
