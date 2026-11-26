import os
from pathlib import Path
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # "anthropic" calls the Claude API; "mock" returns canned records (no API key needed).
    generation_mode: str = os.getenv("GENERATION_MODE", "anthropic")
    generation_model: str = os.getenv("GENERATION_MODEL", "claude-opus-5")
    generation_effort: str = os.getenv("GENERATION_EFFORT", "medium")
    max_concurrency: int = int(os.getenv("MAX_CONCURRENCY", "5"))
    max_samples_per_job: int = int(os.getenv("MAX_SAMPLES_PER_JOB", "20"))
    max_attempts_per_sample: int = int(os.getenv("MAX_ATTEMPTS_PER_SAMPLE", "3"))
    # When set, every request except the health check requires HTTP Basic auth with this password.
    app_password: str = os.getenv("APP_PASSWORD", "")
    # Built frontend to serve at "/" (production). Skipped if the directory doesn't exist.
    static_dir: str = os.getenv(
        "STATIC_DIR", str(Path(__file__).resolve().parents[2] / "frontend" / "dist")
    )


settings = Settings()
