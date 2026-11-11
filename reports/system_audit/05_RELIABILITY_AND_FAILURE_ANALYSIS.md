# Report 05 — End-to-End Reliability & Failure Analysis

**Audit Document:** `reports/system_audit/05_RELIABILITY_AND_FAILURE_ANALYSIS.md`  
**HEAD Commit:** `5b20a3a`  
**Status:** Comprehensive Pipeline Resilience & Failure Mode Audit  

---

## 1. Concept Definition & AI Systems Importance

In AI engineering, **Reliability** is often conflated with model accuracy. In reality, reliable systems design isolates failure modes across distinct layers:
1. **Infrastructure & Execution Reliability:** Does the software stay alive under memory pressure, network drops, or corrupt inputs?
2. **Acoustic Transcription Robustness:** Does the speech recognizer withstand accents, clipping, and background noise?
3. **Semantic Boundary Reliability:** Does the decision router safely refuse out-of-domain or adversarial instructions?
4. **Tool Execution Integrity:** Are database queries strictly bounded, typed, and schema-validated?

---

## 2. Stage-by-Stage Reliability & Failure Containment Matrix

The 11-stage pipeline was audited for failure containment, graceful degradation, and error propagation:

| Stage # & Name | Potential Failure Mode | Implementation Mechanism | Graceful Degradation / Fallback | Containment Rating |
|---|---|---|---|---|
| **1. Audio Intake & Validation** | Oversized file (>25MB), corrupt WAV header, malicious binary payload. | `app/voice/audio_validation.py:validate_audio_file` | Rejects with HTTP 400/413 before allocating model memory. | **High** `[VERIFIED]` |
| **2. Vocoder Obfuscation** | PyWorld C-extension crash, unvoiced audio segment division-by-zero. | `app/voice/obfuscator.py:obfuscate` (try/except block) | Silently falls back to raw unmodified audio, logging warning. | **High** `[VERIFIED]` |
| **3. Whisper Speech-to-Text** | Unintelligible murmur, silence, or background static. | `app/voice/stt.py:transcribe_with_confidence` | Checks `avg_logprob < -1.0` or `no_speech_prob > 0.6`; returns early refusal without calling LLM. | **High** `[VERIFIED]` |
| **4. Transcript Correction** | Hallucinated entity replacement (e.g. "users" replaced with "customers"). | `app/services/correction_guard.py:validate_correction` | Rejects correction if entity swap or lexical overlap < 0.6; falls back to raw Whisper transcript. | **High** `[VERIFIED]` |
| **5. Intent Classification** | Unrecognized domain query or conversational greeting. | `app/services/intent_router.py:classify_intent` | Routes to `GENERAL_CONVERSATION` for direct chat answer without tool execution. | **Medium** `[VERIFIED]` |
| **6. Selective Abstention** | Complex syntactic negation, hypothetical query, conversational mention. | `app/services/abstention_router.py:evaluate_abstention` | **FAILURE POINT:** Lacks linguistic negation/hypothetical rules; 100% false-positive execution on semantic distractors. | **Low (Failure)** `[VERIFIED]` |
| **7. LLM Tool Selection** | Ollama daemon down, inference timeout (>30s), model hallucinating non-existent tool. | `app/services/llm_orchestrator.py:L809-L824` | Traps exception, records `failure_type: llm_tool_call_timeout`, returns clean explanation to user. | **High** `[VERIFIED]` |
| **8. Argument Schema Validation** | LLM emits invalid enum (e.g. `'priority': 'open'`) or negative integers. | `app/services/llm_orchestrator.py:_validate_args` | Intercepts error before connector call; returns clear user error (*"Sorry, couldn't interpret that filter"*). | **High** `[VERIFIED]` |
| **9. Domain Connector Execution** | Missing JSON dataset file, corrupt JSON format, or locking. | `app/services/llm_orchestrator.py:L553-L570` | Zero-fabrication guarantee: never fabricates empty records; retries transient errors up to 2 times. | **High** `[VERIFIED]` |
| **10. Response Synthesis** | LLM crashes during multi-record summarization pass. | `app/services/llm_orchestrator.py:process_query` | Falls back to deterministic record count summary (*"N records found. Showing first 10."*). | **Medium** `[VERIFIED]` |
| **11. Edge-TTS Synthesis** | Microsoft cloud WebSocket drops or internet disconnects. | `app/routers/voice.py:voice_query` (try/except block) | Traps TTS exception; returns text answer in JSON with `audio_url = null`. | **High** `[VERIFIED]` |

---

## 3. Deep Analysis of Failure Containment Mechanisms

### 3.1 Zero-Fabrication Guarantee `[VERIFIED]`
Inspected in [`app/services/llm_orchestrator.py:L572-L585`](file:///d:/Projects/Privacy-Preserving-Voice-Data-Assistant/app/services/llm_orchestrator.py#L572-L585):
```python
# Zero-fabrication guarantee: failed connector never fabricates empty data
if not conn_result.success:
    err_meta = _empty_metadata()
    err_meta.update({
        "connector_error": conn_result.error,
        "tool_calls": call_log,
        "failure_type": "connector_failed",
    })
    return f"I encountered an error retrieving data from {func_name}: {conn_result.error}", err_meta
```
If a connector fails (e.g. `support_tickets.json` is missing or corrupted), the orchestrator never prompts the LLM to "summarize the results," which would cause hallucinated records. It immediately halts tool execution and informs the user of the exact connector error.

### 3.2 Invariant Enforcement: Low-Confidence Acoustic Gate `[VERIFIED]`
Inspected in [`tests/test_invariants.py:L14-L35`](file:///d:/Projects/Privacy-Preserving-Voice-Data-Assistant/tests/test_invariants.py#L14-L35):
When Whisper confidence indicates low quality (`avg_logprob < -1.0` or `no_speech_prob > 0.6`), the voice router refuses to forward the transcript to the LLM or intent router. This prevents "garbage in, garbage out" tool executions triggered by acoustic background noise.

### 3.3 Retry Policy & Backoff Audit `[VERIFIED]`
Inspected in [`app/services/llm_orchestrator.py:L553-L570`](file:///d:/Projects/Privacy-Preserving-Voice-Data-Assistant/app/services/llm_orchestrator.py#L553-L570):
```python
retry_count = 0
max_retries = getattr(settings, "MAX_RETRIES", 2)
conn_result = connector.fetch_result(**args)

while not conn_result.success and retry_count < max_retries:
    err_str = str(conn_result.error or "").lower()
    is_transient = any(w in err_str for w in ["timeout", "temporary", "connection", "locked", "busy"])
    if not is_transient:
        break
    retry_count += 1
    conn_result = connector.fetch_result(**args)
```
- **Strengths:** Strictly bounded ($max=2$); checks error strings to only retry transient faults; avoids infinite loops.
- **Weaknesses:** **No exponential backoff or jitter**; retries execute immediately in a tight loop. Retries only apply to connectors, not to Ollama HTTP timeouts.

---

## 4. Reliability of Subsystems Compared

```
+--------------------------------------------------------------------------+
| Subsystem                     | Reliability  | Primary Failure Mode       |
+--------------------------------------------------------------------------+
| 1. Software Execution (FastAPI)| VERY HIGH    | Event loop blocking on CPU |
| 2. Audio Validation & Format   | VERY HIGH    | Incompatible codecs        |
| 3. Speech Recognition (Whisper)| HIGH         | Severe acoustic distortion |
| 4. Schema & Tool Argument Guard| HIGH         | LLM argument invalid enum  |
| 5. Domain Connectors (Mock)    | VERY HIGH    | File path missing          |
| 6. Speech Synthesis (TTS)      | MEDIUM       | Cloud network drop         |
| 7. Semantic Abstention Router  | LOW (FAIL)   | Negation, mention, hyp.    |
+--------------------------------------------------------------------------+
```

---

## 5. Domain Ratings & Neutral Assessment

| Evaluation Dimension | Rating | Justification & Source Evidence |
|---|---|---|
| **Implementation Maturity** | **Level 3 (Tested Implementation)** | The pipeline features defense-in-depth: vocoder fallback, correction guard, schema validation, zero-fabrication guarantees, and TTS network fallback. It does not reach Level 4 because exponential backoff, circuit breakers, and rate limiters are absent. |
| **Evidence Confidence** | **High** | Invariants and fallbacks verified directly in source code and unit tests (`tests/test_invariants.py`, `tests/test_tool_validation.py`). |
| **Production Relevance** | **High** | The zero-fabrication guarantee and low-confidence STT gating prevent the most dangerous LLM failure modes in enterprise settings. |
| **Distinctiveness** | **High** | Multi-gate defensive programming across every stage of a voice-to-database pipeline is exceptionally rare outside enterprise-grade deployments. |

---

## 6. Recommended 80/20 Improvements

1. **Exponential Backoff in Connector Retries `[PROPOSED]`:**
   - **Action:** Add `time.sleep(0.1 * (2 ** retry_count))` before retrying transient connector calls.
   - **Effort:** 20 minutes.
   - **Impact:** Medium. Prevents hammering busy resources.
2. **Circuit Breaker for Ollama Server `[PROPOSED]`:**
   - **Action:** If Ollama fails or times out 3 consecutive times, trip circuit breaker for 30s to reject incoming queries instantly rather than hanging each request for 30s.
   - **Effort:** 1.5 hours.
   - **Impact:** High. Protects application during local model daemon crashes.
