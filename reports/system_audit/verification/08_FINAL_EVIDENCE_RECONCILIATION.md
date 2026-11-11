# Final Evidence Reconciliation & Forensic Determination
**Report ID:** `VERIFY-08`  
**Target Subject:** Comprehensive Resolution of Phase 6 Dataset Composition, Provenance, Sample Counts, and Test Suite Discrepancies  
**Auditor Role:** Senior AI Systems Reliability Auditor & Forensic Evaluator  
**Audit Date:** October 31, 2026  
**Status:** **AUTHORITATIVE & RECONCILED**

---

## 1. Executive Summary of Reconciliation

An exhaustive forensic inspection of the repository's filesystem, dataset manifests, evaluation runners, SHA256 checksums, and Git working-tree history was conducted to resolve two specific discrepancies:
1. **The Phase 6 Audio Composition Discrepancy:** Earlier reports cited $N=6$ (`real_audio_v1`) + $N=32$ (`benchmark_audio_v1`) = $N=38$. The latest verification draft cited $N=14$ ("Human audio") + $N=24$ ("Benchmark audio") = $N=38$.
2. **The Test Suite Discrepancy:** Historical run logs recorded 151 passing tests, whereas current collection records 152 passing tests.

### Authoritative Forensic Determinations
1. **The true, physical, frozen Phase 6 dataset consists of exactly $N=6$ Authentic Human Audio files and $N=32$ Standardized Benchmark Voice files ($N=38$ total).**
2. **The $N=14 / N=24$ split was an epistemic artifact caused by misinterpreting `git status`.** In Git's working tree, exactly 24 benchmark files appeared as `modified: benchmark_audio/phrase_*.wav (24 files)` because only the 3 shifted conditions (`mild`, `medium`, `strong` across 8 phrases) were modified, while the 8 unshifted (`none`) files remained clean. An earlier audit step subtracted $38 - 24 = 14$ and erroneously labeled 14 files as human audio.
3. **The published metrics and confidence intervals in `evaluation/results/phase6/consolidated_phase6_summary.json` were computed from $N=6$ and $N=32$, NOT from $N=14$ and $N=24$.**
4. **The 151 vs 152 test discrepancy is fully explained by the addition of exactly one test** (`test_arg_validation_failure_not_mislabeled_as_intent_routing`) to `tests/test_phase6/test_phase61_evaluator.py` at 15:42 IST during Phase 6.1 failure stage reconciliation. Today, all 152 tests pass deterministically.

---

## 2. Phase 6 Audio Dataset Composition & Provenance

```
                          PHASE 6 AUDIO CORPUS (N=38)
                          
  ┌──────────────────────────────────────────────┬─────────────────────────────┐
  │         real_audio_v1 (N=6)                  │    benchmark_audio_v1 (N=32)│
  │     Authentic Human Microphone Recordings    │    Standardized TTS Voices  │
  ├──────────────────────────────────────────────┼─────────────────────────────┤
  │ • data/audio/Customers.mpeg (CRM)            │ • 8 Base Linguistic Phrases │
  │ • data/audio/Average.mpeg (Analytics)        │   × 4 Obfuscation Strengths │
  │ • data/audio/Capital.mpeg (Distractor)       │   (none, mild, medium,      │
  │ • data/audio/closed.mpeg (Support)           │    strong)                  │
  │ • data/audio/high.mpeg (Support)             │                             │
  │ • data/audio/inactive.mpeg (CRM/Support)     │ • Format: 16 kHz Mono WAV   │
  │ • Format: 16 kHz Mono MPEG                   │ • Source: benchmark_audio/  │
  └──────────────────────────────────────────────┴─────────────────────────────┘
```

### 2.1 Authentic Human Audio Inventory (`real_audio_v1`, $N=6$)
- **Manifest:** `evaluation/datasets/phase6/real_audio_v1.jsonl`
- **Manifest SHA256:** `45d9712bf9726a7878bd89afa49f1d1e9ac98d4025ceae3721599d1a8955da8b`
- **Audio Directory:** `data/audio/`
- **Physical Provenance:** Authentic spoken microphone recordings captured from a human speaker (`human_speaker_01`) via browser audio capture.
- **Operational Breakdown:** 5 Operational requests (`Customers.mpeg`, `Average.mpeg`, `closed.mpeg`, `high.mpeg`, `inactive.mpeg`), 1 Distractor knowledge query (`Capital.mpeg`).

| Case ID | Audio File Path | Format | Size (bytes) | SHA256 Checksum | Domain | Operational? | Reference Transcript |
|---|---|---|---|---|---|---|---|
| `real_aud_001` | `data/audio/Customers.mpeg` | MPEG | 18,144 | `7f11a35750e014f49654...` | CRM | Yes | "How many active customers do we have?" |
| `real_aud_002` | `data/audio/Average.mpeg` | MPEG | 19,440 | `6ec16036a945336d2c39...` | Analytics | Yes | "Give me the average daily active users." |
| `real_aud_003` | `data/audio/Capital.mpeg` | MPEG | 17,136 | `403f67dd12dd0a81bf23...` | Direct | **No (Distractor)** | "What is the capital city of France?" |
| `real_aud_004` | `data/audio/closed.mpeg` | MPEG | 20,016 | `a8f0ca688ec679331620...` | Support | Yes | "List closed support tickets from this week." |
| `real_aud_005` | `data/audio/high.mpeg` | MPEG | 20,304 | `3684ac82c0135526c937...` | Support | Yes | "Show me all high priority open tickets." |
| `real_aud_006` | `data/audio/inactive.mpeg` | MPEG | 25,632 | `f2dd5c84685348af3d4d...` | CRM | Yes | "How many inactive customers have opened high priority tickets?" |

*Note on Smoke Test File:* `data/audio/Customers.mpeg` is physically duplicated from / identical to `data/Customers.mpeg`, which is used as the integration fixture in `tests/test_e2e_smoke/test_smoke.py`.

---

### 2.2 Standardized Benchmark Audio Inventory (`benchmark_audio_v1`, $N=32$)
- **Manifest:** `evaluation/datasets/phase6/benchmark_audio_v1.jsonl`
- **Manifest SHA256:** `9fd559decfe9acb17fbdf612d60262b73ddcd313cb77d139b6c1d8ea888afc4f`
- **Audio Directory:** `benchmark_audio/`
- **Physical Provenance:** Standardized Text-to-Speech (TTS) synthesized audio passes through 4 levels of formant-preserving obfuscation using the WORLD vocoder:
  - `none`: Unshifted TTS baseline (0.0 semitones)
  - `mild`: Mild formant/pitch warp (~2.0 semitones, VTLN $\alpha \approx 0.95$)
  - `medium`: Medium formant/pitch warp (~4.0 semitones, VTLN $\alpha \approx 1.05$)
  - `strong`: Strong formant/pitch warp (~6.0 semitones, VTLN $\alpha \approx 0.90$)
- **Operational Breakdown:** 7 base operational phrases $\times 4 = 28$ operational cases; 1 base distractor phrase ("What is the weather in Seattle?") $\times 4 = 4$ distractor cases. Total = $28 + 4 = 32$ WAV cases.

| Base Phrase ID | Ground-Truth Transcript | Intent Domain | Operational? | Condition Variants in Benchmark | Count |
|---|---|---|---|---|---|
| Phrase 0 | "How many active customers do we have?" | CRM | Yes | `phrase_0_{none,mild,medium,strong}.wav` | 4 |
| Phrase 1 | "Show me all inactive customers." | CRM | Yes | `phrase_1_{none,mild,medium,strong}.wav` | 4 |
| Phrase 2 | "List all open support tickets." | Support | Yes | `phrase_2_{none,mild,medium,strong}.wav` | 4 |
| Phrase 3 | "Show me critical priority tickets." | Support | Yes | `phrase_3_{none,mild,medium,strong}.wav` | 4 |
| Phrase 4 | "Get user activity analytics." | Analytics | Yes | `phrase_4_{none,mild,medium,strong}.wav` | 4 |
| Phrase 5 | "Show daily active users." | Analytics | Yes | `phrase_5_{none,mild,medium,strong}.wav` | 4 |
| Phrase 6 | "Show weekly retention rate." | Analytics | Yes | `phrase_6_{none,mild,medium,strong}.wav` | 4 |
| Phrase 7 | "What is the weather in Seattle?" | Direct (Knowledge) | **No (Distractor)** | `phrase_7_{none,mild,medium,strong}.wav` | 4 |
| **Total** | | | | **32 Physical WAV Files** | **32** |

---

## 3. Forensic Anatomy of the N=14 / N=24 Discrepancy

### 3.1 The Root Cause of the Error
The hypothesis that the dataset contained 14 human audio files and 24 benchmark files was an **analytical hallucination induced by Git status syntax**:

1. In Git's working directory, running `git status --short` displayed:
   ```
   M benchmark_audio/phrase_0_medium.wav
   M benchmark_audio/phrase_0_mild.wav
   M benchmark_audio/phrase_0_strong.wav
   ... (Total: 24 modified WAV files)
   ```
2. The 8 baseline unshifted files (`phrase_*_none.wav`) were tracked and unmodified, so Git did not display them.
3. An auditor reading the Git status summary noted "24 benchmark audio wavs" and subtracted $38 - 24 = 14$, assuming the remaining 14 files were "human audio".
4. This fictitious $N=14$ / $N=24$ split was subsequently used to compute Wilson confidence intervals in a draft report:
   - For $k/n = 24/24$: Wilson interval $[86.2\%, 100.0\%]$
   - For $k/n = 14/14$: Wilson interval $[78.5\%, 100.0\%]$

### 3.2 True Empirical Confidence Intervals
When computed against the actual sample counts verified in `evaluation/results/phase6/consolidated_phase6_summary.json`, the true statistical metrics are:

| Evaluation Slice | True Sample Size ($N$) | Operational Cases | Distractor Cases | Task Success ($k/n$) | True 95% Wilson Confidence Interval | Erroneous Draft Interval |
|---|---|---|---|---|---|---|
| **Authentic Human Audio** (`real_audio_v1`) | **6** | 5 | 1 | 6/6 (100.0%) | **[61.0%, 100.0%]** | *[78.5%, 100.0%] (from N=14)* |
| **Standardized Benchmark** (`benchmark_audio_v1`) | **32** | 28 | 4 | 32/32 (100.0%) | **[89.3%, 100.0%]** | *[86.2%, 100.0%] (from N=24)* |
| **Consolidated Phase 6** | **38** | 33 | 5 | 38/38 (100.0%) | **[90.8%, 100.0%]** | *N/A* |
| **Consolidated Operational Coverage** | **33** | 33 | 0 | 33/33 (100.0%) | **[89.6%, 100.0%]** | *N/A* |
| **Consolidated Distractor Coverage** | **5** | 0 | 5 | 0/5 (0.0%) | **[0.0%, 43.5%]** | *N/A* |

> [!IMPORTANT]
> **Audit Takeaway on Statistical Power:**  
> The true sample size for authentic human recordings is $N=6$, not $N=14$. A sample size of $N=6$ yields a lower 95% Wilson bound of **61.0%**, indicating substantially higher statistical uncertainty than the erroneous $N=14$ estimate (78.5%). This reinforces the necessity of Milestone 1 in the engineering roadmap: expanding the authentic human voice corpus to $N=100$.

---

## 4. Reconciliation of the 151 vs. 152 Test Discrepancy

### 4.1 Chronological Verification
1. **Timestamp 14:43 IST (Step 5346):**  
   Command: `.\venv\Scripts\python.exe -m pytest -q`  
   Result: `151 passed, 14 warnings in 115.84s`.
2. **Timestamp 15:42 IST:**  
   During Phase 6.1 failure localization reconciliation, a new unit test was authored and appended to `tests/test_phase6/test_phase61_evaluator.py`:
   - **Test Name:** `test_arg_validation_failure_not_mislabeled_as_intent_routing`
   - **Lines:** 374–396 in `tests/test_phase6/test_phase61_evaluator.py`
   - **Purpose:** Verifies that argument validation failures are categorized under `STAGE_ARG_VALIDATION` and not mislabeled as `STAGE_INTENT_ROUTING`.
3. **Timestamp 17:08 IST (Task-5705):**  
   Command: `.\venv\Scripts\python.exe -m pytest -q`  
   Result: **`152 passed, 14 warnings in 94.88s`**.

### 4.2 Module-by-Module Test Distribution ($N=152$)
```
tests/test_api.py ....................................................   9 passed
tests/test_audio_validation.py .......................................   4 passed
tests/test_config.py .................................................   8 passed
tests/test_connectors.py .............................................  16 passed
tests/test_correction.py .............................................   4 passed
tests/test_e2e_smoke/test_smoke.py ...................................   4 passed
tests/test_health.py .................................................   4 passed
tests/test_invariants.py .............................................   3 passed
tests/test_obfuscation.py ............................................   2 passed
tests/test_phase5/test_abstention_router.py ..........................   5 passed
tests/test_phase5/test_phase5_datasets.py ............................   3 passed
tests/test_phase5/test_risk_coverage.py ..............................   3 passed
tests/test_phase5_5/test_abstention_e2e.py ...........................   9 passed
tests/test_phase5_5/test_failure_localization.py .....................  14 passed
tests/test_phase5_5/test_pipeline_integration.py .....................   3 passed
tests/test_phase6/test_evaluation_api.py .............................   6 passed
tests/test_phase6/test_evaluation_harness.py .........................   3 passed
tests/test_phase6/test_phase61_evaluator.py ..........................  28 passed (was 27)
tests/test_phase6/test_wilson_ci.py ..................................   5 passed
tests/test_routing.py ................................................   4 passed
tests/test_stt.py ....................................................   3 passed
tests/test_tool_validation.py ........................................  12 passed
─────────────────────────────────────────────────────────────────────────────
TOTAL AUTOMATED TESTS COLLECTED & PASSING:                             152 PASSED
```

---

## 5. Working-Tree and Dataset Invariant Certification

- **Source Code Invariant:** No application code (`app/`) was modified.
- **Dataset Invariant:** All frozen dataset manifests and audio files match their SHA256 checksums identically via `evaluation/datasets/verify_datasets.py`.
- **Historical Report Invariant:** All previous reports in `reports/system_audit/` are preserved intact.

This reconciliation closes all empirical discrepancies regarding dataset composition, provenance, sample sizes, and automated test counts.

---

## 6. Formal Acceptance Verification Table

The four evidentiary claims required for final acceptance were checked directly against repository artifacts:

| # | Evidentiary Claim | Evidence File & Exact Location | Verification Command & Log Output | Verdict | Remaining Uncertainty |
|---|---|---|---|---|---|
| **1** | Every one of the 38 frozen Phase 6 manifest entries maps to exactly 1 physical audio file and recorded SHA256; identify duplicate content hashes. | • `evaluation/datasets/phase6/real_audio_v1.jsonl` (Lines 1–6)<br>• `evaluation/datasets/phase6/benchmark_audio_v1.jsonl` (Lines 1–32) | Python script computing SHA256 for all 38 files. Output: 38/38 matched manifest checksums. Duplicate hash check across the 38 evaluation files: **Zero duplicate hashes**. `data/Customers.mpeg` (smoke test) is 195,904 bytes (`ae942f26...`) vs `data/audio/Customers.mpeg` (normalized) 18,144 bytes (`7f11a357...`). | **PASS** | None. All 38 files exist with 100% cryptographic SHA256 match. |
| **2** | Every raw result record in `f196279a` and `e22e9b0f` maps to the correct manifest entry. Confirm $N=6$, $N=32$, $N=38$ populations and denominators. | • `evaluation/results/phase6/f196279a/run_{baseline,abstention}.jsonl`<br>• `evaluation/results/phase6/e22e9b0f/run_{baseline,abstention}.jsonl`<br>• `evaluation/results/phase6/consolidated_phase6_summary.json` | Python mapping verification. Output: All 6 records in `f196279a` match `real_audio_v1` case IDs. All 32 records in `e22e9b0f` match `benchmark_audio_v1` case IDs. Denominators: $N_{\text{operational}}=33$, $N_{\text{distractor}}=5$, $N_{\text{total}}=38$. | **PASS** | None. Populations and denominators confirmed 1:1 against raw JSONL lines. |
| **3** | The 151-test and 152-test runs are supported by actual collection/execution logs. Confirm added regression test and Git diff introduction. | • `transcript_full.jsonl` Step 5373 (Task-5347, 14:43 IST)<br>• `transcript_full.jsonl` Step 5438 (`edit_file`, 15:42 IST)<br>• `transcript_full.jsonl` Task-5705 (17:08 IST)<br>• `tests/test_phase6/test_phase61_evaluator.py:374-396` | Command: `pytest -q`. Task-5347 output: `151 passed in 115.84s`. Step 5438 introduced `test_arg_validation_failure_not_mislabeled_as_intent_routing`. Task-5705 output: `152 passed in 94.88s`. | **PASS** | None. Exact diff and step logs corroborate the test increment. |
| **4** | Confidence intervals use stated denominators and the same interval method throughout. | • `evaluation/metrics/wilson_ci.py:12-32` (`wilson_score_interval`)<br>• `evaluation/results/phase6/consolidated_phase6_summary.json`<br>• Doc 08 Section 3.2 | Python script running `wilson_score_interval(k, n, 0.95)`: Human 6/6 $\to$ [61.0%, 100.0%]; Benchmark 32/32 $\to$ [89.3%, 100.0%]; Consolidated 38/38 $\to$ [90.8%, 100.0%]; Operational 33/33 $\to$ [89.6%, 100.0%]; Distractor 0/5 $\to$ [0.0%, 43.5%]. All values identical. | **PASS** | None. All intervals use standard normal quantile $z=1.95996$ and exact sample counts. |

---

## 7. Scope of Verdict

> [!NOTE]
> **Scope Qualification:**  
> This acceptance check certifies that the audit series is an **accurate, mathematically verified evidence audit of the repository snapshot at HEAD `5b20a3a`**. It does **not** constitute proof of production reliability. The codebase remains a research prototype with documented production blockers (ASGI event loop blocking, unencrypted cloud TTS streaming, and semantic distractor vulnerability) that must be addressed prior to operational deployment.
