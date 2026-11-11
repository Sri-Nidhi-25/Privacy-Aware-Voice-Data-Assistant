"""
app/storage/redis_backend.py — Redis-backed implementations of BaseAudioStore and BaseClarificationStore.

Requires redis>=5.0 (which includes redis.asyncio).
Redis availability: selected via STORAGE_BACKEND=redis in config.
If Redis is unavailable at startup, the application FAILS FAST — no silent fallback.

Key schema:
  Audio data:      {prefix}:audio:{audio_id}       (Redis hash)
  Session index:   {prefix}:sess:{session_id}:ids  (Redis Set of audio_ids)
  Clarification:   {prefix}:clarif:{session_id}    (Redis string, JSON)
"""
import json
import logging
import time
from typing import List, Optional, Tuple

import redis.asyncio as aioredis

from app.storage.interfaces import BaseAudioStore, BaseClarificationStore, PendingClarification

logger = logging.getLogger(__name__)

_BURN_GRACE_SECONDS = 15.0


class RedisAudioStore(BaseAudioStore):
    """
    Redis-backed audio store.
    
    Audio stored as a Redis hash. Session-to-audio membership stored in a Redis Set.
    Both records get a TTL so Redis handles expiry natively.
    
    Ownership invariant (same as InMemoryAudioStore):
    - Anonymous audio (session_id=None): only retrievable without a session_id.
    - Session-bound audio: requires exact session_id match.
    """

    def __init__(
        self,
        client: aioredis.Redis,
        default_ttl: float = 3600.0,
        key_prefix: str = "pvda",
    ):
        self._client = client
        self._default_ttl = default_ttl
        self._prefix = key_prefix

    def _audio_key(self, audio_id: str) -> str:
        return f"{self._prefix}:audio:{audio_id}"

    def _sess_key(self, session_id: str) -> str:
        return f"{self._prefix}:sess:{session_id}:ids"

    async def store(
        self,
        audio_id: str,
        data: bytes,
        media_type: str = "audio/wav",
        ttl_seconds: Optional[float] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> str:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        ttl_int = max(1, int(ttl))
        now = time.time()
        akey = self._audio_key(audio_id)
        
        mapping = {
            "data": data,
            "media_type": media_type,
            "session_id": session_id or "",
            "request_id": request_id or "",
            "created_at": str(now),
            "expires_at": str(now + ttl),
            "read_count": "0",
            "burned": "0",
        }
        
        pipe = self._client.pipeline(transaction=True)
        pipe.hset(akey, mapping=mapping)
        pipe.expire(akey, ttl_int)
        if session_id:
            skey = self._sess_key(session_id)
            pipe.sadd(skey, audio_id)
            pipe.expire(skey, ttl_int)
        await pipe.execute()
        return audio_id

    async def retrieve(
        self,
        audio_id: str,
        burn: bool = False,
        session_id: Optional[str] = None,
    ) -> Optional[Tuple[bytes, str]]:
        akey = self._audio_key(audio_id)
        item = await self._client.hgetall(akey)
        if not item:
            return None

        # Check expiry
        now = time.time()
        raw_exp = item.get(b"expires_at", item.get("expires_at", 0))
        if isinstance(raw_exp, bytes):
            raw_exp = raw_exp.decode()
        expires_at = float(raw_exp or 0)
        if now > expires_at:
            await self._client.delete(akey)
            return None

        # Ownership check
        stored_sess = item.get(b"session_id", item.get("session_id", b""))
        if isinstance(stored_sess, bytes):
            stored_sess = stored_sess.decode()
        item_sess = stored_sess if stored_sess else None

        if item_sess is None and session_id is not None:
            return None
        if item_sess is not None and session_id != item_sess:
            return None

        raw_data = item.get(b"data", item.get("data", b""))
        if not isinstance(raw_data, bytes):
            raw_data = str(raw_data).encode()

        raw_mt = item.get(b"media_type", item.get("media_type", b"audio/wav"))
        if isinstance(raw_mt, bytes):
            raw_mt = raw_mt.decode()

        # Increment read_count (best-effort)
        try:
            await self._client.hincrby(akey, "read_count", 1)
        except Exception:
            pass

        if burn:
            grace_expires = min(expires_at, now + _BURN_GRACE_SECONDS)
            remaining = max(1, int(grace_expires - now))
            await self._client.expire(akey, remaining)
            await self._client.hset(akey, "burned", "1")

        return raw_data, raw_mt

    async def burn_session(self, session_id: str) -> int:
        if not session_id:
            return 0
        skey = self._sess_key(session_id)
        audio_ids = await self._client.smembers(skey)
        if not audio_ids:
            return 0
        keys = [self._audio_key(aid.decode() if isinstance(aid, bytes) else aid) for aid in audio_ids]
        pipe = self._client.pipeline(transaction=True)
        for k in keys:
            pipe.delete(k)
        pipe.delete(skey)
        await pipe.execute()
        return len(audio_ids)

    async def burn_all(self) -> int:
        count = 0
        async for key in self._client.scan_iter(f"{self._prefix}:audio:*"):
            await self._client.delete(key)
            count += 1
        async for key in self._client.scan_iter(f"{self._prefix}:sess:*"):
            await self._client.delete(key)
        return count

    async def burn_immediately(self, audio_id: str) -> bool:
        akey = self._audio_key(audio_id)
        raw_sess = await self._client.hget(akey, "session_id")
        existed = bool(await self._client.delete(akey))
        if existed and raw_sess:
            sess = raw_sess.decode() if isinstance(raw_sess, bytes) else raw_sess
            if sess:
                await self._client.srem(self._sess_key(sess), audio_id)
        return existed

    async def cleanup_expired(self) -> int:
        return 0


# Lua script for atomic GETDEL
_GETDEL_LUA = """
local v = redis.call('GET', KEYS[1])
if v then
    redis.call('DEL', KEYS[1])
end
return v
"""


class RedisClarificationStore(BaseClarificationStore):
    """
    Redis-backed clarification context store.
    
    Uses JSON-encoded PendingClarification stored as a Redis string with TTL.
    consume_pending uses a Lua script for atomic GET+DEL (compatible with all Redis versions).
    """

    def __init__(
        self,
        client: aioredis.Redis,
        default_ttl: float = 120.0,
        key_prefix: str = "pvda",
    ):
        self._client = client
        self._default_ttl = default_ttl
        self._prefix = key_prefix

    def _clarif_key(self, session_id: str) -> str:
        return f"{self._prefix}:clarif:{session_id}"

    def _resolve_tool(self, matched_domains: List[str], target_tool: Optional[str]) -> Optional[str]:
        if target_tool:
            return target_tool
        if "support" in matched_domains:
            return "get_support_tickets"
        if "crm" in matched_domains:
            return "get_crm_data"
        if "analytics" in matched_domains:
            return "get_analytics"
        return None

    def _serialize(self, pc: PendingClarification) -> str:
        return json.dumps({
            "session_id": pc.session_id,
            "target_tool": pc.target_tool,
            "matched_domains": pc.matched_domains,
            "reason": pc.reason,
            "created_at": pc.created_at,
            "expires_at": pc.expires_at,
        })

    def _deserialize(self, raw: bytes | str) -> Optional[PendingClarification]:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            d = json.loads(raw)
            return PendingClarification(
                session_id=d["session_id"],
                target_tool=d["target_tool"],
                matched_domains=d["matched_domains"],
                reason=d["reason"],
                created_at=d["created_at"],
                expires_at=d["expires_at"],
            )
        except Exception:
            return None

    async def store_pending(
        self,
        session_id: Optional[str],
        matched_domains: List[str],
        reason: str,
        target_tool: Optional[str] = None,
    ) -> bool:
        if not session_id or not session_id.strip():
            return False
        sess = session_id.strip()
        resolved_tool = self._resolve_tool(matched_domains, target_tool)
        if not resolved_tool:
            return False
        now = time.time()
        ttl_int = max(1, int(self._default_ttl))
        pc = PendingClarification(
            session_id=sess,
            target_tool=resolved_tool,
            matched_domains=list(matched_domains),
            reason=reason,
            created_at=now,
            expires_at=now + self._default_ttl,
        )
        await self._client.set(self._clarif_key(sess), self._serialize(pc), ex=ttl_int)
        return True

    async def get_pending(self, session_id: Optional[str]) -> Optional[PendingClarification]:
        if not session_id or not session_id.strip():
            return None
        raw = await self._client.get(self._clarif_key(session_id.strip()))
        if not raw:
            return None
        pc = self._deserialize(raw)
        if pc is None:
            return None
        if time.time() > pc.expires_at:
            await self._client.delete(self._clarif_key(session_id.strip()))
            return None
        return pc

    async def consume_pending(self, session_id: Optional[str]) -> Optional[PendingClarification]:
        if not session_id or not session_id.strip():
            return None
        key = self._clarif_key(session_id.strip())
        raw = await self._client.eval(_GETDEL_LUA, 1, key)
        if not raw:
            return None
        pc = self._deserialize(raw)
        if pc is None:
            return None
        if time.time() > pc.expires_at:
            return None
        return pc

    async def clear_session(self, session_id: Optional[str]) -> bool:
        if not session_id or not session_id.strip():
            return False
        result = await self._client.delete(self._clarif_key(session_id.strip()))
        return bool(result)
