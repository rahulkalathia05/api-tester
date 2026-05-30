import os
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ALLOWED_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})


class Settings(BaseSettings):
    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "API Tester"
    DEBUG: bool = False

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str   # postgresql+asyncpg://user:pass@host/db

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379"

    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "api-tester"
    JWT_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_EXPIRE_DAYS: int = 7

    # ── Password hashing ──────────────────────────────────────────────────────
    BCRYPT_ROUNDS: int = 12

    # ── CORS ──────────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # ── Rate limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_ENABLED: bool = True

    # ── OpenAI ────────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_REQUEST_TIMEOUT: float = 60.0

    # ── HTTP runner ───────────────────────────────────────────────────────────
    RUNNER_DEFAULT_TIMEOUT_MS: int = 30_000   # per-request default
    RUNNER_MAX_TIMEOUT_MS: int = 120_000       # hard cap clients cannot exceed
    RUNNER_MAX_CONCURRENCY: int = 10           # max parallel requests in a run

    # ── Worker / queue ────────────────────────────────────────────────────────
    RUN_QUEUE_KEY: str = "runner:queue"
    # Sorted set of run_ids scheduled for retry, scored by next-attempt timestamp
    RUN_SCHEDULED_KEY: str = "runner:scheduled"
    # Per-run retry counter prefix — key: runner:retry:{run_id}
    RUN_RETRY_PREFIX: str = "runner:retry:"
    RUN_MAX_RETRIES: int = 3
    # ── Exponential backoff parameters ───────────────────────────────────────
    # Computed delay = min(BASE * MULTIPLIER^(attempt-1), MAX_DELAY_S) ± jitter
    RUN_RETRY_BASE_DELAY_S: int   = 30      # seconds for the first retry
    RUN_RETRY_MULTIPLIER:  float  = 4.0     # delay grows 4× each attempt: 30s → 120s → 480s
    RUN_RETRY_MAX_DELAY_S: int    = 3600    # hard cap (1 hour)
    RUN_RETRY_JITTER:      float  = 0.2     # ±20% random jitter to spread thundering herds
    # TTL for retry counter keys (cleanup after 24 h)
    RUN_RETRY_TTL: int = 86_400
    # Max concurrent collection runs in the worker
    RUN_WORKER_CONCURRENCY: int = 3
    # Seconds without update before a 'running' run is considered stalled
    RUN_STALL_THRESHOLD_SECONDS: int = 600   # 10 minutes

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("JWT_SECRET")
    @classmethod
    def jwt_secret_strength(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError(
                "JWT_SECRET must be at least 32 characters. "
                "Generate: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return v

    @field_validator("JWT_ALGORITHM")
    @classmethod
    def jwt_algorithm_allowed(cls, v: str) -> str:
        if v not in _ALLOWED_ALGORITHMS:
            raise ValueError(f"JWT_ALGORITHM must be one of {sorted(_ALLOWED_ALGORITHMS)}")
        return v

    @field_validator("BCRYPT_ROUNDS")
    @classmethod
    def bcrypt_rounds_range(cls, v: int) -> int:
        if not (4 <= v <= 31):
            raise ValueError("BCRYPT_ROUNDS must be between 4 and 31")
        return v

    @field_validator("CORS_ORIGINS")
    @classmethod
    def cors_no_wildcard(cls, v: list[str]) -> list[str]:
        if "*" in v:
            raise ValueError("CORS_ORIGINS must not contain '*'")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
