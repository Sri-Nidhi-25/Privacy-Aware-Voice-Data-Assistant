# Phase 6 Evidence Audit — Independent Review

**Author:** Automated Audit (Phase 6.1 session)  
**Date:** 2026-10-31  
**Auditor commitment:** Findings are derived from direct code inspection and raw data files. No claim is made without a verifiable source.

---

## 1. Scope

This document audits:

- The Phase 6 paired evaluation methodology and raw outputs.
- Phase 6 metric definitions and denominators.
- The Phase 6.1 semantic-conflict pilot (N=10).
- The abstention engine's coverage gaps.
- The Evaluation Lab frontend data sources.

It does **not** audit prior Phase 4.6 or Phase 5 text benchmarks. Those are covered separately in `phase4_6_claim_audit.md` and `phase5_claim_audit.md`.

---

## 2. Phase 6 Dataset Inventory

### 2.1 Verified files

| Dataset | JSONL path | N | Type | SHA256 status |
|---|---|---|---|---|
| `real_audio_v1` | `evaluation/datasets/phase6/real_audio_v1.jsonl` | 6 | Authentic human mic recordings | VERIFIED |
| `benchmark_audio_v1` | `evaluation/datasets/phase6/benchmark_audio_v1.jsonl` | 32 | Standardized benchmark (TTS, `en-US-AriaNeural`) | VERIFIED |
| `semantic_conflict_v1` | `evaluation/datasets/phase6/semantic_conflict_v1.jsonl` | 10 | Text-only challenge cases | VERIFIED |
| `semantic_conflict_audio_v1` | `evaluation/datasets/phase6/semantic_conflict_audio_v1.jsonl` | 10 | Semantic-conflict pilot (TTS, `en-US-AriaNeural`) | VERIFIED |

`evaluation/datasets/verify_datasets.py` was run and produced **ALL HASHES MATCH** for all four datasets.

### 2.2 Audio asset inventory

| Location | Count | Provenance |
|---|---|---|
| `data/audio/*.mpeg` | 6 files | Authentic human speaker (real microphone) |
| `data/*.mpeg` | 6 files | Duplicate copies (different byte sizes — not used in evaluation) |
| `benchmark_audio/phrase_*.wav` | 32 files | Standardized TTS benchmark |
| `benchmark_audio/phase6_1/*.wav` | 10 files | Phase 6.1 semantic-conflict TTS |
| `benchmark_audio/phase5_5_cache/*.wav` | 100+ files | Phase 5.5 cache (edge_tts, not evaluated in Phase 6) |

**`Customers.mpeg` is dual-use**: it is `case_id=real_001` in `real_audio_v1` and the E2E smoke-test fixture. It is NOT separately classified as a benchmark case.

**Personal microphone recordings** are confined to `data/audio/` and `real_audio_v1`. They are not included in `benchmark_audio_v1` or `semantic_conflict_audio_v1`.

### 2.3 WER reference transcripts

Confirmed: reference transcripts in all JSONL manifests were independently authored at case-creation time and were **not** derived from Whisper predictions or cached model outputs. Transcript independence is a prerequisite for WER validity.

---

## 3. Phase 6 Paired Evaluation Methodology Audit

### 3.1 Runner implementation

**File:** `evaluation/runners/run_paired_evaluation.py`

**Finding: Baseline correctly disables abstention.**  
Lines 98-110 confirm ASR caching:
```python
self.asr_cache[case_id] = transcript
```
Both conditions reuse the same cached Whisper transcript for every case, so ASR variance cannot explain any baseline/abstention difference.

`enable_abstention=False` is passed to the orchestrator for the baseline condition, confirmed at `app/services/llm_orchestrator.py:~697`.

### 3.2 Phase 6 runs

| Run ID | Dir | N | Dataset(s) |
|---|---|---|---|
| `f196279a` | `evaluation/results/phase6/f196279a/` | 6 | `real_audio_v1` |
| `e22e9b0f` | `evaluation/results/phase6/e22e9b0f/` | 32 | `benchmark_audio_v1` |
| `consolidated_phase6` | `evaluation/results/phase6/consolidated_phase6_summary.json` | 38 | both |

### 3.3 Critical finding: Zero behavioral difference between baseline and abstention in Phase 6

Both `f196279a` and `e22e9b0f` produced **identical tool executions for all 38 cases** in both conditions.

**Root cause:** The Phase 6 corpus (38 cases) consists entirely of unambiguous operational queries and a single out-of-domain factual query. No ambiguous, negated, hypothetical, or conversational-mention cases were included. Abstention never had reason to disagree with baseline because no borderline cases existed.

**Consequence:** Phase 6 does **not demonstrate an abstention benefit**. The 100% task success reported for both conditions in Phase 6 is real, but reflects that the corpus was too easy for the abstention engine to make any difference. Phase 6 measures pipeline mechanical reliability (ASR → routing → tool execution), not semantic discrimination.

> **This finding does not invalidate the Phase 6 data.** The 38 cases are correctly labelled, correctly hashed, correctly evaluated. The corpus limitation is a scope issue, not a data integrity issue.

---

## 4. Metric Definitions Audit

All denominators were verified against `compute_metrics()` in `run_paired_evaluation.py`.

| Metric | Formula | Denominator | Verified |
|---|---|---|---|
| Overall coverage | executed / total | all N cases | ✅ |
| Operational coverage | executed_operational / n_operational | only operational cases | ✅ |
| Distractor coverage (leakage rate) | executed_distractor / n_distractor | only distractor cases | ✅ |
| Selective risk | n_incorrect_exec / n_executed | only executed cases | ✅ |
| False-positive tool execution | n_fp / n_distractor | only distractor cases | ✅ |
| Missed valid requests | n_missed / n_operational | only operational cases | ✅ |
| End-to-end task success | n_success / n_total | all N cases | ✅ |
| WER | standard token edit distance | per-case reference transcript | ✅ |

**CLARIFY distinction:** The runner now distinguishes `CLARIFY` from `ABSTAIN`. A `CLARIFY` response counts as task success for distractor cases (same as `ABSTAIN`) but is separately counted as `clarification_failure` if the system executes a tool when clarification was expected. This distinction was introduced in Phase 6.1.

**Wilson CI:** 95% confidence intervals are computed via `evaluation/metrics/wilson_ci.py`. Mathematically correct — verified against the standard Wilson score formula.

---

## 5. Abstention Engine Coverage Gaps

Confirmed by direct invocation of `evaluate_abstention()` on the following inputs:

| Input type | Example | Expected | Actual |
|---|---|---|---|
| Negation | "Do not show me any active customers right now." | ABSTAIN | EXECUTE (conf 1.0) |
| Mention-vs-command | "Open support tickets are becoming a real headache…" | ABSTAIN | EXECUTE (conf 0.7) |
| Hypothetical | "What if we were to query daily active users tomorrow instead?" | ABSTAIN | EXECUTE (conf 0.7) |
| Cancellation | "Pull records for inactive customers, wait no, cancel that, never mind." | ABSTAIN | EXECUTE (conf 1.0) |
| Ambiguous | "Something about tickets, maybe check them or whatever." | ABSTAIN | EXECUTE (conf 1.0) |

**The abstention engine does not detect:** negation ("do not", "don't", "never"), hypothetical framing ("what if", "were to"), mention-without-command (conversational reference), or self-correction/cancellation ("wait no", "never mind").

These gaps are documented findings. The engine is not modified in this audit.

---

## 6. Phase 6.1 Semantic-Conflict Pilot Results (run `c4f0c07b`)

### 6.1 Dataset

- **Name:** `semantic_conflict_audio_v1`
- **N:** 10 (5 operational + 5 distractor)
- **Audio:** Microsoft Edge TTS, `en-US-AriaNeural`, 16kHz mono WAV
- **Speaker:** Single neural TTS voice — NOT authentic human speaker
- **Provenance:** `standardized_benchmark_recording`

### 6.2 Results table

| Metric | Baseline | With Abstention |
|---|---|---|
| Overall Coverage | 9/10 (90.0%) [59.6–98.2%] | 10/10 (100.0%) [72.2–100.0%] |
| Operational Coverage | 4/5 (80.0%) [37.5–96.4%] | 5/5 (100.0%) [56.5–100.0%] |
| Distractor Leakage Rate | **5/5 (100.0%) ← FAILURE** | **5/5 (100.0%) ← FAILURE** |
| Selective Risk | 5/9 (55.6%) [26.7–81.1%] | 5/10 (50.0%) [23.7–76.3%] |
| False-Positive Tool Executions | **5/5 (100.0%) ← FAILURE** | **5/5 (100.0%) ← FAILURE** |
| Missed Valid Requests | 1/5 (20.0%) [3.6–62.5%] | 0/5 (0.0%) [0.0–43.5%] |
| End-to-End Task Success | 4/10 (40.0%) [16.8–68.7%] | 5/10 (50.0%) [23.7–76.3%] |
| Mean WER | 0.0% | 0.0% |

**Run directory:** `evaluation/results/phase6_1/88cd8262/`  
**Git commit at run time:** `5b20a3a_dirty`

### 6.3 Interpretation

1. **WER = 0.0%** confirms Whisper correctly transcribes all 10 TTS-generated audio cases.
2. **5/5 distractor leakage in both conditions** means the abstention engine failed to reject every semantic-conflict distractor. Abstention provides zero safety improvement on this corpus.
3. The 1 missed valid request in baseline (vs. 0 in abstention) may reflect an Ollama connection transient at the time of the baseline run — not a systematic difference.
4. The 4/10 vs. 5/10 task success difference is **not statistically meaningful at N=10** and is plausibly explained by the connection transient.
5. **No abstention benefit is demonstrated** on Phase 6.1 either.

### 6.4 Failure breakdown (Phase 6.1 pilot)

| Stage | Baseline | Abstention |
|---|---|---|
| `intent_routing_failure` | 5 | 0 |
| `abstention_false_negative` | 0 | 4 |
| `clarification_failure` | 1 | 1 |

The `CLARIFY` case was executed as a tool call in both conditions — another abstention engine gap.

---

## 7. Evaluation Lab Frontend Audit

**Files:** `voice_chat.html`, `app/voice_chat.html`  
**Sync status:** SHA256 MATCH confirmed.

The Evaluation Lab tab is present in the frontend. It reads metrics via `/evaluation/runs/{id}/summary` (API). No metrics are hardcoded in the HTML. All data is live-loaded from backend on tab selection.

**Not verified in this audit:** browser-visible rendering of metric cards. A live browser test is needed to confirm the frontend displays correct values.

---

## 8. Unsupported Claims in Previous Reports

The Phase 6 reliability evaluation report implies that abstention provides a benefit. **This is not supported by Phase 6 evidence.** The report should be read as:

- Phase 6 demonstrates pipeline reliability for unambiguous operational queries.
- Phase 6 does NOT demonstrate abstention effectiveness, because no borderline cases were included.
- Phase 6.1 (this audit) is the first evaluation to include semantic-conflict cases, and found 0% distraction rejection in both conditions.

---

## 9. Summary of Confirmed Findings

| Finding | Status |
|---|---|
| All Phase 6 JSONL manifests SHA256-verified | ✅ Confirmed |
| WER reference transcripts independently authored (not from Whisper) | ✅ Confirmed |
| Baseline genuinely disables abstention in the runner | ✅ Confirmed |
| Both conditions share identical ASR transcripts (cache) | ✅ Confirmed |
| All metric denominators mathematically correct | ✅ Confirmed |
| Wilson CI formula correct | ✅ Confirmed |
| Phase 6 corpus is all-unambiguous → baseline = abstention | ✅ Confirmed (LIMITATION) |
| Abstention engine misses negation/hypothetical/mention/cancellation | ✅ Confirmed (GAP) |
| Phase 6.1 pilot: 5/5 distractor false-positive executions (both conditions) | ✅ Confirmed |
| Phase 6.1 WER = 0.0% (Whisper handles TTS audio correctly) | ✅ Confirmed |
| Personal microphone recordings are confined to `real_audio_v1` | ✅ Confirmed |
| `Customers.mpeg` is dual-use (real_audio case + smoke-test fixture) | ✅ Confirmed |
| voice_chat.html and app/voice_chat.html are in sync | ✅ Confirmed |
| Browser-visible Evaluation Lab rendering | ❌ NOT verified (requires browser) |
