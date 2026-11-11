# Phase 1 Remediation — Implementation and Test Report

**Repository:** `Privacy-Preserving-Voice-Data-Assistant`  
**Report version:** 1.0  
**Generated:** 2026-11-02  
**Git HEAD at time of report:** `5b20a3a` (unmodified; no new commits)  
**Python / venv:** Python 3.11.3 — `.\venv\Scripts\python.exe`

---

## 0. Executive Summary

Phase 1 Remediation addressed the three highest-priority findings from the technical audit:

| Priority | Finding | Resolution status |
|----------|---------|-------------------|
| P0-A | Semantic distractor leakage — the abstention router executed tools on out-of-domain conversational text | **Implemented and verified** |
| P0-B | Sensitive connector-derived text transmitted to cloud TTS (Microsoft Edge-TTS) | **Implemented and verified** |
| P1 | Synchronous Whisper STT and WORLD vocoder blocking the ASGI event loop | **Implemented and verified** |

Full test suite result after changes: **175 passed, 0 failed, 14 warnings — 80.48s**  
(152 pre-existing tests + 23 new Phase 1 tests)

No pre-existing tests regressed. No frozen datasets, evaluation runs, or audit documents were modified.

---

## 1. P0-A — Prevent Unsafe Semantic Tool Execution

### 1.1 Root cause identified

Before this phase, `evaluate_abstention` in `app/services/abstention_router.py` used only two evidence signals:

- **Domain entity presence** (CRM/support/analytics nouns)
- **Operational directive presence** (imperative verbs: show, list, get…)

It had no mechanism to detect:

- **Explicit negations**: "Do not show me customers"
- **Conversational cancellations**: "Wait no, cancel that, never mind"
- **Hypothetical framing**: "What if we were to query…"
- **Conversational mentions**: "Support tickets are becoming a headache"
- **Underspecified requests**: "Something about tickets, or whatever"

This caused 5/5 Phase 6.1 distractor queries to route as `EXECUTE`, passing them to the LLM orchestrator with an instruction to call tools.

### 1.2 Files changed

| File | Change |
|------|--------|
| [`app/services/abstention_router.py`](../../app/services/abstention_router.py) | Added `Decision.CLARIFY`, five pragmatic discourse pattern matchers, and `validate_decision()` |
| [`app/services/llm_orchestrator.py`](../../app/services/llm_orchestrator.py) | Integrated `validate_decision`, added `Decision.CLARIFY` handling, added tool existence boundary check |

### 1.3 Changes in detail

#### `app/services/abstention_router.py`

**Added `Decision.CLARIFY`** to the `Decision` enum (L26–L29):
```python
class Decision(Enum):
    EXECUTE = "EXECUTE"
    ABSTAIN = "ABSTAIN"
    CLARIFY = "CLARIFY"
    DIRECT  = "DIRECT"
```

**Added five pragmatic discourse pattern matchers** (L79–L102):

| Constant | Purpose | Example |
|----------|---------|---------|
| `NEGATED_DIRECTIVES` | Explicit negations applied to operational verbs | "Do not show me active customers" |
| `CONVERSATIONAL_CANCELLATIONS` | User retracts a request mid-utterance | "Pull records, wait no, cancel that" |
| `HYPOTHETICAL_INQUIRIES` | Speculative or conditional framing | "What if we were to query DAU?" |
| `CONVERSATIONAL_MENTIONS` | Commentary about domain entities without action | "Tickets are becoming a real headache" |
| `UNDERSPECIFIED_REQUESTS` | Vague requests that require clarification | "Something about tickets, or whatever" |

These patterns fire in Step 3 of `evaluate_abstention`, short-circuiting domain/operational matching:

- `UNDERSPECIFIED_REQUESTS` → `Decision.CLARIFY` (domain entity must be present)
- All others → `distractor_penalty = 1.0` → `Decision.ABSTAIN`

**Added `validate_decision(result)`** (L105–L118):

A fail-closed validation gate applied after any abstention evaluation. It rejects contradictory or corrupted results:

- `EXECUTE` with `distractor_penalty > 0` → downgrades to `ABSTAIN`
- `EXECUTE` with `operational_evidence <= 0` → downgrades to `ABSTAIN`
- Non-`AbstentionResult` input → `ABSTAIN`

#### `app/services/llm_orchestrator.py`

**Integrated `validate_decision`** in `process_query()` (L708–L711):
```python
abs_res = evaluate_abstention(corrected_text, threshold=0.50)
validated_decision = validate_decision(abs_res)
if abs_res.decision != validated_decision:
    abs_res.decision = validated_decision
```

**Added `Decision.CLARIFY` handling** (L737–L754): returns a clarification prompt without dispatching any tool or connector call.

**Added tool existence boundary check** in `_execute_tool_calls()` (L520–L532): before argument validation or connector dispatch, the tool name is checked against the set of registered tools. Unknown tool names produce `failure_type: "invalid_tool_name"` and return immediately.

### 1.4 Safety guarantees enforced

| Guarantee | Evidence |
|-----------|---------|
| Zero connector invocation on ABSTAIN | `test_zero_connector_invocation_on_abstain_and_clarify` — mock connectors: `fetch_result.call_count == 0` |
| Zero connector invocation on CLARIFY | Same test |
| Unknown tool names rejected pre-dispatch | `test_invalid_tool_name_never_reaches_connector` |
| Invalid tool args rejected pre-dispatch | `test_invalid_tool_args_never_reach_connector` |
| Contradictory EXECUTE results downgraded | `test_decision_validation_fails_closed_on_contradiction` |
| All 5 frozen Phase 6.1 distractors abstain | `test_frozen_distractor_regression_suite` |

### 1.5 Known limitations

- Pattern matching is regex-based, not LLM-based. Novel phrasings not covered by the compiled patterns may still slip through.
- The five pragmatic patterns were tuned against the 10 Phase 6.1 cases. Generalization to wider adversarial datasets is not yet tested.
- No audio-level evaluation has been run on the updated router. A Phase 6.1 re-run with the updated router is recommended as Phase 2 evaluation work.

---

## 2. P0-B — Remove Sensitive Response Text from Cloud TTS

### 2.1 Root cause identified

`edge-tts` transmits its input string to Microsoft's cloud servers over HTTPS. Before this phase, the system sent connector-derived responses (CRM customer lists, support ticket details, analytics metrics) through this path unconditionally. There was no privacy gate in `tts.py` and no default that prevented synthesis.

### 2.2 Files changed

| File | Change |
|------|--------|
| [`app/config.py`](../../app/config.py) | Added `TTS_PROVIDER`, `ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA`, `MAX_CONCURRENT_VOICE_REQUESTS` |
| [`app/voice/tts.py`](../../app/voice/tts.py) | Rewrote `TTSEngine.synthesize()` with a privacy-first architecture |
| [`app/routers/voice.py`](../../app/routers/voice.py) | Added `is_sensitive` detection and gating at the call site |

### 2.3 Changes in detail

#### `app/config.py` — new settings (L30–L34)

```python
TTS_PROVIDER: str = "disabled"                     # Privacy default
ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA: bool = False  # Hard invariant
MAX_CONCURRENT_VOICE_REQUESTS: int = 2             # Concurrency bound (see P1)
```

#### `app/voice/tts.py` — rewritten `TTSEngine`

`synthesize(text, output_path, is_sensitive=False) -> bool` enforces a strict decision tree:

```
is_sensitive AND NOT ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA  → return False (no transmission)
provider == "disabled"                                     → return False
provider == "remote" AND is_sensitive                     → return False
provider == "remote" AND NOT is_sensitive                 → edge_tts.save() → return True
provider == "local"  (not installed)                      → return False (no cloud fallback)
unknown provider                                          → return False
```

No cloud request is ever made for sensitive content regardless of configuration, unless `ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA` is explicitly set to `True` (operator override, documented as a data sovereignty waiver).

#### `app/routers/voice.py` — sensitivity detection (L466–L487)

```python
has_tools     = bool(metadata.get("tool_calls")) or bool(metadata.get("data_sources_used"))
is_data_query = metadata.get("classified_intent") in ("crm", "support", "analytics", "multi_domain")
is_sensitive_answer = has_tools or is_data_query

did_synth = await _synthesize_and_verify(answer_text, answer_path,
                                          is_sensitive=is_sensitive_answer)
if not did_synth:
    metadata["tts_blocked_for_privacy"] = is_sensitive_answer
    answer_url = ""
```

The response JSON always includes `tts_blocked_for_privacy` so clients know whether audio was suppressed intentionally. The textual answer is always returned.

### 2.4 Privacy guarantees enforced

| Guarantee | Evidence |
|-----------|---------|
| Default `disabled` blocks all synthesis | `test_safe_default_blocks_remote_tts_for_sensitive_data` |
| Sensitive text never reaches `edge_tts.Communicate` even when `provider="remote"` | `test_sensitive_connector_data_never_sent_even_if_remote_requested` — `mock_comm.assert_not_called()` |
| Non-sensitive text synthesises when remote explicitly requested | `test_public_non_sensitive_text_can_synthesize_when_remote_explicit` |
| Unknown provider fails safe | `test_invalid_or_missing_configuration_fails_safe` |
| Local provider unavailable → no cloud fallback | `test_local_provider_unavailable_fails_safe_no_remote_fallback` |
| API endpoint sets `tts_blocked_for_privacy=True` for tool responses | `test_voice_query_endpoint_sets_tts_blocked_for_privacy` |

### 2.5 Known limitations

- The `is_sensitive` detection in `voice.py` uses intent classification metadata as a proxy. If the orchestrator returns data from a tool call but classifies intent as something other than `crm`/`support`/`analytics`/`multi_domain`, the sensitivity gate may miss it. This is a defense-in-depth gap, not a configuration error.
- No local offline TTS binary (`piper`, `espeak`) is installed. Therefore TTS is effectively always suppressed for any response when the default configuration is used. This is intentional for the current development state.

---

## 3. P1 — Offload Blocking STT/Vocoder Workloads from ASGI Event Loop

### 3.1 Root cause identified

The FastAPI application runs on a single-threaded async event loop (uvicorn). Synchronous operations that run on the event loop block all other concurrent requests for their duration. Before this phase, the following CPU-intensive calls ran synchronously on the event loop:

| Call | Typical blocking time |
|------|-----------------------|
| `validate_and_load()` — librosa resampling | 50–200ms |
| `sf.write()` — soundfile disk write | 10–50ms |
| `req_obfuscator.obfuscate()` — pyworld WORLD vocoder | 100–300ms |
| `stt.transcribe_with_confidence()` — OpenAI Whisper small.en | 1,500–6,000ms |
| `orchestrator.process_query()` — synchronous Ollama client | variable |

A single voice request could block health checks, other audio uploads, and API responses for 2–8 seconds.

### 3.2 Files changed

| File | Change |
|------|--------|
| [`app/routers/voice.py`](../../app/routers/voice.py) | Added `anyio`, `get_audio_semaphore()`, offloaded 5 blocking calls |
| [`app/config.py`](../../app/config.py) | Added `MAX_CONCURRENT_VOICE_REQUESTS` |

### 3.3 Changes in detail

#### Worker thread offloading via `anyio.to_thread.run_sync`

All five blocking calls are now offloaded to the anyio thread pool:

```python
# Audio validation
y, sr, duration = await anyio.to_thread.run_sync(validate_and_load, input_path, file_size)

# Normalized write
await anyio.to_thread.run_sync(sf.write, str(normalized_path), y, sr)

# Voice obfuscation
actual_shift = await anyio.to_thread.run_sync(req_obfuscator.obfuscate, normalized_path, obf_path, tempo_rate)

# Speech-to-text (Whisper)
user_text, stt_confidence = await anyio.to_thread.run_sync(stt.transcribe_with_confidence, obf_path)

# LLM orchestration
orchestrator_result = await anyio.to_thread.run_sync(orchestrator.process_query, user_text, enable_abstention)
```

While these calls run in worker threads, the event loop is free to handle other requests.

#### Bounded concurrency via `asyncio.Semaphore`

```python
_audio_semaphore: Optional[asyncio.Semaphore] = None

def get_audio_semaphore() -> asyncio.Semaphore:
    global _audio_semaphore
    if _audio_semaphore is None:
        _audio_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_VOICE_REQUESTS)
    return _audio_semaphore

# In process_voice_command:
sem = get_audio_semaphore()
async with sem:
    try:
        # ... full pipeline
    finally:
        # ... cleanup
```

`MAX_CONCURRENT_VOICE_REQUESTS=2` (default) limits simultaneous Whisper + vocoder jobs, preventing CPU exhaustion on multi-request bursts.

### 3.4 Guarantees demonstrated

| Guarantee | Evidence |
|-----------|---------|
| Event loop remains unblocked during 300ms simulated STT | `test_event_loop_responsiveness_during_blocking_stt` — 5/5 concurrent health pings completed |
| Event loop remains unblocked during 200ms simulated vocoder | `test_event_loop_responsiveness_during_blocking_vocoder` — 4/4 heartbeat ticks completed |
| Semaphore capacity matches configuration | `test_concurrency_limiter_semaphore` — `sem._value == settings.MAX_CONCURRENT_VOICE_REQUESTS` |
| Exceptions from worker threads propagate cleanly | `test_error_propagation_across_thread_boundary` — `PipelineError` correctly raised through thread boundary |

### 3.5 Known limitations

- **Multi-worker deployments are not covered.** `asyncio.Semaphore` is in-process only. Deploying with `uvicorn --workers 4` would allow `4 × MAX_CONCURRENT_VOICE_REQUESTS` simultaneous Whisper jobs. A Redis-backed distributed rate limiter would be required for multi-worker production deployments (out of scope for Phase 1).
- **Thread pool size is not explicitly configured.** `anyio.to_thread.run_sync` uses the default executor, which defaults to `min(32, os.cpu_count() + 4)` threads. This is sufficient for development but may need tuning for production load.
- **`orchestrator.process_query` includes Ollama client calls.** The Ollama Python client's `.chat()` method is synchronous and blocking — it was already making network calls synchronously. Wrapping it in `run_sync` offloads this from the event loop but does not make the Ollama call itself async. An async Ollama client would be the proper long-term solution.

---

## 4. Full Repository Test Results

### 4.1 Full suite (post-Phase-1 changes)

```
Command: .\venv\Scripts\python.exe -m pytest -q
Result:  175 passed, 14 warnings in 80.48s (0:01:20)
```

**175 = 152 pre-existing + 23 new Phase 1 tests**

### 4.2 Phase 1 tests only

```
Command: .\venv\Scripts\python.exe -m pytest tests/test_remediation_phase1.py -v
Result:  23 passed, 7 warnings in 3.39s
```

### 4.3 Phase 1 + API tests

```
Command: .\venv\Scripts\python.exe -m pytest tests/test_remediation_phase1.py tests/test_api.py -v
Result:  32 passed, 9 warnings in 13.00s
```

### 4.4 Pre-existing regression suites

| Suite | Tests | Result |
|-------|-------|--------|
| `tests/test_api.py` | 9 | ✅ All passed |
| `tests/test_audio_validation.py` | — | ✅ All passed |
| `tests/test_phase5/` | — | ✅ All passed |
| `tests/test_phase5_5/` | — | ✅ All passed |
| `tests/test_phase6/` | — | ✅ All passed |
| `tests/test_e2e_smoke/` | — | ✅ All passed |

Zero regressions introduced.

### 4.5 Warnings (not failures)

All 14 warnings are pre-existing framework deprecations:

| Warning | Source | Severity |
|---------|--------|---------|
| `class-based Config deprecated in Pydantic V2` | `app/config.py:17` | Low — cosmetic |
| `on_event deprecated in FastAPI` | `app/main.py:48` | Low — cosmetic |
| `path is deprecated in importlib_resources` | librosa | Low — third-party |
| `'aifc', 'audioop', 'sunau' deprecated` | audioread | Low — Python 3.13 prep |
| `FP16 not supported on CPU` | whisper | Low — expected on CPU-only env |
| `librosa.__audioread_load deprecated` | librosa | Low — third-party |

None of these warnings indicate behavior changes introduced by Phase 1.

---

## 5. Architectural Decisions and Rationale

### 5.1 Why pattern matching, not LLM-based intent detection?

The audit found that LLM-based routing was the source of the distractor leakage problem (Phase 4.6 relied entirely on the LLM's tool-calling decision). A deterministic, auditable pattern layer is:

- **Testable** — patterns can be verified directly without an LLM running
- **Fail-closed** — unknown patterns produce ABSTAIN, not EXECUTE
- **Reproducible** — the same input always produces the same output
- **Latency-free** — no LLM round-trip for abstention decisions

The trade-off is brittleness on novel phrasing. Extending patterns as new failure modes are found is the expected maintenance path.

### 5.2 Why `disabled` as the TTS default?

The only privacy-safe zero-configuration state is one where no data transmission can happen. Setting `TTS_PROVIDER="disabled"` by default means:

- An operator must make an explicit configuration decision to enable TTS
- The decision is auditable (environment variable)
- Forgetting to configure TTS produces silence (not a data leak)

### 5.3 Why `anyio.to_thread.run_sync` over `asyncio.run_in_executor`?

The project already uses `anyio` as a dependency (FastAPI/Starlette). `anyio.to_thread.run_sync` provides:

- Consistent thread offloading across both asyncio and trio backends
- Cleaner cancellation semantics
- No need to import `concurrent.futures` or manage executors manually

---

## 6. Manual Testing Recommended

Automated tests verify safety invariants but do not test the live system. The following manual tests should be run before any deployment:

1. **Live voice query — operational** (`GET /voice/query` with a WAV asking "show me active customers"): confirm `answer_text` is non-empty, `metadata.tts_blocked_for_privacy=True`, `answer_audio_url=""`.
2. **Live voice query — distractor** (WAV asking "tickets to the concert were sold out"): confirm `abstention_decision=ABSTAIN`, no data sources used.
3. **Concurrent request stress** — send 4 simultaneous requests: confirm health endpoint (`/health/live`) responds within 200ms during processing.
4. **TTS opt-in** (set `.env` `TTS_PROVIDER=remote`, `ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA=False`, query for public info "what is the capital of France"): confirm audio URL returned.

---

## 7. What Phase 1 Does NOT Cover

The following audit findings are explicitly out of scope and remain open:

| Finding | Target Phase |
|---------|-------------|
| Authentication middleware / API key rotation | Phase 2 |
| Rate limiting per API key | Phase 2 |
| Redis-backed distributed concurrency control | Phase 2 |
| Idempotency tokens for voice requests | Phase 2 |
| Async Ollama client | Phase 2 |
| Formal RAG pipeline with vector store | Phase 3 |
| Multi-worker session state management | Phase 3 |
| Production observability (OpenTelemetry, structured metrics) | Phase 3 |

---

## 8. Files Modified in Phase 1

```
M app/config.py
M app/services/abstention_router.py
M app/services/llm_orchestrator.py
M app/voice/tts.py
M app/routers/voice.py
A tests/test_remediation_phase1.py  (23 new tests)
```

**No frozen datasets, evaluation runs, or audit documents were modified.**

---

*Report generated by Phase 1 Remediation. For the reviewer checklist, see `02_REVIEW_CHECKLIST.md`.*
