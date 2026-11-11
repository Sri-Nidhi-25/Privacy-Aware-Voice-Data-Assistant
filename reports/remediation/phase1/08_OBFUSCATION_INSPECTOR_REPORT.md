# Phase 1 Remediation — Step 2: Obfuscation Inspector Implementation Report

**Date:** 2026-11-03  
**Status:** COMPLETE  
**Verdict:** `OBFUSCATION INSPECTOR IMPLEMENTED`  
**Scope:** Added an unobtrusive "Obfuscation Inspector" audio comparison component to the UI and API, enabling users to listen to their original voice input alongside the obfuscated audio passed into the Whisper STT pipeline.

---

## 1. Existing Audio-Retention Behavior Discovered

Prior to this implementation:
- **Obfuscated Audio:** Was converted from disk to an ephemeral in-memory buffer (`EphemeralAudioStore` in RAM) via `audio_store.store(obf_audio_id, ...)` and immediately unlinked from disk. It was returned as `obfuscated_audio_url`.
- **Original Audio:** The raw uploaded file (`input_path`) and the normalized 16kHz mono audio (`normalized_path`) were written to disk during preprocessing. In the `finally` block of `/voice/query`, both were unlinked (`unlink(missing_ok=True)`). The original audio was **never retained in memory or disk** once the query request finished.
- **Answer TTS Audio:** Synthesized to disk, read into `audio_store`, unlinked from disk, and returned as `answer_audio_url`.
- **Endpoints:** `/voice/audio/{file_id}` was authenticated with API keys, but did not enforce session-level isolation if an alien session ID was passed.
- **Forensic Guarantee:** Zero disk residue existed after request execution, but audio comparison was impossible because the original audio was wiped immediately upon completion of vocoder processing.

---

## 2. Source Files Changed

1. **`app/models/voice.py`**:
   - Added `original_audio_url: Optional[str] = ""` to `QueryResponse` model for clean, backward-compatible API exposure.

2. **`app/voice/audio_store.py`**:
   - Updated `EphemeralAudioStore.store()` to record `request_id` alongside `session_id`.
   - Updated `EphemeralAudioStore.retrieve()` to enforce **session isolation**: if the caller supplies a `session_id` and the stored audio item is bound to a session, mismatched session queries are rejected (`return None`).
   - Added `get_info()` helper for metadata inspection without reading raw bytes.

3. **`app/routers/voice.py`**:
   - In `stream_audio` (`/voice/audio/{file_id}`), added `session_id` query parameter and `x-session-id` header support, passing them to `audio_store.retrieve()` to prevent cross-session access.
   - In `/voice/query`:
     - Stored the normalized 16kHz mono user speech (`normalized_path`) in `audio_store` under key `orig_{request_id}_{uuid.hex[:8]}` bound to `session_id` and `request_id`.
     - Bound obfuscated audio and answer audio to `request_id` and `session_id`.
     - Added `metadata["audio_inspector"]` detailing `request_id`, `session_id`, `original_audio_url`, `obfuscated_audio_url`, `has_original`, and `has_obfuscated`.
     - Returned `original_audio_url` in `QueryResponse`.
     - Preserved strict disk file deletion in the `finally:` block (zero forensic disk persistence).

4. **`voice_chat.html` & `app/voice_chat.html`**:
   - Added an unobtrusive, responsive **Obfuscation Inspector** comparison section right below the assistant response card.
   - Displays side-by-side cards for:
     - 🎤 **Original Audio** (User Recording)
     - 🛡️ **Processed Audio** (Vocoder Obfuscated)
   - Stacks gracefully on mobile screens via CSS `grid-template-columns: repeat(auto-fit, minmax(250px, 1fr))`.
   - Included audio event listeners for idle, playing, and error/unavailable states ("Audio unavailable or expired").
   - Explicitly displays an **Inspection Notice**: clarifies that this demonstrates acoustic formant/pitch shifts for demonstration and observability, and is *not* a mathematical proof of anonymity.
   - Controls appear *only* when both audio files are available (`${(data.original_audio_url && data.obfuscated_audio_url) ? ... : ''}`).

5. **`tests/test_obfuscation_inspector.py`**:
   - Created dedicated test suite (7 comprehensive test cases).

---

## 3. API Changes and Access-Control Behavior

### Endpoint: `POST /voice/query`
- **Response Format:**
  ```json
  {
    "original_audio_url": "/voice/audio/orig_req123_abc456?api_key=...&session_id=sess_789",
    "obfuscated_audio_url": "/voice/audio/obf_req123_def789?api_key=...&session_id=sess_789",
    "answer_audio_url": "/voice/audio/ans_req123_ghi012?api_key=...&session_id=sess_789",
    "transcript": "...",
    "answer_text": "...",
    "metadata": {
      "request_id": "req123",
      "session_id": "sess_789",
      "audio_inspector": {
        "request_id": "req123",
        "session_id": "sess_789",
        "original_audio_url": "...",
        "obfuscated_audio_url": "...",
        "has_original": true,
        "has_obfuscated": true
      }
    }
  }
  ```

### Endpoint: `GET /voice/audio/{file_id}`
- **Authentication:** Requires valid `api_key` (via header `api-key` or query parameter `api_key`). Invalid keys receive `401 Unauthorized`.
- **Session Isolation:** If the stored audio is bound to `session_A` and a request specifies `session_id=session_B`, access is rejected with `404 Audio expired or session ended`.
- **Ephemeral Storage:** Audio is stored strictly in memory (`io.BytesIO`). Disk persistence is zero.
- **Session Cleanup:** When the browser tab refreshes or closes (`POST /voice/session/cleanup?session_id=sess_789`), both the original and processed audio are burned simultaneously from RAM.

---

## 4. UI Behavior

- **Appearance:** Embedded cleanly into the conversational message history directly below the response text.
- **Conditional Visibility:** If `original_audio_url` or `obfuscated_audio_url` is missing or empty, the comparison section is omitted entirely.
- **Playback States:**
  - *Idle:* Standard browser audio controls with `preload="none"` to conserve bandwidth.
  - *Playing:* Status indicator updates to `"Playing..."`.
  - *Unavailable / Expired:* Status indicator displays `"Unavailable or expired"` in red text if the audio was purged by session cleanup.
- **Layout:** CSS Grid layout ensures side-by-side display on desktop (>600px) and vertical stacking on mobile devices.

---

## 5. Evaluation of Speaker Similarity Measurement

### Inspection of `eval_speaker_similarity.py`
`eval_speaker_similarity.py` uses `transformers` to load `anton-l/wav2vec2-base-superb-sv` (a ~360MB neural x-vector model) to compute deep acoustic speaker embeddings and calculate cosine similarity drop:
$$\text{Sim Drop} = 1.0 - \cos(\mathbf{e}_{\text{clean}}, \mathbf{e}_{\text{obf}})$$

### Decision: Excluded from Live Interactive Serving
Per Step 2 instruction 4:
> *"If the existing evaluation implementation is unsuitable for live use, leave similarity measurement out of this phase. Audio playback is the primary requirement."*

**Reasons:**
1. **Model Download & Offline Invariant:** The model weights (`anton-l/wav2vec2-base-superb-sv`) are hosted on Hugging Face Hub. Downloading or requiring this model during runtime would break offline/air-gapped operation and add ~360MB of model weights to memory.
2. **Latency Overhead:** Running deep neural transformer feature extraction on CPU adds ~500–1,500ms of latency per query, degrading interactive voice assistant responsiveness.
3. **Misleading Anonymity Framing:** Displaying an x-vector cosine similarity score to end users creates a false impression of mathematical privacy or biometric anonymity. Formant-preserving pitch shift does not guarantee anonymity against state-of-the-art forensic voice biometrics.

Therefore, live speaker similarity metrics are excluded from this phase; offline evaluation via `eval_speaker_similarity.py` remains available for offline benchmarking.

---

## 6. Test Evidence and Results

### 1. Dedicated Test Suite
Command:
```powershell
.\venv\Scripts\python.exe -m pytest tests/test_obfuscation_inspector.py -v
```
Output:
```
tests/test_obfuscation_inspector.py::TestObfuscationInspectorBackend::test_voice_query_associates_both_audio_versions_with_request PASSED [ 14%]
tests/test_obfuscation_inspector.py::TestObfuscationInspectorBackend::test_both_audio_streams_are_accessible_and_stream_valid_wav PASSED [ 28%]
tests/test_obfuscation_inspector.py::TestObfuscationInspectorBackend::test_audio_streaming_requires_valid_api_key PASSED [ 42%]
tests/test_obfuscation_inspector.py::TestObfuscationInspectorBackend::test_invalid_or_expired_audio_identifiers_return_404 PASSED [ 57%]
tests/test_obfuscation_inspector.py::TestObfuscationInspectorBackend::test_session_isolation_blocks_cross_session_retrieval PASSED [ 71%]
tests/test_obfuscation_inspector.py::TestObfuscationInspectorBackend::test_session_cleanup_burns_both_audio_files PASSED [ 85%]
tests/test_obfuscation_inspector.py::TestObfuscationInspectorBackend::test_zero_disk_persistence_after_request PASSED [100%]

======================== 7 passed, 5 warnings in 5.07s ========================
```

### 2. Full Repository Test Suite
Command:
```powershell
.\venv\Scripts\python.exe -m pytest -q --tb=short
```
Output:
```
283 passed, 12 warnings in 76.92s (0:01:16)
```
**All 283 tests passed with zero failures and zero regressions.**

---

## 7. Manual Verification Instructions

1. Start the API server:
   ```powershell
   .\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
2. Open `http://127.0.0.1:8000/` in a web browser.
3. Record a short query (e.g. "What are the active customers?") using the microphone or upload a test WAV file.
4. When the response arrives:
   - Observe the **Obfuscation Inspector** section below the assistant response.
   - Click Play on **🎤 Original Audio** — verify clear, un-shifted playback of your recording.
   - Click Play on **🛡️ Processed Audio** — verify the pitch-shifted / formant-warped version passed to Whisper.
5. Refresh the page:
   - Verify that session cleanup executes and cached audio URLs fail safe if accessed after page unload.

---

## 8. Remaining Limitations

1. **In-Memory RAM Footprint:** Holding both original and obfuscated audio in RAM during the active session consumes ~300–600 KB per query. In long-running browser sessions with hundreds of queries, RAM usage is bounded by `default_ttl_seconds=3600.0` (1 hour) and explicit session cleanup on tab close.
2. **Inspection vs. Anonymity:** Obfuscation alters vocal pitch and formants to obscure speaker identity for casual eavesdropping, but does not constitute cryptographic or mathematical anonymity against dedicated biometric models.

---

## Final Verdict

`OBFUSCATION INSPECTOR IMPLEMENTED`
