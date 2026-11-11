"""
app/storage/factory.py — Storage backend factory and lifecycle management.

Initializes the correct backend (memory or redis) based on STORAGE_BACKEND setting.
Holds a single shared Redis client (created once at startup, closed at shutdown).

IMPORTANT: If STORAGE_BACKEND=redis and Redis is unavailable, startup FAILS FAST.
There is NO silent fallback from Redis to memory.
"""
import logging
from typing import Optional

from app.storage.interfaces import BaseAudioStore, BaseClarificationStore

logger = logging.getLogger(__name__)

_audio_store: Optional[BaseAudioStore] = None
_clarification_store: Optional[BaseClarificationStore] = None
_redis_client = None  # redis.asyncio.Redis | None


async def init_storage(settings) -> None:
    """
    Initialize storage backends based on settings.STORAGE_BACKEND.
    Called once from app lifespan at startup.

    Raises:
        ValueError: If STORAGE_BACKEND is not 'memory' or 'redis'.
        redis.asyncio.ConnectionError / redis.asyncio.RedisError:
            If STORAGE_BACKEND=redis and Redis is unreachable. NOT caught here —
            propagates to fail application startup.
    """
    global _audio_store, _clarification_store, _redis_client

    backend = settings.STORAGE_BACKEND

    if backend == "memory":
        from app.storage.memory import InMemoryAudioStore, InMemoryClarificationStore
        _audio_store = InMemoryAudioStore(default_ttl_seconds=settings.AUDIO_TTL_SECONDS)
        _clarification_store = InMemoryClarificationStore(default_ttl_seconds=settings.CLARIFICATION_TTL_SECONDS)
        logger.info("Storage backend: in-memory (single-process, no Redis required)")

    elif backend == "redis":
        import redis.asyncio as aioredis
        from app.storage.redis_backend import RedisAudioStore, RedisClarificationStore

        client = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
        # Fail fast: ping raises ConnectionError if Redis is unreachable
        await client.ping()
        _redis_client = client

        _audio_store = RedisAudioStore(
            client=client,
            default_ttl=settings.AUDIO_TTL_SECONDS,
        )
        _clarification_store = RedisClarificationStore(
            client=client,
            default_ttl=settings.CLARIFICATION_TTL_SECONDS,
        )
        logger.info("Storage backend: Redis at %s", settings.REDIS_URL)

    else:
        raise ValueError(
            f"STORAGE_BACKEND must be 'memory' or 'redis', got: {backend!r}"
        )


async def close_storage() -> None:
    """Close the Redis client and reset stores on shutdown."""
    global _redis_client, _audio_store, _clarification_store
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis client closed")
    _audio_store = None
    _clarification_store = None


def get_audio_store() -> BaseAudioStore:
    global _audio_store
    if _audio_store is None:
        from app.config import settings
        if getattr(settings, "STORAGE_BACKEND", "memory") == "redis":
            raise RuntimeError(
                "Storage backend is configured as 'redis', but storage has not been initialized. "
                "Call init_storage() during application startup."
            )
        from app.storage.memory import InMemoryAudioStore
        _audio_store = InMemoryAudioStore(default_ttl_seconds=settings.AUDIO_TTL_SECONDS)
    return _audio_store


def get_clarification_store() -> BaseClarificationStore:
    global _clarification_store
    if _clarification_store is None:
        from app.config import settings
        if getattr(settings, "STORAGE_BACKEND", "memory") == "redis":
            raise RuntimeError(
                "Storage backend is configured as 'redis', but storage has not been initialized. "
                "Call init_storage() during application startup."
            )
        from app.storage.memory import InMemoryClarificationStore
        _clarification_store = InMemoryClarificationStore(default_ttl_seconds=settings.CLARIFICATION_TTL_SECONDS)
    return _clarification_store
