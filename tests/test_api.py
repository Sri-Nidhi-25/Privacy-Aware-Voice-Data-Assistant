"""
tests/test_api.py - Integration and failure path tests for FastAPI endpoints.
"""
from pathlib import Path
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from app.config import settings
from app.routers import voice


def test_api_unauthorized(client: TestClient, valid_wav_file: Path):
    with open(valid_wav_file, "rb") as f:
        res = client.post(
            "/voice/query",
            files={"audio_file": ("test.wav", f, "audio/wav")},
            headers={"api-key": "wrong-key"},
        )
    assert res.status_code == 401


def test_api_unsupported_content_type(client: TestClient, valid_wav_file: Path):
    with open(valid_wav_file, "rb") as f:
        res = client.post(
            "/voice/query",
            files={"audio_file": ("test.wav", f, "text/plain")},
            headers={"api-key": settings.API_KEY},
        )
    assert res.status_code == 400


def test_api_undecodable_audio(client: TestClient, corrupt_audio_file: Path):
    with open(corrupt_audio_file, "rb") as f:
        res = client.post(
            "/voice/query",
            files={"audio_file": ("corrupt.wav", f, "audio/wav")},
            headers={"api-key": settings.API_KEY},
        )
    assert res.status_code == 400
    assert "decode" in res.json()["detail"]["error"]


def test_api_successful_end_to_end_mocked(client: TestClient, valid_wav_file: Path, monkeypatch):
    # Mock STT and TTS to keep test fast and isolated
    mock_stt = MagicMock()
    mock_stt.transcribe_with_confidence.return_value = (
        "how many active customers",
        {"avg_logprob": -0.2, "no_speech_prob": 0.01, "compression_ratio": 1.0, "low_confidence": False},
    )
    monkeypatch.setattr(voice, "stt", mock_stt)

    # Mock synthesize to avoid remote network dependency in test
    async def mock_synth(text, path):
        path.write_bytes(b"MOCK_MP3_DATA")
    monkeypatch.setattr(voice, "_synthesize_and_verify", mock_synth)

    with open(valid_wav_file, "rb") as f:
        res = client.post(
            "/voice/query",
            files={"audio_file": ("query.wav", f, "audio/wav")},
            headers={"api-key": settings.API_KEY},
        )

    assert res.status_code == 200
    data = res.json()
    assert "transcript" in data
    assert "answer_text" in data
    assert "metadata" in data

    meta = data["metadata"]
    assert "request_id" in meta
    assert "latency_ms" in meta
    assert "validation" in meta["latency_ms"]
    assert "total" in meta["latency_ms"]


def test_api_temp_file_cleanup(client: TestClient, valid_wav_file: Path, monkeypatch):
    """Ensure raw uploads and intermediate input WAV files are cleaned from temp_audio."""
    temp_dir = Path("temp_audio")
    initial_files = set(temp_dir.glob("*.input.wav"))

    mock_stt = MagicMock()
    mock_stt.transcribe_with_confidence.return_value = (
        "hello",
        {"avg_logprob": -0.2, "no_speech_prob": 0.01, "compression_ratio": 1.0, "low_confidence": False},
    )
    monkeypatch.setattr(voice, "stt", mock_stt)

    async def mock_synth(text, path):
        path.write_bytes(b"MOCK")
    monkeypatch.setattr(voice, "_synthesize_and_verify", mock_synth)

    with open(valid_wav_file, "rb") as f:
        client.post(
            "/voice/query",
            files={"audio_file": ("query.wav", f, "audio/wav")},
            headers={"api-key": settings.API_KEY},
        )

    # All intermediate .input.wav files must be cleaned up in finally block
    current_input_files = set(temp_dir.glob("*.input.wav"))
    assert current_input_files == initial_files


def test_stream_audio_unauthorized(client: TestClient):
    res = client.get("/voice/audio/some_audio_id", headers={"api-key": "bad-key"})
    assert res.status_code == 401


def test_stream_audio_authorized_and_burn_after_reading(client: TestClient):
    from app.voice.audio_store import audio_store

    test_id = "test_burn_id"
    test_content = b"WAV_OR_MP3_BINARY_DATA"
    audio_store.store(test_id, test_content, media_type="audio/wav")

    # 1. First authorized read via query parameter: should succeed with 200
    res1 = client.get(f"/voice/audio/{test_id}?api_key={settings.API_KEY}")
    assert res1.status_code == 200
    assert res1.content == test_content
    assert res1.headers["content-type"] == "audio/wav"

    # Burn immediately for test assertion
    audio_store.burn_immediately(test_id)

    # 2. Subsequent read: should return 404 (burned from memory)
    res2 = client.get(f"/voice/audio/{test_id}?api_key={settings.API_KEY}")
    assert res2.status_code == 404


def test_stream_audio_replay_multiple_times(client: TestClient):
    """Verifies that users can replay audio multiple times while the session is active."""
    from app.voice.audio_store import audio_store

    replay_id = "test_replay_id"
    replay_content = b"REPLAY_AUDIO_CONTENT"
    audio_store.store(replay_id, replay_content, media_type="audio/mpeg")

    # Multiple consecutive plays/replays must succeed
    for _ in range(3):
        res = client.get(f"/voice/audio/{replay_id}?api_key={settings.API_KEY}")
        assert res.status_code == 200
        assert res.content == replay_content


def test_session_audio_cleanup_on_refresh_or_close(client: TestClient):
    """Verifies that calling /voice/session/cleanup wipes all audio associated with a session."""
    from app.voice.audio_store import audio_store

    sess_id = "test_sess_999"
    audio_store.store("sess_audio_1", b"AUDIO_1", media_type="audio/wav", session_id=sess_id)
    audio_store.store("sess_audio_2", b"AUDIO_2", media_type="audio/mpeg", session_id=sess_id)

    # Both audio files are accessible initially with matching session_id
    assert client.get(f"/voice/audio/sess_audio_1?api_key={settings.API_KEY}&session_id={sess_id}").status_code == 200
    assert client.get(f"/voice/audio/sess_audio_2?api_key={settings.API_KEY}&session_id={sess_id}").status_code == 200

    # Frontend fires cleanup on page refresh / close
    cleanup_res = client.post(f"/voice/session/cleanup?session_id={sess_id}&api_key={settings.API_KEY}")
    assert cleanup_res.status_code == 200
    assert cleanup_res.json()["cleaned_count"] >= 2

    # Both files are now burned and return 404
    assert client.get(f"/voice/audio/sess_audio_1?api_key={settings.API_KEY}&session_id={sess_id}").status_code == 404
    assert client.get(f"/voice/audio/sess_audio_2?api_key={settings.API_KEY}&session_id={sess_id}").status_code == 404
