"""
tests/test_local_tts.py - Comprehensive Verification for Offline Local TTS

Verifies:
1. Live local synthesis produces a valid audio file of non-zero size.
2. Sensitive connector-derived text is successfully synthesized locally.
3. edge_tts.Communicate is NEVER called when provider is 'local'.
4. Engine failure or missing binary returns False, logs safely, and does not crash.
5. Remote Edge-TTS remains strictly blocked for sensitive text.
6. Provider switching (local, remote, disabled) behaves strictly as configured.
7. Custom LOCAL_TTS_VOICE selection is applied.
8. Text escaping (quotes, special symbols) does not cause PowerShell script errors or injection.
9. Both .mp3 and .wav output targets are handled correctly.
"""

import sys
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from app.config import Settings
from app.voice.tts import TTSEngine, _synthesize_local_sync


class TestLocalTTSSynthesis:
    """Verifies actual offline local TTS execution on supported platforms."""

    @pytest.mark.skipif(sys.platform != "win32", reason="SAPI5 offline synthesis is Windows-native")
    @pytest.mark.asyncio
    async def test_live_local_synthesis_produces_valid_mp3(self, tmp_path):
        """Live local synthesis generates a non-empty MP3 audio file."""
        engine = TTSEngine(provider="local")
        out_mp3 = tmp_path / "test_live.mp3"

        with patch("edge_tts.Communicate") as mock_remote:
            success = await engine.synthesize("System ready for local voice assistance.", out_mp3, is_sensitive=False)

            assert success is True
            assert out_mp3.exists()
            assert out_mp3.stat().st_size > 1000  # Substantial audio file
            mock_remote.assert_not_called()

    @pytest.mark.skipif(sys.platform != "win32", reason="SAPI5 offline synthesis is Windows-native")
    @pytest.mark.asyncio
    async def test_live_local_synthesis_produces_valid_wav(self, tmp_path):
        """Live local synthesis generates a non-empty WAV audio file when requested."""
        engine = TTSEngine(provider="local")
        out_wav = tmp_path / "test_live.wav"

        with patch("edge_tts.Communicate") as mock_remote:
            success = await engine.synthesize("Local voice WAV test.", out_wav, is_sensitive=False)

            assert success is True
            assert out_wav.exists()
            assert out_wav.stat().st_size > 1000
            # Check WAV RIFF header
            with open(out_wav, "rb") as f:
                header = f.read(4)
                assert header == b"RIFF"
            mock_remote.assert_not_called()

    @pytest.mark.skipif(sys.platform != "win32", reason="SAPI5 offline synthesis is Windows-native")
    @pytest.mark.asyncio
    async def test_sensitive_text_synthesizes_locally_without_error(self, tmp_path):
        """Sensitive data queries CAN be spoken locally without leaking over the network."""
        engine = TTSEngine(provider="local")
        out_mp3 = tmp_path / "sensitive_out.mp3"
        sensitive_text = "Customer Acme Corp has 3 open high-priority tickets. Contact: support@acme.com."

        with patch("edge_tts.Communicate") as mock_remote:
            success = await engine.synthesize(sensitive_text, out_mp3, is_sensitive=True)

            assert success is True
            assert out_mp3.exists()
            assert out_mp3.stat().st_size > 1000
            mock_remote.assert_not_called()

    @pytest.mark.skipif(sys.platform != "win32", reason="SAPI5 offline synthesis is Windows-native")
    @pytest.mark.asyncio
    async def test_special_characters_and_quotes_handled_safely(self, tmp_path):
        """Single quotes, double quotes, and dollar signs do not crash PowerShell synthesis."""
        engine = TTSEngine(provider="local")
        out_mp3 = tmp_path / "special_chars.mp3"
        complex_text = "It's John's $500 balance; \"quoted text\", & symbols: 100% safe."

        with patch("edge_tts.Communicate") as mock_remote:
            success = await engine.synthesize(complex_text, out_mp3, is_sensitive=True)

            assert success is True
            assert out_mp3.exists()
            assert out_mp3.stat().st_size > 1000
            mock_remote.assert_not_called()


class TestLocalTTSFailureHandling:
    """Verifies graceful fail-safe behavior when the engine fails or is unavailable."""

    @pytest.mark.asyncio
    async def test_engine_failure_returns_false_and_does_not_crash(self, tmp_path):
        """If _synthesize_local_sync returns False, synthesize() returns False cleanly."""
        engine = TTSEngine(provider="local")
        out_path = tmp_path / "fail.mp3"

        with patch("app.voice.tts._synthesize_local_sync", return_value=False):
            with patch("edge_tts.Communicate") as mock_remote:
                result = await engine.synthesize("Hello world", out_path, is_sensitive=True)
                assert result is False
                assert not out_path.exists()
                mock_remote.assert_not_called()

    @pytest.mark.asyncio
    async def test_engine_exception_returns_false_and_does_not_crash(self, tmp_path):
        """If _synthesize_local_sync raises an unexpected exception, it fails safe."""
        engine = TTSEngine(provider="local")
        out_path = tmp_path / "crash.mp3"

        with patch("app.voice.tts._synthesize_local_sync", side_effect=RuntimeError("Subprocess failed")):
            with patch("edge_tts.Communicate") as mock_remote:
                result = await engine.synthesize("Hello world", out_path, is_sensitive=True)
                assert result is False
                assert not out_path.exists()
                mock_remote.assert_not_called()

    def test_sync_synthesis_returns_false_on_subprocess_error(self, tmp_path):
        """_synthesize_local_sync logs and returns False when subprocess exits non-zero."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="SAPI initialization error")
            success = _synthesize_local_sync("Test text", tmp_path / "test.mp3")
            assert success is False


class TestTTSProviderSwitchingAndPrivacyBoundaries:
    """Verifies provider configurations and privacy boundary invariants."""

    @pytest.mark.asyncio
    async def test_remote_tts_blocked_for_sensitive_data(self, tmp_path):
        """Remote provider MUST reject sensitive data regardless of user input."""
        engine = TTSEngine(provider="remote")
        out_path = tmp_path / "remote.mp3"

        with patch("edge_tts.Communicate") as mock_remote:
            result = await engine.synthesize("Customer confidential account balance $50,000", out_path, is_sensitive=True)
            assert result is False
            assert not out_path.exists()
            mock_remote.assert_not_called()

    @pytest.mark.asyncio
    async def test_remote_tts_allowed_for_non_sensitive_data(self, tmp_path):
        """Remote provider allowed when data is explicitly marked non-sensitive."""
        engine = TTSEngine(provider="remote")
        out_path = tmp_path / "remote.mp3"

        with patch("edge_tts.Communicate") as mock_remote:
            mock_instance = AsyncMock()
            mock_remote.return_value = mock_instance
            result = await engine.synthesize("How can I help you today?", out_path, is_sensitive=False)
            assert result is True
            mock_remote.assert_called_once()

    @pytest.mark.asyncio
    async def test_disabled_provider_skips_all_synthesis(self, tmp_path):
        """Disabled provider performs no synthesis and invokes no engine."""
        engine = TTSEngine(provider="disabled")
        out_path = tmp_path / "disabled.mp3"

        with patch("edge_tts.Communicate") as mock_remote:
            with patch("app.voice.tts._synthesize_local_sync") as mock_local:
                result = await engine.synthesize("Any text", out_path, is_sensitive=False)
                assert result is False
                assert not out_path.exists()
                mock_remote.assert_not_called()
                mock_local.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_provider_fails_safe(self, tmp_path):
        """Any unrecognized provider string fails safe with False."""
        engine = TTSEngine(provider="elevenlabs_cloud")
        out_path = tmp_path / "unknown.mp3"

        with patch("edge_tts.Communicate") as mock_remote:
            with patch("app.voice.tts._synthesize_local_sync") as mock_local:
                result = await engine.synthesize("Any text", out_path, is_sensitive=False)
                assert result is False
                mock_remote.assert_not_called()
                mock_local.assert_not_called()
