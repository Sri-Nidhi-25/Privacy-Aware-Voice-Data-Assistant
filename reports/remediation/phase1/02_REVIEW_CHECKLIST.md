# Phase 1 Remediation — Reviewer Checklist

**Repository:** `Privacy-Preserving-Voice-Data-Assistant`  
**Checklist version:** 1.0  
**Date:** 2026-11-02  
**Applies to:** Changes introduced in Phase 1 Remediation (`app/config.py`, `app/services/abstention_router.py`, `app/services/llm_orchestrator.py`, `app/voice/tts.py`, `app/routers/voice.py`, `tests/test_remediation_phase1.py`)

> [!IMPORTANT]
> This checklist is for code review, not for deployment approval. Additional integration testing, penetration testing, and infrastructure review are required before production deployment.

---

## Section 1 — Semantic Execution Safety (P0-A)

### 1.1 Abstention boundary correctness

- [ ] **Decision.CLARIFY is a new Decision enum value.** Confirm it is handled in every switch/match that handles `Decision.ABSTAIN` and `Decision.DIRECT`. Check: `llm_orchestrator.py:process_query()`.
- [ ] **Five new regex patterns are compiled at module load.** Confirm each pattern compiles without error and does not exhibit catastrophic backtracking on long inputs. Check: `abstention_router.py:L79–L102`.
- [ ] **`NEGATED_DIRECTIVES` covers the key forms:** `do not`, `don't`, `dont`, `never`, `stop`, `refrain from`, `avoid`. Review the pattern for false-positive risk on legitimate queries containing these words in other positions (e.g., "find customers who have not churned").
- [ ] **`CONVERSATIONAL_CANCELLATIONS` catches multi-part utterances** (e.g., "pull records, wait no, cancel that"). Confirm the pattern matches mid-sentence, not just at the start.
- [ ] **`UNDERSPECIFIED_REQUESTS` requires `domain_evidence > 0`** before returning CLARIFY. Confirm this guard is in place (line 152). Without it, any vague sentence would return CLARIFY unnecessarily.
- [ ] **Control queries are not false-positively blocked.** Verify that "show me customers who do not have open tickets", "list tickets with no priority", and "find inactive accounts" all route to `Decision.EXECUTE`.

### 1.2 Fail-closed validation gate

- [ ] **`validate_decision()` rejects contradictory EXECUTE results.** Verify: `EXECUTE` + `distractor_penalty > 0` → `ABSTAIN`.
- [ ] **`validate_decision()` rejects non-AbstentionResult inputs.** Verify: `None`, strings, dicts → `ABSTAIN`.
- [ ] **`validate_decision()` is called in `process_query()`** before branching on `abs_res.decision`. Check `llm_orchestrator.py:L709`.
- [ ] **`abs_res.decision` is overwritten if validation changes it.** Confirm that `abs_res.decision = validated_decision` executes before any branch check.

### 1.3 Tool execution boundary

- [ ] **Valid tool name whitelist.** The `valid_tool_names` set is built from `TOOLS` (the same list used to call the LLM). Any mismatch between `TOOLS` and `connector_map` keys would cause valid calls to pass the name check but fail silently at connector lookup. Confirm all three tools appear in both.
- [ ] **Invalid tool name check occurs before argument validation and connector dispatch.** Check order in `_execute_tool_calls()` — name check (L526), then args coerce/validate (L545–L557), then connector fetch (L566).
- [ ] **Zero connector invocation on ABSTAIN and CLARIFY.** Confirm that both `process_query()` early returns (ABSTAIN at L718–L735, CLARIFY at L737–L754) return before reaching `_execute_tool_calls()`.

### 1.4 Regression safety

- [ ] **Frozen Phase 6.1 dataset exists at `evaluation/datasets/phase6/semantic_conflict_v1.jsonl`** and was not modified.
- [ ] **`test_frozen_distractor_regression_suite` passes** — all 5 `is_operational=False` cases in the dataset result in `ABSTAIN` or `CLARIFY` with zero connector calls.
- [ ] **Five valid operational queries still route to `EXECUTE`.** Check `test_clear_valid_operational_requests`.

---

## Section 2 — TTS Privacy Boundary (P0-B)

### 2.1 Default configuration

- [ ] **`TTS_PROVIDER` defaults to `"disabled"`.** Check `app/config.py:L30`.
- [ ] **`ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA` defaults to `False`.** Check `app/config.py:L31`.
- [ ] **Neither value requires explicit `.env` configuration to be safe.** The safe state is the default state.

### 2.2 Sensitive data gate

- [ ] **`TTSEngine.synthesize()` is `async`.** Confirm the caller in `voice.py` `await`s it via `asyncio.wait_for(tts.synthesize(...))`.
- [ ] **Sensitive check is applied before any provider-specific logic.** Confirm the `is_sensitive and not ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA` guard (L34) is the first conditional in `synthesize()`.
- [ ] **`edge_tts.Communicate` is never instantiated for sensitive text.** The guard at L34 returns `False` before the `provider == "remote"` branch at L42. Even if a reviewer forgets the outer guard, the inner check at L43 provides a second defence.
- [ ] **Unknown providers fail safe** — `return False` at L65, not an exception that would bubble up as a 500 error.
- [ ] **Local provider unavailability does not fall back to remote.** Confirm `provider == "local"` branch (L57–L61) returns `False` unconditionally.

### 2.3 Call-site sensitivity detection

- [ ] **`is_sensitive_answer` is set to `True` when `tool_calls` or `data_sources_used` is non-empty.** Check `voice.py:L466–L468`.
- [ ] **`is_sensitive_answer` is also `True` when `classified_intent` is in `("crm", "support", "analytics", "multi_domain")`.** This covers cases where abstention was bypassed but the query is classified as data-related.
- [ ] **`metadata["tts_blocked_for_privacy"]` is set in the response** when synthesis is skipped for privacy reasons, so clients know why audio is absent.
- [ ] **`answer_url` is `""` when TTS is blocked.** Clients must not interpret a missing audio URL as an error.
- [ ] **Text answer is always returned** even when TTS is blocked. Confirm `answer_text` is populated in the `QueryResponse` regardless of TTS outcome.

### 2.4 TTS timeout handling

- [ ] **TTS is wrapped in `asyncio.wait_for` with `TTS_TIMEOUT_SECONDS`** in `_synthesize_and_verify()`. Confirm a `TimeoutError` is caught and re-raised as a `PipelineError(FailureType.TIMEOUT)`.
- [ ] **TTS failure is a degraded response, not a 500.** When TTS fails, the text answer is still returned. Check the `except Exception as tts_exc` block (L488–L493).

---

## Section 3 — Async Workload Isolation (P1)

### 3.1 Thread offloading correctness

- [ ] **All five blocking calls are offloaded.** Confirm `anyio.to_thread.run_sync()` wraps each of:
  1. `validate_and_load` (L272)
  2. `sf.write` (L282)
  3. `req_obfuscator.obfuscate` (L330–L332)
  4. `stt.transcribe_with_confidence` (L358–L360)
  5. `orchestrator.process_query` (L432–L434)
- [ ] **`sf.write` call signature is correct.** `anyio.to_thread.run_sync(sf.write, str(normalized_path), y, sr)` — positional args, not kwargs. Confirm `sf.write` accepts `(file, data, samplerate)` positionally.
- [ ] **No blocking I/O remains in the hot path between the thread calls.** Review the sections of `voice_query()` that run on the event loop between offloaded calls. File path construction, dict updates, and log calls are acceptable. `shutil.copyfileobj` (L264) for the initial upload save runs on the event loop — this is acceptable for the current development state but should be noted for production.

### 3.2 Concurrency semaphore

- [ ] **Semaphore is a module-level singleton.** `get_audio_semaphore()` uses a global `_audio_semaphore` variable. Confirm it is initialized lazily and reused across requests.
- [ ] **Semaphore is acquired before the pipeline `try` block.** The `async with sem:` wraps the entire `try: ... finally:` block, ensuring cleanup runs even if the semaphore is held.
- [ ] **`MAX_CONCURRENT_VOICE_REQUESTS` is a positive integer.** The config validator does not explicitly validate this field. Adding a `> 0` check to `_validate_and_sanitize` would be a low-cost improvement.
- [ ] **The semaphore does not prevent health checks from responding.** Health endpoints (`/health/live`, `/health/ready`) are not gated by the semaphore and should always respond.

### 3.3 Exception propagation

- [ ] **`PipelineError` raised in offloaded thread propagates to the caller.** Verified by `test_error_propagation_across_thread_boundary`. The `anyio` library unwraps and re-raises exceptions from worker threads.
- [ ] **The `finally:` cleanup block in `voice_query()` executes even if the thread raises.** Confirm that `created_files` cleanup in the `finally:` block (L516–L524) runs on any exception path.

---

## Section 4 — Observability and Metadata

- [ ] **`tts_blocked_for_privacy` is always present in `metadata`** when TTS is disabled or blocked. Clients relying on this field for UI feedback need it to be consistently set.
- [ ] **`abstention_decision` in metadata records one of:** `"EXECUTE"`, `"ABSTAIN"`, `"CLARIFY"`, `"DIRECT"`. Confirm no other values can appear.
- [ ] **`execution_prevented_by_abstention`** is set to `True` for ABSTAIN and CLARIFY, `False` for EXECUTE and DIRECT. Verify in each branch of `process_query()`.
- [ ] **Latency fields** (`abstention_latency_ms`, `routing_latency_ms`, `tool_latency_ms`) are always present in metadata (initialized to `0` in `_empty_metadata()` and updated if the relevant stage runs).

---

## Section 5 — Regression Risk Summary

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| New pragmatic patterns cause false-positive abstentions on operational queries | Low | Covered by `test_operational_control_queries_with_negative_words_remain_operational` and `test_clear_valid_operational_requests` |
| `CLARIFY` branch skips the LLM entirely | Intentional | Connectors are not called; clarification text is returned |
| `anyio.to_thread.run_sync(sf.write, ...)` passes wrong arg order | Low | Covered by `test_api_successful_end_to_end_mocked` which exercises the full pipeline |
| Semaphore deadlock if cleanup fails | Very low | `async with sem` exits on exception; `finally:` cleanup is independent |
| `tts_blocked_for_privacy` missing from response | Low | Set in two branches (success L483, skip L486); test verifies presence |

---

## Section 6 — Test Coverage Assessment

| Area | Test class | Coverage |
|------|-----------|---------|
| Valid operational routing | `TestSemanticExecutionSafety` | 5 queries confirmed EXECUTE |
| Distractor patterns | `TestSemanticExecutionSafety` | All 5 pragmatic markers tested |
| CLARIFY routing | `TestSemanticExecutionSafety` | 1 test |
| Fail-closed validation | `TestSemanticExecutionSafety` | 3 corrupted/invalid inputs |
| Zero connector invocation | `TestSemanticExecutionSafety` | ABSTAIN + CLARIFY branches |
| Tool name boundary | `TestSemanticExecutionSafety` | Invalid name rejected |
| Tool arg boundary | `TestSemanticExecutionSafety` | Bad enum rejected |
| Frozen dataset regression | `TestSemanticExecutionSafety` | 5 Phase 6.1 distractors |
| TTS disabled default | `TestTTSPrivacyBoundary` | Confirmed no synthesis |
| Sensitive data gate (remote) | `TestTTSPrivacyBoundary` | edge_tts never called |
| Non-sensitive remote synthesis | `TestTTSPrivacyBoundary` | Confirmed synthesis |
| Unknown provider | `TestTTSPrivacyBoundary` | Fails safe |
| Local provider no fallback | `TestTTSPrivacyBoundary` | No cloud fallback |
| API endpoint privacy flag | `TestTTSPrivacyBoundary` | `tts_blocked_for_privacy` verified |
| Event loop unblocked (STT) | `TestAsyncWorkloadIsolation` | 5 pings during 300ms block |
| Event loop unblocked (vocoder) | `TestAsyncWorkloadIsolation` | 4 ticks during 200ms block |
| Semaphore capacity | `TestAsyncWorkloadIsolation` | Matches config |
| Thread exception propagation | `TestAsyncWorkloadIsolation` | PipelineError propagated |

**Not covered by automated tests:**
- Live Whisper inference (only mocked)
- Live Ollama inference (only mocked)
- Multi-worker semaphore behaviour
- Physical edge-tts network transmission (intentionally not tested; verified by mock)

---

## Section 7 — Open Items for Phase 2

> [!NOTE]
> The following items were identified during Phase 1 but are explicitly out of scope. They are recorded here for Phase 2 planning.

1. **`MAX_CONCURRENT_VOICE_REQUESTS` config validator** — add `> 0` guard in `config.py:_validate_and_sanitize()`.
2. **`shutil.copyfileobj` on event loop** — the initial file save still blocks briefly. Move to thread for high-concurrency production deployments.
3. **Async Ollama client** — `ollama.Client().chat()` is a blocking synchronous call wrapped in a thread. Switching to an async HTTP client (e.g., `httpx.AsyncClient`) would remove the thread overhead.
4. **Pydantic V2 `model_config = ConfigDict(...)` migration** — `class Config` is deprecated; no behavior impact yet.
5. **FastAPI `lifespan` migration** — `@app.on_event("startup")` is deprecated; no behavior impact yet.
6. **`valid_tool_names` vs `connector_map` consistency check** — add an assertion at orchestrator init that `connector_map.keys() == valid_tool_names`.

---

*This checklist was generated for the Phase 1 Remediation of the Privacy-Preserving Voice Data Assistant. Implementation details are in `01_IMPLEMENTATION_AND_TEST_REPORT.md`. Baseline inspection is in `00_BASELINE_AND_PLAN.md`.*
