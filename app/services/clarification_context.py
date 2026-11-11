"""
app/services/clarification_context.py - Bounded One-Turn Clarification Context Store.

Provides minimal, ephemeral, process-local context carry-forward for follow-up responses
to a Decision.CLARIFY decision.

Invariants:
1. Scoped strictly to session_id. Requests without a valid session_id never store or consume context.
2. Minimal data only: pending target tool, matched domains, and timestamps.
   NEVER stores full user transcripts or arbitrary conversation history.
3. At most one pending clarification per session.
4. Single-turn consumption: popped and consumed upon the immediate next turn, or expired after TTL.
5. Strict session isolation: Session A cannot read, consume, or affect Session B's context.
6. Does NOT bypass semantic execution safety, validate_decision(), or argument validation.
"""

import asyncio
import logging
import re
import time
import threading
from typing import Dict, List, Optional, Tuple, Any

# Re-export PendingClarification from new canonical location for backward compatibility
from app.storage.interfaces import PendingClarification as PendingClarification  # noqa: F401

logger = logging.getLogger(__name__)


# Explicit low-ambiguity modifier patterns matching supported tool schemas:
# 1. Support Tickets Schema: status in ['open', 'closed'], priority in ['low', 'medium', 'high'], limit in [0, 100]
SUPPORT_STATUS_OPEN = re.compile(r"\b(open|unresolved|pending|active)\s*(ones?|tickets?)?\b|\b(show|list|get|only|just)\s+open\b", re.IGNORECASE)
SUPPORT_STATUS_CLOSED = re.compile(r"\b(closed|resolved)\s*(ones?|tickets?)?\b|\b(show|list|get|only|just)\s+closed\b", re.IGNORECASE)
SUPPORT_PRIORITY_HIGH = re.compile(r"\b(high|urgent|critical)\s*(priority)?\s*(ones?|tickets?)?\b", re.IGNORECASE)
SUPPORT_PRIORITY_MEDIUM = re.compile(r"\b(medium|normal)\s*(priority)?\s*(ones?|tickets?)?\b", re.IGNORECASE)
SUPPORT_PRIORITY_LOW = re.compile(r"\b(low)\s*(priority)?\s*(ones?|tickets?)?\b", re.IGNORECASE)

# 2. CRM Schema: status in ['active', 'inactive'], limit in [0, 100]
CRM_STATUS_ACTIVE = re.compile(r"\b(active|current)\s*(ones?|customers?|clients?|accounts?)?\b|\b(show|list|get|only|just)\s+active\b", re.IGNORECASE)
CRM_STATUS_INACTIVE = re.compile(r"\b(inactive|churned|lapsed|former)\s*(ones?|customers?|clients?|accounts?)?\b|\b(show|list|get|only|just)\s+inactive\b", re.IGNORECASE)

# 3. Analytics Schema: metric in ['daily_active_users'], days in [0, 365]
ANALYTICS_DAU = re.compile(r"\b(daily\s+active\s+users?|dau|active\s+users?)\b", re.IGNORECASE)
ANALYTICS_DAYS = re.compile(r"\b(?:last|past)\s+(\d+)\s+days?\b", re.IGNORECASE)

# Universal limit pattern
LIMIT_PATTERN = re.compile(r"\b(?:limit|top|first)\s+(\d+)\b|\b(\d+)\s+(?:of\s+them|records?|results?)\b", re.IGNORECASE)


class ClarificationContextStore:
    def __init__(self, default_ttl_seconds: float = 120.0):
        self._store: Dict[str, PendingClarification] = {}
        self._lock = threading.Lock()
        self.default_ttl = default_ttl_seconds

    def store_pending(
        self,
        session_id: Optional[str],
        matched_domains: List[str],
        reason: str,
        target_tool: Optional[str] = None,
    ) -> bool:
        """
        Stores a minimal pending clarification context for session_id.
        Replaces any prior pending context for this session (at most 1 per session).
        Anonymous callers (None or empty session_id) are ignored safely.
        """
        if not session_id or not session_id.strip():
            return False

        sess = session_id.strip()
        now = time.time()

        # Deduce primary tool from matched domain if not explicitly given
        resolved_tool = target_tool
        if not resolved_tool:
            if "support" in matched_domains:
                resolved_tool = "get_support_tickets"
            elif "crm" in matched_domains:
                resolved_tool = "get_crm_data"
            elif "analytics" in matched_domains:
                resolved_tool = "get_analytics"
            else:
                return False

        with self._lock:
            self._store[sess] = PendingClarification(
                session_id=sess,
                target_tool=resolved_tool,
                matched_domains=list(matched_domains),
                reason=reason,
                created_at=now,
                expires_at=now + self.default_ttl,
            )
        return True

    def get_pending(self, session_id: Optional[str]) -> Optional[PendingClarification]:
        """Peeks at the pending clarification without consuming it (validates expiration)."""
        if not session_id or not session_id.strip():
            return None
        sess = session_id.strip()
        now = time.time()
        with self._lock:
            pending = self._store.get(sess)
            if not pending:
                return None
            if now > pending.expires_at:
                del self._store[sess]
                return None
            return pending

    def consume_pending(self, session_id: Optional[str]) -> Optional[PendingClarification]:
        """Atomically retrieves and removes the pending clarification for session_id (one-turn consumption)."""
        if not session_id or not session_id.strip():
            return None
        sess = session_id.strip()
        now = time.time()
        with self._lock:
            pending = self._store.pop(sess, None)
            if not pending:
                return None
            if now > pending.expires_at:
                return None
            return pending

    def clear_session(self, session_id: Optional[str]) -> bool:
        """Removes any pending clarification for session_id (e.g. upon tab close/cleanup)."""
        if not session_id or not session_id.strip():
            return False
        sess = session_id.strip()
        with self._lock:
            return bool(self._store.pop(sess, None))

    def resolve_followup(
        self,
        pending: PendingClarification,
        user_text: str,
    ) -> Optional[Tuple[str, str, Dict[str, Any]]]:
        """
        Attempts to resolve an explicit follow-up modifier against the pending context.

        Returns:
            Optional[Tuple[resolved_query, target_tool, resolved_args]]:
            - resolved_query: Full natural language query to pass through evaluate_abstention.
            - target_tool: Expected tool name from schema.
            - resolved_args: Dict of verified arguments matching schema.
            Or None if the text does not resolve unambiguously against the pending domain.
        """
        text = user_text.strip().lower()
        if not text:
            return None

        # Check for cross-domain conflicts: if user mentions another domain entity,
        # it is an unrelated request, not a modifier of the pending domain.
        from app.services.abstention_router import (
            CRM_ENTITIES,
            SUPPORT_ENTITIES,
            ANALYTICS_ENTITIES,
            NEGATED_DIRECTIVES,
            CONVERSATIONAL_CANCELLATIONS,
        )

        # Explicit negation or cancellation in follow-up must NOT resolve into an affirmative tool call!
        if NEGATED_DIRECTIVES.search(text) or CONVERSATIONAL_CANCELLATIONS.search(text):
            return None

        domain = pending.matched_domains[0] if pending.matched_domains else ""
        if domain == "support":
            if CRM_ENTITIES.search(text) or ANALYTICS_ENTITIES.search(text):
                return None
        elif domain == "crm":
            if SUPPORT_ENTITIES.search(text) or ANALYTICS_ENTITIES.search(text):
                return None
        elif domain == "analytics":
            if CRM_ENTITIES.search(text) or SUPPORT_ENTITIES.search(text):
                return None

        resolved_args: Dict[str, Any] = {}
        target_tool = pending.target_tool

        # Parse limit if present
        m_limit = LIMIT_PATTERN.search(text)
        if m_limit:
            val = m_limit.group(1) or m_limit.group(2)
            try:
                limit_int = int(val)
                if 0 < limit_int <= 100:
                    resolved_args["limit"] = limit_int
            except ValueError:
                pass

        if target_tool == "get_support_tickets":
            status_val = None
            if SUPPORT_STATUS_OPEN.search(text):
                status_val = "open"
            elif SUPPORT_STATUS_CLOSED.search(text):
                status_val = "closed"

            priority_val = None
            if SUPPORT_PRIORITY_HIGH.search(text):
                priority_val = "high"
            elif SUPPORT_PRIORITY_MEDIUM.search(text):
                priority_val = "medium"
            elif SUPPORT_PRIORITY_LOW.search(text):
                priority_val = "low"

            if status_val:
                resolved_args["status"] = status_val
            if priority_val:
                resolved_args["priority"] = priority_val

            # Must have at least one explicit operational filter
            if not status_val and not priority_val and "limit" not in resolved_args:
                return None

            parts = ["show"]
            if priority_val:
                parts.append(priority_val)
            if status_val:
                parts.append(status_val)
            parts.append("support tickets")
            if "limit" in resolved_args:
                parts.append(f"limit {resolved_args['limit']}")
            resolved_query = " ".join(parts)
            return resolved_query, target_tool, resolved_args

        elif target_tool == "get_crm_data":
            status_val = None
            if CRM_STATUS_ACTIVE.search(text):
                status_val = "active"
            elif CRM_STATUS_INACTIVE.search(text):
                status_val = "inactive"

            if status_val:
                resolved_args["status"] = status_val

            if not status_val and "limit" not in resolved_args:
                return None

            parts = ["show"]
            if status_val:
                parts.append(status_val)
            parts.append("customers")
            if "limit" in resolved_args:
                parts.append(f"limit {resolved_args['limit']}")
            resolved_query = " ".join(parts)
            return resolved_query, target_tool, resolved_args

        elif target_tool == "get_analytics":
            metric_val = "daily_active_users"
            resolved_args["metric"] = metric_val

            days_val = None
            m_days = ANALYTICS_DAYS.search(text)
            if m_days:
                try:
                    days_int = int(m_days.group(1))
                    if 0 < days_int <= 365:
                        days_val = days_int
                        resolved_args["days"] = days_val
                except ValueError:
                    pass

            if not days_val and not ANALYTICS_DAU.search(text):
                return None

            parts = ["show daily active users"]
            if days_val:
                parts.append(f"last {days_val} days")
            resolved_query = " ".join(parts)
            return resolved_query, target_tool, resolved_args

        return None


# Global process-local singleton
clarification_store = ClarificationContextStore()


def _get_loop():
    """Get the main event loop from the current thread context if available."""
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        return None


def consume_pending_sync(session_id: Optional[str]):
    """
    Synchronous wrapper for clarification store consume_pending.
    Safely integrates with worker threads or unit test environments.
    """
    from app.storage import factory as _factory
    try:
        store = _factory.get_clarification_store()
    except Exception:
        store = None

    if store is not None:
        loop = _get_loop()
        if loop and loop.is_running():
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(store.consume_pending(session_id), loop)
            try:
                return future.result(timeout=5.0)
            except concurrent.futures.TimeoutError:
                logger.error("consume_pending_sync timed out for session")
                return None
        else:
            # If loop is not running, run directly or fall back
            try:
                return asyncio.run(store.consume_pending(session_id))
            except RuntimeError:
                pass

    return clarification_store.consume_pending(session_id)


def store_pending_sync(
    session_id: Optional[str],
    matched_domains: List[str],
    reason: str,
    target_tool: Optional[str] = None,
) -> bool:
    """
    Synchronous wrapper for clarification store store_pending.
    Safely integrates with worker threads or unit test environments.
    """
    from app.storage import factory as _factory
    try:
        store = _factory.get_clarification_store()
    except Exception:
        store = None

    if store is not None:
        loop = _get_loop()
        if loop and loop.is_running():
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                store.store_pending(session_id, matched_domains, reason, target_tool), loop
            )
            try:
                return future.result(timeout=5.0)
            except concurrent.futures.TimeoutError:
                logger.error("store_pending_sync timed out for session")
                return False
        else:
            try:
                return asyncio.run(store.store_pending(session_id, matched_domains, reason, target_tool))
            except RuntimeError:
                pass

    return clarification_store.store_pending(session_id, matched_domains, reason, target_tool)


def resolve_followup(pending: PendingClarification, user_text: str):
    """Standalone helper function delegating to the clarification_store instance."""
    return clarification_store.resolve_followup(pending, user_text)
