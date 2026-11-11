# Repository Stabilization, Evaluation Recovery, and E2E Smoke Test Report

**Date:** October 27, 2026  
**Repository:** `Privacy-Preserving-Voice-Data-Assistant`  
**Git Branch:** `main`  
**Base Commit:** `5b20a3aac193abf532ec479325c946a87dc4b15f`  
**Python Runtime:** Python 3.11.3 (Windows x86_64, `venv`)  
**Status:** Successfully Stabilized & Smoke Tested  

---

## 1. Executive Summary

Following a forensic audit that uncovered removed historical evaluation artifacts, untracked runtime modules, undeclared machine learning dependencies, and a concurrency race condition in voice obfuscation, this stabilization phase established a recoverable, reproducible foundation.

Key accomplishments:
1. **Safety Protocol Adherence:** All uncommitted changes were preserved; a complete standalone backup was placed in the external brain directory (`baseline_backup/`). Zero destructive commands (`git reset --hard`, `git clean -fd`) were executed.
2. **Selective Evaluation Recovery:** Recovered 48 historical files from commits `02aa494`, `5553b80`, and `d87f542`, including all frozen Phase 4.6 evaluation datasets (`dev_v1`, `validation_v1`, `challenge_v1`, `held_out_test_v1`), metric calculators, and the Phase 5/5.5 test suites. Obsolete ablation runners and broken mock frameworks were purposefully not restored.
3. **Cryptographic Dataset Integrity:** Verified all frozen datasets against `evaluation/datasets/manifest.json`. All 4 SHA256 hashes matched with 100% precision (including Windows CRLF handling for `held_out_test_v1.jsonl`).
4. **Untracked File Documentation:** Analyzed `app/voice/audio_store.py` (runtime TTL audio buffer) and undeclared dependencies (`torch`, `transformers` in virtual environment but missing from `requirements.txt`).
5. **Obfuscator Concurrency Isolation:** Resolved global mutable state in `app/routers/voice.py` where incoming requests mutated shared attributes (`base_shift`, `jitter`) on a singleton obfuscator. Each request now instantiates a clean, isolated `FormantPreservingObfuscator`.
6. **Abstention Enforcement Verification:** Verified that `app/services/llm_orchestrator.py` strictly prevents downstream tool invocation when `abstention_router.route()` yields `Decision.ABSTAIN`.
7. **End-to-End Real Audio Smoke Test:** Authored and verified `tests/test_e2e_smoke/test_smoke.py`, testing live audio query over HTTP (`Customers.mpeg`), abstention boundaries, and concurrent obfuscator isolation. Total test suite stands at **110 passing tests**.

---

## 2. Baseline Repository State & Preservation

### Initial State
- **Git Branch:** `main` at `5b20a3a` ("Initial commit")
- **Tracked Modifications (13 files):**
  - Application logic: `app/config.py`, `app/main.py`, `app/routers/voice.py`, `app/services/abstention_router.py`, `app/services/intent_router.py`, `app/services/llm_orchestrator.py`, `app/voice/obfuscator.py`.
  - Frontend: `app/voice_chat.html`, `voice_chat.html`.
  - Documentation/Config: `.env.example`, `README.md`.
  - Tests: `tests/test_api.py`.
  - Benchmark artifacts: `benchmark_audio/results.csv`, generated audio phrases (`phrase_*.wav`).
- **Untracked Files:**
  - `app/voice/audio_store.py`: In-memory temporary WAV storage with auto-cleanup TTL.
  - `eval_speaker_similarity.py`: Neural speaker verification script using `speechbrain` ECAPA-TDNN.
  - `benchmark_obfuscation.py`: Obfuscation benchmark harness.
  - `data/questions_and_answers.md`: Evaluation reference Q&A.
  - `docs/phase4_6_claim_audit.md`, `docs/phase5_claim_audit.md`: Historical claim audit logs.

### Preservation Actions
Prior to touching the working tree, an external backup was created:
- **Location:** `C:\Users\HP\.gemini\antigravity\brain\0c9cbc4d-34ea-4cd5-978a-63d5fcfc74bf\scratch\baseline_backup\`
- **Contents:** Full copies of all 13 modified files, all untracked files, and a unified diff `uncommitted_changes.diff` representing the exact uncommitted state.

---

## 3. Evaluation Infrastructure & Dataset Recovery

Historical commits `02aa494`, `5553b80`, and `d87f542` were inspected. Rather than performing a bulk restore that would introduce broken or dead dependencies, files were selectively recovered:

### Recovered Files
1. **Frozen Datasets (`evaluation/datasets/`):**
   - `manifest.json`
   - `dev_v1.jsonl` (SHA256: `1f881eed2fd710edca69755be15aee450f06b2b3798b12a76fd5f39b5ac3d4cb`)
   - `validation_v1.jsonl` (SHA256: `4844b091a30c09457ad45824e6a5ea9dfd4f4843dab7a1e816e099dc84aaa349`)
   - `challenge_v1.jsonl` (SHA256: `0ded94acbe7bd6e3c050990b3073d989e3ab0b30678c92a2b4b59dd727e0ab66`)
   - `held_out_test_v1.jsonl` (SHA256: `82efa536759a51819176d576aa168ad12c03be7ac0db3487985457791c9924f7`)
   - Phase 5 / 5.5 datasets: `phase5_synthetic_shift_dataset.jsonl`, `phase5_audio_cache_manifest.json`, `phase5_5_multimodal_failure_dataset.jsonl`, `phase5_5_synthetic_shift_dataset.jsonl`.
2. **Metrics & Scorers (`evaluation/metrics/`):**
   - `asr_wer.py` (Whisper Word Error Rate computation)
   - `acoustic_obfuscation.py` (F0 and spectral envelope perturbation)
   - `speaker_similarity.py` (Resemblyzer / ECAPA-TDNN distance)
   - `downstream_intent.py`
   - `reliability_matrix.py`
3. **Phase 5 & 5.5 Evaluators:**
   - `evaluation/phase5/` (Abstention distribution shift evaluator, synthetic generator, audit reporter)
   - `evaluation/phase5_5/` (Multimodal failure localization evaluator, synthetic shift generator)
4. **Historical Test Suites:**
   - `tests/test_phase5/test_distribution_shift.py`, `test_abstention_evaluation.py` (11 tests)
   - `tests/test_phase5_5/test_failure_localization.py` (14 tests)

### Intentionally Omitted Files
- `tests/test_phase4_6/test_evaluation_integrity.py`: Depended on dead Phase 3 connector fault-injection scaffolding (`evaluation.fault_injection.connectors`) and non-reproducible static result JSONs.
- `evaluation/run_final_experiment.py`, `evaluation/run_phase4_experiment.py`: Obsolete single-run mock scripts superseded by Phase 5 and Phase 5.5 pipelines.

### Cryptographic Hash Verification

| Dataset | Manifest Expected SHA256 | Computed SHA256 | Status |
| :--- | :--- | :--- | :--- |
| `dev_v1.jsonl` | `1f881eed2fd710edca69755be15aee450f06b2b3798b12a76fd5f39b5ac3d4cb` | `1f881eed2fd710edca69755be15aee450f06b2b3798b12a76fd5f39b5ac3d4cb` | **MATCH** |
| `validation_v1.jsonl` | `4844b091a30c09457ad45824e6a5ea9dfd4f4843dab7a1e816e099dc84aaa349` | `4844b091a30c09457ad45824e6a5ea9dfd4f4843dab7a1e816e099dc84aaa349` | **MATCH** |
| `challenge_v1.jsonl` | `0ded94acbe7bd6e3c050990b3073d989e3ab0b30678c92a2b4b59dd727e0ab66` | `0ded94acbe7bd6e3c050990b3073d989e3ab0b30678c92a2b4b59dd727e0ab66` | **MATCH** |
| `held_out_test_v1.jsonl` | `82efa536759a51819176d576aa168ad12c03be7ac0db3487985457791c9924f7` | `82efa536759a51819176d576aa168ad12c03be7ac0db3487985457791c9924f7` | **MATCH** |

*(Note: `held_out_test_v1.jsonl` was preserved with Windows CRLF line-endings matching the original Phase 4.6 creation environment).*

---

## 4. Codebase Fixes & Concurrency Hardening

### Issue: Mutable Global State on `FormantPreservingObfuscator`
In `app/routers/voice.py`, `obfuscator = FormantPreservingObfuscator(...)` was instantiated at module scope. During `/voice/query` and `/voice/process`, incoming request query parameters (`semitone_shift`, `jitter`) directly mutated the global instance:
```python
# Race Condition in previous implementation:
obfuscator.semitone_shift = semitone_shift
obfuscator.jitter = jitter
processed_path = obfuscator.obfuscate_file(saved_path)
```
Under concurrent requests, request B would overwrite the pitch shift and jitter of request A before request A completed `obfuscate_file()`.

### Resolution: Per-Request Obfuscator Instantiation
`app/routers/voice.py` was updated to construct a fresh, immutable-per-request obfuscator instance while retaining default fallbacks:
```python
base_shift = semitone_shift if semitone_shift is not None else settings.OBFUSCATION_SEMITONE_SHIFT
jitter_val = jitter if jitter is not None else settings.OBFUSCATION_JITTER

req_obfuscator = FormantPreservingObfuscator(
    semitone_shift=base_shift,
    jitter=jitter_val,
)
processed_path = req_obfuscator.obfuscate_file(saved_path)
```
Module-level `obfuscator` remains exposed for backward-compatibility with tests or external callers, but is no longer mutated by HTTP endpoints.

---

## 5. Architectural Verification: Abstention Enforcement Boundary

Inspection and regression testing of `app/services/llm_orchestrator.py` confirmed strict adherence to the abstention boundary:

1. **Audio Ingestion & Obfuscation:** Incoming audio is validated, stored via `AudioStore`, and obfuscated via `FormantPreservingObfuscator`.
2. **ASR:** Whisper transcribes the obfuscated audio to text.
3. **Abstention Gate:** In `LLMOrchestrator.execute_voice_pipeline()`, when `evaluate_abstention=True`, `abstention_router.route(transcript)` is evaluated prior to tool selection.
4. **Execution Boundary:**
   ```python
   if abs_res.decision == Decision.ABSTAIN:
       return {
           "status": "abstained",
           "message": abs_res.user_facing_message or "Request abstained due to ambiguity or out-of-domain scope.",
           "transcript": transcript,
           "abstention_result": abs_res.to_dict(),
           "tool_name": None,
           "tool_result": None,
           "audio_response_path": None,
       }
   ```
   If the decision is `ABSTAIN`, execution halts immediately. No tools, DB connectors, external APIs, or synthesis routines are executed.
5. **Baseline Mode:** When `evaluate_abstention=False`, the gate is bypassed for baseline comparison experiments.

---

## 6. End-to-End Smoke Test Suite

Created `tests/test_e2e_smoke/test_smoke.py` containing 4 deterministic test scenarios:

1. `test_live_voice_query_e2e_traceable_outcome`:
   - Posts `data/audio/Customers.mpeg` to `POST /voice/query`.
   - Executes real Whisper transcription, formant obfuscation, Ollama routing, and customer tool execution.
   - Asserts 200 OK response with populated transcript ("Customers"), tool result, non-empty response text, and generated audio response path.
2. `test_abstain_blocks_tool_execution`:
   - Mocks `AbstentionRouter.route` to return `Decision.ABSTAIN`.
   - Asserts `tool_name is None` and `tool_result is None`, verifying no side effects occurred.
3. `test_baseline_bypasses_abstention`:
   - Disables abstention (`evaluate_abstention=False`).
   - Asserts pipeline passes through to tool selection.
4. `test_concurrent_obfuscator_isolation`:
   - Spawns two concurrent threads with divergent semitone parameters (`+7.0` vs `-5.0`).
   - Verifies each request retains its isolated parameters without mutation bleed.

### Smoke Test Execution Result:
```text
tests/test_e2e_smoke/test_smoke.py::TestEndToEndRealAudioPipeline::test_live_voice_query_e2e_traceable_outcome PASSED [ 25%]
tests/test_e2e_smoke/test_smoke.py::TestAbstentionEnforcementBoundary::test_abstain_blocks_tool_execution PASSED [ 50%]
tests/test_e2e_smoke/test_smoke.py::TestAbstentionEnforcementBoundary::test_baseline_bypasses_abstention PASSED [ 75%]
tests/test_e2e_smoke/test_smoke.py::TestObfuscatorConcurrencySafety::test_concurrent_obfuscator_isolation PASSED [100%]
================== 4 passed in 120.41s ==================
```

---

## 7. Full Regression Test Results

Running the repository-wide test suite (`tests/`):
- **Core Unit & API Tests:** 81 passed
- **Phase 5 Distribution Shift & Abstention Tests:** 11 passed
- **Phase 5.5 Failure Localization Tests:** 14 passed
- **E2E Smoke Tests:** 4 passed
- **Total Passing Tests:** **110 passed** (0 failures, 13 benign deprecation warnings regarding Pydantic v2 Config and FastAPI `@app.on_event`).

---

## 8. Remaining Limitations & Non-Verified Items

1. **Undeclared Heavy Dependencies in `requirements.txt`:**
   `torch`, `transformers`, `torchaudio`, and `speechbrain` are present in the active virtual environment (`venv`) but are not pinned in `requirements.txt`. Clean checkouts in a fresh virtualenv will require updating `requirements.txt`.
2. **Untracked Production Audio Store:**
   `app/voice/audio_store.py` is necessary for the FastAPI app to run and serve temporary audio files. It is currently uncommitted and untracked.
3. **Biometric Privacy Caveat:**
   Acoustic obfuscation reliably shifts F0 and formants, but neural speaker-embedding distance drop (ECAPA-TDNN cosine similarity) is an empirical measure of voiceprint degradation, not an absolute cryptographic anonymity guarantee.
4. **Execution Time of Full Multimodal Evaluation:**
   Live Whisper STT and Ollama LLM execution took ~120s for 4 test cases on CPU. A full 500-sample Phase 5.5 multimodal evaluation will require substantial compute or batched cached inference.

---

## 9. Recommended Next Step

With the repository stabilized, concurrency hardened, frozen datasets verified, and the smoke test passing:
- **Proceed to Phase 5.5 Evaluation:** Formally execute the planned Phase 5.5 end-to-end multimodal reliability and abstention evaluation using the recovered `phase5_5` evaluators and cached audio datasets.
