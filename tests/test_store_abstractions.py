"""
tests/test_store_abstractions.py — Tests for storage interface implementations.

In-memory tests: always run.
Redis integration tests: skipped unless Redis is reachable at localhost:6379.
"""
import asyncio
import time
import pytest
import pytest_asyncio

from app.storage.interfaces import BaseAudioStore, BaseClarificationStore, PendingClarification
from app.storage.memory import InMemoryAudioStore, InMemoryClarificationStore

import os
import threading

_TEST_REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

# Check Redis availability.
# socket.socket().settimeout().connect() is unreliable on Windows+WSL2 loopback
# even when the port IS open. We run an asyncio ping in an isolated thread so
# that (a) we avoid the "cannot run nested event loops" error that occurs when
# pytest-asyncio has already installed a loop, and (b) we get a true async
# probe rather than a raw TCP timeout.
_REDIS_AVAILABLE = False
try:
    import redis.asyncio as _aioredis_check

    def _probe_redis() -> bool:
        import asyncio as _asyncio

        async def _ping() -> bool:
            client = _aioredis_check.from_url(
                _TEST_REDIS_URL,
                socket_connect_timeout=3,
            )
            try:
                await client.ping()
                return True
            except Exception:
                return False
            finally:
                await client.aclose()

        return _asyncio.run(_ping())

    _result: list = []

    def _thread_target():
        _result.append(_probe_redis())

    _t = threading.Thread(target=_thread_target, daemon=True)
    _t.start()
    _t.join(timeout=6)
    _REDIS_AVAILABLE = bool(_result and _result[0])
except Exception:
    _REDIS_AVAILABLE = False


# ---------------------------------------------------------------------------
# In-memory audio store tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inmemory_audio_store_satisfies_interface():
    store = InMemoryAudioStore()
    assert isinstance(store, BaseAudioStore)


@pytest.mark.asyncio
async def test_inmemory_audio_store_and_retrieve_with_session():
    store = InMemoryAudioStore()
    await store.store("id1", b"audio_data", session_id="sess1")
    result = await store.retrieve("id1", session_id="sess1")
    assert result is not None
    data, mt = result
    assert data == b"audio_data"
    assert mt == "audio/wav"


@pytest.mark.asyncio
async def test_inmemory_audio_missing_session_blocks_session_bound():
    store = InMemoryAudioStore()
    await store.store("id2", b"data", session_id="sess1")
    # Caller provides NO session_id — cannot retrieve session-bound audio
    result = await store.retrieve("id2", session_id=None)
    assert result is None


@pytest.mark.asyncio
async def test_inmemory_audio_mismatched_session_blocks_retrieval():
    store = InMemoryAudioStore()
    await store.store("id3", b"data", session_id="sessA")
    result = await store.retrieve("id3", session_id="sessB")
    assert result is None


@pytest.mark.asyncio
async def test_inmemory_anonymous_audio_blocked_by_session_id():
    store = InMemoryAudioStore()
    await store.store("id4", b"anon_data", session_id=None)
    # Any session_id blocks access to anonymous audio
    result = await store.retrieve("id4", session_id="some_session")
    assert result is None


@pytest.mark.asyncio
async def test_inmemory_anonymous_audio_accessible_without_session():
    store = InMemoryAudioStore()
    await store.store("id5", b"anon_data", session_id=None)
    result = await store.retrieve("id5", session_id=None)
    assert result is not None
    assert result[0] == b"anon_data"


@pytest.mark.asyncio
async def test_inmemory_repeatable_playback():
    store = InMemoryAudioStore()
    await store.store("id6", b"replay", session_id=None)
    for _ in range(5):
        result = await store.retrieve("id6", session_id=None)
        assert result is not None
        assert result[0] == b"replay"


@pytest.mark.asyncio
async def test_inmemory_burn_shortens_expiry():
    store = InMemoryAudioStore()
    await store.store("id7", b"burn_me", session_id=None, ttl_seconds=3600.0)
    result = await store.retrieve("id7", burn=True, session_id=None)
    assert result is not None
    # After burn, the item is still retrievable within grace window
    result2 = await store.retrieve("id7", session_id=None)
    assert result2 is not None


@pytest.mark.asyncio
async def test_inmemory_burn_session_removes_session_records():
    store = InMemoryAudioStore()
    await store.store("a1", b"d1", session_id="sessX")
    await store.store("a2", b"d2", session_id="sessX")
    await store.store("a3", b"d3", session_id="sessY")
    
    removed = await store.burn_session("sessX")
    assert removed == 2
    
    assert await store.retrieve("a1", session_id="sessX") is None
    assert await store.retrieve("a2", session_id="sessX") is None
    # sessY unaffected
    r = await store.retrieve("a3", session_id="sessY")
    assert r is not None


@pytest.mark.asyncio
async def test_inmemory_burn_session_does_not_affect_other_sessions():
    store = InMemoryAudioStore()
    await store.store("b1", b"d", session_id="sessA")
    await store.store("b2", b"d", session_id="sessB")
    
    await store.burn_session("sessA")
    
    r = await store.retrieve("b2", session_id="sessB")
    assert r is not None


@pytest.mark.asyncio
async def test_inmemory_cleanup_expired_removes_expired():
    store = InMemoryAudioStore()
    await store.store("exp1", b"expired", session_id=None, ttl_seconds=-10.0)
    await store.store("alive1", b"alive", session_id=None, ttl_seconds=3600.0)
    
    removed = await store.cleanup_expired()
    assert removed >= 1
    
    assert await store.retrieve("exp1", session_id=None) is None
    assert await store.retrieve("alive1", session_id=None) is not None


@pytest.mark.asyncio
async def test_inmemory_expired_record_returns_none():
    store = InMemoryAudioStore()
    await store.store("ex2", b"data", session_id=None, ttl_seconds=-1.0)
    result = await store.retrieve("ex2", session_id=None)
    assert result is None


# ---------------------------------------------------------------------------
# In-memory clarification store tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inmemory_clarification_store_satisfies_interface():
    store = InMemoryClarificationStore()
    assert isinstance(store, BaseClarificationStore)


@pytest.mark.asyncio
async def test_inmemory_clarification_store_round_trip():
    store = InMemoryClarificationStore()
    ok = await store.store_pending("sess1", ["support"], "needs filter", "get_support_tickets")
    assert ok is True
    pc = await store.get_pending("sess1")
    assert pc is not None
    assert pc.session_id == "sess1"
    assert pc.target_tool == "get_support_tickets"


@pytest.mark.asyncio
async def test_inmemory_clarification_consume_is_atomic():
    """Two concurrent tasks must NOT both receive the same pending clarification."""
    store = InMemoryClarificationStore()
    await store.store_pending("sess_atomic", ["support"], "test", "get_support_tickets")
    
    results = await asyncio.gather(
        store.consume_pending("sess_atomic"),
        store.consume_pending("sess_atomic"),
    )
    non_none = [r for r in results if r is not None]
    assert len(non_none) == 1, "Exactly one consumer should get the clarification"


@pytest.mark.asyncio
async def test_inmemory_clarification_expired_returns_none():
    store = InMemoryClarificationStore(default_ttl_seconds=0.01)
    await store.store_pending("sess_exp", ["crm"], "expired test", "get_crm_data")
    await asyncio.sleep(0.05)
    result = await store.get_pending("sess_exp")
    assert result is None


@pytest.mark.asyncio
async def test_inmemory_clarification_session_isolation():
    store = InMemoryClarificationStore()
    await store.store_pending("sessA", ["support"], "test", "get_support_tickets")
    result_b = await store.consume_pending("sessB")
    assert result_b is None
    # sessA's context must still be there
    result_a = await store.consume_pending("sessA")
    assert result_a is not None


@pytest.mark.asyncio
async def test_inmemory_clarification_anonymous_session_stores_nothing():
    store = InMemoryClarificationStore()
    ok = await store.store_pending(None, ["support"], "test", "get_support_tickets")
    assert ok is False
    ok2 = await store.store_pending("", ["support"], "test", "get_support_tickets")
    assert ok2 is False


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_factory_returns_inmemory_store_for_memory_backend():
    """get_audio_store() returns InMemoryAudioStore with STORAGE_BACKEND=memory."""
    from app.storage import factory
    from app.storage.memory import InMemoryAudioStore, InMemoryClarificationStore
    
    class FakeSettings:
        STORAGE_BACKEND = "memory"
        AUDIO_TTL_SECONDS = 3600.0
        CLARIFICATION_TTL_SECONDS = 120.0
    
    # Reset factory state
    factory._audio_store = None
    factory._clarification_store = None
    factory._redis_client = None
    
    await factory.init_storage(FakeSettings())
    
    assert isinstance(factory.get_audio_store(), InMemoryAudioStore)
    assert isinstance(factory.get_clarification_store(), InMemoryClarificationStore)
    
    # Reset factory state back
    factory._audio_store = None
    factory._clarification_store = None


# ---------------------------------------------------------------------------
# Redis integration tests (skipped if Redis unavailable)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _REDIS_AVAILABLE, reason="Redis not running at localhost:6379")
@pytest.mark.asyncio
async def test_redis_audio_store_round_trip():
    import redis.asyncio as aioredis
    from app.storage.redis_backend import RedisAudioStore
    
    client = aioredis.from_url(_TEST_REDIS_URL, decode_responses=False)
    store = RedisAudioStore(client=client, default_ttl=60.0, key_prefix="pvda_test")
    
    try:
        await store.store("r_id1", b"redis_data", session_id="rs1")
        result = await store.retrieve("r_id1", session_id="rs1")
        assert result is not None
        assert result[0] == b"redis_data"
    finally:
        await store.burn_session("rs1")
        await client.aclose()


@pytest.mark.skipif(not _REDIS_AVAILABLE, reason="Redis not running at localhost:6379")
@pytest.mark.asyncio
async def test_redis_audio_ownership_checks():
    import redis.asyncio as aioredis
    from app.storage.redis_backend import RedisAudioStore
    
    client = aioredis.from_url(_TEST_REDIS_URL, decode_responses=False)
    store = RedisAudioStore(client=client, default_ttl=60.0, key_prefix="pvda_test")
    
    try:
        await store.store("r_id2", b"data", session_id="sessA")
        # Wrong session
        assert await store.retrieve("r_id2", session_id="sessB") is None
        # No session
        assert await store.retrieve("r_id2", session_id=None) is None
        # Correct session
        assert await store.retrieve("r_id2", session_id="sessA") is not None
    finally:
        await store.burn_session("sessA")
        await client.aclose()


@pytest.mark.skipif(not _REDIS_AVAILABLE, reason="Redis not running at localhost:6379")
@pytest.mark.asyncio
async def test_redis_clarification_atomic_consume():
    import redis.asyncio as aioredis
    from app.storage.redis_backend import RedisClarificationStore
    
    client = aioredis.from_url(_TEST_REDIS_URL, decode_responses=False)
    store = RedisClarificationStore(client=client, default_ttl=60.0, key_prefix="pvda_test")
    
    try:
        await store.store_pending("r_sess1", ["support"], "test", "get_support_tickets")
        results = await asyncio.gather(
            store.consume_pending("r_sess1"),
            store.consume_pending("r_sess1"),
        )
        non_none = [r for r in results if r is not None]
        assert len(non_none) == 1
    finally:
        await client.aclose()


@pytest.mark.skipif(not _REDIS_AVAILABLE, reason="Redis not running at localhost:6379")
@pytest.mark.asyncio
async def test_redis_startup_failure_with_unavailable_redis():
    """STORAGE_BACKEND=redis with bad URL must raise, not fall back."""
    from app.storage import factory
    
    class FakeSettings:
        STORAGE_BACKEND = "redis"
        REDIS_URL = "redis://localhost:19999/0"
        AUDIO_TTL_SECONDS = 3600.0
        CLARIFICATION_TTL_SECONDS = 120.0
    
    factory._audio_store = None
    factory._clarification_store = None
    factory._redis_client = None
    
    with pytest.raises(Exception):
        await factory.init_storage(FakeSettings())
    
    factory._audio_store = None
    factory._clarification_store = None
    factory._redis_client = None


# ---------------------------------------------------------------------------
# Task 4 — Multi-instance tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _REDIS_AVAILABLE, reason="Redis not running at localhost:6379")
@pytest.mark.asyncio
async def test_multi_instance_audio_cross_instance_retrieval_and_isolation():
    """
    Multi-instance test:
    1. Instance A stores audio; instance B retrieves it with the correct session.
    2. Instance B cannot retrieve it using another session ID or without session ID.
    """
    import redis.asyncio as aioredis
    from app.storage.redis_backend import RedisAudioStore

    client_a = aioredis.from_url(_TEST_REDIS_URL, decode_responses=False)
    client_b = aioredis.from_url(_TEST_REDIS_URL, decode_responses=False)

    store_a = RedisAudioStore(client=client_a, default_ttl=60.0, key_prefix="pvda_multi")
    store_b = RedisAudioStore(client=client_b, default_ttl=60.0, key_prefix="pvda_multi")

    test_audio_id = "multi_audio_1"
    sess_id = "session_multi_user"

    try:
        # 1. Instance A stores audio
        await store_a.store(test_audio_id, b"SHARED_MULTI_AUDIO_BYTES", media_type="audio/wav", session_id=sess_id)

        # 2. Instance B retrieves it with correct session
        res_b = await store_b.retrieve(test_audio_id, session_id=sess_id)
        assert res_b is not None
        assert res_b[0] == b"SHARED_MULTI_AUDIO_BYTES"
        assert res_b[1] == "audio/wav"

        # 3. Instance B cannot retrieve using wrong session ID
        assert await store_b.retrieve(test_audio_id, session_id="wrong_session") is None

        # 4. Instance B cannot retrieve without session ID
        assert await store_b.retrieve(test_audio_id, session_id=None) is None
    finally:
        await store_b.burn_session(sess_id)
        await client_a.aclose()
        await client_b.aclose()


@pytest.mark.skipif(not _REDIS_AVAILABLE, reason="Redis not running at localhost:6379")
@pytest.mark.asyncio
async def test_multi_instance_clarification_cross_instance_consume_and_race():
    """
    Multi-instance test:
    3. Instance A stores clarification; instance B consumes it.
    4. Two concurrent consumers (across instances A and B) cannot both receive the same clarification.
    """
    import redis.asyncio as aioredis
    from app.storage.redis_backend import RedisClarificationStore

    client_a = aioredis.from_url(_TEST_REDIS_URL, decode_responses=False)
    client_b = aioredis.from_url(_TEST_REDIS_URL, decode_responses=False)

    store_a = RedisClarificationStore(client=client_a, default_ttl=60.0, key_prefix="pvda_multi")
    store_b = RedisClarificationStore(client=client_b, default_ttl=60.0, key_prefix="pvda_multi")

    sess_1 = "sess_multi_clarif_1"
    sess_2 = "sess_multi_clarif_race"

    try:
        # Part 1: Instance A stores; Instance B consumes
        await store_a.store_pending(sess_1, ["support"], "reason1", "get_support_tickets")
        consumed_by_b = await store_b.consume_pending(sess_1)
        assert consumed_by_b is not None
        assert consumed_by_b.session_id == sess_1
        assert consumed_by_b.target_tool == "get_support_tickets"

        # Subsequent consume by A must be None
        assert await store_a.consume_pending(sess_1) is None

        # Part 2: Concurrent race across instance A and instance B
        await store_a.store_pending(sess_2, ["crm"], "reason2", "get_crm_data")
        results = await asyncio.gather(
            store_a.consume_pending(sess_2),
            store_b.consume_pending(sess_2),
        )
        non_none = [r for r in results if r is not None]
        assert len(non_none) == 1, "Exactly one cross-instance consumer must win the atomic GETDEL race"
    finally:
        await store_a.clear_session(sess_1)
        await store_b.clear_session(sess_2)
        await client_a.aclose()
        await client_b.aclose()


@pytest.mark.skipif(not _REDIS_AVAILABLE, reason="Redis not running at localhost:6379")
@pytest.mark.asyncio
async def test_multi_instance_burn_session_cross_instance_cleanup():
    """
    Multi-instance test:
    5. Session cleanup from instance B removes audio stored by instance A.
    """
    import redis.asyncio as aioredis
    from app.storage.redis_backend import RedisAudioStore

    client_a = aioredis.from_url(_TEST_REDIS_URL, decode_responses=False)
    client_b = aioredis.from_url(_TEST_REDIS_URL, decode_responses=False)

    store_a = RedisAudioStore(client=client_a, default_ttl=60.0, key_prefix="pvda_multi")
    store_b = RedisAudioStore(client=client_b, default_ttl=60.0, key_prefix="pvda_multi")

    sess = "sess_multi_cleanup_test"
    aid_1 = "audio_from_a_1"
    aid_2 = "audio_from_a_2"

    try:
        await store_a.store(aid_1, b"DATA_1", session_id=sess)
        await store_a.store(aid_2, b"DATA_2", session_id=sess)

        # Instance B executes burn_session
        cleaned = await store_b.burn_session(sess)
        assert cleaned == 2

        # Both instances now see None
        assert await store_a.retrieve(aid_1, session_id=sess) is None
        assert await store_b.retrieve(aid_2, session_id=sess) is None
    finally:
        await store_a.burn_session(sess)
        await client_a.aclose()
        await client_b.aclose()


@pytest.mark.skipif(not _REDIS_AVAILABLE, reason="Redis not running at localhost:6379")
@pytest.mark.asyncio
async def test_multi_instance_ttl_expiry_respected():
    """
    Multi-instance test:
    6. TTL expiry is respected across both instances.
    """
    import redis.asyncio as aioredis
    from app.storage.redis_backend import RedisAudioStore, RedisClarificationStore

    client_a = aioredis.from_url(_TEST_REDIS_URL, decode_responses=False)
    client_b = aioredis.from_url(_TEST_REDIS_URL, decode_responses=False)

    audio_a = RedisAudioStore(client=client_a, default_ttl=1.0, key_prefix="pvda_multi")
    audio_b = RedisAudioStore(client=client_b, default_ttl=1.0, key_prefix="pvda_multi")
    clarif_a = RedisClarificationStore(client=client_a, default_ttl=1.0, key_prefix="pvda_multi")
    clarif_b = RedisClarificationStore(client=client_b, default_ttl=1.0, key_prefix="pvda_multi")

    sess = "sess_ttl_expiry_test"
    aid = "audio_ttl_test"

    try:
        await audio_a.store(aid, b"SHORT_LIVED", session_id=sess, ttl_seconds=1.0)
        await clarif_a.store_pending(sess, ["analytics"], "ttl_test", "get_analytics")

        # Verify initially accessible from B
        assert await audio_b.retrieve(aid, session_id=sess) is not None
        assert await clarif_b.get_pending(sess) is not None

        # Wait for TTL to elapse
        await asyncio.sleep(1.2)

        # Both instances must now see expired records as None
        assert await audio_b.retrieve(aid, session_id=sess) is None
        assert await audio_a.retrieve(aid, session_id=sess) is None
        assert await clarif_b.get_pending(sess) is None
        assert await clarif_a.get_pending(sess) is None
    finally:
        await audio_a.burn_session(sess)
        await clarif_a.clear_session(sess)
        await client_a.aclose()
        await client_b.aclose()


@pytest.mark.skipif(not _REDIS_AVAILABLE, reason="Redis not running at localhost:6379")
@pytest.mark.asyncio
async def test_multi_instance_original_and_obfuscated_audio_retrieval():
    """
    Multi-instance test:
    7. Original and obfuscated audio artifacts retain intended retrieval behavior across instances.
    """
    import redis.asyncio as aioredis
    from app.storage.redis_backend import RedisAudioStore

    client_a = aioredis.from_url(_TEST_REDIS_URL, decode_responses=False)
    client_b = aioredis.from_url(_TEST_REDIS_URL, decode_responses=False)

    store_a = RedisAudioStore(client=client_a, default_ttl=60.0, key_prefix="pvda_multi")
    store_b = RedisAudioStore(client=client_b, default_ttl=60.0, key_prefix="pvda_multi")

    req_id = "req_dual_test_123"
    orig_id = f"orig_{req_id}"
    obf_id = f"obf_{req_id}"
    session_id = "sess_dual_audio_test"

    orig_bytes = b"ORIGINAL_RAW_VOICE_PCM_DATA"
    obf_bytes = b"OBFUSCATED_PITCH_SHIFTED_DATA"

    try:
        # Instance A stores both artifacts associated with the session
        await store_a.store(orig_id, orig_bytes, media_type="audio/wav", session_id=session_id)
        await store_a.store(obf_id, obf_bytes, media_type="audio/wav", session_id=session_id)

        # Instance B retrieves original audio with matching session
        orig_retrieved = await store_b.retrieve(orig_id, session_id=session_id)
        assert orig_retrieved is not None
        assert orig_retrieved[0] == orig_bytes
        assert orig_retrieved[1] == "audio/wav"

        # Instance B retrieves obfuscated audio with matching session
        obf_retrieved = await store_b.retrieve(obf_id, session_id=session_id)
        assert obf_retrieved is not None
        assert obf_retrieved[0] == obf_bytes
        assert obf_retrieved[1] == "audio/wav"

        # Repeatable playback across instances
        repeat_orig = await store_b.retrieve(orig_id, session_id=session_id)
        assert repeat_orig is not None and repeat_orig[0] == orig_bytes

        # Cross-session isolation: mismatched session gets None
        assert await store_b.retrieve(orig_id, session_id="wrong_session") is None
        assert await store_b.retrieve(obf_id, session_id="wrong_session") is None

        # Missing session gets None
        assert await store_b.retrieve(orig_id, session_id=None) is None
        assert await store_b.retrieve(obf_id, session_id=None) is None

        # Instance B burns session -> both artifacts burned
        burned_count = await store_b.burn_session(session_id)
        assert burned_count == 2
        assert await store_a.retrieve(orig_id, session_id=session_id) is None
        assert await store_b.retrieve(obf_id, session_id=session_id) is None
    finally:
        await store_a.burn_session(session_id)
        await client_a.aclose()
        await client_b.aclose()


@pytest.mark.skipif(not _REDIS_AVAILABLE, reason="Redis not running at localhost:6379")
@pytest.mark.asyncio
async def test_redis_factory_lifecycle_and_fail_fast():
    """
    Multi-instance lifecycle test:
    8. Redis connection/client lifecycle and fail-fast behavior without accidental fallback.
    """
    from app.storage import factory
    from app.storage.redis_backend import RedisAudioStore, RedisClarificationStore

    class ValidRedisSettings:
        STORAGE_BACKEND = "redis"
        REDIS_URL = _TEST_REDIS_URL
        AUDIO_TTL_SECONDS = 3600.0
        CLARIFICATION_TTL_SECONDS = 120.0

    # Reset factory state
    factory._audio_store = None
    factory._clarification_store = None
    factory._redis_client = None

    try:
        # Initialize storage with Redis backend
        await factory.init_storage(ValidRedisSettings())

        # Verify correct store types returned
        audio_store = factory.get_audio_store()
        clarif_store = factory.get_clarification_store()
        assert isinstance(audio_store, RedisAudioStore)
        assert isinstance(clarif_store, RedisClarificationStore)
        assert factory._redis_client is not None

        # Graceful shutdown closes client and resets stores
        await factory.close_storage()
        assert factory._redis_client is None
        assert factory._audio_store is None
        assert factory._clarification_store is None

        # Post-shutdown: when STORAGE_BACKEND=redis and uninitialized, calling get_audio_store
        # must raise RuntimeError, preventing accidental fallback to in-memory store
        from app.config import settings
        orig_backend = settings.STORAGE_BACKEND
        try:
            settings.STORAGE_BACKEND = "redis"
            with pytest.raises(RuntimeError, match="Storage backend is configured as 'redis'"):
                factory.get_audio_store()
            with pytest.raises(RuntimeError, match="Storage backend is configured as 'redis'"):
                factory.get_clarification_store()
        finally:
            settings.STORAGE_BACKEND = orig_backend
    finally:
        await factory.close_storage()

