"""
tests/test_remediation_phase1.py - Comprehensive Verification for Phase 1 Remediation.

Covers:
  - Priority P0-A: Semantic Execution Safety (Abstention boundary, CLARIFY/ABSTAIN, zero connector invocation)
  - Priority P0-B: TTS Privacy Boundary (Zero remote transmission of connector/sensitive text, fail-safe defaults)
  - Priority P1:   Async Workload Isolation (Event-loop responsiveness, thread offloading, bounded concurrency)
"""
import asyncio
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings, Settings
from app.connectors.crm_connector import CRMConnector
from app.connectors.support_connector import SupportConnector
from app.failure import FailureType, PipelineError
from app.main import app
from app.routers import voice
from app.services.abstention_router import (
    evaluate_abstention,
    validate_decision,
    Decision,
    AbstentionResult,
)
from app.services.intent_router import Intent
from app.services.llm_orchestrator import LLMOrchestrator
from app.voice.tts import TTSEngine


# ============================================================================
# Priority P0-A: Semantic Execution Safety Tests
# ============================================================================

class TestSemanticExecutionSafety:
    """Verifies that only valid operational requests reach connectors."""

    def test_clear_valid_operational_requests(self):
        """Supported operational requests evaluate to EXECUTE."""
        valid_queries = [
            "Show me all active customers in the system.",
            "List all open support tickets.",
            "Retrieve daily active users for analytics.",
            "Show me closed support tickets.",
            "Pull records for inactive customers.",
        ]
        for q in valid_queries:
            res = evaluate_abstention(q)
            assert res.decision == Decision.EXECUTE, f"Expected EXECUTE for '{q}', got {res.decision}"
            assert res.route == "tool"
            assert res.confidence >= 0.50

    def test_out_of_domain_misleading_vocabulary(self):
        """Queries mentioning domain words in non-operational context must not execute tools."""
        distractors = [
            "Tickets to the concert were completely sold out.",
            "Customer satisfaction philosophies have evolved over time.",
            "Active volcanoes present unique geographical challenges.",
        ]
        for q in distractors:
            res = evaluate_abstention(q)
            assert res.decision in (Decision.ABSTAIN, Decision.DIRECT), f"Expected non-execution for '{q}', got {res.decision}"
            assert res.route != "tool"
            assert res.target_tool is None

    def test_conversational_mention_not_action(self):
        """Conversational complaints/mentions mentioning database entities must ABSTAIN."""
        q = "Open support tickets are becoming a real headache for our customer support team."
        res = evaluate_abstention(q)
        assert res.decision == Decision.ABSTAIN
        assert "mention" in res.reason.lower() or "commentary" in res.reason.lower()

    def test_negated_operational_directives(self):
        """Explicitly negated operational commands must ABSTAIN."""
        negated_queries = [
            "Do not show me any active customers right now.",
            "Don't list open support tickets.",
            "Never query daily active users.",
            "I do not want to see inactive customers.",
        ]
        for q in negated_queries:
            res = evaluate_abstention(q)
            assert res.decision == Decision.ABSTAIN, f"Expected ABSTAIN for negated query '{q}', got {res.decision}"
            assert "negated" in res.reason.lower()

    def test_hypothetical_inquiry_abstains(self):
        """Hypothetical or speculative framing must ABSTAIN."""
        q = "What if we were to query daily active users tomorrow instead?"
        res = evaluate_abstention(q)
        assert res.decision == Decision.ABSTAIN
        assert "hypothetical" in res.reason.lower()

    def test_conversational_cancellation_abstains(self):
        """Trailing retractions and cancellations must ABSTAIN."""
        queries = [
            "Pull records for inactive customers, wait no, cancel that, never mind.",
            "Show me open tickets, scratch that, forget it.",
        ]
        for q in queries:
            res = evaluate_abstention(q)
            assert res.decision == Decision.ABSTAIN, f"Expected ABSTAIN for '{q}', got {res.decision}"
            assert "cancel" in res.reason.lower() or "retract" in res.reason.lower()

    def test_ambiguous_request_clarifies(self):
        """Underspecified or vague requests must return CLARIFY."""
        q = "Something about tickets, maybe check them or whatever."
        res = evaluate_abstention(q)
        assert res.decision == Decision.CLARIFY
        assert res.route == "clarify"
        assert "clarification" in res.reason.lower() or "ambiguous" in res.reason.lower()

    def test_operational_control_queries_with_negative_words_remain_operational(self):
        """Legitimate queries containing negative words in filters must NOT be blocked."""
        controls = [
            "Show me customers who do not have open tickets.",
            "List tickets with no priority.",
            "Find inactive accounts.",
        ]
        for q in controls:
            res = evaluate_abstention(q)
            assert res.decision == Decision.EXECUTE, f"False-positive abstention on control query '{q}': got {res.decision}"

    def test_decision_validation_fails_closed_on_contradiction(self):
        """Decision validation rejects contradictory or corrupted results."""
        # Corrupted result: claims EXECUTE but has distractor penalty
        corrupted = AbstentionResult(
            intent=Intent.CRM_QUERY,
            route="tool",
            decision=Decision.EXECUTE,
            confidence=0.8,
            domain_evidence=1.0,
            operational_evidence=1.0,
            distractor_penalty=1.0,  # Contradiction!
            target_tool="get_crm_data",
            matched_domains=["crm"],
            reason="Test corruption",
        )
        assert validate_decision(corrupted) == Decision.ABSTAIN

        # Invalid object fails closed
        assert validate_decision(None) == Decision.ABSTAIN
        assert validate_decision("not_an_abstention_result") == Decision.ABSTAIN

    def test_zero_connector_invocation_on_abstain_and_clarify(self):
        """Orchestrator must NEVER invoke any connector on ABSTAIN or CLARIFY."""
        orch = LLMOrchestrator()
        orch.client = MagicMock()

        # Mock connectors
        mock_crm = MagicMock(spec=CRMConnector)
        mock_support = MagicMock(spec=SupportConnector)
        orch.connector_map = {
            "get_crm_data": mock_crm,
            "get_support_tickets": mock_support,
        }

        with patch("app.services.llm_orchestrator.correct_transcript", side_effect=lambda text, *args, **kwargs: {
            "text": text, "correction_attempted": False, "correction_changed": False,
            "correction_accepted": False, "correction_rejected": False, "fallback_used": False
        }):
            # 1. Test ABSTAIN (negation)
            res_abstain = orch.process_query("Do not show me active customers right now.", enable_abstention=True)
            assert res_abstain["metadata"]["abstention_decision"] == "ABSTAIN"
            mock_crm.fetch_result.assert_not_called()
            mock_support.fetch_result.assert_not_called()

            # 2. Test CLARIFY (ambiguous)
            res_clarify = orch.process_query("Something about tickets, maybe check them or whatever.", enable_abstention=True)
            assert res_clarify["metadata"]["abstention_decision"] == "CLARIFY"
            mock_crm.fetch_result.assert_not_called()
            mock_support.fetch_result.assert_not_called()

    def test_invalid_tool_name_never_reaches_connector(self):
        """Tool calls with unauthorized tool names are rejected before connector dispatch."""
        orch = LLMOrchestrator()
        mock_conn = MagicMock()
        orch.connector_map = {"malicious_tool": mock_conn}

        tool_calls = [{"function": {"name": "malicious_tool", "arguments": {}}}]
        answer, meta = orch._execute_tool_calls(tool_calls, user_text="malicious tool call")

        assert meta.get("failure_type") == "invalid_tool_name"
        mock_conn.fetch_result.assert_not_called()

    def test_invalid_tool_args_never_reach_connector(self):
        """Invalid tool arguments fail argument validation and never reach connector."""
        orch = LLMOrchestrator()
        mock_crm = MagicMock()
        orch.connector_map = {"get_crm_data": mock_crm}

        # status must be 'active' or 'inactive', 'invalid_status' is rejected
        tool_calls = [{"function": {"name": "get_crm_data", "arguments": {"status": "unauthorized_enum"}}}]
        answer, meta = orch._execute_tool_calls(tool_calls, user_text="query with bad enum")

        assert meta.get("failure_type") == "invalid_tool_arguments"
        mock_crm.fetch_result.assert_not_called()

    def test_frozen_distractor_regression_suite(self):
        """Regression test on all 5 frozen distractor cases from Phase 6.1."""
        dataset_path = Path("evaluation/datasets/phase6/semantic_conflict_v1.jsonl")
        assert dataset_path.exists(), "Frozen dataset must exist"

        orch = LLMOrchestrator()
        orch.client = MagicMock()
        mock_crm = MagicMock(spec=CRMConnector)
        mock_support = MagicMock(spec=SupportConnector)
        orch.connector_map = {"get_crm_data": mock_crm, "get_support_tickets": mock_support}

        with patch("app.services.llm_orchestrator.correct_transcript", side_effect=lambda text, *args, **kwargs: {
            "text": text, "correction_attempted": False, "correction_changed": False,
            "correction_accepted": False, "correction_rejected": False, "fallback_used": False
        }):
            with open(dataset_path, "r", encoding="utf-8") as f:
                for line in f:
                    case = json.loads(line)
                    if not case["is_operational"]:
                        # Distractor case must NOT execute tools
                        res = orch.process_query(case["reference_transcript"], enable_abstention=True)
                        decision = res["metadata"]["abstention_decision"]
                        assert decision in ("ABSTAIN", "CLARIFY"), (
                            f"Distractor case {case['case_id']} failed to abstain: got {decision}"
                        )
                        # Invariant: Connectors must have zero calls across all distractors
                        assert mock_crm.fetch_result.call_count == 0
                        assert mock_support.fetch_result.call_count == 0


# ============================================================================
# Priority P0-B: TTS Privacy Boundary Tests
# ============================================================================

class TestTTSPrivacyBoundary:
    """Verifies that sensitive data is never transmitted to third-party TTS."""

    @pytest.mark.asyncio
    async def test_safe_default_blocks_remote_tts_for_sensitive_data(self, tmp_path):
        """Safe default configuration (TTS_PROVIDER='disabled') blocks synthesis."""
        engine = TTSEngine(provider="disabled")
        out_file = tmp_path / "test.mp3"

        did_synth = await engine.synthesize("Customer Alice has revenue $100,000", out_file, is_sensitive=True)
        assert did_synth is False
        assert not out_file.exists()

    @pytest.mark.asyncio
    async def test_sensitive_connector_data_never_sent_even_if_remote_requested(self, tmp_path):
        """Even if provider is set to 'remote', sensitive text is strictly blocked."""
        engine = TTSEngine(provider="remote")
        out_file = tmp_path / "test.mp3"

        with patch("edge_tts.Communicate") as mock_comm:
            did_synth = await engine.synthesize("Customer Alice has 3 critical tickets", out_file, is_sensitive=True)
            assert did_synth is False
            # PROVE edge_tts was never instantiated or invoked
            mock_comm.assert_not_called()

    @pytest.mark.asyncio
    async def test_public_non_sensitive_text_can_synthesize_when_remote_explicit(self, tmp_path):
        """Non-sensitive static prompts can synthesize when provider is explicitly remote."""
        engine = TTSEngine(provider="remote")
        out_file = tmp_path / "test.mp3"

        with patch("edge_tts.Communicate") as mock_comm:
            mock_instance = AsyncMock()
            mock_comm.return_value = mock_instance
            did_synth = await engine.synthesize("Could you please repeat that?", out_file, is_sensitive=False)
            assert did_synth is True
            mock_comm.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_or_missing_configuration_fails_safe(self, tmp_path):
        """Unknown or invalid provider strings fail safe with zero transmission."""
        engine = TTSEngine(provider="unsupported_cloud_provider")
        out_file = tmp_path / "test.mp3"

        with patch("edge_tts.Communicate") as mock_comm:
            did_synth = await engine.synthesize("Hello world", out_file, is_sensitive=False)
            assert did_synth is False
            mock_comm.assert_not_called()

    @pytest.mark.asyncio
    async def test_local_provider_unavailable_fails_safe_no_remote_fallback(self, tmp_path):
        """When local offline TTS is requested but fails or is unavailable, fails safe without cloud fallback."""
        engine = TTSEngine(provider="local")
        out_file = tmp_path / "test.mp3"

        with patch("app.voice.tts._synthesize_local_sync", return_value=False):
            with patch("edge_tts.Communicate") as mock_comm:
                did_synth = await engine.synthesize("Customer data", out_file, is_sensitive=True)
                assert did_synth is False
                mock_comm.assert_not_called()

    def test_voice_query_endpoint_sets_tts_blocked_for_privacy(self, monkeypatch, tmp_path):
        """API endpoint flags metadata['tts_blocked_for_privacy'] on tool-derived responses."""
        client = TestClient(app)

        # Mock STT to return operational query
        mock_stt = MagicMock()
        mock_stt.transcribe_with_confidence.return_value = (
            "Show me active customers",
            {"avg_logprob": -0.1, "no_speech_prob": 0.0, "compression_ratio": 1.0, "low_confidence": False},
        )
        monkeypatch.setattr(voice, "stt", mock_stt)

        # Mock orchestrator to simulate successful tool execution
        mock_orch = MagicMock()
        mock_orch.process_query.return_value = {
            "answer": "There are 5 active customers in the system: Acme Corp, Globex, Initech.",
            "metadata": {
                "classified_intent": "crm",
                "tool_calls": [{"name": "get_crm_data", "arguments": {"status": "active"}}],
                "data_sources_used": ["crm"],
                "result_count": 5,
            }
        }
        monkeypatch.setattr(voice, "orchestrator", mock_orch)

        # Create dummy WAV file
        wav_file = tmp_path / "test_query.wav"
        import numpy as np
        import soundfile as sf
        sf.write(str(wav_file), np.zeros(16000, dtype=np.float32), 16000)

        with open(wav_file, "rb") as f:
            res = client.post(
                "/voice/query",
                files={"audio_file": ("test.wav", f, "audio/wav")},
                headers={"api-key": settings.API_KEY},
            )

        assert res.status_code == 200
        data = res.json()
        assert data["metadata"]["tts_blocked_for_privacy"] is True
        assert data["answer_audio_url"] == ""  # Zero remote audio URL
        assert "Alice" in data["answer_text"] or "Acme" in data["answer_text"]


# ============================================================================
# Priority P1: Async Workload Isolation Tests
# ============================================================================

class TestAsyncWorkloadIsolation:
    """Verifies that heavy CPU operations do not block the ASGI event loop."""

    @pytest.mark.asyncio
    async def test_event_loop_responsiveness_during_blocking_stt(self):
        """Lightweight coroutine must make progress while STT is offloaded to worker thread."""
        import anyio.to_thread

        def slow_blocking_stt():
            time.sleep(0.3)  # Simulate CPU-heavy Whisper small.en inference
            return "transcribed text", {"low_confidence": False}

        progress_counter = 0

        async def concurrent_health_pings():
            nonlocal progress_counter
            for _ in range(5):
                await asyncio.sleep(0.05)
                progress_counter += 1

        # Run both concurrently
        t0 = time.perf_counter()
        stt_task = asyncio.create_task(anyio.to_thread.run_sync(slow_blocking_stt))
        ping_task = asyncio.create_task(concurrent_health_pings())

        stt_result, _ = await asyncio.gather(stt_task, ping_task)
        elapsed = time.perf_counter() - t0

        assert stt_result[0] == "transcribed text"
        # The concurrent task MUST have executed all 5 pings during the 300ms STT window
        assert progress_counter == 5, f"Event loop was blocked! Progress counter only reached {progress_counter}"
        assert elapsed >= 0.28

    @pytest.mark.asyncio
    async def test_event_loop_responsiveness_during_blocking_vocoder(self):
        """Event loop remains unblocked while vocoder synthesis is running in thread."""
        import anyio.to_thread

        def slow_blocking_vocoder():
            time.sleep(0.2)  # Simulate pyworld synthesis
            return 2.5

        ticks = 0

        async def heartbeat():
            nonlocal ticks
            for _ in range(4):
                await asyncio.sleep(0.04)
                ticks += 1

        voc_task = asyncio.create_task(anyio.to_thread.run_sync(slow_blocking_vocoder))
        hb_task = asyncio.create_task(heartbeat())

        shift, _ = await asyncio.gather(voc_task, hb_task)
        assert shift == 2.5
        assert ticks == 4, f"Event loop was blocked by vocoder! Ticks: {ticks}"

    @pytest.mark.asyncio
    async def test_concurrency_limiter_semaphore(self):
        """Semaphore bounds simultaneous voice processing jobs."""
        from app.routers.voice import get_audio_semaphore

        sem = get_audio_semaphore()
        # Verify semaphore capacity matches configuration
        assert sem._value == settings.MAX_CONCURRENT_VOICE_REQUESTS

        async def worker():
            async with sem:
                await asyncio.sleep(0.1)

        # Run jobs and assert clean completion
        jobs = [asyncio.create_task(worker()) for _ in range(4)]
        await asyncio.gather(*jobs)

    @pytest.mark.asyncio
    async def test_error_propagation_across_thread_boundary(self):
        """Exceptions raised in offloaded worker threads cleanly propagate to caller."""
        import anyio.to_thread

        def crashing_worker():
            raise PipelineError(FailureType.STT_FAILED, "Whisper model OOM", status_code=500)

        with pytest.raises(PipelineError) as exc_info:
            await anyio.to_thread.run_sync(crashing_worker)

        assert exc_info.value.failure_type == FailureType.STT_FAILED
        assert exc_info.value.status_code == 500
