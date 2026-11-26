import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    # "anthropic" calls the Claude API; "mock" returns canned records (no API key needed).
    generation_mode: str = os.getenv("GENERATION_MODE", "anthropic")
    generation_model: str = os.getenv("GENERATION_MODEL", "claude-opus-5")
    generation_effort: str = os.getenv("GENERATION_EFFORT", "medium")
    max_concurrency: int = int(os.getenv("MAX_CONCURRENCY", "5"))
    max_samples_per_job: int = int(os.getenv("MAX_SAMPLES_PER_JOB", "20"))
    max_attempts_per_sample: int = int(os.getenv("MAX_ATTEMPTS_PER_SAMPLE", "3"))

    # Postgres URL in production (e.g. Supabase); a local SQLite file otherwise.
    database_url: str = os.getenv(
        "DATABASE_URL", f"sqlite+aiosqlite:///{BACKEND_DIR / 'dev.db'}"
    )

    # Billing
    free_positive_samples: int = int(os.getenv("FREE_POSITIVE_SAMPLES", "1"))
    free_negative_samples: int = int(os.getenv("FREE_NEGATIVE_SAMPLES", "1"))
    price_per_sample_cents: int = int(os.getenv("PRICE_PER_SAMPLE_CENTS", "50"))
    # "stripe" in production; "mock" shows a fake payment page (local development only).
    payment_mode: str = os.getenv("PAYMENT_MODE", "stripe")
    stripe_secret_key: str = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    # Base URL Stripe redirects back to. Render sets RENDER_EXTERNAL_URL automatically.
    public_url: str = os.getenv("PUBLIC_URL", os.getenv("RENDER_EXTERNAL_URL", ""))

    session_days: int = int(os.getenv("SESSION_DAYS", "30"))

    # Built frontend to serve at "/" (production). Skipped if the directory doesn't exist.
    static_dir: str = os.getenv("STATIC_DIR", str(BACKEND_DIR.parent / "frontend" / "dist"))


settings = Settings()
