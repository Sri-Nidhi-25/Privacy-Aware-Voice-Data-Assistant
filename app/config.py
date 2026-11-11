"""
app/config.py - Application configuration with startup validation.

All settings come from environment variables / .env file.
Invalid or missing configuration is detected at startup, not at first request.
"""
import logging
from typing import Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_VALID_OBFUSCATION = {"mild", "medium", "strong", "high", "very_strong", "verystrong", "very strong"}


class Settings(BaseSettings):
    APP_NAME: str = "Voice Data Assistant"
    MAX_RESULTS: int = 10

    # Voice
    OBFUSCATION_STRENGTH: str = "mild"
    STT_MODEL: str = "small.en"

    # LLM
    OLLAMA_MODEL: str = "llama3.2:latest"

    # TTS
    EDGE_TTS_VOICE: str = "en-US-GuyNeural"
    TTS_PROVIDER: str = "disabled"  # Options: "disabled" (privacy default), "local", "remote" (explicit opt-in)
    ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA: bool = False  # Hard invariant: NEVER transmit private/connector data to cloud
    LOCAL_TTS_VOICE: Optional[str] = None  # Optional voice name for local synthesis (e.g. "Microsoft David Desktop", "Microsoft Zira Desktop")

    # Concurrency limit for heavy voice operations
    MAX_CONCURRENT_VOICE_REQUESTS: int = 2

    # Security — no production default; empty = dev warning mode
    API_KEY: Optional[str] = None

    # Audio limits
    MAX_AUDIO_SIZE_MB: int = 25
    MAX_AUDIO_DURATION_SECONDS: float = 120.0

    # Timeouts (seconds) for blocking operations
    LLM_TIMEOUT_SECONDS: float = 30.0
    TTS_TIMEOUT_SECONDS: float = 45.0
    STT_TIMEOUT_SECONDS: float = 60.0
    OBFUSCATION_TIMEOUT_SECONDS: float = 30.0

    # CORS — comma-separated origins; "*" means all (dev only)
    ALLOWED_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000"

    # Privacy: set True to include transcripts in structured logs (dev only)
    LOG_TRANSCRIPTS: bool = False

    # Reliability: Maximum bounded retries for transient failures
    MAX_RETRIES: int = 2

    # Storage backend
    STORAGE_BACKEND: str = "memory"   # "memory" or "redis"
    REDIS_URL: str = "redis://localhost:6379/0"
    AUDIO_TTL_SECONDS: float = 3600.0
    CLARIFICATION_TTL_SECONDS: float = 120.0

    @model_validator(mode="after")
    def _validate_and_sanitize(self) -> "Settings":
        # Strip whitespace from string fields
        self.OLLAMA_MODEL = self.OLLAMA_MODEL.strip()
        self.STT_MODEL = self.STT_MODEL.strip()
        self.EDGE_TTS_VOICE = self.EDGE_TTS_VOICE.strip()
        self.TTS_PROVIDER = self.TTS_PROVIDER.strip().lower()
        if self.LOCAL_TTS_VOICE:
            self.LOCAL_TTS_VOICE = self.LOCAL_TTS_VOICE.strip()
        self.OBFUSCATION_STRENGTH = self.OBFUSCATION_STRENGTH.strip().lower()
        if self.OBFUSCATION_STRENGTH == "high":
            self.OBFUSCATION_STRENGTH = "strong"
        elif self.OBFUSCATION_STRENGTH in {"verystrong", "very strong"}:
            self.OBFUSCATION_STRENGTH = "very_strong"
        if self.ALLOWED_ORIGINS:
            self.ALLOWED_ORIGINS = self.ALLOWED_ORIGINS.strip()

        # Validate obfuscation strength
        if self.OBFUSCATION_STRENGTH not in {"mild", "medium", "strong", "very_strong"}:
            raise ValueError(
                f"OBFUSCATION_STRENGTH must be one of {_VALID_OBFUSCATION}, "
                f"got: {self.OBFUSCATION_STRENGTH!r}"
            )

        # Validate numeric fields
        if self.MAX_CONCURRENT_VOICE_REQUESTS < 1:
            raise ValueError(f"MAX_CONCURRENT_VOICE_REQUESTS must be >= 1, got {self.MAX_CONCURRENT_VOICE_REQUESTS}")
        if self.MAX_RESULTS <= 0:
            raise ValueError(f"MAX_RESULTS must be > 0, got {self.MAX_RESULTS}")
        if self.MAX_AUDIO_SIZE_MB <= 0:
            raise ValueError(f"MAX_AUDIO_SIZE_MB must be > 0, got {self.MAX_AUDIO_SIZE_MB}")
        if self.MAX_AUDIO_DURATION_SECONDS <= 0:
            raise ValueError(f"MAX_AUDIO_DURATION_SECONDS must be > 0")
        for name, val in [
            ("LLM_TIMEOUT_SECONDS", self.LLM_TIMEOUT_SECONDS),
            ("TTS_TIMEOUT_SECONDS", self.TTS_TIMEOUT_SECONDS),
            ("STT_TIMEOUT_SECONDS", self.STT_TIMEOUT_SECONDS),
            ("OBFUSCATION_TIMEOUT_SECONDS", self.OBFUSCATION_TIMEOUT_SECONDS),
        ]:
            if val <= 0:
                raise ValueError(f"{name} must be > 0, got {val}")

        # API key: warn if using placeholder / not set
        if not self.API_KEY or self.API_KEY in ("", "secret-key-change-me"):
            logger.warning(
                "API_KEY is not configured or uses the default placeholder. "
                "Set a secure API_KEY in your .env file before production use. "
                "Using insecure dev key."
            )
            self.API_KEY = "dev-insecure-key"

        # Validate storage backend
        self.STORAGE_BACKEND = self.STORAGE_BACKEND.strip().lower()
        if self.STORAGE_BACKEND not in {"memory", "redis"}:
            raise ValueError(
                f"STORAGE_BACKEND must be 'memory' or 'redis', got: {self.STORAGE_BACKEND!r}"
            )

        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
