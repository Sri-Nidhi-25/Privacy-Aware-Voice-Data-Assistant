# Phase 1 Remediation — Baseline Inspection and Implementation Plan
**Document:** `reports/remediation/phase1/00_BASELINE_AND_PLAN.md`  
**Repository:** `Privacy-Preserving-Voice-Data-Assistant`  
**Date:** November 2, 2026  
**Auditor / Implementer:** Senior AI Systems & Reliability Engineer  
**Scope:** P0-A (Semantic Execution Safety), P0-B (TTS Privacy Boundary), P1 (Async Workload Isolation)

---

## 1. Executive Baseline & Current Repository State

A comprehensive forensic inspection of the codebase prior to source modification revealed the exact operational mechanisms, gaps, and invariants:

```
                            CURRENT PIPELINE REALITY
                            
 [User Voice Audio]
        │
        ▼ (FastAPI async def process_voice_command)
 1. validate_and_load() ──────► SYNCHRONOUS audio decoding on ASGI event loop
        │
 2. req_obfuscator.obfuscate() ─► SYNCHRONOUS pyworld vocoder on ASGI event loop (Blocks 100-300ms)
        │
 3. stt.transcribe_with_confidence() ─► SYNCHRONOUS Whisper PyTorch on ASGI event loop (Blocks 1.5-6.0s)
        │
 4. orchestrator.process_query() ─────► SYNCHRONOUS Ollama HTTP & connectors on ASGI event loop
        │                                 │
        │                                 ├──► evaluate_abstention() (Regex only! 100% distractor leakage)
        │                                 └──► _execute_tool_calls() (No semantic boundary before execution)
        │
 5. _synthesize_and_verify() ─────────► edge-tts transmits connector response to Microsoft Cloud!
```

---

## 2. Priority P0-A: Semantic Execution Safety

### 2.1 Current Behavior & Code Evidence
- **File:** `app/services/abstention_router.py` (`evaluate_abstention`)
  - Evaluates queries using regex keyword matching (`CRM_ENTITIES`, `OPERATIONAL_DIRECTIVES`, `NON_OPERATIONAL_DISTRACTORS`).
  - When tested on the 5 frozen semantic distractor cases from `semantic_conflict_v1.jsonl`:
    - `sem_conf_002` ("Do not show me any active customers right now.") $\to$ **`Decision.EXECUTE`** (Confidence 1.0)
    - `sem_conf_004` ("Open support tickets are becoming a real headache...") $\to$ **`Decision.EXECUTE`** (Confidence 0.7)
    - `sem_conf_006` ("What if we were to query daily active users tomorrow...") $\to$ **`Decision.EXECUTE`** (Confidence 0.7)
    - `sem_conf_008` ("Something about tickets, maybe check them...") $\to$ **`Decision.EXECUTE`** (Confidence 1.0)
    - `sem_conf_010` ("Pull records for inactive customers, wait no, cancel that...") $\to$ **`Decision.EXECUTE`** (Confidence 1.0)
  - **Result:** 5/5 semantic distractors are granted tool authorization because keywords match despite negative, hypothetical, conversational, or cancelled intent.
- **File:** `app/services/llm_orchestrator.py` (`process_query`, `_execute_tool_calls`)
  - In `process_query`, once `evaluate_abstention` returns `EXECUTE`, `self.client.chat(tools=TOOLS)` is called.
  - In `_execute_tool_calls`, tool calls are dispatched directly to connectors (`connector.fetch_result(**args)`) without an explicit semantic decision boundary.
  - The decision schema in `abstention_router.py` only defines `EXECUTE`, `ABSTAIN`, `DIRECT`. It lacks `CLARIFY`.
  - While argument validation (`_validate_args`) exists in `llm_orchestrator.py:254`, invalid arguments return an error string without formal stage localization metadata for the caller.

### 2.2 Existing Tests
- `tests/test_phase5/test_abstention_router.py` (5 tests for basic regex abstention)
- `tests/test_routing.py` (4 tests for basic keyword intent classification)
- `tests/test_tool_validation.py` (12 tests for connector argument validation)
- `tests/test_phase6/test_phase61_evaluator.py` (28 tests checking Phase 6.1 metrics and expected actions)

### 2.3 Missing Tests
- Tests verifying that negated requests (`"Do not show me..."`) return `ABSTAIN` and do NOT invoke connectors.
- Tests verifying that conversational mentions (`"Tickets are a headache..."`) return `ABSTAIN` and do NOT invoke connectors.
- Tests verifying that hypothetical inquiries (`"What if we were to query..."`) return `ABSTAIN` and do NOT invoke connectors.
- Tests verifying that trailing cancellations (`"...wait no, cancel that"`) return `ABSTAIN` and do NOT invoke connectors.
- Tests verifying that ambiguous requests (`"Something about tickets..."`) return `CLARIFY` and do NOT invoke connectors.
- Tests verifying that malformed or contradictory decision outputs fail closed.
- Tests asserting zero connector invocation (`mock_connector.fetch.assert_not_called()`) on `ABSTAIN` and `CLARIFY`.

### 2.4 Planned Minimal Changes
1. **Extend `Decision` Schema:** Add `CLARIFY = "CLARIFY"` to `class Decision(Enum)` in `app/services/abstention_router.py`.
2. **Implement Explicit Semantic Decision Boundary Gate:**
   - Create a structured semantic intent validator with explicit schema:
     `SemanticDecision`: `action` (`EXECUTE`, `CLARIFY`, `ABSTAIN`), `intent`, `confidence`, `reason`.
   - Incorporate pragmatic discourse markers in `abstention_router.py`:
     - **Negation scope detection:** Explicit prohibition markers (`"do not"`, `"don't"`, `"never"`) governing operational verbs.
     - **Hypothetical modality:** Counterfactual markers (`"what if"`, `"suppose"`, `"imagine"`).
     - **Conversational cancellation:** Trailing retractions (`"cancel that"`, `"never mind"`, `"wait no"`).
     - **Conversational mention / complaint:** Pure evaluative commentary without request verbs (`"becoming a headache"`, `"are frustrating"`).
     - **Ambiguous / Underspecified:** Vague noun references lacking filters or clear parameters $\to$ `Decision.CLARIFY`.
3. **Fail-Closed Execution Boundary in Orchestrator:**
   - In `_execute_tool_calls`, introduce an invariant check: before any connector `fetch_result` is invoked, verify that `decision == Decision.EXECUTE`.
   - If decision is `ABSTAIN` or `CLARIFY`, connector execution is strictly prohibited.
   - Retries and fallbacks cannot bypass this boundary.

---

## 3. Priority P0-B: Remove Sensitive Response Text from Cloud TTS

### 3.1 Current Behavior & Code Evidence
- **File:** `app/voice/tts.py` (`TTSEngine.synthesize`)
  - Calls `edge_tts.Communicate(text, self.voice)` unconditionally.
  - Sends whatever `text` is passed directly to Microsoft's cloud servers over HTTPS.
- **File:** `app/routers/voice.py` (lines 367, 434)
  - Passes `answer_text` (synthesized from CRM, Support, and Analytics connector records) directly to `_synthesize_and_verify(answer_text, answer_path)`.
- **Environment:**
  - Neither `pyttsx3`, `piper-tts`, nor local offline TTS engines are currently installed in `requirements.txt` or the virtual environment.

### 3.2 Existing Tests
- `tests/test_api.py` mocks `_synthesize_and_verify` with dummy bytes to avoid network calls.
- No test checks whether connector data is leaked to remote TTS.

### 3.3 Missing Tests
- Tests proving that responses derived from tool execution (CRM, Support, Analytics) do NOT call `edge_tts`.
- Tests verifying that remote TTS is disabled by default for sensitive responses.
- Tests verifying that when remote TTS is disabled, the textual answer is preserved and audio URL is safely `None`.
- Tests proving that invalid or missing configuration fails safely to offline mode (no audio synthesis).
- Tests verifying that non-sensitive, static error messages (e.g. "I could not hear you clearly") can safely synthesize if explicitly configured.

### 3.4 Planned Minimal Changes
1. **Privacy Policy in Configuration (`app/config.py`):**
   - Add `TTS_PROVIDER: str = "disabled"` (default safe mode: no external transmission).
   - Add `ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA: bool = False` (hard invariant: strictly disallow remote TTS for tool-derived data).
2. **Privacy Boundary in `app/voice/tts.py`:**
   - Implement `TTSEngine` with privacy-aware gating:
     - Check `is_sensitive` flag on synthesis requests.
     - If `is_sensitive=True`, refuse remote transmission; return immediately or raise `PrivacyViolationError`.
     - Support local offline TTS engine interface (with mockable or fallback offline synthesis).
3. **Integration in `app/routers/voice.py`:**
   - Mark `answer_text` as sensitive whenever `orchestrator_result["metadata"].get("tool_calls")` is non-empty or `classified_intent != "direct"`.
   - For sensitive answers: bypass remote TTS, set `metadata["tts_blocked_for_privacy"] = True`, set audio ID to `None`, and return textual answer.
   - For non-sensitive static system prompts ("Please repeat that"): allow TTS only if provider is explicitly enabled.

---

## 4. Priority P1: Offload Blocking STT/Vocoder Workloads from ASGI Event Loop

### 4.1 Current Behavior & Code Evidence
- **File:** `app/routers/voice.py`
  - Line 251: `y, sr, duration = validate_and_load(input_path, file_size)` $\to$ Synchronous audio file reading on main thread.
  - Line 309: `actual_shift = req_obfuscator.obfuscate(...)` $\to$ Synchronous C/NumPy WORLD vocoder on main thread (100–300ms).
  - Line 335: `user_text, stt_confidence = stt.transcribe_with_confidence(obf_path)` $\to$ Synchronous PyTorch Whisper inference on main thread (1.5–6.0s CPU).
  - Line 402: `orchestrator_result = orchestrator.process_query(...)` $\to$ Synchronous Ollama HTTP client and tool execution on main thread (500–2500ms).
- **Result:** While any voice query is processing, the ASGI event loop thread is 100% frozen. Health checks (`/health/live`) and concurrent requests cannot be served.

### 4.2 Existing Tests
- `tests/test_health.py` tests health endpoints in isolation.
- `tests/test_api.py` tests endpoint responses using TestClient (synchronous).
- Zero tests currently measure event loop responsiveness or concurrent health checks during audio processing.

### 4.3 Missing Tests
- Async responsiveness test: Verify that an independent lightweight coroutine or `/health/live` check can execute and complete while a simulated heavy STT or vocoder job is in progress.
- Thread offloading test: Verify that `validate_and_load`, `obfuscate`, `transcribe_with_confidence`, and `process_query` execute in separate worker threads via `anyio.to_thread.run_sync()`.
- Concurrency limit test: Verify that an `asyncio.Semaphore` bounds concurrent audio processing jobs to prevent CPU starvation.

### 4.4 Planned Minimal Changes
1. **Thread Offloading in `app/routers/voice.py`:**
   - Wrap heavy CPU/blocking calls with `anyio.to_thread.run_sync()`:
     - `await anyio.to_thread.run_sync(validate_and_load, input_path, file_size)`
     - `await anyio.to_thread.run_sync(req_obfuscator.obfuscate, normalized_path, obf_path, tempo_rate)`
     - `await anyio.to_thread.run_sync(stt.transcribe_with_confidence, obf_path)`
     - `await anyio.to_thread.run_sync(orchestrator.process_query, user_text, enable_abstention)`
2. **Concurrency Limiter:**
   - Add `AUDIO_PROCESSING_SEMAPHORE = asyncio.Semaphore(settings.MAX_CONCURRENT_VOICE_REQUESTS)` (default: 2) to prevent thread exhaustion on multi-core hosts.
3. **Preserve Error Propagation & Order:**
   - Exceptions raised in worker threads are natively re-raised into the async route handler, preserving all existing try/except error boundaries.

---

## 5. Potential Regressions & Mitigation Strategy

| Component | Potential Regression | Mitigation Strategy |
|---|---|---|
| **Abstention Router** | Legitimate operational queries containing negative keywords (e.g. "customers with no open tickets") might falsely abstain. | Use syntactic clause matching: only negative directives applied to the request verb (`do not show`) trigger abstention; attribute filters (`status=inactive`, `priority=none`) must remain operational. |
| **TTS Engine** | Frontend UI might expect an audio URL and render broken audio player if `audio_id` is None. | In `voice.py`, ensure response JSON schema remains identical; return `audio_id: null` and `audio_url: null` with explicit `tts_blocked_for_privacy: true` flag in metadata. |
| **Thread Offloading** | Unhandled threadpool context propagation or mocking issues in existing pytest suite. | Use standard `anyio.to_thread.run_sync()`; existing test mocks patch `voice.stt` and `voice.orchestrator` directly, which work seamlessly with `run_sync`. |

---

## 6. Pre-Existing Working Tree State

Git status before remediation begins:
- Tracked modified files: 38 files (including configuration, benchmark audio files, documentation).
- Untracked files: `reports/`, `evaluation/`, `experiments/`, `docs/`, `tests/test_phase6/`.
- **Constraint:** Zero resets, zero checkout of existing files, zero modification of frozen evaluation datasets or historical results.

---

## 7. Ambiguities & Decisions for User Confirmation

1. **Local TTS Availability:**
   - Because no local TTS binary (Piper or eSpeak) is installed in the local virtualenv, the privacy-preserving default will be: **disable TTS audio synthesis for sensitive responses and return clean textual answers with `tts_blocked_for_privacy: True`**.
   - Remote Edge-TTS will be strictly prohibited from receiving connector-derived or customer data.
2. **Decision Schema Alignment:**
   - We will extend `Decision(Enum)` in `app/services/abstention_router.py` to include `CLARIFY = "CLARIFY"`, aligning it with `run_paired_evaluation.py` and Phase 6.1 evaluation standards.

**Next Step:** Proceed to implement Priority P0-A, P0-B, and P1 in sequence, verify with focused tests, and produce the final implementation report and checklist.
