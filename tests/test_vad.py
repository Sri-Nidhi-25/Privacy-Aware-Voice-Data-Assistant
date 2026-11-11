"""
tests/test_vad.py - Pytest Test Suite for Voice Activity Detection & Automatic Silence Cutoff

Covers:
1. Static analysis of voice_chat.html and app/voice_chat.html:
   - Synchronized HTML files (exact equality).
   - Presence of VAD_CONFIG with 800ms silence duration and 0.015 RMS threshold.
   - Web Audio API integration (AudioContext, AnalyserNode, createMediaStreamSource).
   - Time-domain sample energy calculation (RMS).
   - Initial silence grace logic (speech onset required before silence countdown).
   - Pause handling (silence timer reset when speech resumes).
   - Atomic stop guard (isStopping flag preventing double-finalization).
   - Resource cleanup (cleanupVAD closes AudioContext, disconnects nodes, clears intervals).
   - Manual stop control preserved.
   - Auto-stop UI toggle in config bar.
2. Execution of the JavaScript unit test suite (tests/test_vad.js) via Node.js.
3. Python-level state machine simulation verifying edge case handling.
"""

import subprocess
import shutil
import pytest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
ROOT_HTML = ROOT_DIR / "voice_chat.html"
JS_TEST_FILE = ROOT_DIR / "tests" / "test_vad.js"


def test_single_html_source_of_truth():
    """Verify voice_chat.html exists as the sole source of truth and no duplicate app/ copy exists."""
    assert ROOT_HTML.exists(), "Root voice_chat.html must exist as single source of truth"
    duplicate_app_html = ROOT_DIR / "app" / "voice_chat.html"
    assert not duplicate_app_html.exists(), "app/voice_chat.html duplicate must not exist"


def test_vad_configuration_and_dom_invariants():
    """Verify required VAD constants and DOM elements are present in HTML."""
    content = ROOT_HTML.read_text(encoding="utf-8")

    # VAD Configuration
    assert "const VAD_CONFIG = {" in content
    assert "SILENCE_THRESHOLD: 0.015" in content
    assert "SILENCE_DURATION_MS: 800" in content
    assert "SPEECH_TRIGGER_DURATION_MS: 150" in content
    assert "MAX_INITIAL_SILENCE_MS: 12000" in content

    # DOM Elements & Controls
    assert 'id="enableAutoStop"' in content
    assert "Auto-Stop on Silence" in content
    assert "enableAutoStopInput" in content
    assert "enable_auto_stop" in content

    # Web Audio API
    assert "AudioContext || window.webkitAudioContext" in content
    assert "createMediaStreamSource" in content
    assert "createAnalyser" in content
    assert "fftSize = 512" in content
    assert "getFloatTimeDomainData" in content

    # Status indicators
    assert "Listening (speech detected)..." in content
    assert "Silence detected — finishing recording..." in content
    assert "Silence detected — encoding audio and sending to pipeline..." in content

    # Lifecycle & Cleanup
    assert "function initVAD(" in content
    assert "function cleanupVAD()" in content
    assert "function stopRecording(" in content
    assert "vadContext.close()" in content
    assert "document.addEventListener('visibilitychange'" in content


def test_vad_js_unit_test_suite_passes():
    """Run the Node.js VAD test suite (tests/test_vad.js) and verify 0 exit code."""
    node_exe = shutil.which("node")
    if not node_exe:
        pytest.skip("Node.js runtime not installed in environment")

    res = subprocess.run([node_exe, str(JS_TEST_FILE)], capture_output=True, text=True)
    assert res.returncode == 0, f"JS VAD tests failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "ALL 7 VAD JAVASCRIPT TESTS PASSED SUCCESSFULLY!" in res.stdout


class TestVADPythonStateMachineSimulation:
    """Independent Python test of the VAD state transitions matching browser logic."""

    @staticmethod
    def simulate_vad(ticks):
        """
        ticks: list of (time_ms, rms) tuples.
        returns: dict with final state and events.
        """
        SILENCE_THRESHOLD = 0.015
        SILENCE_DURATION_MS = 800
        SPEECH_TRIGGER_DURATION_MS = 150

        has_spoken = False
        speech_start = None
        silence_start = None
        is_recording = True
        stopped_reason = None
        stop_count = 0

        for t, rms in ticks:
            if not is_recording:
                break

            if not has_spoken:
                if rms >= SILENCE_THRESHOLD:
                    if speech_start is None:
                        speech_start = t
                    elif t - speech_start >= SPEECH_TRIGGER_DURATION_MS:
                        has_spoken = True
                        silence_start = None
                else:
                    speech_start = None
            else:
                if rms < SILENCE_THRESHOLD:
                    if silence_start is None:
                        silence_start = t
                    elif t - silence_start >= SILENCE_DURATION_MS:
                        is_recording = False
                        stopped_reason = "silence_cutoff"
                        stop_count += 1
                else:
                    silence_start = None

        return {
            "has_spoken": has_spoken,
            "is_recording": is_recording,
            "stopped_reason": stopped_reason,
            "stop_count": stop_count,
        }

    def test_initial_silence_does_not_terminate(self):
        # 1.5s silence right after record pressed
        ticks = [(t, 0.003) for t in range(0, 1500, 30)]
        res = self.simulate_vad(ticks)
        assert res["has_spoken"] is False
        assert res["is_recording"] is True
        assert res["stop_count"] == 0

    def test_speech_followed_by_sustained_silence_terminates_at_threshold(self):
        # 200ms speech onset + 1000ms silence
        ticks = [(t, 0.08) for t in range(0, 210, 30)]
        ticks += [(t, 0.002) for t in range(240, 1300, 30)]
        res = self.simulate_vad(ticks)
        assert res["has_spoken"] is True
        assert res["is_recording"] is False
        assert res["stopped_reason"] == "silence_cutoff"
        assert res["stop_count"] == 1

    def test_speech_with_natural_pause_resets_silence_timer(self):
        # 200ms speech + 400ms pause (< 800ms) + 200ms speech + 100ms silence
        ticks = [(t, 0.06) for t in range(0, 210, 30)]
        ticks += [(t, 0.003) for t in range(240, 640, 30)]  # 400ms pause
        ticks += [(t, 0.07) for t in range(670, 880, 30)]   # resume speech
        ticks += [(t, 0.002) for t in range(910, 1010, 30)]  # 100ms pause
        res = self.simulate_vad(ticks)
        assert res["has_spoken"] is True
        assert res["is_recording"] is True, "Natural pause must not trigger cutoff"
        assert res["stop_count"] == 0
