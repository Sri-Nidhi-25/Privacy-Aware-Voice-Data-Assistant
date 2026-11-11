"""
app/storage/interfaces.py — Abstract async interfaces for audio and clarification storage.

Both backends (in-memory and Redis) implement these protocols identically.
Callers depend only on these interfaces, not on concrete implementations.

Design rules:
- All public methods are async coroutines.
- Signatures are identical across all implementations.
- In-memory implementations use asyncio.Lock to avoid blocking the event loop.
- Sensitive audio bytes, session IDs, and transcript content must never appear in logs.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any


# ---------------------------------------------------------------------------
# Shared data model
# ---------------------------------------------------------------------------

@dataclass
class PendingClarification:
    """
    Minimal bounded clarification state stored between a CLARIFY turn and its follow-up.

    Invariants:
    - NEVER stores full user transcripts or arbitrary conversation history.
    - At most one entry per session.
    - Expires after TTL_SECONDS (120s by default).
    - Single-turn consumption: popped and gone on the next request.
    """
    session_id: str
    target_tool: str
    matched_domains: List[str]
    reason: str
    created_at: float
    expires_at: float


# ---------------------------------------------------------------------------
# Audio store interface
# ---------------------------------------------------------------------------

class BaseAudioStore(ABC):
    """
    Async interface for ephemeral audio storage.

    Ownership / isolation contract:
    - Audio stored with a session_id may ONLY be retrieved by a caller presenting
      the same session_id.
    - Audio stored without a session_id (anonymous) may ONLY be retrieved without
      a session_id.  A missing or mismatched session_id never bypasses ownership.
    - Repeatable retrieval (burn=False, default): the caller may stream the same
      audio multiple times while it remains alive.
    - Explicit burn (burn=True): a 15-second grace window is applied; the item
      expires shortly after.
    - Session cleanup: burn_session() removes all audio records belonging to that
      session immediately.
    """

    @abstractmethod
    async def store(
        self,
        audio_id: str,
        data: bytes,
        media_type: str = "audio/wav",
        ttl_seconds: Optional[float] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> str:
        """Store audio bytes; returns audio_id."""

    @abstractmethod
    async def retrieve(
        self,
        audio_id: str,
        burn: bool = False,
        session_id: Optional[str] = None,
    ) -> Optional[Tuple[bytes, str]]:
        """
        Retrieve audio bytes and media_type.

        Returns None when:
        - audio_id does not exist or has expired.
        - session_id does not match the stored owner session.
        - audio stored with no session_id is requested with a session_id (or vice versa).
        """

    @abstractmethod
    async def burn_session(self, session_id: str) -> int:
        """Delete all audio belonging to session_id. Returns count removed."""

    @abstractmethod
    async def burn_all(self) -> int:
        """Delete all stored audio. Returns count removed."""

    @abstractmethod
    async def burn_immediately(self, audio_id: str) -> bool:
        """Delete a single audio record immediately. Returns True if it existed."""

    @abstractmethod
    async def cleanup_expired(self) -> int:
        """Remove all expired records. Returns count removed."""


# ---------------------------------------------------------------------------
# Clarification store interface
# ---------------------------------------------------------------------------

class BaseClarificationStore(ABC):
    """
    Async interface for bounded one-turn clarification context.

    Invariants (identical to the original in-memory implementation):
    - Scoped strictly to session_id.
    - Anonymous callers (None or empty session_id) never store or consume context.
    - At most one pending clarification per session.
    - Single-turn consumption: atomically retrieved and deleted in one operation.
    - TTL: 120 seconds (enforced per-implementation).
    - Session A cannot read, consume, or affect Session B's context.
    - resolve_followup() lives on the concrete ClarificationContextStore class (not
      on the interface) because it is pure-Python regex logic and backend-independent.
    """

    @abstractmethod
    async def store_pending(
        self,
        session_id: Optional[str],
        matched_domains: List[str],
        reason: str,
        target_tool: Optional[str] = None,
    ) -> bool:
        """
        Store minimal pending clarification context.
        Returns True if stored, False if session_id is absent or domain is unknown.
        """

    @abstractmethod
    async def get_pending(
        self,
        session_id: Optional[str],
    ) -> Optional[PendingClarification]:
        """Peek at pending clarification without consuming it."""

    @abstractmethod
    async def consume_pending(
        self,
        session_id: Optional[str],
    ) -> Optional[PendingClarification]:
        """
        Atomically retrieve and delete the pending clarification.
        Returns None if absent, expired, or session_id is invalid.
        Two concurrent callers must NOT both receive the same pending context.
        """

    @abstractmethod
    async def clear_session(self, session_id: Optional[str]) -> bool:
        """Remove any pending clarification for session_id. Returns True if one existed."""
