"""
tests/test_e2e_smoke/test_smoke.py
==================================
Minimal, Safe, Reproducible End-to-End Smoke Test Suite.

Verifies:
1. Full physical pipeline execution using real audio files through POST /voice/query.
2. Stage-by-stage observability (request_id, per-stage latencies, metadata).
3. Selective abstention execution boundary (ABSTAIN strictly blocks tool/connector execution).
4. Stateless, thread-safe voice obfuscation avoiding concurrency cross-pollution.
"""
import io
import threading
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.services.llm_orchestrator import LLMOrchestrator
from app.voice.obfuscator import FormantPreservingObfuscator

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CLIENT = TestClient(app)
API_KEY = settings.API_KEY or "dev-insecure-key"


class TestEndToEndRealAudioPipeline:
    """Exercises the live HTTP pipeline with a real audio recording."""

    @pytest.fixture
    def sample_audio_path(self):
        # Prefer small benchmark WAV or MPEG in data/
        candidates = [
            PROJECT_ROOT / "data" / "audio" / "Customers.mpeg",
            PROJECT_ROOT / "data" / "Customers.mpeg",
            PROJECT_ROOT / "benchmark_audio" / "phrase_1.wav",
        ]
        for p in candidates:
            if p.exists() and p.stat().st_size > 0:
                return p
        pytest.skip("No real audio sample available for live E2E smoke test")

    def test_live_voice_query_e2e_traceable_outcome(self, sample_audio_path):
        """
        Sends real audio file to POST /voice/query and verifies:
        - Validation and decodability succeed
        - Voice obfuscation applies physical shift & spectral warp
        - STT produces transcript
        - Intent & Abstention decisions are recorded
        - Stage latencies and request_id are present
        """
        content_type = "audio/mpeg" if sample_audio_path.suffix.lower() in (".mp3", ".mpeg") else "audio/wav"
        audio_bytes = sample_audio_path.read_bytes()

        response = CLIENT.post(
            "/voice/query?obfuscation_strength=mild&enable_abstention=true",
            headers={"api-key": API_KEY},
            files={"audio_file": (sample_audio_path.name, io.BytesIO(audio_bytes), content_type)},
        )

        assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}: {response.text}"
        data = response.json()

        # 1. Output structure
        assert "answer_text" in data
        assert "transcript" in data
        assert "metadata" in data
        meta = data["metadata"]

        # 2. Traceability & Request ID
        assert "request_id" in meta
        assert len(meta["request_id"]) > 0

        # 3. Obfuscation execution & parameters
        assert meta.get("obfuscation_strength") == "mild"
        obf_details = meta.get("obfuscation_details", {})
        assert "actual_shift_semitones" in obf_details
        assert "formant_warp_alpha" in obf_details

        # 4. STT confidence signals
        stt_conf = meta.get("stt_confidence", {})
        assert "avg_logprob" in stt_conf
        assert "low_confidence" in stt_conf

        # 5. Abstention decision metadata
        assert "abstention_decision" in meta
        assert meta["abstention_decision"] in ("EXECUTE", "ABSTAIN", "DIRECT")
        assert "execution_prevented_by_abstention" in meta

        # 6. Latency breakdown
        lat = meta.get("latency_ms", {})
        assert "total" in lat
        assert "validation" in lat
        assert "obfuscation" in lat
        assert lat["total"] >= 0


class TestAbstentionEnforcementBoundary:
    """Verifies that an ABSTAIN decision strictly blocks tool/connector execution."""

    def test_abstain_blocks_tool_execution(self):
        """A semantic distractor must return ABSTAIN and NEVER execute data tools."""
        orch = LLMOrchestrator(model=settings.OLLAMA_MODEL)
        distractor = "I bought a concert ticket for tomorrow's performance."

        result = orch.process_query(distractor, enable_abstention=True)
        meta = result.get("metadata", {})

        assert meta.get("abstention_decision") == "ABSTAIN"
        assert meta.get("execution_prevented_by_abstention") is True
        assert meta.get("result_count") == 0
        assert meta.get("data_sources_used") == []
        assert meta.get("tool_calls") == []
        assert "I cannot run a data query" in result.get("answer", "")

    def test_baseline_bypasses_abstention(self):
        """When enable_abstention=False, baseline mode does not block the query."""
        orch = LLMOrchestrator(model=settings.OLLAMA_MODEL)
        distractor = "I bought a concert ticket for tomorrow's performance."

        result = orch.process_query(distractor, enable_abstention=False)
        meta = result.get("metadata", {})

        assert meta.get("abstention_decision") == "BASELINE_NO_ABSTENTION"
        assert meta.get("execution_prevented_by_abstention") is False


class TestObfuscatorConcurrencySafety:
    """Verifies that separate FormantPreservingObfuscator instances do not cross-pollute parameters."""

    def test_concurrent_obfuscator_isolation(self, tmp_path):
        """Runs two concurrent obfuscation threads with different parameters to verify isolation."""
        import soundfile as sf
        import numpy as np

        # Create dummy input tone
        sr = 16000
        duration = 0.5
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        tone = 0.5 * np.sin(2 * np.pi * 220.0 * t).astype(np.float32)
        in_path = tmp_path / "test_tone.wav"
        sf.write(str(in_path), tone, sr)

        results = {}

        def worker(worker_id: str, semitones: float, tempo: float):
            out_file = tmp_path / f"out_{worker_id}.wav"
            obf = FormantPreservingObfuscator(semitone_shift=semitones, randomize=False)
            shift_applied = obf.obfuscate(in_path, out_file, tempo_rate=tempo)
            results[worker_id] = {
                "shift": shift_applied,
                "alpha": obf.last_alpha,
                "tempo": obf.last_tempo_rate,
            }

        t1 = threading.Thread(target=worker, args=("worker_mild", 2.0, 1.0))
        t2 = threading.Thread(target=worker, args=("worker_strong", 6.0, 1.1))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert results["worker_mild"]["shift"] == 2.0
        assert results["worker_strong"]["shift"] == 6.0
        assert results["worker_mild"]["tempo"] == 1.0
        assert results["worker_strong"]["tempo"] == 1.1
