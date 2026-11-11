"""
app/storage/memory.py — Async in-memory implementations of BaseAudioStore and
BaseClarificationStore.

These are the default backends (STORAGE_BACKEND=memory).  They require no
external services and work correctly in single-process deployments.

Thread-safety: asyncio.Lock is used so awaiting in async context is safe.
The lock is non-blocking for the event loop (it yields control while waiting,
unlike threading.Lock which blocks the OS thread).

Documented limitation: state is process-local. Multi-worker ASGI deployments
(uvicorn --workers N > 1) without sticky sessions will not share state across
workers.  Use STORAGE_BACKEND=redis for shared state.

Legacy Compatibility Bridge:
To support existing synchronous test suites (e.g., test_api.py and test_obfuscation_inspector.py)
that directly interact with `app.voice.audio_store.audio_store` or `app.services.clarification_context`,
InMemoryAudioStore and InMemoryClarificationStore maintain thread-safe bidirectional state mirroring
with those legacy singletons. This ensures synchronous TestClient harnesses remain fully operational
without requiring immediate architectural rewrites of legacy test modules.
"""
import asyncio
import time
import logging
from typing import Dict, List, Optional, Tuple

from app.storage.interfaces import BaseAudioStore, BaseClarificationStore, PendingClarification

logger = logging.getLogger(__name__)

_BURN_GRACE_SECONDS = 15.0  # Grace window after explicit burn before expiry


class InMemoryAudioStore(BaseAudioStore):
    """
    Async in-memory audio store.

    Ownership invariant (tightened per Phase 2.1 requirements):
    - Audio stored with session_id=None (anonymous) can ONLY be retrieved without
      supplying a session_id.  If a caller provides any session_id, retrieval of
      anonymous audio is blocked.
    - Audio stored with session_id=X can ONLY be retrieved by a caller presenting
      session_id=X.  A missing session_id from the caller also blocks retrieval.
    """

    def __init__(self, default_ttl_seconds: float = 3600.0):
        self.default_ttl = default_ttl_seconds
        self._store: Dict[str, dict] = {}
        self._lock = asyncio.Lock()

    async def store(
        self,
        audio_id: str,
        data: bytes,
        media_type: str = "audio/wav",
        ttl_seconds: Optional[float] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> str:
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        now = time.time()
        async with self._lock:
            self._store[audio_id] = {
                "data": data,
                "media_type": media_type,
                "session_id": session_id,       # None means anonymous
                "request_id": request_id,
                "created_at": now,
                "expires_at": now + ttl,
                "read_count": 0,
                "burned": False,
            }
        # Also sync to legacy audio_store if imported
        try:
            from app.voice.audio_store import audio_store as legacy
            if legacy is not None and legacy is not self and hasattr(legacy, "_store"):
                with legacy._lock:
                    legacy._store[audio_id] = {
                        "data": data,
                        "media_type": media_type,
                        "session_id": session_id,
                        "request_id": request_id,
                        "created_at": now,
                        "expires_at": now + ttl,
                        "read_count": 0,
                        "burned": False,
                    }
        except Exception:
            pass
        return audio_id

    async def retrieve(
        self,
        audio_id: str,
        burn: bool = False,
        session_id: Optional[str] = None,
    ) -> Optional[Tuple[bytes, str]]:
        """
        Ownership rules (strict):
        - Stored session_id == None (anonymous): caller MUST NOT supply a session_id.
        - Stored session_id == X: caller MUST supply the exact same X.
        Any mismatch or missing session when one is required returns None → 404.
        """
        now = time.time()
        # Strictly check if deleted in legacy store
        try:
            from app.voice.audio_store import audio_store as legacy
            if legacy is not None and legacy is not self and hasattr(legacy, "_store"):
                with legacy._lock:
                    if audio_id not in legacy._store and audio_id in self._store:
                        # It was explicitly burned or deleted in legacy store
                        del self._store[audio_id]
                        return None
                    elif audio_id not in self._store and audio_id in legacy._store:
                        self._store[audio_id] = dict(legacy._store[audio_id])
        except Exception:
            pass

        async with self._lock:
            item = self._store.get(audio_id)
            if not item:
                return None
            if now > item["expires_at"]:
                del self._store[audio_id]
                return None

            item_sess = item.get("session_id")

            # Strict ownership check:
            # Case 1: anonymous audio — caller must not supply any session_id.
            if item_sess is None and session_id is not None:
                return None
            # Case 2: session-bound audio — caller must supply the exact session_id.
            if item_sess is not None and session_id != item_sess:
                return None

            item["read_count"] += 1
            data = item["data"]
            media_type = item["media_type"]

            if burn:
                item["burned"] = True
                item["expires_at"] = min(item["expires_at"], now + _BURN_GRACE_SECONDS)

            return data, media_type

    async def burn_session(self, session_id: str) -> int:
        if not session_id:
            return 0
        async with self._lock:
            keys = [k for k, v in self._store.items() if v.get("session_id") == session_id]
            for k in keys:
                del self._store[k]
        try:
            from app.voice.audio_store import audio_store as legacy
            if legacy is not None and legacy is not self and hasattr(legacy, "burn_session"):
                legacy.burn_session(session_id)
        except Exception:
            pass
        return len(keys)

    async def burn_all(self) -> int:
        async with self._lock:
            count = len(self._store)
            self._store.clear()
        try:
            from app.voice.audio_store import audio_store as legacy
            if legacy is not None and legacy is not self and hasattr(legacy, "burn_all"):
                legacy.burn_all()
        except Exception:
            pass
        return count

    async def burn_immediately(self, audio_id: str) -> bool:
        existed = False
        async with self._lock:
            if audio_id in self._store:
                del self._store[audio_id]
                existed = True
        try:
            from app.voice.audio_store import audio_store as legacy
            if legacy is not None and legacy is not self and hasattr(legacy, "burn_immediately"):
                if legacy.burn_immediately(audio_id):
                    existed = True
        except Exception:
            pass
        return existed

    async def cleanup_expired(self) -> int:
        now = time.time()
        async with self._lock:
            expired = [k for k, v in self._store.items() if now > v["expires_at"]]
            for k in expired:
                del self._store[k]
        return len(expired)


class InMemoryClarificationStore(BaseClarificationStore):
    """
    Async in-memory clarification store.

    Atomic consume: asyncio.Lock ensures that two concurrent coroutines in the
    same process cannot both pop the same pending clarification.  (For cross-process
    atomicity, use the Redis backend.)
    """

    def __init__(self, default_ttl_seconds: float = 120.0):
        self._store: Dict[str, PendingClarification] = {}
        self._lock = asyncio.Lock()
        self.default_ttl = default_ttl_seconds

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
        pc = PendingClarification(
            session_id=sess,
            target_tool=resolved_tool,
            matched_domains=list(matched_domains),
            reason=reason,
            created_at=now,
            expires_at=now + self.default_ttl,
        )
        async with self._lock:
            self._store[sess] = pc

        # Sync to legacy clarification_store if present
        try:
            from app.services.clarification_context import clarification_store as legacy
            if legacy is not None and legacy is not self and hasattr(legacy, "_store"):
                with legacy._lock:
                    legacy._store[sess] = pc
        except Exception:
            pass
        return True

    async def get_pending(self, session_id: Optional[str]) -> Optional[PendingClarification]:
        if not session_id or not session_id.strip():
            return None
        sess = session_id.strip()
        now = time.time()
        # Fallback check legacy
        try:
            from app.services.clarification_context import clarification_store as legacy
            if sess not in self._store and legacy is not None and legacy is not self and hasattr(legacy, "_store"):
                with legacy._lock:
                    if sess in legacy._store:
                        self._store[sess] = legacy._store[sess]
        except Exception:
            pass

        async with self._lock:
            pc = self._store.get(sess)
            if not pc:
                return None
            if now > pc.expires_at:
                del self._store[sess]
                return None
            return pc

    async def consume_pending(self, session_id: Optional[str]) -> Optional[PendingClarification]:
        if not session_id or not session_id.strip():
            return None
        sess = session_id.strip()
        now = time.time()
        # Fallback check legacy
        try:
            from app.services.clarification_context import clarification_store as legacy
            if sess not in self._store and legacy is not None and legacy is not self and hasattr(legacy, "_store"):
                with legacy._lock:
                    if sess in legacy._store:
                        self._store[sess] = legacy._store[sess]
        except Exception:
            pass

        async with self._lock:
            pc = self._store.pop(sess, None)
            if not pc:
                return None
            if now > pc.expires_at:
                return None

        # Clean from legacy too
        try:
            from app.services.clarification_context import clarification_store as legacy
            if legacy is not None and legacy is not self and hasattr(legacy, "_store"):
                with legacy._lock:
                    legacy._store.pop(sess, None)
        except Exception:
            pass

        return pc

    async def clear_session(self, session_id: Optional[str]) -> bool:
        if not session_id or not session_id.strip():
            return False
        sess = session_id.strip()
        async with self._lock:
            res = bool(self._store.pop(sess, None))
        try:
            from app.services.clarification_context import clarification_store as legacy
            if legacy is not None and legacy is not self and hasattr(legacy, "_store"):
                with legacy._lock:
                    if legacy._store.pop(sess, None):
                        res = True
        except Exception:
            pass
        return res
