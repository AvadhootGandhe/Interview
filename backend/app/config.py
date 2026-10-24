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

    # Claude (Phase 3). Models are config, never hard-coded in agents.
    planner_model: str = "claude-sonnet-5-5"
    evaluator_model: str = "claude-sonnet-5-5"
    reporter_model: str = "claude-sonnet-5-5"
    interviewer_model: str = "claude-haiku-5-5"  # latency-sensitive: spoken every turn
    cheap_model: str = "claude-haiku-5-5"  # company-profile summary and other small jobs
    planner_effort: str = "medium"
    evaluator_effort: str = "medium"
    reporter_effort: str = "medium"
    interviewer_effort: str = "low"
    claude_timeout_s: float = 60.0

    # Planner + flow controller (Phase 3)
    planner_min_segments: int = 4
    planner_max_segments: int = 6
    topic_focus_share: float = 0.6  # when a topic is chosen, this share of segments must use it
    max_difficulty_jump: int = 2
    flow_harder_at: int = 85  # final score >= this: next question gets harder
    flow_easier_at: int = 50  # final score <= this: next question gets easier
    style_examples: int = 3  # similar retrieved questions shown to the interviewer
    speech_max_words: int = 60

    # Orchestrator (Phase 3)
    interview_time_limit_s: int = 1800  # 0 disables
    followup_log_path: str = ""  # default: <repo>/data/followup_train.jsonl (git-ignored)


settings = Settings()
