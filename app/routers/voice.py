"""
app/routers/voice.py - Voice query router with observability, failure handling,
and guaranteed resource cleanup.
"""
import asyncio
import io
import inspect
import logging
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import anyio
import soundfile as sf
from fastapi import APIRouter, UploadFile, File, Header, HTTPException, BackgroundTasks, Query, Request
from fastapi.responses import StreamingResponse

from app.config import settings, Settings
from app.failure import FailureType, PipelineError
from app.models.voice import QueryResponse
from app.services.llm_orchestrator import LLMOrchestrator
from app.storage import factory as _storage_factory
from app.utils.logging import log_event
from app.utils.security import validate_api_key
from app.voice.audio_store import audio_store as _legacy_audio_store
from app.voice.audio_validation import validate_and_load
from app.voice.obfuscator import FormantPreservingObfuscator
from app.voice.stt import STTEngine
from app.voice.tts import TTSEngine

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_CONTENT_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/webm",
    "audio/ogg",
    "video/mpeg",
    "audio/mp4",
}
MAX_FILE_SIZE = settings.MAX_AUDIO_SIZE_MB * 1024 * 1024
AUDIO_DIR = Path("temp_audio")
AUDIO_DIR.mkdir(exist_ok=True)

STRENGTH_TO_SEMITONES = {
    "mild": 2.0,
    "medium": 4.0,
    "strong": 6.0,
    "high": 6.0,
    "very_strong": 8.0,
    "verystrong": 8.0,
    "very strong": 8.0,
}

# Singletons
obfuscator = FormantPreservingObfuscator(
    semitone_shift=STRENGTH_TO_SEMITONES.get(settings.OBFUSCATION_STRENGTH, 2.0),
    jitter=0.5 if settings.OBFUSCATION_STRENGTH == "mild" else 1.0,
)
stt = STTEngine(model_name=settings.STT_MODEL)
tts = TTSEngine(voice=settings.EDGE_TTS_VOICE)
orchestrator = LLMOrchestrator(model=settings.OLLAMA_MODEL)


def _get_audio_store():
    """
    Returns the factory-initialized audio store.
    
    If storage is uninitialized and configured as 'redis', RuntimeError propagates
    fail-fast rather than silently falling back to in-memory/legacy storage.
    """
    try:
        return _storage_factory.get_audio_store()
    except RuntimeError:
        raise
    except Exception:
        return _legacy_audio_store


async def _call_store(method, *args, **kwargs):
    """Executes a storage backend method, awaiting if async or calling directly if synchronous."""
    if inspect.iscoroutinefunction(method):
        return await method(*args, **kwargs)
    return method(*args, **kwargs)


_audio_semaphore: Optional[asyncio.Semaphore] = None
_audio_semaphore_loop: Optional[asyncio.AbstractEventLoop] = None


def init_audio_semaphore(app_instance, max_concurrent: Optional[int] = None) -> asyncio.Semaphore:
    """Initializes and binds the semaphore to the current running event loop and stores in app.state."""
    limit = max_concurrent or settings.MAX_CONCURRENT_VOICE_REQUESTS
    sem = asyncio.Semaphore(limit)
    app_instance.state.audio_semaphore = sem
    global _audio_semaphore, _audio_semaphore_loop
    _audio_semaphore = sem
    try:
        _audio_semaphore_loop = asyncio.get_running_loop()
    except RuntimeError:
        _audio_semaphore_loop = None
    return sem


def get_audio_semaphore(request: Optional[Request] = None) -> asyncio.Semaphore:
    """
    Returns an event-loop-safe concurrency semaphore.
    Prefers the semaphore bound to app.state via lifespan.
    Falls back gracefully if called outside lifespan context or across different event loops in tests.
    """
    global _audio_semaphore, _audio_semaphore_loop

    # 1. If request is provided, inspect app.state
    if request is not None and hasattr(request.app, "state") and hasattr(request.app.state, "audio_semaphore"):
        sem = request.app.state.audio_semaphore
        # Verify loop binding
        try:
            curr_loop = asyncio.get_running_loop()
            if getattr(sem, "_loop", None) in (None, curr_loop):
                return sem
        except RuntimeError:
            return sem

    # 2. Check running event loop against cached loop
    try:
        curr_loop = asyncio.get_running_loop()
    except RuntimeError:
        curr_loop = None

    if _audio_semaphore is None or (curr_loop is not None and _audio_semaphore_loop != curr_loop):
        _audio_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_VOICE_REQUESTS)
        _audio_semaphore_loop = curr_loop

    return _audio_semaphore


def _clean_stale_temp_files(max_age_seconds: float = 300.0) -> None:
    """Removes temp audio files older than max_age_seconds and cleans expired RAM buffers."""
    now = time.time()
    try:
        _legacy_audio_store.cleanup_expired()
        store = _get_audio_store()
        if hasattr(store, "cleanup_expired"):
            if inspect.iscoroutinefunction(store.cleanup_expired):
                # Schedule or run if possible
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(store.cleanup_expired())
                except RuntimeError:
                    pass
        for p in AUDIO_DIR.glob("*"):
            if p.is_file() and (now - p.stat().st_mtime) > max_age_seconds:
                p.unlink(missing_ok=True)
    except Exception:
        pass


@router.get("/voice/audio/{file_id}")
async def stream_audio(
    file_id: str,
    api_key: Optional[str] = Header(None, alias="api-key"),
    key: Optional[str] = Query(None, alias="api_key"),
    session_id: Optional[str] = Query(None, alias="session_id"),
    x_session_id: Optional[str] = Header(None, alias="x-session-id"),
):
    """
    Authenticated Audio Streaming Endpoint (Zero static directory exposure).
    Requires valid API key via Header 'api-key' or Query parameter 'api_key'.
    Allows unlimited in-page replays while the session is active.
    Audio is purged when the client refreshes or closes the page via /voice/session/cleanup.
    Session isolation: cross-session retrieval is rejected.
    """
    effective_key = api_key or key
    if not validate_api_key(effective_key or ""):
        log_event(logger, file_id, "security", "unauthorized_audio_stream")
        raise HTTPException(status_code=401, detail="Invalid API key")

    effective_session = session_id or x_session_id

    # 1. Check in-memory ephemeral RAM store (RAM buffer) without premature burning
    store = _get_audio_store()
    audio_data = await _call_store(store.retrieve, file_id, burn=False, session_id=effective_session)

    if audio_data:
        content_bytes, media_type = audio_data
        return StreamingResponse(
            io.BytesIO(content_bytes),
            media_type=media_type,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Content-Length": str(len(content_bytes)),
            },
        )

    # 2. Check ephemeral disk fallback
    safe_name = Path(file_id).name
    file_path = AUDIO_DIR / safe_name
    if file_path.is_file():
        content_bytes = file_path.read_bytes()
        media_type = "audio/mpeg" if safe_name.endswith((".mp3", ".mpeg")) else "audio/wav"
        # Ingest into RAM store so subsequent replays hit memory directly
        await _call_store(store.store, file_id, content_bytes, media_type=media_type)
        file_path.unlink(missing_ok=True)
        return StreamingResponse(
            io.BytesIO(content_bytes),
            media_type=media_type,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Content-Length": str(len(content_bytes)),
            },
        )

    raise HTTPException(status_code=404, detail="Audio expired or session ended")


@router.api_route("/voice/session/cleanup", methods=["GET", "POST"])
async def cleanup_session_audio(
    session_id: Optional[str] = Query(None),
    api_key: Optional[str] = Header(None, alias="api-key"),
    key: Optional[str] = Query(None, alias="api_key"),
):
    """
    Session-Scoped Audio Cleanup Endpoint.
    Invoked when the browser tab is refreshed or closed (via beforeunload / pagehide).
    Wipes all audio files associated with session_id from RAM immediately.
    """
    effective_key = api_key or key
    if not validate_api_key(effective_key or ""):
        log_event(logger, str(session_id), "security", "unauthorized_cleanup")
        raise HTTPException(status_code=401, detail="Invalid API key")

    store = _get_audio_store()
    clarif_store = _storage_factory.get_clarification_store()

    if session_id:
        cleaned = await _call_store(store.burn_session, session_id)
        await _call_store(clarif_store.clear_session, session_id)
        log_event(logger, session_id, "session_cleanup", "completed", cleaned=cleaned)
    else:
        cleaned = await _call_store(store.burn_all)
        log_event(logger, "all", "session_cleanup", "completed", cleaned=cleaned)

    return {"status": "ok", "cleaned_count": cleaned}


async def _synthesize_and_verify(
    text: str,
    output_path: Path,
    timeout: Optional[float] = None,
    is_sensitive: bool = False,
) -> bool:
    """
    Runs TTS with timeout, then confirms the output file exists on disk with content.
    Returns True if synthesized successfully, False if skipped/blocked for privacy.
    Raises PipelineError on unexpected failure.
    """
    timeout_sec = timeout if timeout is not None else Settings().TTS_TIMEOUT_SECONDS
    try:
        did_synth = await asyncio.wait_for(
            tts.synthesize(text, output_path, is_sensitive=is_sensitive),
            timeout=timeout_sec,
        )
        if not did_synth:
            return False
    except asyncio.TimeoutError:
        raise PipelineError(
            FailureType.TIMEOUT,
            f"TTS synthesis timed out after {timeout_sec}s.",
            status_code=504,
        )
    except Exception as exc:
        raise PipelineError(
            FailureType.TTS_FAILED,
            f"TTS synthesis failed: {exc}",
            status_code=500,
        )

    for _ in range(10):
        if output_path.exists() and output_path.stat().st_size > 0:
            return True
        await asyncio.sleep(0.1)

    raise PipelineError(
        FailureType.TTS_FAILED,
        f"TTS output file not found or empty after synthesis: {output_path.name}",
        status_code=500,
    )


def _save_upload_sync(file_obj, suffix: str) -> tuple[Path, int]:
    """Helper executed in a worker thread to prevent disk I/O from blocking the event loop."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=AUDIO_DIR) as tmp:
        shutil.copyfileobj(file_obj, tmp)
        file_size = tmp.tell()
        input_path = Path(tmp.name)
    return input_path, file_size


@router.post("/voice/query", response_model=QueryResponse)
async def voice_query(
    request: Request,
    audio_file: UploadFile = File(...),
    api_key: str = Header(...),
    enable_abstention: bool = True,
    obfuscation_strength: Optional[str] = Query(None, description="Obfuscation intensity override: mild, medium, strong, or high"),
    time_shift: Optional[str] = Query(None, description="Time shift / speech tempo: normal, slower, faster, random, or float factor"),
    session_id: Optional[str] = Query(None, description="Client session identifier for scoped audio lifecycle"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    request_id = str(uuid.uuid4())
    t_start = time.perf_counter()
    latency_ms: dict[str, int] = {}
    created_files: list[Path] = []
    request_succeeded = False
    current_settings = Settings()

    # Stale file cleanup in background
    background_tasks.add_task(_clean_stale_temp_files)

    log_event(logger, request_id, "request", "received", content_type=audio_file.content_type)

    if not validate_api_key(api_key):
        log_event(logger, request_id, "security", "unauthorized")
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Hardening: Normal API callers cannot disable semantic safety via untrusted query parameters.
    # If enable_abstention is set to False, verify authorization or enforce fail-safe True for standard API traffic.
    # To allow evaluation harnesses to run baseline comparisons safely, check header or evaluate caller intent.
    effective_enable_abstention = True
    if not enable_abstention:
        eval_auth_header = request.headers.get("x-evaluation-baseline-mode")
        if eval_auth_header and eval_auth_header.strip().lower() in ("true", "1", "allow"):
            effective_enable_abstention = False
            log_event(logger, request_id, "security", "baseline_abstention_bypass_authorized")
        else:
            effective_enable_abstention = True
            log_event(logger, request_id, "security", "unauthorized_baseline_bypass_prevented")

    if audio_file.content_type not in ALLOWED_CONTENT_TYPES:
        log_event(logger, request_id, "validation", "invalid_content_type", content_type=audio_file.content_type)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio type: {audio_file.content_type}. Allowed: WAV, MP3, WebM, OGG",
        )

    suffix_map = {
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "video/mpeg": ".mpeg",
        "audio/mp4": ".m4a",
    }
    suffix = suffix_map.get(audio_file.content_type, ".wav")

    sem = get_audio_semaphore(request)
    async with sem:
        try:
            # 1. Save uploaded file offloaded to worker thread (prevents event-loop blocking)
            t_upload_start = time.perf_counter()
            input_path, file_size = await anyio.to_thread.run_sync(_save_upload_sync, audio_file.file, suffix)
            created_files.append(input_path)
            latency_ms["upload_save"] = int((time.perf_counter() - t_upload_start) * 1000)

            # 2. Audio validation layer (size, format, decodability, duration)
            t_val_start = time.perf_counter()
            try:
                y, sr, duration = await anyio.to_thread.run_sync(validate_and_load, input_path, file_size)
            except PipelineError as pe:
                log_event(logger, request_id, "validation", pe.failure_type.value, error=pe.message)
                raise pe.to_http()

            latency_ms["validation"] = int((time.perf_counter() - t_val_start) * 1000)
            log_event(logger, request_id, "validation", "passed", duration_seconds=round(duration, 2), latency_ms=latency_ms["validation"])

            # Write normalized 16kHz mono WAV for downstream vocoder
            normalized_path = input_path.with_suffix(".input.wav")
            await anyio.to_thread.run_sync(sf.write, str(normalized_path), y, sr)
            created_files.append(normalized_path)

            # Store original normalized audio in ephemeral RAM buffer for Obfuscation Inspector
            orig_audio_id = f"orig_{request_id}_{uuid.uuid4().hex[:8]}"
            try:
                store = _get_audio_store()
                await _call_store(
                    store.store,
                    orig_audio_id,
                    normalized_path.read_bytes(),
                    media_type="audio/wav",
                    session_id=session_id,
                    request_id=request_id,
                )
                original_audio_url = f"/voice/audio/{orig_audio_id}?api_key={api_key}"
                if session_id:
                    original_audio_url += f"&session_id={session_id}"
            except Exception as orig_err:
                logger.warning("Failed to store original audio in RAM store: %s", orig_err)
                original_audio_url = ""

            # Resolve obfuscation strength (query param > fresh .env reading > settings > "mild")
            effective_strength = obfuscation_strength
            if not effective_strength:
                effective_strength = current_settings.OBFUSCATION_STRENGTH
            effective_strength = (effective_strength or "mild").strip().lower()
            if effective_strength == "high":
                effective_strength = "strong"
            elif effective_strength in {"verystrong", "very strong"}:
                effective_strength = "very_strong"
            if effective_strength not in STRENGTH_TO_SEMITONES:
                effective_strength = "mild"

            # Resolve time-stretch / tempo rate
            tempo_rate = 1.0
            if time_shift:
                ts_clean = str(time_shift).strip().lower()
                if ts_clean == "slower":
                    tempo_rate = 0.90
                elif ts_clean == "faster":
                    tempo_rate = 1.10
                elif ts_clean in ("random", "randomized"):
                    import random
                    tempo_rate = round(random.uniform(0.92, 1.08), 3)
                elif ts_clean == "normal":
                    tempo_rate = 1.0
                else:
                    try:
                        parsed_rate = float(ts_clean)
                        tempo_rate = max(0.75, min(1.35, parsed_rate))
                    except ValueError:
                        tempo_rate = 1.0

            # 3. Voice Obfuscation (Per-request instance to prevent concurrent state corruption)
            t_obf_start = time.perf_counter()
            obf_path = input_path.with_suffix(".obf.wav")
            created_files.append(obf_path)
            base_shift = STRENGTH_TO_SEMITONES[effective_strength]
            jitter_val = 0.5 if effective_strength == "mild" else (1.5 if effective_strength == "very_strong" else 1.0)
            req_obfuscator = FormantPreservingObfuscator(
                semitone_shift=base_shift,
                jitter=jitter_val,
            )

            actual_shift = None
            try:
                actual_shift = await anyio.to_thread.run_sync(
                    req_obfuscator.obfuscate, normalized_path, obf_path, tempo_rate
                )
            except Exception as exc:
                log_event(logger, request_id, "obfuscation", "failed", error=str(exc))
                raise PipelineError(FailureType.OBFUSCATION_FAILED, f"Voice obfuscation failed: {exc}", status_code=500).to_http()

            latency_ms["obfuscation"] = int((time.perf_counter() - t_obf_start) * 1000)
            obfuscation_details = {
                "strength": effective_strength,
                "base_semitones": base_shift,
                "actual_shift_semitones": round(actual_shift, 2) if actual_shift is not None else None,
                "formant_warp_alpha": round(getattr(req_obfuscator, "last_alpha", 1.0), 3),
                "tempo_rate": round(getattr(req_obfuscator, "last_tempo_rate", 1.0), 2),
            }
            log_event(
                logger,
                request_id,
                "obfuscation",
                "completed",
                latency_ms=latency_ms["obfuscation"],
                strength=effective_strength,
                actual_shift=round(actual_shift, 2) if actual_shift is not None else None,
            )

            # 4. Speech-to-Text (Whisper)
            t_stt_start = time.perf_counter()
            try:
                user_text, stt_confidence = await anyio.to_thread.run_sync(
                    stt.transcribe_with_confidence, obf_path
                )
            except Exception as exc:
                log_event(logger, request_id, "stt", "failed", error=str(exc))
                raise PipelineError(FailureType.STT_FAILED, f"Speech-to-text failed: {exc}", status_code=500).to_http()

            latency_ms["stt"] = int((time.perf_counter() - t_stt_start) * 1000)
            stt_log_kwargs = {
                "latency_ms": latency_ms["stt"],
                "avg_logprob": stt_confidence.get("avg_logprob"),
                "low_confidence": stt_confidence.get("low_confidence"),
            }
            if settings.LOG_TRANSCRIPTS:
                stt_log_kwargs["transcript"] = user_text
            log_event(logger, request_id, "stt", "completed", **stt_log_kwargs)

            # Ingest obfuscated audio into Ephemeral RAM buffer and purge from disk
            obf_audio_id = f"obf_{request_id}_{uuid.uuid4().hex[:8]}"
            try:
                store = _get_audio_store()
                await _call_store(
                    store.store,
                    obf_audio_id,
                    obf_path.read_bytes(),
                    media_type="audio/wav",
                    session_id=session_id,
                    request_id=request_id,
                )
                obf_path.unlink(missing_ok=True)
                obfuscated_audio_url = f"/voice/audio/{obf_audio_id}?api_key={api_key}"
                if session_id:
                    obfuscated_audio_url += f"&session_id={session_id}"
            except Exception:
                obfuscated_audio_url = ""

            # Low-confidence STT invariant: abstain, never execute data tools
            if stt_confidence["low_confidence"]:
                log_event(logger, request_id, "stt", "low_confidence_abstain")
                answer_text = "Sorry, I didn't catch that clearly. Could you try again?"
                answer_path = input_path.with_suffix(".answer.mp3")
                created_files.append(answer_path)

                try:
                    did_synth = await _synthesize_and_verify(
                        answer_text, answer_path, timeout=current_settings.TTS_TIMEOUT_SECONDS, is_sensitive=False
                    )
                    if did_synth:
                        ans_audio_id = f"ans_{request_id}_{uuid.uuid4().hex[:8]}"
                        store = _get_audio_store()
                        await _call_store(
                            store.store,
                            ans_audio_id,
                            answer_path.read_bytes(),
                            media_type="audio/mpeg",
                            session_id=session_id,
                            request_id=request_id,
                        )
                        answer_path.unlink(missing_ok=True)
                        answer_url = f"/voice/audio/{ans_audio_id}?api_key={api_key}"
                        if session_id:
                            answer_url += f"&session_id={session_id}"
                    else:
                        answer_url = ""
                except Exception as tts_err:
                    log_event(logger, request_id, "tts", "fallback_failed", error=str(tts_err))
                    answer_url = ""

                latency_ms["total"] = int((time.perf_counter() - t_start) * 1000)
                request_succeeded = True
                return QueryResponse(
                    original_audio_url=original_audio_url,
                    obfuscated_audio_url=obfuscated_audio_url,
                    answer_audio_url=answer_url,
                    transcript=user_text,
                    answer_text=answer_text,
                    metadata={
                        "request_id": request_id,
                        "session_id": session_id,
                        "data_sources_used": [],
                        "result_count": 0,
                        "freshness": "unknown",
                        "retrieved_at": "",
                        "source_last_updated": "unknown",
                        "tool_calls": [],
                        "low_confidence_transcription": True,
                        "obfuscation_strength": effective_strength,
                        "obfuscation_details": obfuscation_details,
                        "stt_confidence": stt_confidence,
                        "latency_ms": latency_ms,
                        "fallback_used": True,
                        "audio_inspector": {
                            "request_id": request_id,
                            "session_id": session_id,
                            "original_audio_url": original_audio_url,
                            "obfuscated_audio_url": obfuscated_audio_url,
                            "has_original": bool(original_audio_url),
                            "has_obfuscated": bool(obfuscated_audio_url),
                        },
                    },
                )

            # 5. LLM Orchestration & Tool Execution
            t_orch_start = time.perf_counter()
            orchestrator_result = await anyio.to_thread.run_sync(
                orchestrator.process_query, user_text, effective_enable_abstention, session_id
            )
            latency_ms["orchestrator"] = int((time.perf_counter() - t_orch_start) * 1000)
            answer_text = orchestrator_result["answer"]
            metadata = orchestrator_result["metadata"]

            # Merge sub-stage latencies into latency_ms
            if "correction_latency_ms" in metadata:
                latency_ms["correction"] = metadata["correction_latency_ms"]
            if "routing_latency_ms" in metadata:
                latency_ms["routing"] = metadata["routing_latency_ms"]
            if "abstention_latency_ms" in metadata:
                latency_ms["abstention"] = metadata["abstention_latency_ms"]
            if "tool_latency_ms" in metadata:
                latency_ms["tool"] = metadata["tool_latency_ms"]

            log_event(
                logger,
                request_id,
                "orchestrator",
                "completed",
                latency_ms=latency_ms["orchestrator"],
                data_sources=metadata.get("data_sources_used", []),
                result_count=metadata.get("result_count", 0),
            )

            # 6. Text-to-Speech (TTS)
            t_tts_start = time.perf_counter()
            answer_path = input_path.with_suffix(".answer.mp3")
            created_files.append(answer_path)
            answer_url = ""

            # Privacy boundary: check if response contains sensitive or connector-derived data
            has_tools = bool(metadata.get("tool_calls")) or bool(metadata.get("data_sources_used"))
            is_data_query = metadata.get("classified_intent") in ("crm", "support", "analytics", "multi_domain")
            is_sensitive_answer = has_tools or is_data_query

            try:
                did_synth = await _synthesize_and_verify(
                    answer_text,
                    answer_path,
                    timeout=current_settings.TTS_TIMEOUT_SECONDS,
                    is_sensitive=is_sensitive_answer,
                )
                if did_synth:
                    ans_audio_id = f"ans_{request_id}_{uuid.uuid4().hex[:8]}"
                    store = _get_audio_store()
                    await _call_store(
                        store.store,
                        ans_audio_id,
                        answer_path.read_bytes(),
                        media_type="audio/mpeg",
                        session_id=session_id,
                        request_id=request_id,
                    )
                    answer_path.unlink(missing_ok=True)
                    answer_url = f"/voice/audio/{ans_audio_id}?api_key={api_key}"
                    if session_id:
                        answer_url += f"&session_id={session_id}"
                    metadata["tts_failed"] = False
                    metadata["tts_blocked_for_privacy"] = False
                else:
                    metadata["tts_failed"] = False
                    metadata["tts_blocked_for_privacy"] = is_sensitive_answer
                    answer_url = ""
            except Exception as tts_exc:
                # Controlled failure: preserve text answer even if TTS fails
                log_event(logger, request_id, "tts", "failed_preserving_text", error=str(tts_exc))
                metadata["tts_failed"] = True
                metadata["tts_error"] = str(tts_exc)
                metadata["fallback_used"] = True

            latency_ms["tts"] = int((time.perf_counter() - t_tts_start) * 1000)
            latency_ms["total"] = int((time.perf_counter() - t_start) * 1000)

            metadata["request_id"] = request_id
            metadata["session_id"] = session_id
            metadata["obfuscation_strength"] = effective_strength
            metadata["obfuscation_details"] = obfuscation_details
            metadata["low_confidence_transcription"] = False
            metadata["stt_confidence"] = stt_confidence
            metadata["latency_ms"] = latency_ms
            metadata["audio_inspector"] = {
                "request_id": request_id,
                "session_id": session_id,
                "original_audio_url": original_audio_url,
                "obfuscated_audio_url": obfuscated_audio_url,
                "has_original": bool(original_audio_url),
                "has_obfuscated": bool(obfuscated_audio_url),
            }

            log_event(logger, request_id, "request", "completed", total_latency_ms=latency_ms["total"])
            request_succeeded = True

            return QueryResponse(
                original_audio_url=original_audio_url,
                obfuscated_audio_url=obfuscated_audio_url,
                answer_audio_url=answer_url,
                transcript=user_text,
                answer_text=answer_text,
                metadata=metadata,
            )

        finally:
            # Guaranteed cleanup of raw uploaded audio, normalized WAV, and any disk artifacts
            # Ensures zero forensic disk residue on both success and failure paths
            if "input_path" in locals():
                input_path.unlink(missing_ok=True)
            if "normalized_path" in locals():
                normalized_path.unlink(missing_ok=True)
            for f in created_files:
                f.unlink(missing_ok=True)
