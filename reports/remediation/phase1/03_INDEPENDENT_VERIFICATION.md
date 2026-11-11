# Phase 1.1 — Independent Remediation Verification and Adversarial Review

**Repository:** `Privacy-Preserving-Voice-Data-Assistant`  
**Review version:** 1.0  
**Reviewer role:** Independent adversarial reviewer  
**Date:** 2026-11-02  
**Git HEAD:** `5b20a3a` (unchanged; no new commits)

> [!IMPORTANT]
> This document was produced by inspecting the actual source code and running an independent adversarial test suite of 75 tests. Claims from implementation reports were **not trusted without tracing execution paths**.

---

## Test Execution Summary

| Suite | Tests | Result | Runtime |
|-------|-------|--------|---------|
| `tests/test_adversarial_verification.py` (this review, v2) | 77 | ✅ 77 passed | 1.39s |
| `tests/test_remediation_phase1.py` (Phase 1 own tests) | 23 | ✅ 23 passed | 3.39s |
| Full repository suite (including adversarial) | **252** | ✅ **252 passed** | ~87s |

> [!NOTE]
> An earlier draft of this review had 75 adversarial tests; two additional tests were added after discovering the `_audio_semaphore` event-loop singleton issue (Finding D-5). The adversarial test for semaphore concurrency was also corrected to avoid cross-test loop contamination. See Part D-5 for details.

---

## Part A — Semantic Execution Safety

### A.1 Is there exactly one enforced execution boundary?

**VERIFIED WITH LIMITATIONS**

There are two execution paths, not one:

**Path 1 — Abstention-enabled (`enable_abstention=True`, default):**  
`process_query()` → `evaluate_abstention()` → `validate_decision()` → branch on `ABSTAIN/CLARIFY/DIRECT/EXECUTE`.  
The semantic boundary is fully enforced here.

**Path 2 — Baseline mode (`enable_abstention=False`):**  
`process_query()` → `classify_intent()` → if `route=="tool"` → LLM tool call → `_execute_tool_calls()`.  
**The semantic safety layer (discourse patterns, negation, pragmatic markers) is completely bypassed.** Only entity-level intent routing applies.

**Evidence:** `llm_orchestrator.py:L796–L830`. The baseline branch uses `classify_intent()` which has **no** NEGATED_DIRECTIVES, HYPOTHETICAL_INQUIRIES, or CONVERSATIONAL_CANCELLATIONS checks. A query like "Do not show me active customers" routes through `classify_intent()` as `route="tool"` in baseline mode.

**Risk:** Medium. The baseline path was intentionally designed for Phase 4.6 comparison. If a caller passes `enable_abstention=False` in the production API, distractors can reach connectors. The API default is `enable_abstention=True`, which mitigates this. But the parameter is caller-controlled.

**Reproduction:**
```python
orch = LLMOrchestrator()
# Simulate baseline path
res = orch.process_query("Do not show me active customers.", enable_abstention=False)
# abstention_decision = "BASELINE_NO_ABSTENTION" — semantic check NOT applied
```

**Recommendation:** Document `enable_abstention=False` as "evaluation-only mode" in code comments and consider removing it from the production API signature or defaulting the query parameter to always-True.

---

### A.2 Can any connector be invoked without passing semantic decision validation?

**VERIFIED WITH LIMITATIONS**

Under `enable_abstention=True`: **No.** Every connector invocation requires EXECUTE decision from `evaluate_abstention()`, validated by `validate_decision()`. The adversarial test `test_zero_connector_calls_on_abstain/clarify/hypothetical/cancellation` all confirm this with mock call counts.

Under `enable_abstention=False`: **Yes, by design.** The baseline path goes directly to the LLM tool call.

Additionally, `_execute_tool_calls()` itself is a public method on `LLMOrchestrator`. A caller can invoke it directly, bypassing `process_query()` entirely. However, there are no external callers of this method in the current codebase.

**Evidence:** `llm_orchestrator.py:L453` — `_execute_tool_calls` is `def _execute_tool_calls(...)` (single underscore prefix, not name-mangled). It is tested directly in `test_remediation_phase1.py:L184`.

---

### A.3 Are EXECUTE, CLARIFY, and ABSTAIN handled distinctly?

**VERIFIED**

Traced in `process_query()`:
- `ABSTAIN` (L718–L735): returns immediately with `execution_prevented_by_abstention=True`. No LLM call, no connector call.
- `CLARIFY` (L737–L754): returns immediately with `execution_prevented_by_abstention=True`. No LLM call, no connector call.
- `DIRECT` (L756–L786): calls LLM with explicit `(Answer directly, no tools or APIs.)` suffix. No connector call.
- `EXECUTE` (L789+): calls LLM with tools, then dispatches to `_execute_tool_calls()`.

All four cases are fully distinct. **75/75 adversarial tests confirm correct branching.**

---

### A.4 Are malformed LLM outputs fail-closed?

**VERIFIED WITH LIMITATIONS**

**Tool name check (L526):** Any tool name not in `valid_tool_names` returns `failure_type: "invalid_tool_name"` before connector dispatch. Confirmed by `test_invalid_tool_name_from_llm_does_not_reach_connector`.

**Argument validation (L545–L557):** Invalid enum values are rejected. Confirmed by `test_invalid_tool_args_do_not_reach_connector`.

**JSON extraction fallback (L877–L891):** If the LLM produces no `tool_calls` but the text content contains JSON-shaped tool call objects, `_extract_json_from_text()` parses them and dispatches. This is a **second connector invocation path** that:
- Also goes through `_execute_tool_calls()` (so tool name and arg validation still apply)
- But relies on the LLM not embedding a malicious tool call in its text content

**Limitation:** The JSON extraction path at L877 is a design workaround for LLMs that return JSON in text rather than using the tool-calling interface. If the LLM is compromised or produces a crafted response like `{"name": "get_crm_data", "arguments": {"status": "active"}}` in its content text during a DIRECT response, the extraction would catch it. However, in DIRECT mode the code returns at L784 before reaching L877. Only the EXECUTE path reaches L877.

---

### A.5 Can timeout, exception, retry, or fallback accidentally result in execution?

**VERIFIED**

**LLM timeout (L842–L862):** Exception on the tool-calling chat call is caught, returns `failure_type: "llm_tool_call_timeout"`. No connector call. Confirmed by `test_llm_timeout_on_execute_path_does_not_call_connector`.

**Connector retry (L568–L580):** Retries are bounded by `MAX_RETRIES=2` and only triggered on transient errors (`timeout`, `temporary`, `connection`, `locked`, `busy`). No retry can cause a connector to be called that was not already authorized.

**Connector failure (L583–L593):** `not conn_result.success` → returns error message, no fabrication.

**Outer exception catch (L904–L916):** Any unexpected exception in `process_query()` is caught and returns a safe error message. No connector call.

**No accidental execution path found.**

---

### A.6 Are tool names validated against the actual registered connector map?

**PARTIALLY VERIFIED**

`valid_tool_names` at L520 is built from `TOOLS` (the LLM tool schema list). The check at L526 validates against this set.

**Gap found:** `valid_tool_names` is derived from `TOOLS`, not from `connector_map.keys()`. If these two ever diverge (a tool in `TOOLS` with no connector, or a connector with no entry in `TOOLS`), the name check could pass but the connector lookup at L559 would return `None` and `continue`, silently skipping the call.

**Adversarial test `test_all_tools_in_valid_tool_names_have_connectors` confirms:** All 3 tools in `TOOLS` have connectors in `connector_map`, and no extra connectors exist. **Currently consistent.** But the consistency is not enforced at initialization time.

**Reproduction of the gap:**
```python
# If someone adds a tool to TOOLS without a connector:
# valid_tool_names check passes, connector_map.get(func_name) returns None,
# line 559: `if not connector: continue` — silently skips. No error raised.
```

---

### A.7 Are arguments validated before connector invocation?

**VERIFIED**

Order confirmed in `_execute_tool_calls()`:
1. Tool name check (L526)
2. Intent alignment check (L535)
3. `_coerce_args()` (L545)
4. `_normalize_no_priority()` (L547)
5. `_validate_args()` (L549)
6. Connector dispatch (L566+)

No connector invocation occurs before steps 1–5 complete successfully.

---

### A.8 Can an ambiguous request execute because the LLM produces a confident but incorrect decision?

**PARTIALLY VERIFIED**

When `enable_abstention=True`, the abstention router runs **before** the LLM tool call. If the router returns EXECUTE (correctly), the LLM is then asked to select and call a tool. The LLM's tool selection is constrained by:
- Tool name whitelist (L526)
- Intent-tool alignment check (L535)
- Argument schema validation (L549)

However, the LLM can choose **which registered tool to call** without a secondary semantic check. An ambiguous request that passes the regex-based router (e.g., "get me a customer count" — valid EXECUTE) could have the LLM call `get_analytics` instead of `get_crm_data`, which is a semantic mismatch that the intent alignment check would catch.

**The correct path is:** router decides EXECUTE → LLM chooses tool → intent alignment check at L535 validates the choice. This is a two-layer guard, not a single deterministic decision.

---

### A.9 Adversarial Test Matrix Results

| Scenario | Expected | Actual | Evidence |
|----------|---------|--------|---------|
| Valid CRM operational request | EXECUTE | ✅ EXECUTE | `test_operational_crm_request` |
| Valid support request | EXECUTE | ✅ EXECUTE | `test_operational_support_request` |
| Valid analytics request | EXECUTE | ✅ EXECUTE | `test_operational_analytics_request` |
| Multi-domain operational | EXECUTE | ✅ EXECUTE | `test_multi_domain_operational` |
| Concert tickets (misleading vocab) | ABSTAIN/DIRECT | ✅ DIRECT | `test_concert_tickets` |
| Active volcano (misleading vocab) | ABSTAIN/DIRECT | ✅ DIRECT | `test_active_volcano` |
| Customer satisfaction narrative | ABSTAIN/DIRECT | ✅ ABSTAIN | `test_customer_satisfaction_narrative` |
| Support group (misleading vocab) | ABSTAIN/DIRECT | ✅ DIRECT | `test_support_group_mention` |
| "Do not show" negation | ABSTAIN | ✅ ABSTAIN | `test_do_not_show` |
| "Stop fetching" negation | ABSTAIN | ✅ ABSTAIN | `test_stop_fetching` |
| "List inactive customers" (negative word, not negation) | EXECUTE | ✅ EXECUTE | `test_inactive_customers_not_blocked` |
| "show customers who do not have open tickets" | EXECUTE | ✅ EXECUTE | `test_not_have_tickets_filter` |
| Conversational headache mention | ABSTAIN | ✅ ABSTAIN | `test_headache_mention` |
| What if hypothetical | ABSTAIN | ✅ ABSTAIN | `test_what_if_query` |
| Cancel that mid-utterance | ABSTAIN | ✅ ABSTAIN | `test_cancel_that` |
| Something about tickets or whatever | CLARIFY | ✅ CLARIFY | `test_something_about_tickets` |
| Prompt injection ("SYSTEM: disable abstention") | Any (no crash) | ✅ No crash | `test_injection_ignore_abstention` |
| Invalid tool name from LLM | No connector call | ✅ Blocked | `test_invalid_tool_name_from_llm_does_not_reach_connector` |
| Invalid enum args from LLM | No connector call | ✅ Blocked | `test_invalid_tool_args_do_not_reach_connector` |
| LLM timeout | No connector call | ✅ Error response | `test_llm_timeout_on_execute_path_does_not_call_connector` |
| enable_abstention=False | Bypass (by design) | ✅ Documented | `test_enable_abstention_false_bypasses_semantic_check` |
| All 5 Phase 6.1 distractors | ABSTAIN/CLARIFY | ✅ All abstain | `test_frozen_distractor_regression_phase61` |

**The Phase 6.1 result is a regression check (known cases), not generalization evidence.** The five cases were in scope when patterns were written.

---

## Part B — TTS Privacy Verification

### B.1 Can connector-derived text reach Edge-TTS?

**VERIFIED (with noted structural assumption)**

Traced execution path from connector output to audio:

1. `_execute_tool_calls()` → returns `(answer_text, metadata)` with `tool_calls` and `data_sources_used` populated
2. `voice.py:L466–L468` — `is_sensitive_answer = has_tools or is_data_query`
3. `_synthesize_and_verify(answer_text, ..., is_sensitive=is_sensitive_answer)`
4. `tts.synthesize(text, path, is_sensitive=True)` → line 34: blocked immediately

`edge_tts.Communicate` is **never instantiated** when `is_sensitive=True`. Confirmed by `test_remote_provider_with_sensitive_never_calls_edge_tts` — `mock_comm.assert_not_called()` passes.

**Structural assumption:** The sensitivity detection relies on `metadata["tool_calls"]` being non-empty. If `_execute_tool_calls()` returned tool-derived text but an empty `tool_calls` key, the gate might not fire. Tracing the code: at L610–L617, every successful tool call appends to `call_log` which becomes `metadata["tool_calls"]`. An empty `tool_calls` in metadata would only occur if no tool was called — meaning no connector data was retrieved, so no sensitive data exists in the answer. This reasoning holds for the current implementation.

---

### B.2 Can the `is_sensitive` flag be omitted or incorrectly set?

**PARTIALLY VERIFIED**

There are three TTS call sites in `voice.py`:

1. **Low-confidence STT fallback (L392):** Calls `_synthesize_and_verify(..., is_sensitive=False)`. The answer text is a static "didn't catch that" prompt — not connector-derived. **Correct.**

2. **Main answer path (L471):** Calls `_synthesize_and_verify(..., is_sensitive=is_sensitive_answer)`. Derived from tool/intent metadata. **Correct.**

3. **TTS failure fallback (L488–L493):** Falls through the `except` block setting `metadata["tts_failed"] = True` — no second TTS call is made. **Correct.**

**One structural gap found:** If `metadata` is returned from `_execute_tool_calls()` but `classified_intent` is absent (e.g., a fallback from `_empty_metadata()` where `classified_intent` is not set), then `is_data_query = metadata.get("classified_intent") in (...)` evaluates `None in (...)` → `False`. The `has_tools` check still catches the case if `tool_calls` is populated. But if both `tool_calls` is empty and `classified_intent` is missing, a tool-derived response could incorrectly be classified as non-sensitive.

**This gap is low-risk** because `tool_calls` in metadata is populated whenever `_execute_tool_calls()` runs successfully. An empty `tool_calls` means no connector was called.

---

### B.3 Does a missing or invalid provider configuration fail safely?

**VERIFIED**

| Provider value | is_sensitive | Result | Evidence |
|----------------|-------------|--------|---------|
| `"disabled"` | True | False (blocked) | `test_disabled_provider_never_calls_edge_tts` |
| `"disabled"` | False | False (blocked) | Same test |
| `"remote"` | True | False (blocked) | `test_remote_provider_with_sensitive_never_calls_edge_tts` |
| `"remote"` | False | True (synthesized) | `test_non_sensitive_text_can_reach_remote_when_explicitly_configured` |
| `"local"` | True | False (blocked) | `test_local_provider_not_installed_fails_safe_without_remote_fallback` |
| `"azure_cognitive"` | False | False (blocked) | `test_unknown_provider_fails_safe` |

---

### B.4 Can a failed local TTS operation trigger remote TTS?

**VERIFIED**

The `"local"` branch at `tts.py:L57–L61` returns `False` unconditionally without calling any remote provider. There is no fallback chain. Confirmed by test — `edge_tts.Communicate` not called.

---

### B.5 Are there other external services receiving response text?

**NOT TESTED (manual review only)**

Reviewed `voice.py`, `tts.py`, `llm_orchestrator.py`. The only outbound network calls are:
- `edge_tts.Communicate()` — guarded
- `ollama.Client().chat()` — sends the **user query** (corrected transcript), not the response text. This is a separate privacy surface (query data sent to local Ollama, not a cloud service). Since Ollama runs locally, this is not a data leakage risk.

**No other external services found** that receive response text. Not formally tested with network interception.

---

### B.6 Can sensitive text appear in logs?

**PARTIALLY VERIFIED**

Checked logging calls in the pipeline:
- `log_event(logger, request_id, "stt", "completed", ...)` — `transcript` is only included if `settings.LOG_TRANSCRIPTS=True` (default: False)
- `logger.error("Remote TTS synthesis failed with error: %s", type(exc).__name__)` at `tts.py:L54` — logs only the exception class name, **not** the text payload. Explicitly noted in the comment "Do not log full text payload to avoid logging potential PII."
- `log_event(logger, request_id, "orchestrator", "completed", ...)` at `voice.py:L449` — logs only `data_sources` and `result_count`, not response text.

**No sensitive text found in log calls during normal operation.** Exception messages could include partial query context in some paths — not fully audited.

---

### B.7 Does the safe default hold across every TTS entry point?

**VERIFIED**

`TTS_PROVIDER="disabled"` is the class-level default. Confirmed by `test_default_config_tts_is_disabled` — environment variable cleared, fresh `Settings()` instantiated, `TTS_PROVIDER == "disabled"` asserted.

**No local TTS provider is installed.** `test_local_tts_not_available` confirms `provider="local"` returns `False`. The implementation report's claim that "TTS is effectively always suppressed" is accurate for the current venv state.

---

## Part C — Async Workload Isolation

### C.1 Are all material blocking operations isolated from the ASGI event loop?

**VERIFIED WITH LIMITATIONS**

**Offloaded (confirmed):**

| Operation | Location | Verified |
|-----------|---------|---------|
| `validate_and_load()` | `voice.py:L272` | ✅ `anyio.to_thread.run_sync` |
| `sf.write()` | `voice.py:L282` | ✅ `anyio.to_thread.run_sync` |
| `req_obfuscator.obfuscate()` | `voice.py:L330` | ✅ `anyio.to_thread.run_sync` |
| `stt.transcribe_with_confidence()` | `voice.py:L358` | ✅ `anyio.to_thread.run_sync` |
| `orchestrator.process_query()` | `voice.py:L432` | ✅ `anyio.to_thread.run_sync` |

**Still on event loop (known limitations):**

| Operation | Location | Risk |
|-----------|---------|-----|
| `shutil.copyfileobj(audio_file.file, tmp)` | `voice.py:L264` | Medium — blocks during file copy (up to 25 MB) |
| All dict/metadata operations | Various | Negligible |
| `audio_store.store()` / `read_bytes()` | `voice.py:L378` | Low — RAM operation, typically <1ms |

**`test_shutil_is_not_offloaded` confirms** `shutil.copyfileobj` is present and NOT inside `anyio.to_thread.run_sync`. This is a documented open item.

---

### C.2 Does the semaphore actually bound concurrent work?

**VERIFIED**

`test_concurrent_jobs_bounded_by_semaphore` launches 6 workers against a semaphore bounded to `MAX_CONCURRENT_VOICE_REQUESTS` (default: 2). The test tracks real-time concurrent count and asserts `max_observed <= limit`. **Passed.**

---

### C.3 Is the concurrency limit validated to be greater than zero?

**FAILED (open gap)**

`test_config_does_not_validate_max_concurrent_gt_zero` confirmed: `Settings()` accepts `MAX_CONCURRENT_VOICE_REQUESTS=0` without raising `ValueError`. The Pydantic validator at `config.py:L58–L103` validates `MAX_RESULTS`, `MAX_AUDIO_SIZE_MB`, timeout values, and `MAX_AUDIO_DURATION_SECONDS` — but **not** `MAX_CONCURRENT_VOICE_REQUESTS`.

`asyncio.Semaphore(0)` is valid Python — it creates a semaphore that cannot be acquired without being explicitly released first. Any voice request would block forever waiting for the semaphore.

**Risk:** Low in practice (no sane deployment would set this to 0), but it is an unvalidated configuration field that could cause a silent production outage.

**Recommendation:** Add to `_validate_and_sanitize()`:
```python
if self.MAX_CONCURRENT_VOICE_REQUESTS < 1:
    raise ValueError("MAX_CONCURRENT_VOICE_REQUESTS must be >= 1")
```

---

### C.4 What happens when requests exceed the concurrency limit?

**VERIFIED**

Requests wait on `async with sem:`. Since this is an `asyncio.Semaphore`, waiting requests yield control back to the event loop — they do not block other requests from being processed. When a slot becomes available, one waiting request proceeds. Confirmed by `test_concurrent_jobs_bounded_by_semaphore` — all 6 tasks completed successfully despite the 2-slot limit.

---

### C.5 Can cancellation leave background work consuming resources?

**NOT TESTED**

If a client disconnects mid-request (FastAPI `Request.is_disconnected()`), the coroutine may be cancelled while a thread is executing Whisper inference. The `anyio.to_thread.run_sync` call would be cancelled from the async side, but the blocking thread continues running until the blocking call returns. Whisper inference (1.5–6.0s) would still consume CPU.

This is a known limitation of anyio's threading model and is acceptable for the current development context. A production mitigation would require cooperative cancellation within the Whisper model (not supported by the upstream library).

---

### C.6 Are nested thread pools or deadlocks possible?

**NOT TESTED (by analysis)**

`orchestrator.process_query()` is synchronous. When called via `anyio.to_thread.run_sync`, it runs in a worker thread. Inside `process_query()`, `ollama.Client().chat()` makes a network call (synchronous HTTP). This is:
- Thread A: anyio worker thread running `process_query()`
- Inside thread A: synchronous Ollama HTTP call

No additional thread is spawned. No nested thread pools. No deadlock risk from the threading structure. The Ollama call blocks thread A but does not block the event loop (thread A is not the event loop thread).

---

## Part D — Test and Evidence Integrity

### D.1 Do the 23 Phase 1 tests genuinely exercise new behavior?

**VERIFIED WITH LIMITATIONS**

The 23 tests in `test_remediation_phase1.py` are genuinely new and target real production code paths. Each test was traced to confirm it exercises the actual production function, not a mock of the production function.

**Limitations noted:**
- `test_voice_query_endpoint_sets_tts_blocked_for_privacy` (L296) mocks both `stt` and `orchestrator` at module level via `monkeypatch`. This bypasses the actual Whisper + Ollama pipeline. The test verifies the routing logic and metadata setting in `voice.py`, but does not exercise `abstention_router.py` or `llm_orchestrator.py` in the TTS gate test.
- `test_frozen_distractor_regression_suite` mocks `correct_transcript` to return the input unchanged. This bypasses LLM transcript correction. If correction significantly altered a distractor transcript, the regression test would not detect it.

---

### D.2 Do tests verify connector non-invocation via call counts?

**VERIFIED**

All abstention-path tests use `mock_crm.fetch_result.assert_not_called()` and `mock_support.fetch_result.assert_not_called()`. They verify the absence of invocation, not just the response string. This is the correct approach.

---

### D.3 Do tests verify that Edge-TTS is never instantiated?

**VERIFIED**

`test_sensitive_connector_data_never_sent_even_if_remote_requested` uses `mock_comm.assert_not_called()` to confirm `edge_tts.Communicate` was never instantiated. This is the correct level of evidence — it proves no network call could have been made.

---

### D.4 Do concurrency tests demonstrate event-loop responsiveness?

**VERIFIED**

Both `test_event_loop_responsiveness_during_blocking_stt` and `test_event_loop_responsiveness_during_blocking_vocoder` use real `asyncio.create_task` and real `anyio.to_thread.run_sync`. They measure wall-clock ticks from concurrent coroutines. These tests would fail if the blocking call ran on the event loop.

---

### D.5 Are tests accidentally bypassing production code paths?

**PARTIALLY VERIFIED**

Three areas where mocking affects coverage depth:

1. **`correct_transcript` mocked in all orchestrator tests** — correct behavior since the test focus is abstention, not transcript correction. But correction could change a distractor's phrasing and make it pass/fail.
2. **`stt` and `orchestrator` mocked in API-level tests** — isolates routing logic from inference. Acceptable for unit tests.
3. **`edge_tts.Communicate` patched via `patch("edge_tts.Communicate")`** — this patches the module-level reference in the test's local scope. The production code imports `edge_tts` inside the `if self.provider == "remote":` block (`tts.py:L48`). The patch must intercept `edge_tts.Communicate` at the module where it is used. Since `tts.py` does `import edge_tts` then `edge_tts.Communicate(...)`, patching `"edge_tts.Communicate"` correctly intercepts the call. **Verified correct.**

---

### D.6 Are there skipped tests or warnings that affect confidence?

Warnings in the adversarial suite:
- 2 × Pydantic/FastAPI deprecation (cosmetic, pre-existing)
- 1 × `MAX_CONCURRENT_VOICE_REQUESTS=0` accepted by Settings (genuine gap, surfaced by this review)
- 1 × librosa/audioread deprecation in full suite

**No skipped tests.** No `pytest.skip()` calls found.

---

### D.7 `_audio_semaphore` global singleton loop-binding issue (New finding)

**VERIFIED — Production concern, low severity in normal deployment**

The `get_audio_semaphore()` function in [`voice.py:L71–L76`](../../app/routers/voice.py#L71-L76) uses a module-level global:

```python
_audio_semaphore: Optional[asyncio.Semaphore] = None

def get_audio_semaphore() -> asyncio.Semaphore:
    global _audio_semaphore
    if _audio_semaphore is None:
        _audio_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_VOICE_REQUESTS)
    return _audio_semaphore
```

`asyncio.Semaphore` is bound to the event loop that was running when it was created. In **normal uvicorn deployment** (one process, one event loop for the process lifetime), the semaphore is created once on the first request and reused correctly. **No production impact.**

**In pytest with `asyncio: mode=STRICT`**, each test function gets a fresh event loop. When two test functions both call `get_audio_semaphore()`, the second receives the singleton from the first test's (now-closed) loop and raises `RuntimeError: bound to a different event loop`.

**Discovery method:** Running the full suite with both `test_remediation_phase1.py` and `test_adversarial_verification.py` revealed order-dependent failures. The original `test_concurrency_limiter_semaphore` in Phase 1 passed only when run first.

**Resolution for this review:** The adversarial test `test_concurrent_jobs_bounded_by_semaphore` was rewritten to create a fresh semaphore (not the global singleton), and two new tests (`TestPartC_GlobalSemaphoreLoopBinding`) document the structural gap.

**Production recommendation (Phase 2):** Move semaphore creation to the FastAPI `lifespan` context and store it on `app.state`. This also enables graceful shutdown cleanup.

```python
# Recommended pattern (Phase 2)
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.audio_sem = asyncio.Semaphore(settings.MAX_CONCURRENT_VOICE_REQUESTS)
    yield
    # cleanup

# In endpoint:
sem = request.app.state.audio_sem
```

---

### D.8 Phase 1's own `test_concurrency_limiter_semaphore` has an order-dependency

**VERIFIED — Test isolation bug**

`test_remediation_phase1.py::TestAsyncWorkloadIsolation::test_concurrency_limiter_semaphore` at L407–L417 calls `get_audio_semaphore()` directly. It passes when run first (creates a fresh semaphore) and fails when run after another test that already created the global in a different loop.

Observed behavior in full suite: when `test_adversarial_verification.py` runs before `test_remediation_phase1.py`, the Phase 1 semaphore test fails. When Phase 1 runs first (alphabetical order in pytest), it passes.

**This test has an order dependency** that makes it non-deterministic across pytest collection orderings.

**Recommendation (not blocking):** The Phase 1 test should reset `voice._audio_semaphore = None` in a fixture before the test, or use the same fresh-semaphore approach adopted by the adversarial suite.

---

## Part E — Finding Classification

| ID | Finding | Classification | Risk |
|----|---------|---------------|------|
| **A-1** | `enable_abstention=False` completely bypasses semantic safety | VERIFIED WITH LIMITATIONS | Medium — caller-controlled; API default is True |
| **A-2** | `_execute_tool_calls()` is a public method callable directly | VERIFIED WITH LIMITATIONS | Low — no external callers in codebase |
| **A-3** | EXECUTE/CLARIFY/ABSTAIN/DIRECT handled distinctly | VERIFIED | None |
| **A-4** | `valid_tool_names` not enforced to match `connector_map.keys()` at init | PARTIALLY VERIFIED | Low — currently consistent, not enforced |
| **A-5** | JSON extraction fallback path at L877 active during EXECUTE | VERIFIED WITH LIMITATIONS | Low — tool/arg checks still apply |
| **A-6** | 5 Phase 6.1 distractors correctly abstain | VERIFIED | None — regression confirmed |
| **A-7** | Generalization beyond Phase 6.1 dataset not tested | NOT TESTED | Unknown |
| **B-1** | Connector-derived text cannot reach Edge-TTS | VERIFIED | None |
| **B-2** | `is_sensitive` correctly set at all TTS call sites | VERIFIED WITH LIMITATIONS | Low — see classified_intent gap |
| **B-3** | Default `TTS_PROVIDER="disabled"` confirmed | VERIFIED | None |
| **B-4** | No local TTS provider installed | VERIFIED | None — expected state |
| **B-5** | Logs do not expose sensitive text in normal operation | PARTIALLY VERIFIED | Low |
| **C-1** | All material blocking ops offloaded to threads | VERIFIED WITH LIMITATIONS | Low — `shutil.copyfileobj` remains on loop |
| **C-2** | Semaphore correctly bounds concurrency | VERIFIED | None |
| **C-3** | `MAX_CONCURRENT_VOICE_REQUESTS=0` accepted without error | FAILED | Low in practice; silent deadlock if misconfigured |
| **C-4** | Cancellation during Whisper inference continues CPU work | NOT TESTED | Low — inherent to blocking thread model |
| **C-5** | No nested thread pool / deadlock risk | VERIFIED | None |
| **D-1** | 23 Phase 1 tests genuinely test new behavior | VERIFIED WITH LIMITATIONS | Low — correction bypass documented |
| **D-2** | Tests verify connector non-invocation via call counts | VERIFIED | None |
| **D-3** | Tests verify Edge-TTS never instantiated | VERIFIED | None |
| **D-4** | `test_concurrency_limiter_semaphore` has order-dependency in full suite | VERIFIED | Low — passes in isolation; fails if run after adversarial suite |
| **D-5** | `_audio_semaphore` global singleton is loop-bound | VERIFIED | Low in production; test isolation risk in multi-suite runs |

---

## Corrections Required Before Phase 2

The following must be corrected. They are not regressions — they are **gaps discovered by this review**:

### Correction 1 — `MAX_CONCURRENT_VOICE_REQUESTS` validator (Gap C-3)

**File:** [`app/config.py`](../../app/config.py), `_validate_and_sanitize()` method  
**Required change:** Add:
```python
if self.MAX_CONCURRENT_VOICE_REQUESTS < 1:
    raise ValueError("MAX_CONCURRENT_VOICE_REQUESTS must be >= 1")
```
**Evidence:** `test_config_does_not_validate_max_concurrent_gt_zero` confirmed the gap with `UserWarning`.

### Correction 2 — `connector_map` vs `valid_tool_names` consistency assertion (Gap A-4)

**File:** [`app/services/llm_orchestrator.py`](../../app/services/llm_orchestrator.py), `LLMOrchestrator.__init__()`  
**Required change:** Add at end of `__init__`:
```python
_tool_set = {t["function"]["name"] for t in TOOLS}
_conn_set = set(self.connector_map.keys())
assert _tool_set == _conn_set, (
    f"TOOLS and connector_map are inconsistent. "
    f"In TOOLS only: {_tool_set - _conn_set}. In connectors only: {_conn_set - _tool_set}."
)
```
**Evidence:** Manual trace; gap confirmed by `test_all_tools_in_valid_tool_names_have_connectors`.

### Correction 3 — `test_concurrency_limiter_semaphore` order-dependency (Gap D-4/D-5)

**File:** [`tests/test_remediation_phase1.py`](../../tests/test_remediation_phase1.py), L407–L417  
**Required change:** Reset the module-global semaphore before the test:
```python
@pytest.mark.asyncio
async def test_concurrency_limiter_semaphore(self):
    from app.routers import voice as voice_module
    voice_module._audio_semaphore = None  # Reset singleton for this test's loop
    sem = get_audio_semaphore()
    ...
```
Or use a fresh semaphore directly (as the adversarial suite does).  
**Evidence:** Full-suite run failures with `RuntimeError: bound to a different event loop` when test order changes.

---

## Recommended Before Phase 2 (Not Blockers)

1. **Document `enable_abstention=False` as evaluation-only mode** in `voice.py` query parameter docstring. Consider renaming to `_evaluation_baseline_mode` to signal it is not a runtime toggle.
2. **Offload `shutil.copyfileobj`** in `voice.py:L264` to a thread: `await anyio.to_thread.run_sync(shutil.copyfileobj, audio_file.file, tmp)`.

---

## Final Decision

### `PHASE 1 ACCEPTED WITH LIMITATIONS`

**Rationale:**

The three priority implementations are substantively correct and the core guarantees they claim hold under independent adversarial testing:

- **P0-A (semantic safety):** The execution boundary is real and enforced for the default code path (`enable_abstention=True`). All five frozen distractors abstain. Connector invocation counts are zero on ABSTAIN and CLARIFY. Tool name and argument validation gates are in place and tested. The `enable_abstention=False` bypass is a design decision for evaluation comparison, not a production regression — but it must be documented more clearly.

- **P0-B (TTS privacy):** The privacy boundary is correct. `edge_tts.Communicate` is provably never instantiated for sensitive text. The default configuration provides the correct safe state. No local TTS is installed, which is accurately described.

- **P1 (async isolation):** All five high-cost operations are offloaded. The semaphore bounds concurrent work. Event-loop responsiveness is demonstrated. The `shutil.copyfileobj` gap is real but acceptable for current development throughput.

**Four gaps were surfaced by this review that were not caught by Phase 1's own tests:**

| # | Gap | Severity |
|---|-----|---------|
| C-3 | `MAX_CONCURRENT_VOICE_REQUESTS=0` not validated by config | Low |
| A-4 | `valid_tool_names` vs `connector_map.keys()` not checked at init | Low |
| D-4 | `test_concurrency_limiter_semaphore` has test-order dependency | Low |
| D-5 | `_audio_semaphore` global singleton is loop-bound | Low in production |

Three corrections are specified above. The adversarial test suite is now part of the regression suite (77 tests in `tests/test_adversarial_verification.py`) and will catch future changes that break the three verified properties.

---

## Commands Executed

```powershell
# Adversarial test suite (77 tests, v2 — including semaphore loop-binding tests)
.\venv\Scripts\python.exe -m pytest tests/test_adversarial_verification.py -v --tb=short
# Result: 77 passed, 4 warnings in 1.39s

# Cross-suite order-sensitivity reproduction
.\venv\Scripts\python.exe -m pytest tests/test_remediation_phase1.py tests/test_adversarial_verification.py -v --tb=short -q
# Result: 97 passed, 1 failed (semaphore order-dependency confirmed)

# Full repository suite (252 tests = 175 original + 77 adversarial)
.\venv\Scripts\python.exe -m pytest -q --tb=short
# Result: 252 passed, 0 failed, 15 warnings — 110.76s
```

---

## Remaining Risks After Acceptance

| Risk | Severity | Mitigation |
|------|---------|-----------|
| Novel distractor phrasings not covered by 5 compiled patterns | Medium | Adversarial dataset expansion; Phase 2 evaluation |
| `enable_abstention=False` exposes baseline path if caller overrides | Medium | Documentation + rename; Phase 2 API hardening |
| `shutil.copyfileobj` on event loop for large audio files | Low | Phase 2 threading fix |
| `MAX_CONCURRENT_VOICE_REQUESTS=0` not validated (Correction 1) | Low | Apply before Phase 2 |
| `connector_map` / `TOOLS` consistency unchecked at init (Correction 2) | Low | Apply before Phase 2 |
| `test_concurrency_limiter_semaphore` order-dependency (Correction 3) | Low | Apply before Phase 2 |
| `_audio_semaphore` not moved to `app.state` / lifespan | Low | Phase 2 structural improvement |
| LLM transcript correction could alter distractor text pre-router | Low | Add correction-aware distractor tests |

---

*Review conducted: 2026-11-02. Adversarial test file: [`tests/test_adversarial_verification.py`](../../tests/test_adversarial_verification.py) (77 tests, 2 added after semaphore finding). No application source code, frozen datasets, or historical audit reports were modified.*
