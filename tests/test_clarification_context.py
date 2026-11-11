"""
tests/test_clarification_context.py - Comprehensive Verification for One-Turn Clarification Context

Covers:
1. CLARIFY creates pending context.
2. Valid explicit modifier resolves the pending intent.
3. Ambiguous follow-up does not execute a tool.
4. Unrelated request clears pending context.
5. Context expires or is consumed after one follow-up.
6. Session A cannot access or consume Session B context.
7. Missing session ID does not accidentally share context.
8. Existing abstention and tool validation boundaries remain enforced.
9. Existing normal single-turn requests behave unchanged.
"""

import time
import pytest
from unittest.mock import patch, MagicMock

from app.services.llm_orchestrator import LLMOrchestrator
from app.services.abstention_router import Decision
from app.services.clarification_context import clarification_store, PendingClarification
from app.connectors.base import ConnectorResult
from app.connectors.crm_connector import CRMConnector
from app.connectors.support_connector import SupportConnector
from app.connectors.analytics_connector import AnalyticsConnector


def make_res(data: list, name: str = "") -> ConnectorResult:
    return ConnectorResult(
        data=data,
        retrieved_at="2026-11-04T12:00:00Z",
        source_last_updated="2026-11-04T11:00:00Z",
        freshness_status="fresh",
        success=True,
        connector_name=name,
    )


def noop_correct(text, *args, **kwargs):
    return {
        "text": text,
        "correction_attempted": False,
        "correction_changed": False,
        "correction_accepted": False,
        "correction_rejected": False,
        "fallback_used": False,
    }


@pytest.fixture(autouse=True)
def clean_clarification_store():
    """Ensure the clarification store is completely cleared before and after each test."""
    with clarification_store._lock:
        clarification_store._store.clear()
    yield
    with clarification_store._lock:
        clarification_store._store.clear()


@pytest.fixture
def mock_orchestrator():
    """Creates an orchestrator with mock connectors and noop transcript correction."""
    orch = LLMOrchestrator()
    orch.client = MagicMock()
    # Default chat mock returns simple assistant message
    orch.client.chat.return_value = {
        "message": {"content": "Processed query response", "tool_calls": []}
    }

    orch.mock_crm = MagicMock(spec=CRMConnector)
    orch.mock_support = MagicMock(spec=SupportConnector)
    orch.mock_analytics = MagicMock(spec=AnalyticsConnector)

    orch.mock_crm.fetch_result.return_value = make_res([{"id": 1, "name": "Acme", "status": "active"}], "crm")
    orch.mock_support.fetch_result.return_value = make_res([{"id": 101, "subject": "Bug", "status": "open", "priority": "high"}], "support")
    orch.mock_analytics.fetch_result.return_value = make_res([{"date": "2026-11-01", "daily_active_users": 1500}], "analytics")

    orch.connector_map = {
        "get_crm_data": orch.mock_crm,
        "get_support_tickets": orch.mock_support,
        "get_analytics": orch.mock_analytics,
    }
    return orch


class TestOneTurnClarificationContext:
    """Verifies bounded one-turn clarification context carry-forward."""

    def test_clarify_creates_pending_context(self, mock_orchestrator):
        """1. CLARIFY creates pending context scoped to the session."""
        sess_id = "sess_clarify_create_1"
        query = "Something about tickets, maybe check them or whatever."

        with patch("app.services.llm_orchestrator.correct_transcript", side_effect=noop_correct):
            res = mock_orchestrator.process_query(query, enable_abstention=True, session_id=sess_id)
        assert res["metadata"]["abstention_decision"] == "CLARIFY"

        pending = clarification_store.get_pending(sess_id)
        assert pending is not None
        assert pending.session_id == sess_id
        assert pending.target_tool == "get_support_tickets"
        assert "support" in pending.matched_domains
        assert pending.expires_at > time.time()

        # Connectors must not have been invoked on CLARIFY
        mock_orchestrator.mock_support.fetch_result.assert_not_called()

    def test_valid_explicit_modifier_resolves_pending_intent(self, mock_orchestrator):
        """2. Valid explicit modifier ('Show open ones') resolves the pending ticket intent."""
        sess_id = "sess_resolve_2"

        with patch("app.services.llm_orchestrator.correct_transcript", side_effect=noop_correct):
            # Turn 1: Underspecified request -> CLARIFY
            res1 = mock_orchestrator.process_query(
                "Something about tickets, or whatever.",
                enable_abstention=True,
                session_id=sess_id,
            )
            assert res1["metadata"]["abstention_decision"] == "CLARIFY"
            assert clarification_store.get_pending(sess_id) is not None

            # Turn 2: Explicit follow-up modifier -> Resolves to get_support_tickets(status="open")
            res2 = mock_orchestrator.process_query(
                "Show open ones.",
                enable_abstention=True,
                session_id=sess_id,
            )

        assert res2["metadata"]["abstention_decision"] == "EXECUTE"
        assert res2["metadata"].get("data_sources_used") == ["support"]
        assert mock_orchestrator.mock_support.fetch_result.call_count == 1
        called_args = mock_orchestrator.mock_support.fetch_result.call_args.kwargs
        assert called_args.get("status") == "open"

        # Context must now be consumed
        assert clarification_store.get_pending(sess_id) is None

    def test_valid_explicit_modifier_crm_active(self, mock_orchestrator):
        """2b. Valid modifier ('Only active') resolves pending CRM intent."""
        sess_id = "sess_crm_resolve"

        with patch("app.services.llm_orchestrator.correct_transcript", side_effect=noop_correct):
            # Turn 1: Vague customer request -> CLARIFY
            res1 = mock_orchestrator.process_query(
                "Some stuff about customers, or whatever.",
                enable_abstention=True,
                session_id=sess_id,
            )
            assert res1["metadata"]["abstention_decision"] == "CLARIFY"

            # Turn 2: Follow-up 'Only active' -> get_crm_data(status="active")
            res2 = mock_orchestrator.process_query(
                "Only active.",
                enable_abstention=True,
                session_id=sess_id,
            )
        assert res2["metadata"]["abstention_decision"] == "EXECUTE"
        assert res2["metadata"].get("data_sources_used") == ["crm"]
        assert mock_orchestrator.mock_crm.fetch_result.call_count == 1
        called_args = mock_orchestrator.mock_crm.fetch_result.call_args.kwargs
        assert called_args.get("status") == "active"

    def test_ambiguous_followup_does_not_execute_tool(self, mock_orchestrator):
        """3. Ambiguous follow-up does NOT execute a tool."""
        sess_id = "sess_ambig_3"

        with patch("app.services.llm_orchestrator.correct_transcript", side_effect=noop_correct):
            # Turn 1: CLARIFY
            mock_orchestrator.process_query(
                "Something about tickets, check them or whatever.",
                enable_abstention=True,
                session_id=sess_id,
            )

            # Turn 2: Ambiguous response with no valid operational modifier
            res2 = mock_orchestrator.process_query(
                "Maybe some, I don't know.",
                enable_abstention=True,
                session_id=sess_id,
            )

        # Must NOT execute tool
        assert res2["metadata"]["abstention_decision"] in ("CLARIFY", "DIRECT", "ABSTAIN")
        mock_orchestrator.mock_support.fetch_result.assert_not_called()
        mock_orchestrator.mock_crm.fetch_result.assert_not_called()

    def test_unrelated_request_clears_pending_context(self, mock_orchestrator):
        """4. Unrelated request clears pending context and executes on its own merits."""
        sess_id = "sess_unrelated_4"

        with patch("app.services.llm_orchestrator.correct_transcript", side_effect=noop_correct):
            # Turn 1: Pending ticket request
            mock_orchestrator.process_query(
                "Something about tickets, check them or whatever.",
                enable_abstention=True,
                session_id=sess_id,
            )
            assert clarification_store.get_pending(sess_id) is not None

            # Turn 2: Unrelated request about CRM customers
            mock_orchestrator.client.chat.return_value = {
                "message": {
                    "tool_calls": [{"function": {"name": "get_crm_data", "arguments": {"status": "active"}}}]
                }
            }
            res2 = mock_orchestrator.process_query(
                "Show me active customers.",
                enable_abstention=True,
                session_id=sess_id,
            )

        # Executes CRM, NOT tickets
        assert res2["metadata"]["abstention_decision"] == "EXECUTE"
        assert res2["metadata"].get("data_sources_used") == ["crm"]
        assert mock_orchestrator.mock_crm.fetch_result.call_count == 1
        mock_orchestrator.mock_support.fetch_result.assert_not_called()

        # Ticket context must be cleared
        assert clarification_store.get_pending(sess_id) is None

    def test_context_consumed_after_one_followup(self, mock_orchestrator):
        """5. Context is strictly single-turn: cannot be consumed a second time."""
        sess_id = "sess_consume_5"

        with patch("app.services.llm_orchestrator.correct_transcript", side_effect=noop_correct):
            # Turn 1: CLARIFY
            mock_orchestrator.process_query(
                "Something about tickets, check them or whatever.",
                enable_abstention=True,
                session_id=sess_id,
            )

            # Turn 2: Follow-up resolves
            res2 = mock_orchestrator.process_query("Show open ones.", enable_abstention=True, session_id=sess_id)
            assert res2["metadata"]["abstention_decision"] == "EXECUTE"
            assert mock_orchestrator.mock_support.fetch_result.call_count == 1

            # Turn 3: Another bare modifier cannot reuse the consumed context
            res3 = mock_orchestrator.process_query("Show closed ones.", enable_abstention=True, session_id=sess_id)
            # Without context, "Show closed ones" has no domain entity and routes to DIRECT
            assert res3["metadata"]["abstention_decision"] == "DIRECT"
            # Support connector was NOT called on Turn 3
            assert mock_orchestrator.mock_support.fetch_result.call_count == 1

    def test_context_expiration_ttl(self, mock_orchestrator):
        """5b. Expired context (> 120s) is rejected safely."""
        sess_id = "sess_expired_5b"

        # Manually store expired pending context
        clarification_store.store_pending(sess_id, ["support"], "test", "get_support_tickets")
        with clarification_store._lock:
            clarification_store._store[sess_id].expires_at = time.time() - 10.0

        # Attempt to get or consume -> returns None
        assert clarification_store.get_pending(sess_id) is None
        assert clarification_store.consume_pending(sess_id) is None

        # Query receives no context
        with patch("app.services.llm_orchestrator.correct_transcript", side_effect=noop_correct):
            res = mock_orchestrator.process_query("Show open ones.", enable_abstention=True, session_id=sess_id)
        assert res["metadata"]["abstention_decision"] == "DIRECT"
        mock_orchestrator.mock_support.fetch_result.assert_not_called()

    def test_session_isolation_prevents_cross_session_leak(self, mock_orchestrator):
        """6. Session A cannot access or consume Session B context."""
        sess_a = "session_alice"
        sess_b = "session_bob"

        with patch("app.services.llm_orchestrator.correct_transcript", side_effect=noop_correct):
            # Alice triggers CLARIFY
            mock_orchestrator.process_query(
                "Something about tickets, check them or whatever.",
                enable_abstention=True,
                session_id=sess_a,
            )
            assert clarification_store.get_pending(sess_a) is not None
            assert clarification_store.get_pending(sess_b) is None

            # Bob says "Show open ones." -> Has no context, routes to DIRECT
            res_bob = mock_orchestrator.process_query("Show open ones.", enable_abstention=True, session_id=sess_b)
            assert res_bob["metadata"]["abstention_decision"] == "DIRECT"
            mock_orchestrator.mock_support.fetch_result.assert_not_called()

            # Alice's context is untouched
            assert clarification_store.get_pending(sess_a) is not None

            # Alice says "Show open ones." -> Successfully executes with Alice's context
            res_alice = mock_orchestrator.process_query("Show open ones.", enable_abstention=True, session_id=sess_a)
            assert res_alice["metadata"]["abstention_decision"] == "EXECUTE"
            assert mock_orchestrator.mock_support.fetch_result.call_count == 1

    def test_missing_session_id_does_not_share_context(self, mock_orchestrator):
        """7. Missing session_id (None or empty) never stores or shares context."""
        with patch("app.services.llm_orchestrator.correct_transcript", side_effect=noop_correct):
            # Anonymous query 1
            res1 = mock_orchestrator.process_query(
                "Something about tickets, check them or whatever.",
                enable_abstention=True,
                session_id=None,
            )
            assert res1["metadata"]["abstention_decision"] == "CLARIFY"
            assert clarification_store.get_pending(None) is None
            assert clarification_store.get_pending("") is None

            # Anonymous query 2
            res2 = mock_orchestrator.process_query("Show open ones.", enable_abstention=True, session_id=None)
            assert res2["metadata"]["abstention_decision"] == "DIRECT"
            mock_orchestrator.mock_support.fetch_result.assert_not_called()

    def test_existing_abstention_and_validation_boundaries_enforced(self, mock_orchestrator):
        """8. Abstention and tool validation boundaries remain strictly enforced."""
        sess_id = "sess_safety_8"

        with patch("app.services.llm_orchestrator.correct_transcript", side_effect=noop_correct):
            # Pending context established
            mock_orchestrator.process_query(
                "Something about tickets, check them or whatever.",
                enable_abstention=True,
                session_id=sess_id,
            )

            # Follow-up containing explicit negation: "Do not show open tickets right now" -> distractor penalty!
            res = mock_orchestrator.process_query(
                "Do not show open tickets right now.",
                enable_abstention=True,
                session_id=sess_id,
            )
        # Negation triggers ABSTAIN, never tool execution!
        assert res["metadata"]["abstention_decision"] == "ABSTAIN"
        mock_orchestrator.mock_support.fetch_result.assert_not_called()

    def test_existing_normal_single_turn_requests_unaffected(self, mock_orchestrator):
        """9. Existing normal single-turn requests behave completely unchanged."""
        queries = [
            ("Show me all active customers.", "crm", mock_orchestrator.mock_crm, {"status": "active"}),
            ("List all open support tickets.", "support", mock_orchestrator.mock_support, {"status": "open"}),
            ("What is our daily active users count?", "analytics", mock_orchestrator.mock_analytics, {"metric": "daily_active_users"}),
        ]
        with patch("app.services.llm_orchestrator.correct_transcript", side_effect=noop_correct):
            for q, domain, mock_conn, tool_args in queries:
                mock_conn.reset_mock()
                tool_name = "get_crm_data" if domain == "crm" else ("get_support_tickets" if domain == "support" else "get_analytics")
                mock_orchestrator.client.chat.return_value = {
                    "message": {
                        "tool_calls": [{"function": {"name": tool_name, "arguments": tool_args}}]
                    }
                }
                res = mock_orchestrator.process_query(q, enable_abstention=True, session_id="single_turn_sess")
                assert res["metadata"]["abstention_decision"] == "EXECUTE"
                assert mock_conn.fetch_result.call_count == 1

    def test_session_cleanup_endpoint_clears_clarification_context(self):
        """10. Endpoint /voice/session/cleanup clears any pending clarification context."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.config import settings

        client = TestClient(app)
        sess_id = "test_cleanup_sess_api"
        clarification_store.store_pending(sess_id, ["support"], "test clarification", "get_support_tickets")
        assert clarification_store.get_pending(sess_id) is not None

        res = client.post(f"/voice/session/cleanup?session_id={sess_id}&api_key={settings.API_KEY}")
        assert res.status_code == 200
        assert clarification_store.get_pending(sess_id) is None
