# Phase 6 — Reproducible Real-Audio Reliability Evaluation, Selective Abstention Analysis & Evidence Audit

**Date:** October 30, 2026  
**Repository:** `Privacy-Preserving-Voice-Data-Assistant`  
**Git Branch:** `main`  
**Git HEAD:** `5b20a3aac193abf532ec479325c946a87dc4b15f`  
**Lead Evaluator:** Senior AI Reliability & Evaluation Lead  
**Operating System:** Windows x86_64  
**Runtime:** Python 3.11.3 (Virtual Environment `venv`)  
**Core Dependencies:** `fastapi==0.115.6`, `torch==2.12.1`, `transformers==5.20.2`, `openai-whisper==20250625`, `librosa==0.10.2`, `pyworld==0.3.5`, `ollama==0.6.2`  

---

## 1. Executive Summary

Phase 6 implements a rigorous, evidence-based reliability evaluation of the voice-to-tool execution pipeline on real and standardized benchmark audio. This evaluation moves beyond unit tests and cached transcripts, subjecting the complete end-to-end architecture to paired experimental controls:

$$\text{Audio Input} \longrightarrow \text{Validation} \longrightarrow \text{Obfuscation} \longrightarrow \text{Whisper ASR} \longrightarrow \text{LLM Correction} \longrightarrow \text{Intent Routing} \longrightarrow \text{Abstention Gate} \longrightarrow \text{Tool Validation} \longrightarrow \text{Connector Execution} \longrightarrow \text{TTS}$$

### Key Empirical Accomplishments:
1. **Dependency Integrity:** Fixed `requirements.txt` by explicitly adding `torch`, `torchaudio`, `transformers`, and `speechbrain`.
2. **Dataset Inventory & Verification:** Formally cataloged all audio assets. Authored schema `collection_manifest_schema.json` and manifests for 6 authentic human recordings (`real_audio_v1.jsonl`) and 32 benchmark recordings (`benchmark_audio_v1.jsonl`). Verified cryptographic SHA256 hashes of all frozen Phase 4.6 and Phase 6 datasets (100% match).
3. **Paired Baseline-vs-Abstention Evaluation Harness:** Implemented `evaluation/runners/run_paired_evaluation.py`, executing identical audio through both Baseline (abstention disabled) and Abstention conditions. Calculated Coverage, Selective Risk, False-Positive Tool Execution, Missed Valid Requests, and Task Success with exact numerators, denominators, and Wilson 95% confidence intervals.
4. **Historical Reproduction Audit:** Re-executed the Phase 5 Generalization Benchmark (8 datasets, $N=150$), Phase 5 Distractor/Matched Pairs ($N=30$), and Phase 5.5 E2E ($N=6$). Confirmed the decontaminated Phase 4.6 challenge score of 68.0% and observed Phase 5 distractor FPR drop from 85.0% to 0.0%.
5. **Biometric Privacy Audit:** Completed forensic evaluation in `docs/phase6_privacy_evidence_audit.md`. Documented that observed neural embedding cosine similarity drops ($0.98 \rightarrow 0.88$) establish acoustic voice transformation but do not prove biometric anonymization or de-identification.
6. **Regression Testing:** Added comprehensive tests in `tests/test_phase6/`. Total passing repository test suite increased to **118 passed tests** (0 failures).

---

## 2. Workstream A: Labelled Audio Dataset Design & Provenance

### 2.1 Available Audio Asset Inventory

The repository was searched for existing audio assets. The available real and calibrated audio assets comprise:
- **`data/audio/*.mpeg` ($N=6$):** Authentic human microphone recordings captured during real user queries.
- **`benchmark_audio/phrase_*_*.wav` ($N=32$):** Standardized voice recordings of 8 database prompts evaluated across 4 obfuscation strengths (`none`, `mild`, `medium`, `strong`).
- **`benchmark_audio/phase5_5_cache/` ($N=100$):** Calibrated TTS audio variants generated with controlled Gaussian noise (clean, 20 dB, 10 dB) for synthetic failure localization.

### 2.2 Dataset Breakdown & Metadata

| Dataset Partition | File Path | Provenance | Format | Cases ($N$) | Operational | Non-Operational / Distractor | Speakers | Conditions | SHA256 Hash |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`real_audio_v1`** | `evaluation/datasets/phase6/real_audio_v1.jsonl` | Authentic Human Recording | MPEG (16 kHz mono) | 6 | 5 | 1 | 1 | Clean room | `45d9712bf...` |
| **`benchmark_audio_v1`** | `evaluation/datasets/phase6/benchmark_audio_v1.jsonl` | Standard Benchmark Voice | WAV (16 kHz mono) | 32 | 28 | 4 | 1 | none, mild, medium, strong | `9fd559dec...` |
| **Total Evaluated** | — | — | — | **38** | **33** | **5** | 2 | 5 acoustic levels | Verified |

### 2.3 Data Collection Manifest & Schema

To scale evaluation to the target 100–150 cases, `evaluation/datasets/phase6/collection_manifest_schema.json` establishes strict validation rules:
- **Target sample size:** 100 cases (6 authentic human currently available; 94 additional required).
- **Target split:** 20 Development, 20 Validation, 60 Held-Out Test.
- **Diversity requirements:** Minimum 5 distinct consented human speakers across genders and accents, $\ge 20$ semantic distractors, $\ge 20$ linguistic boundary cases, $\ge 15$ underspecified queries requiring clarification.
- **Integrity Rule:** Synthetic speech must never be labelled as authentic human recording.

---

## 3. Workstream B: Paired Baseline-vs-Abstention Evaluation

### 3.1 Experimental Controls
To guarantee fair comparison:
1. **Shared ASR:** Both conditions processed identical audio bytes and identical Whisper STT transcripts ($WER = 0.0\%$).
2. **Identical Connectors:** Tool calls were routed to isolated local mock DB connectors with reset state.
3. **Single Variable Intervention:** The only difference between conditions was the execution of `evaluate_abstention()` in the orchestrator pipeline.

### 3.2 Evaluation Results on Authentic Human Audio ($N=6$)

Evaluated using `python evaluation/runners/run_paired_evaluation.py --real-only` (Run ID: `f196279a`):

| Metric | Baseline (No Abstention) | With Selective Abstention | Delta / Effect |
| :--- | :--- | :--- | :--- |
| **Eligible Cases ($N$)** | 6 | 6 | Paired Identical |
| **Overall Coverage** | 5/6 (83.3%) [95% CI: 43.6% - 97.0%] | 5/6 (83.3%) [95% CI: 43.6% - 97.0%] | 0.0% |
| **Operational Coverage** | 5/5 (100.0%) [95% CI: 56.5% - 100.0%] | 5/5 (100.0%) [95% CI: 56.5% - 100.0%] | 0.0% |
| **Distractor Coverage (Leakage)** | 0/1 (0.0%) [95% CI: 0.0% - 79.3%] | 0/1 (0.0%) [95% CI: 0.0% - 79.3%] | 0.0% |
| **Selective Risk (Executed Errors)** | 0/5 (0.0%) [95% CI: 0.0% - 43.5%] | 0/5 (0.0%) [95% CI: 0.0% - 43.5%] | 0.0% |
| **False-Positive Tool Executions** | 0/1 (0.0%) [95% CI: 0.0% - 79.3%] | 0/1 (0.0%) [95% CI: 0.0% - 79.3%] | 0.0% |
| **Missed Valid Requests** | 0/5 (0.0%) [95% CI: 0.0% - 43.5%] | 0/5 (0.0%) [95% CI: 0.0% - 43.5%] | 0.0% |
| **End-to-End Task Success** | 6/6 (100.0%) [95% CI: 61.0% - 100.0%] | 6/6 (100.0%) [95% CI: 61.0% - 100.0%] | 0.0% |
| **Mean Word Error Rate (WER)** | 0.0% | 0.0% | 0.0% |

> [!NOTE]
> On the 6 authentic human recordings, both the baseline intent router and the abstention router correctly classified the out-of-domain knowledge query (`Capital.mpeg`: *"What is the capital city of France?"*) as `direct`, resulting in 0 tool executions in both conditions. The Wilson 95% confidence interval $[0.0\%, 79.3\%]$ highlights the high statistical uncertainty of this small sample.

### 3.3 Evaluation Results on Benchmark Voice Audio ($N=32$)

Evaluated using `python evaluation/runners/run_paired_evaluation.py --benchmark` (Run ID: `e22e9b0f`):

| Metric | Baseline (No Abstention) | With Selective Abstention | Delta / Effect |
| :--- | :--- | :--- | :--- |
| **Eligible Cases ($N$)** | 32 | 32 | Paired Identical |
| **Overall Coverage** | 28/32 (87.5%) [95% CI: 71.9% - 95.0%] | 28/32 (87.5%) [95% CI: 71.9% - 95.0%] | 0.0% |
| **Operational Coverage** | 28/28 (100.0%) [95% CI: 87.9% - 100.0%] | 28/28 (100.0%) [95% CI: 87.9% - 100.0%] | 0.0% |
| **Distractor Coverage (Leakage)** | 0/4 (0.0%) [95% CI: 0.0% - 49.0%] | 0/4 (0.0%) [95% CI: 0.0% - 49.0%] | 0.0% |
| **Selective Risk (Executed Errors)** | 0/28 (0.0%) [95% CI: 0.0% - 12.1%] | 0/28 (0.0%) [95% CI: 0.0% - 12.1%] | 0.0% |
| **False-Positive Tool Executions** | 0/4 (0.0%) [95% CI: 0.0% - 49.0%] | 0/4 (0.0%) [95% CI: 0.0% - 49.0%] | 0.0% |
| **Missed Valid Requests** | 0/28 (0.0%) [95% CI: 0.0% - 12.1%] | 0/28 (0.0%) [95% CI: 0.0% - 12.1%] | 0.0% |
| **End-to-End Task Success** | 32/32 (100.0%) [95% CI: 89.3% - 100.0%] | 32/32 (100.0%) [95% CI: 89.3% - 100.0%] | 0.0% |
| **Mean Word Error Rate (WER)** | 0.0% | 0.0% | 0.0% |

### 3.4 Consolidated Audio Evaluation ($N=38$)

| Metric | Baseline | With Selective Abstention | Wilson 95% Confidence Interval |
| :--- | :--- | :--- | :--- |
| **Overall Coverage** | 33/38 (86.8%) | 33/38 (86.8%) | $[72.7\%, 94.2\%]$ |
| **Operational Coverage** | 33/33 (100.0%) | 33/33 (100.0%) | $[89.6\%, 100.0\%]$ |
| **Distractor Coverage** | 0/5 (0.0%) | 0/5 (0.0%) | $[0.0\%, 43.5\%]$ |
| **Selective Risk** | 0/33 (0.0%) | 0/33 (0.0%) | $[0.0\%, 10.4\%]$ |
| **False-Positive Tool Executions** | 0/5 (0.0%) | 0/5 (0.0%) | $[0.0\%, 43.5\%]$ |
| **Missed Valid Requests** | 0/33 (0.0%) | 0/33 (0.0%) | $[0.0\%, 10.4\%]$ |
| **End-to-End Task Success** | 38/38 (100.0%) | 38/38 (100.0%) | $[90.8\%, 100.0\%]$ |

> [!WARNING]
> While task success is 100% on the 38 evaluated clean/standard audio cases, the statistical upper bound on selective risk is **10.4%**, and the false-positive execution rate bound is **43.5%**. Zero observed errors in a sample of 38 cases does NOT demonstrate zero underlying risk. Stress-testing under semantic distractors and adversarial distribution shifts reveals significant failures (see Section 5).

---

## 4. Workstream C: Failure Localization & Error Propagation

### 4.1 12-Stage Pipeline Failure Localization Taxonomy

The pipeline defines 12 distinct failure stages to distinguish root causes from downstream symptoms:
1. `input_validation_failure` (corrupt format, out-of-bounds duration)
2. `asr_transcription_failure` (Whisper hallucination, high WER, missing audio)
3. `correction_induced_semantic_change` (LLM transcript normalizer mutates entities)
4. `intent_routing_failure` (misclassifies domain intent)
5. `abstention_false_positive` (unnecessarily abstains on valid operational query)
6. `abstention_false_negative` (fails to abstain on distractor / adversarial query)
7. `argument_validation_failure` (omits or violates required tool parameter schemas)
8. `tool_selection_failure` (selects incorrect tool)
9. `connector_execution_failure` (database timeout or execution exception)
10. `response_generation_failure` (LLM answer fails to synthesize tool output)
11. `tts_failure` (Edge-TTS speech synthesis failure)
12. `infrastructure_failure` (process crash or runtime exception)

### 4.2 Error Propagation Observations
- On the 38 clean/benchmark cases, **0 stage failures** occurred.
- In the Phase 5 Generalization Benchmark ($N=150$), failures originated primarily at:
  - **Stage 4 (`intent_routing_failure` in Baseline):** High failure rates on semantic distractors (17/20 = 85.0%) and adversarial queries (11/15 = 73.3%).
  - **Stage 6 (`abstention_false_negative` in Abstention):** On subtle adversarial queries, abstention failed to trigger on 2 of 15 cases (13.3%), allowing unsafe tool execution.
  - **Stage 5 (`abstention_false_positive`):** On the challenge set, abstention was triggered on 8 operational queries with ambiguous wording, reducing coverage from 68.0% to 48.0%.

---

## 5. Workstream D: Historical Evaluation Reproduction Audit

To eliminate conflicting claims, all historical evaluation suites were re-executed against the current codebase in the active environment.

### 5.1 Historical Reproduction Results Table

| Phase / Experiment | Historical Reported Result | Current Reproduction Result | Dataset Version & SHA256 | Input Type | Model / Config | Exact Command | Sample ($N$) | Status | Difference & Explanation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Phase 4.6 Frozen Held-Out Test** | Baseline Acc: 86.7% | **86.7%** (26/30) | `held_out_test_v1.jsonl` (`82efa536...`) | Text / Transcripts | Llama-3.2, threshold 0.50 | `python -m evaluation.phase5.generalization_eval` | 30 | **REPRODUCED** | Exact match. |
| **Phase 4.6 Frozen Challenge Set** | Decontaminated: 68.0% (Old contaminated: 84.0%) | **68.0%** (17/25) | `challenge_v1.jsonl` (`0ded94ac...`) | Text / Transcripts | Llama-3.2, threshold 0.50 | `python -m evaluation.phase5.generalization_eval` | 25 | **REPRODUCED** | Matches Phase 4.6 decontaminated benchmark exactly. (Historical 84% was contaminated by benchmark-specific regexes). |
| **Phase 5 Distractors Benchmark** | Base FPR: 85.0% -> Abs FPR: 0.0% | **Base FPR: 85.0% -> Abs FPR: 0.0%** | `distractors_v1.jsonl` | Text / Transcripts | Llama-3.2, threshold 0.50 | `python -m evaluation.phase5.distractor_eval` | 20 | **REPRODUCED** | Exact match. Baseline FP: 17/20 (85.0%); Abstention FP: 0/20 (0.0%). Safe abstention: 100%. |
| **Phase 5 Matched Pairs** | Base: 0.0% -> Abs: 50.0% | **Base: 0.0% -> Abs: 50.0%** | `matched_pairs_v1.jsonl` | Text / Transcripts | Llama-3.2, threshold 0.50 | `python -m evaluation.phase5.distractor_eval` | 10 | **REPRODUCED** | Exact match. Abstention successfully separated 5 of 10 matched pairs. |
| **Phase 5 Generalization Suite** | 8 datasets ($N=150$) | **8 datasets ($N=150$)** | Phase 5 Suite (all verified) | Text / Transcripts | Llama-3.2, threshold 0.50 | `python -m evaluation.phase5.generalization_eval` | 150 | **REPRODUCED** | Full breakdown reproduced in `experiments/phase5/generalization/summary.json`. |
| **Phase 5.5 E2E Pipeline** | Baseline Unsafe: 0.0%, Abs Unsafe: 0.0% | **Baseline Unsafe: 0.0%, Abs Unsafe: 0.0%** | `phase5_5` clean & distractors | Calibrated WAVs | Whisper small.en + Llama-3.2 | `python -m evaluation.phase5_5.run_e2e --quick` | 6 | **REPRODUCED** | Exact match on quick subset. Full 500-sample run not run due to CPU inference limits (~20h estimated). |

### 5.2 Phase 5 Generalization Benchmark Breakdown ($N=150$)

| Dataset Partition | $N$ | Baseline Accuracy | Baseline FPR | Abstention Coverage | Abstention Risk | Abstention Unsafe Execution Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `phase5_dev` | 20 | 70.0% | 30.0% | 55.0% | 9.1% | 5.0% |
| `phase5_val` | 20 | 60.0% | 40.0% | 35.0% | 14.3% | 5.0% |
| `frozen_held_out` | 30 | 86.7% | 10.0% | 63.3% | 0.0% | 0.0% |
| `frozen_challenge` | 25 | 68.0% | 24.0% | 48.0% | 33.3% | 16.0% |
| `phase5_distractors` | 20 | 15.0% | 85.0% | 0.0% | 0.0% | 0.0% |
| `phase5_ambiguity` | 15 | 53.3% | 46.7% | 0.0% | 0.0% | 0.0% |
| `phase5_adversarial` | 15 | 26.7% | 73.3% | 13.3% | 100.0% | 13.3% |
| `phase5_ood` | 15 | 40.0% | 40.0% | 33.3% | 0.0% | 0.0% |

---

## 6. Workstream E: Privacy Evidence & Claims Audit

The forensic audit documented in `docs/phase6_privacy_evidence_audit.md` evaluated `eval_speaker_similarity.py` and `benchmark_audio/speaker_similarity_results.csv`:

### 6.1 Supported Claims
1. **Acoustic Signal Perturbation:** The system shifts $F_0$ pitch and warps spectral envelopes via the WORLD vocoder.
2. **x-vector Cosine Similarity Drop:** On 8 Edge-TTS voice phrases, cosine similarity drops from 1.0 (clean) to:
   - Mild: $0.976$ ($\Delta = 0.024$)
   - Medium: $0.945$ ($\Delta = 0.055$)
   - Strong: $0.914$ ($\Delta = 0.086$)
   - Strong with tempo: $0.877$ ($\Delta = 0.123$)
3. **Intelligibility Retention:** Whisper transcription remains accurate ($WER \le 0.167$) under evaluated shifts.

### 6.2 Unsupported Claims
1. **"Biometric Anonymization Guarantee":** Unsupported. A cosine similarity of $0.87 - 0.91$ is well within the match threshold ($0.60 - 0.75$) of commercial biometric verification systems.
2. **"Unlinkability":** Unsupported. No cross-session or randomized parameter trials were evaluated.
3. **"Equal Error Rate (EER)":** Unsupported. Zero different-speaker (impostor) trials exist, making EER calculation impossible.

---

## 7. Safety, Data Handling & Execution Isolation

- **Connector Safety:** All evaluation scripts route tool executions to isolated mock database connectors (`get_crm_data`, `get_support_tickets`, `get_analytics`). Zero external API calls, write operations, or customer notifications occurred.
- **Data Privacy:** All audio files used are local non-sensitive recordings. No audio or transcripts were transmitted to external cloud endpoints.
- **State Isolation:** Per-request obfuscator instantiation prevented concurrency leakage.

---

## 8. Reproducibility Guide

### Prerequisites
- Python 3.11 with virtual environment `venv` activated.
- Ollama running locally at `http://127.0.0.1:11434` with model `llama3.2:latest`.
- Dependencies installed from `requirements.txt`.

### Exact Reproduction Commands

```powershell
# 1. Cryptographic dataset verification (All frozen and Phase 6 datasets)
.\venv\Scripts\python.exe -m evaluation.datasets.verify_datasets

# 2. Phase 6 Paired Real-Audio Evaluation (Authentic human recordings, N=6)
.\venv\Scripts\python.exe evaluation/runners/run_paired_evaluation.py --real-only

# 3. Phase 6 Paired Benchmark Evaluation (Standardized voice phrases, N=32)
.\venv\Scripts\python.exe evaluation/runners/run_paired_evaluation.py --benchmark

# 4. Phase 5 Distractor & Matched Pairs Benchmark (N=30)
.\venv\Scripts\python.exe -m evaluation.phase5.distractor_eval

# 5. Phase 5 Generalization & Abstention Benchmark (8 datasets, N=150)
.\venv\Scripts\python.exe -m evaluation.phase5.generalization_eval

# 6. Phase 5.5 E2E Pipeline Quick Evaluation (N=6)
.\venv\Scripts\python.exe -m evaluation.phase5_5.run_e2e --quick

# 7. Complete Regression Test Suite
.\venv\Scripts\python.exe -m pytest tests/ -q
```

---

## 9. Remaining Limitations & Recommended Next Actions

1. **Authentic Human Sample Size ($N=6$):** The repository currently contains 6 authentic human recordings. While 32 benchmark recordings and 100 calibrated audio files are available, additional consented multi-speaker recordings are required to reach the target $N=100$.
2. **Biometric Impostor Trials:** To substantiate privacy claims, an evaluation using 20+ human speakers from LibriSpeech or VoxCeleb with same-speaker vs. different-speaker trials must be conducted to establish true Equal Error Rates.
3. **ASR Inference Speed:** Real audio transcription on CPU requires ~15–20s per case. GPU acceleration or batch caching is recommended for large-scale evaluations ($N \ge 500$).
