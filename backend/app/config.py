"""All tunable numbers live here. Override any of them from `.env`."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    llama_server_url: str = "http://127.0.0.1:8081"
    database_url: str = "sqlite:///./interview.db"
    fake_llm: bool = False
    cors_origins: list[str] = ["http://localhost:3000"]

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
    flow_harder_at: int = 85  # final score >= this -> harder next question
    flow_easier_at: int = 50  # final score <= this -> easier next question

    # Retrieval (Phase 2)
    level_difficulty: dict[str, int] = {
        "Fresher": 1, "SDE-1": 2, "SDE-1/2": 3, "SDE-2/3": 4, "Architect/Principal": 5,
    }
    topic_max_share: float = 0.4  # no topic may fill more than this share of a pool
    company_min_share: float = 0.7  # G10: share of company-specific items when a company has matches
    company_min_items: int = 12  # below this many matches a company counts as sparse and widens freely
    recent_sessions_excluded: int = 3  # don't repeat questions from the user's last N sessions
    retriever_candidates_per_stage: int = 500
    ingest_batch_size: int = 5000

    # Company profile + context pack (Phase 2)
    profile_sample_questions: int = 30
    profile_summary_max_tokens: int = 300
    max_context_tokens: int = 3000  # estimated as chars / 4
    generated_per_pack: int = 3

    # Claude (Phase 3). Model ids come from here, never from agent code.
    claude_model: str = "claude-sonnet-5-5"  # evaluator, planner, interviewer, reporter
    claude_model_cheap: str = "claude-haiku-5-5"  # company-profile summary
    claude_effort: str = "medium"  # low|medium|high: thinking depth vs latency
    claude_max_tokens: int = 2048
    claude_timeout_s: float = 60.0

    # Interview loop (Phase 3)
    max_interview_minutes: int = 45  # 0 disables the time limit
    examples_per_ask: int = 3  # similar retrieved questions shown to the interviewer as style examples
    max_spoken_words: int = 60
    followup_train_path: str = ""  # default: <repo>/data/followup_train.jsonl


settings = Settings()
