"""
app/voice/audio_store.py - Ephemeral In-Memory Audio RAM Buffer (Legacy Synchronous Store).

Provides synchronous in-memory audio storage (io.BytesIO) to eliminate disk persistence
of sensitive speech and answer audio, mitigating forensic disk recovery risks.

NOTE ON ARCHITECTURE & STORAGE ABSTRACTION:
  This module represents the legacy synchronous single-process audio store.
  Modern application endpoints and tests use the unified async storage abstraction
  (app.storage.factory.get_audio_store(), backed by InMemoryAudioStore or RedisAudioStore).
  
  For backwards-compatibility with synchronous test suites (e.g. test_api.py,
  test_obfuscation_inspector.py), app.storage.memory.InMemoryAudioStore maintains a
  bidirectional synchronization bridge with this store. New application code should
  target app.storage.factory.get_audio_store().

Lifecycle Policy:
- Audio artifacts are held in memory during the active browser session.
- Users can replay, seek, and inspect audio without premature 15-second expiration.
- Audio is burned from RAM immediately when the page session ends (page refresh or tab/window close).
- Safety TTL (default 1 hour) ensures abandoned sessions do not leak memory.
"""
import io
import time
import threading
from typing import Optional, Tuple, Dict


class EphemeralAudioStore:
    def __init__(self, default_ttl_seconds: float = 3600.0):
        self.default_ttl = default_ttl_seconds
        self._store: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def store(
        self,
        audio_id: str,
        data: bytes,
        media_type: str = "audio/wav",
        ttl_seconds: Optional[float] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> str:
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        with self._lock:
            self._store[audio_id] = {
                "data": data,
                "media_type": media_type,
                "session_id": session_id,
                "request_id": request_id,
                "created_at": time.time(),
                "expires_at": time.time() + ttl,
                "read_count": 0,
                "burned": False,
            }
        return audio_id

    def retrieve(
        self,
        audio_id: str,
        burn: bool = False,
        session_id: Optional[str] = None,
    ) -> Optional[Tuple[bytes, str]]:
        now = time.time()
        with self._lock:
            item = self._store.get(audio_id)
            if not item:
                return None
            if now > item["expires_at"]:
                del self._store[audio_id]
                return None

            # Session isolation: if an explicit session_id is provided and the stored
            # audio item is bound to a session, verify they match.
            item_sess = item.get("session_id")
            if session_id is not None and item_sess is not None and session_id != item_sess:
                return None

            item["read_count"] += 1
            data = item["data"]
            media_type = item["media_type"]

            if burn:
                # Explicit burn requested: mark as burned with grace window
                item["burned"] = True
                item["expires_at"] = min(item["expires_at"], now + 15.0)

            return data, media_type

    def get_info(self, audio_id: str) -> Optional[dict]:
        """Returns non-sensitive metadata for a stored audio item without reading bytes."""
        with self._lock:
            item = self._store.get(audio_id)
            if not item:
                return None
            return {
                "audio_id": audio_id,
                "media_type": item["media_type"],
                "session_id": item.get("session_id"),
                "request_id": item.get("request_id"),
                "created_at": item["created_at"],
                "expires_at": item["expires_at"],
                "read_count": item["read_count"],
            }

    def burn_session(self, session_id: str) -> int:
        """Purges all audio files associated with a given client session immediately."""
        if not session_id:
            return 0
        removed = 0
        with self._lock:
            keys_to_delete = [
                k for k, v in self._store.items()
                if v.get("session_id") == session_id
            ]
            for k in keys_to_delete:
                del self._store[k]
                removed += 1
        return removed

    def burn_all(self) -> int:
        """Purges all stored audio files immediately."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    def burn_immediately(self, audio_id: str) -> bool:
        """Wipes a single audio ID immediately from RAM."""
        with self._lock:
            if audio_id in self._store:
                del self._store[audio_id]
                return True
            return False

    def cleanup_expired(self) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            expired_keys = [k for k, v in self._store.items() if now > v["expires_at"]]
            for k in expired_keys:
                del self._store[k]
                removed += 1
        return removed


# Global in-memory ephemeral audio store singleton (1 hour session safety TTL)
# In Phase 2.1, this is an alias to the factory in-memory audio store when in memory mode
audio_store = EphemeralAudioStore(default_ttl_seconds=3600.0)
