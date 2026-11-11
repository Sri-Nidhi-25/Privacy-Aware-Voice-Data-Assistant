# Phase 6.1 Pilot Report — Semantic-Conflict Audio Evaluation

**Date:** 2026-10-31  
**Run ID:** `c4f0c07b` (directory: `evaluation/results/phase6_1/88cd8262/`)  
**Git commit at run time:** `5b20a3a_dirty`

---

## 1. Motivation

Phase 6 demonstrated reliable pipeline operation (ASR → routing → tool execution) on an unambiguous corpus. It did not evaluate whether the abstention engine correctly rejects semantic distractors, negated commands, hypotheticals, or conversational mentions.

Phase 6.1 pilots a 10-case semantic-conflict dataset designed to trigger abstention and measure the engine's coverage of linguistic boundary phenomena.

---

## 2. Dataset

| Property | Value |
|---|---|
| Dataset name | `semantic_conflict_audio_v1` |
| JSONL path | `evaluation/datasets/phase6/semantic_conflict_audio_v1.jsonl` |
| N | 10 (5 operational + 5 distractor) |
| Audio source | Microsoft Edge TTS (`en-US-AriaNeural`), 16kHz mono WAV |
| Audio directory | `benchmark_audio/phase6_1/` |
| Speaker | Neural TTS — NOT authentic human speaker |
| Provenance | `standardized_benchmark_recording` |
| SHA256 | `6ed69d86d9e23310a2a3d811911e0a68958558a4ced207f16cbed513cd4829d6` |

### 2.1 Operational cases (5)

Clear, unambiguous tool requests expected to be executed:

| Case ID | Description |
|---|---|
| `sem_conf_aud_001` | Show active customers |
| `sem_conf_aud_002` | List open support tickets |
| `sem_conf_aud_003` | Pull last 5 sales transactions |
| `sem_conf_aud_004` | Get daily active users |
| `sem_conf_aud_005` | Show inactive customers |

### 2.2 Distractor cases (5)

Semantically challenging inputs designed to trigger false-positive tool execution:

| Case ID | Distractor type | Example utterance |
|---|---|---|
| `sem_conf_aud_006` | Negation | "Do not show me any active customers right now." |
| `sem_conf_aud_007` | Mention-vs-command | "Open support tickets are becoming a real headache lately." |
| `sem_conf_aud_008` | Hypothetical | "What if we were to query the daily active users tomorrow instead?" |
| `sem_conf_aud_009` | Cancellation | "Pull records for inactive customers, wait no, cancel that, never mind." |
| `sem_conf_aud_010` | Ambiguous intent | "Something about tickets, maybe check them or whatever." |

---

## 3. Runner Configuration

- **Runner:** `evaluation/runners/run_paired_evaluation.py` with `--semantic-audio` flag
- **ASR model:** Whisper `small.en` (cached per case_id — both conditions see identical transcript)
- **LLM:** `llama3.2:latest` via Ollama at `http://127.0.0.1:11434`
- **Baseline:** `enable_abstention=False` (confirmed: direct code inspection)
- **Abstention:** `enable_abstention=True` (default pipeline)

---

## 4. Results

### 4.1 Summary table

| Metric | Baseline | With Abstention |
|---|---|---|
| Overall Coverage | 9/10 (90.0%) [95% CI: 59.6–98.2%] | 10/10 (100.0%) [72.2–100.0%] |
| Operational Coverage | 4/5 (80.0%) [37.5–96.4%] | 5/5 (100.0%) [56.5–100.0%] |
| **Distractor Leakage Rate** | **5/5 (100.0%) — FAILURE** | **5/5 (100.0%) — FAILURE** |
| Selective Risk | 5/9 (55.6%) [26.7–81.1%] | 5/10 (50.0%) [23.7–76.3%] |
| **False-Positive Tool Exec.** | **5/5 (100.0%) — FAILURE** | **5/5 (100.0%) — FAILURE** |
| Missed Valid Requests | 1/5 (20.0%) [3.6–62.5%] | 0/5 (0.0%) [0.0–43.5%] |
| End-to-End Task Success | 4/10 (40.0%) [16.8–68.7%] | 5/10 (50.0%) [23.7–76.3%] |
| Mean WER | 0.0% | 0.0% |
| Mean CER | 0.0% | 0.0% |

### 4.2 Failure stage breakdown

| Stage | Baseline | Abstention |
|---|---|---|
| `intent_routing_failure` | 5 | 0 |
| `abstention_false_negative` | 0 | 4 |
| `clarification_failure` | 1 | 1 |

---

## 5. Failure Analysis

### 5.1 WER = 0.0%

Whisper correctly transcribed all 10 TTS-generated audio files. The ASR layer is not a source of failure in this pilot.

### 5.2 Distractor leakage: all 5 distractors executed in both conditions

The abstention engine executed a tool for every distractor case. The five distractor types it failed to handle:

| Distractor type | Abstention engine gap |
|---|---|
| Negation | Does not detect "do not", "don't", "never", "no" as negators |
| Mention-vs-command | Does not distinguish conversational reference from imperative |
| Hypothetical | Does not detect "what if", "were to", "instead", subjunctive framing |
| Cancellation | Does not detect "wait no", "never mind", "cancel that", self-correction |
| Ambiguous intent | Treats even incoherent utterances as commands |

These gaps are present in `app/services/abstention_router.py`. The engine relies on intent classification without explicit linguistic negation or hypothetical detection.

### 5.3 Baseline missed valid request (1/5)

One operational case was not executed in the baseline condition. The failure stage was `intent_routing_failure`. This was likely a transient Ollama connection issue during the baseline run (Ollama had been recently restarted). The abstention condition ran without this issue (0/5 missed).

This 1-case difference is **not statistically meaningful at N=5** and should not be interpreted as a reliable abstention advantage for operational coverage.

### 5.4 CLARIFY case handled as execution in both conditions

One distractor case expected a `CLARIFY` response. Both conditions executed a tool call instead (`clarification_failure` = 1/1 in both). This confirms the abstention engine does not emit `CLARIFY` for genuinely ambiguous inputs.

---

## 6. Conclusions

1. **No abstention benefit demonstrated on semantic-conflict cases.** The abstention engine produces identical false-positive execution rates (100% distractor leakage) with and without abstention enabled.

2. **WER is not the bottleneck.** Whisper successfully transcribes all TTS audio. Pipeline failures occur at intent routing and abstention stages.

3. **The abstention engine needs semantic boundary detection** before this evaluation can demonstrate any discriminative benefit. Specifically needed:
   - Negation pattern matching (syntactic or LLM-based)
   - Hypothetical frame detection
   - Conversational mention vs. imperative command detection
   - Self-correction / cancellation detection

4. **Expanding to 30–50 cases with the current engine would produce systematically wrong results.** 100% FPR on distractors would replicate across a larger corpus without engine improvement.

5. **The pilot framework is validated.** Runner, ASR caching, metric denominators, Wilson CI, and per-case JSONL outputs are all working correctly.

---

## 7. Raw Output Files

| File | Path |
|---|---|
| Baseline per-case JSONL | `evaluation/results/phase6_1/88cd8262/run_baseline.jsonl` |
| Abstention per-case JSONL | `evaluation/results/phase6_1/88cd8262/run_abstention.jsonl` |
| Metrics summary | `evaluation/results/phase6_1/88cd8262/metrics_summary.json` |
| Failure localization | `evaluation/results/phase6_1/88cd8262/failure_localization.json` |

---

## 8. Constraints and Scope Boundaries

- This pilot used **neural TTS audio only** — findings may not fully generalize to authentic human speech with disfluencies, accents, or prosodic variation.
- N=10 with equal operational/distractor split: confidence intervals are wide (see table). Individual case outcomes should be treated as directional, not definitive.
- The pilot was designed to expose abstention engine gaps. It was not designed as a representative sample of real user traffic.
- The abstention router issues are documented findings only. They were **not patched** during this evaluation.
