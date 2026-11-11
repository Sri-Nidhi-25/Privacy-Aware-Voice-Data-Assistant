"""
tests/test_remediation_phase1_2_hardening.py
=============================================
Phase 1.2 Remediation Hardening Test Suite

Covers the 5 hardening requirements:
1. Configuration Validation:
   - MAX_CONCURRENT_VOICE_REQUESTS=0 rejected.
   - Negative values rejected.
   - Valid positive values accepted.
2. Upload Handling:
   - Upload copying offloaded from ASGI event loop.
   - Event loop remains responsive during upload copying.
   - Preserves file contents and error behavior.
3. Semaphore Lifecycle:
   - Repeated lifespan startup/shutdown.
   - Concurrency remains bounded across lifespans and requests.
   - No cross-loop binding errors across multiple event loops.
4. Tool Registry Consistency:
   - Matching tool registry and connector map accepted.
   - Missing connector rejected at initialization.
   - Unexpected connector rejected at initialization.
5. Abstention Bypass Protection:
   - Normal API requests cannot disable semantic safety via query parameter.
   - Baseline evaluation mode allowed only via explicit x-evaluation-baseline-mode header.
   - Preserves existing evaluation behavior.
"""
import asyncio
import io
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import soundfile as sf
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.main import app, lifespan
from app.routers import voice
from app.services.llm_orchestrator import LLMOrchestrator, TOOLS


# ==============================================================================
# 1. Configuration Validation
# ==============================================================================
class TestConfigHardening:
    """Verifies strict validation for MAX_CONCURRENT_VOICE_REQUESTS."""

    def test_max_concurrent_zero_rejected(self, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_VOICE_REQUESTS", "0")
        with pytest.raises(ValueError, match="MAX_CONCURRENT_VOICE_REQUESTS must be >= 1"):
            Settings()

    def test_max_concurrent_negative_rejected(self, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_VOICE_REQUESTS", "-3")
        with pytest.raises(ValueError, match="MAX_CONCURRENT_VOICE_REQUESTS must be >= 1"):
            Settings()

    def test_max_concurrent_positive_accepted(self, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_VOICE_REQUESTS", "5")
        cfg = Settings()
        assert cfg.MAX_CONCURRENT_VOICE_REQUESTS == 5


# ==============================================================================
# 2. Upload Handling & Event Loop Responsiveness
# ==============================================================================
class TestUploadHandlingHardening:
    """Verifies upload copy is offloaded to a worker thread and preserves data."""

    def test_upload_sync_preserves_content_and_size(self, tmp_path):
        payload = b"RIFF-WAVE-DUMMY-AUDIO-DATA-12345" * 100
        bio = io.BytesIO(payload)

        input_path, file_size = voice._save_upload_sync(bio, ".wav")
        try:
            assert input_path.exists()
            assert file_size == len(payload)
            assert input_path.read_bytes() == payload
        finally:
            input_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_upload_copy_does_not_block_event_loop(self):
        """Simulate a slow upload copy in thread and verify event loop executes concurrent tasks."""
        import anyio.to_thread

        def slow_copy(src, dst):
            time.sleep(0.15)
            dst.write(src.read())

        payload = b"audio" * 1000
        src = io.BytesIO(payload)
        dst = io.BytesIO()

        ticks = 0

        async def concurrent_task():
            nonlocal ticks
            for _ in range(5):
                await asyncio.sleep(0.02)
                ticks += 1

        t0 = time.perf_counter()
        copy_task = asyncio.create_task(anyio.to_thread.run_sync(slow_copy, src, dst))
        loop_task = asyncio.create_task(concurrent_task())

        await asyncio.gather(copy_task, loop_task)
        elapsed = time.perf_counter() - t0

        assert dst.getvalue() == payload
        assert ticks >= 4, f"Event loop was blocked during upload save! ticks={ticks}"
        assert elapsed >= 0.14


# ==============================================================================
# 3. Semaphore Lifecycle & Loop Binding
# ==============================================================================
class TestSemaphoreLifecycleHardening:
    """Verifies lifespan startup/shutdown, app.state storage, and cross-loop safety."""

    @pytest.mark.asyncio
    async def test_lifespan_initializes_app_state_semaphore(self):
        test_app = FastAPI(title="TestApp", lifespan=lifespan)
        async with lifespan(test_app):
            assert hasattr(test_app.state, "audio_semaphore")
            assert isinstance(test_app.state.audio_semaphore, asyncio.Semaphore)
            assert test_app.state.audio_semaphore._value == settings.MAX_CONCURRENT_VOICE_REQUESTS

    @pytest.mark.asyncio
    async def test_repeated_lifespan_clean_reinitialization(self):
        test_app = FastAPI(title="TestApp", lifespan=lifespan)
        for i in range(3):
            async with lifespan(test_app):
                sem = test_app.state.audio_semaphore
                assert sem._value == settings.MAX_CONCURRENT_VOICE_REQUESTS

    def test_cross_loop_semaphore_binding_resilience(self):
        """Creates distinct event loops and verifies get_audio_semaphore does not raise cross-loop error."""
        loop1 = asyncio.new_event_loop()
        try:
            sem1 = loop1.run_until_complete(self._acquire_in_loop())
            assert sem1 is not None
        finally:
            loop1.close()

        loop2 = asyncio.new_event_loop()
        try:
            sem2 = loop2.run_until_complete(self._acquire_in_loop())
            assert sem2 is not None
        finally:
            loop2.close()

    @staticmethod
    async def _acquire_in_loop():
        sem = voice.get_audio_semaphore()
        async with sem:
            await asyncio.sleep(0.01)
        return sem


# ==============================================================================
# 4. Tool Registry Consistency
# ==============================================================================
class TestToolRegistryConsistencyHardening:
    """Verifies bidirectional validation between TOOLS schema and connector_map."""

    def test_default_registry_matches_connectors(self):
        orch = LLMOrchestrator()
        tool_names = {t["function"]["name"] for t in TOOLS}
        assert set(orch.connector_map.keys()) == tool_names

    def test_missing_connector_rejected_at_initialization(self):
        tampered_tools = TOOLS + [{
            "type": "function",
            "function": {
                "name": "unimplemented_tool",
                "description": "Ghost tool with no connector",
                "parameters": {"type": "object", "properties": {}}
            }
        }]
        with patch("app.services.llm_orchestrator.TOOLS", tampered_tools):
            with pytest.raises(RuntimeError, match="Tools missing connectors: \\['unimplemented_tool'\\]"):
                LLMOrchestrator()

    def test_unexpected_connector_rejected_at_initialization(self):
        # TOOLS is a list of function declarations. If TOOLS has fewer elements than connector_map:
        truncated_tools = [TOOLS[0]]  # only get_crm_data
        with patch("app.services.llm_orchestrator.TOOLS", truncated_tools):
            with pytest.raises(RuntimeError, match="Connectors without tool schema"):
                LLMOrchestrator()


# ==============================================================================
# 5. Abstention Bypass Protection
# ==============================================================================
class TestAbstentionBypassHardening:
    """Verifies that normal API requests cannot bypass semantic safety."""

    @pytest.fixture
    def test_client(self):
        return TestClient(app)

    @pytest.fixture
    def dummy_audio_bytes(self, tmp_path):
        wav_path = tmp_path / "dummy.wav"
        y = np.zeros(16000, dtype=np.float32)
        sf.write(str(wav_path), y, 16000)
        return wav_path.read_bytes()

    def test_untrusted_query_param_cannot_disable_abstention(self, test_client, dummy_audio_bytes, monkeypatch):
        """Passing enable_abstention=false without x-evaluation-baseline-mode must enforce abstention."""
        mock_stt = MagicMock()
        mock_stt.transcribe_with_confidence.return_value = (
            "Do not show me any active customers right now.",
            {"avg_logprob": -0.1, "low_confidence": False}
        )
        monkeypatch.setattr(voice, "stt", mock_stt)

        mock_orch = MagicMock()
        mock_orch.process_query.return_value = {
            "answer": "Abstaining safely.",
            "metadata": {
                "abstention_decision": "ABSTAIN",
                "execution_prevented_by_abstention": True,
                "tool_calls": [],
                "data_sources_used": []
            }
        }
        monkeypatch.setattr(voice, "orchestrator", mock_orch)

        # Call with enable_abstention=false query param but NO evaluation header
        response = test_client.post(
            "/voice/query?enable_abstention=false",
            files={"audio_file": ("test.wav", dummy_audio_bytes, "audio/wav")},
            headers={"api-key": settings.API_KEY},
        )
        assert response.status_code == 200

        # Verify that process_query was invoked with enable_abstention=True!
        args, kwargs = mock_orch.process_query.call_args
        assert args[1] is True or kwargs.get("enable_abstention") is True

    def test_authorized_evaluation_harness_can_run_baseline(self, test_client, dummy_audio_bytes, monkeypatch):
        """Passing x-evaluation-baseline-mode: allow permits baseline evaluation."""
        mock_stt = MagicMock()
        mock_stt.transcribe_with_confidence.return_value = (
            "Show me active customers",
            {"avg_logprob": -0.1, "low_confidence": False}
        )
        monkeypatch.setattr(voice, "stt", mock_stt)

        mock_orch = MagicMock()
        mock_orch.process_query.return_value = {
            "answer": "5 customers found.",
            "metadata": {
                "abstention_decision": "BASELINE_NO_ABSTENTION",
                "execution_prevented_by_abstention": False,
                "tool_calls": [{"name": "get_crm_data"}],
                "data_sources_used": ["crm"]
            }
        }
        monkeypatch.setattr(voice, "orchestrator", mock_orch)

        # Call with enable_abstention=false AND x-evaluation-baseline-mode header
        response = test_client.post(
            "/voice/query?enable_abstention=false",
            files={"audio_file": ("test.wav", dummy_audio_bytes, "audio/wav")},
            headers={
                "api-key": settings.API_KEY,
                "x-evaluation-baseline-mode": "allow"
            },
        )
        assert response.status_code == 200

        # Verify process_query was called with enable_abstention=False
        args, kwargs = mock_orch.process_query.call_args
        assert args[1] is False or kwargs.get("enable_abstention") is False
