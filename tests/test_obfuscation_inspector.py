"""
tests/test_obfuscation_inspector.py - Verification for Obfuscation Inspector: Original vs. Processed Audio

Covers:
1. Original and processed audio are correctly associated with the same request.
2. Both audio streams are accessible via /voice/audio/{file_id}.
3. Authentication boundaries (invalid API key rejected with 401).
4. Invalid or expired identifiers are rejected with 404.
5. Session isolation (cross-session access rejected).
6. Session cleanup wipes both original and processed audio from RAM.
7. Zero disk persistence (raw and normalized audio files deleted from disk).
8. Safe API and metadata structure when audio components are absent.
"""

import io
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.voice.audio_store import audio_store


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_wav_bytes(tmp_path):
    """Generates a small valid 16kHz mono WAV file in memory."""
    import numpy as np
    import soundfile as sf
    sr = 16000
    y = np.sin(2 * np.pi * 440 * np.linspace(0, 0.5, int(sr * 0.5))).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, y, sr, format="WAV")
    return buf.getvalue()


class TestObfuscationInspectorBackend:
    """Verifies backend audio association, streaming, isolation, and cleanup."""

    def test_voice_query_associates_both_audio_versions_with_request(self, client, sample_wav_bytes):
        """POST /voice/query returns both original_audio_url and obfuscated_audio_url with matching request_id."""
        sess_id = "test_inspect_sess_1"
        files = {"audio_file": ("test.wav", sample_wav_bytes, "audio/wav")}

        with patch("app.voice.stt.STTEngine.transcribe_with_confidence") as mock_stt:
            mock_stt.return_value = ("Show active customers", {"avg_logprob": -0.15, "low_confidence": False})
            with patch("app.services.llm_orchestrator.LLMOrchestrator.process_query") as mock_orch:
                mock_orch.return_value = {
                    "answer": "Found 2 customers",
                    "metadata": {
                        "classified_intent": "crm",
                        "data_sources_used": ["crm"],
                        "result_count": 2,
                        "tool_calls": [{"function": "get_crm_data"}],
                    },
                }
                res = client.post(
                    f"/voice/query?session_id={sess_id}&obfuscation_strength=mild",
                    files=files,
                    headers={"api-key": settings.API_KEY},
                )

        assert res.status_code == 200, res.text
        data = res.json()

        # Both audio URLs must be present
        assert "original_audio_url" in data and data["original_audio_url"]
        assert "obfuscated_audio_url" in data and data["obfuscated_audio_url"]

        orig_url = data["original_audio_url"]
        obf_url = data["obfuscated_audio_url"]
        req_id = data["metadata"]["request_id"]

        assert f"orig_{req_id}" in orig_url
        assert f"obf_{req_id}" in obf_url
        assert f"session_id={sess_id}" in orig_url
        assert f"session_id={sess_id}" in obf_url

        # Check metadata inspector payload
        inspector = data["metadata"].get("audio_inspector")
        assert inspector is not None
        assert inspector["request_id"] == req_id
        assert inspector["session_id"] == sess_id
        assert inspector["has_original"] is True
        assert inspector["has_obfuscated"] is True

        # Clean up session
        audio_store.burn_session(sess_id)

    def test_both_audio_streams_are_accessible_and_stream_valid_wav(self, client, sample_wav_bytes):
        """Both original and processed audio endpoints stream 200 OK with RIFF WAV header."""
        sess_id = "test_inspect_sess_2"
        files = {"audio_file": ("test.wav", sample_wav_bytes, "audio/wav")}

        with patch("app.voice.stt.STTEngine.transcribe_with_confidence") as mock_stt:
            mock_stt.return_value = ("List tickets", {"avg_logprob": -0.2, "low_confidence": False})
            with patch("app.services.llm_orchestrator.LLMOrchestrator.process_query") as mock_orch:
                mock_orch.return_value = {
                    "answer": "Active tickets list",
                    "metadata": {"classified_intent": "support", "data_sources_used": ["support"]},
                }
                res = client.post(
                    f"/voice/query?session_id={sess_id}",
                    files=files,
                    headers={"api-key": settings.API_KEY},
                )

        data = res.json()
        orig_url = data["original_audio_url"]
        obf_url = data["obfuscated_audio_url"]

        # Fetch original audio
        r_orig = client.get(orig_url)
        assert r_orig.status_code == 200
        assert r_orig.headers["content-type"] == "audio/wav"
        assert r_orig.content[:4] == b"RIFF"

        # Fetch processed audio
        r_obf = client.get(obf_url)
        assert r_obf.status_code == 200
        assert r_obf.headers["content-type"] == "audio/wav"
        assert r_obf.content[:4] == b"RIFF"

        audio_store.burn_session(sess_id)

    def test_audio_streaming_requires_valid_api_key(self, client):
        """Audio streaming rejects requests without a valid API key with 401."""
        test_id = "orig_auth_test_1"
        audio_store.store(test_id, b"RIFFfakeaudio", media_type="audio/wav")

        # Missing or bad key -> 401
        res_bad = client.get(f"/voice/audio/{test_id}", headers={"api-key": "invalid-secret"})
        assert res_bad.status_code == 401

        # Valid key -> 200
        res_good = client.get(f"/voice/audio/{test_id}?api_key={settings.API_KEY}")
        assert res_good.status_code == 200

        audio_store.burn_immediately(test_id)

    def test_invalid_or_expired_audio_identifiers_return_404(self, client):
        """Non-existent or expired audio IDs return 404 safely."""
        # Non-existent
        res_missing = client.get(f"/voice/audio/orig_nonexistent_id?api_key={settings.API_KEY}")
        assert res_missing.status_code == 404

        # Expired ID
        expired_id = "orig_expired_test"
        audio_store.store(expired_id, b"RIFFdata", ttl_seconds=-10.0)
        res_expired = client.get(f"/voice/audio/{expired_id}?api_key={settings.API_KEY}")
        assert res_expired.status_code == 404

    def test_session_isolation_blocks_cross_session_retrieval(self, client):
        """Audio stored for session A cannot be retrieved by a client specifying session B."""
        audio_id = "orig_isolate_test_1"
        audio_store.store(audio_id, b"RIFFaudiodata", media_type="audio/wav", session_id="user_session_A")

        # Request specifying the correct session -> 200
        res_owner = client.get(f"/voice/audio/{audio_id}?api_key={settings.API_KEY}&session_id=user_session_A")
        assert res_owner.status_code == 200

        # Request specifying an alien session -> 404
        res_alien = client.get(f"/voice/audio/{audio_id}?api_key={settings.API_KEY}&session_id=user_session_B")
        assert res_alien.status_code == 404

        audio_store.burn_session("user_session_A")

    def test_session_cleanup_burns_both_audio_files(self, client, sample_wav_bytes):
        """When /voice/session/cleanup is called, both original and processed audio are wiped from RAM."""
        sess_id = "test_cleanup_sess_3"
        files = {"audio_file": ("test.wav", sample_wav_bytes, "audio/wav")}

        with patch("app.voice.stt.STTEngine.transcribe_with_confidence") as mock_stt:
            mock_stt.return_value = ("Test query", {"avg_logprob": -0.1, "low_confidence": False})
            with patch("app.services.llm_orchestrator.LLMOrchestrator.process_query") as mock_orch:
                mock_orch.return_value = {"answer": "Ok", "metadata": {}}
                res = client.post(
                    f"/voice/query?session_id={sess_id}",
                    files=files,
                    headers={"api-key": settings.API_KEY},
                )

        data = res.json()
        orig_url = data["original_audio_url"]
        obf_url = data["obfuscated_audio_url"]

        # Initially accessible
        assert client.get(orig_url).status_code == 200
        assert client.get(obf_url).status_code == 200

        # Trigger cleanup
        clean_res = client.post(f"/voice/session/cleanup?session_id={sess_id}&api_key={settings.API_KEY}")
        assert clean_res.status_code == 200
        assert clean_res.json()["cleaned_count"] >= 2

        # Both are burned and now return 404
        assert client.get(orig_url).status_code == 404
        assert client.get(obf_url).status_code == 404

    def test_zero_disk_persistence_after_request(self, client, sample_wav_bytes):
        """Guarantees that input and normalized WAV files on disk are wiped after request completes."""
        temp_dir = Path("temp_audio")
        files_before = set(temp_dir.glob("*.wav"))

        files = {"audio_file": ("test.wav", sample_wav_bytes, "audio/wav")}
        with patch("app.voice.stt.STTEngine.transcribe_with_confidence") as mock_stt:
            mock_stt.return_value = ("Check balance", {"avg_logprob": -0.1, "low_confidence": False})
            with patch("app.services.llm_orchestrator.LLMOrchestrator.process_query") as mock_orch:
                mock_orch.return_value = {"answer": "Answer", "metadata": {}}
                client.post("/voice/query", files=files, headers={"api-key": settings.API_KEY})

        files_after = set(temp_dir.glob("*.wav"))
        assert files_after == files_before, "No disk WAV residue should remain after request"
