# Phase 6 Evidence Audit & Metric Verification Report

**Repository:** `Privacy-Preserving-Voice-Data-Assistant`  
**Date of Audit:** October 30, 2026  
**Auditor:** Senior AI Reliability Engineer & Experimental Lead  
**Audit Status:** COMPLETE — Evidence-Backed & Reproducible  

---

## 1. Complete Audio Dataset Inventory (N=38)

The Phase 6 evaluation corpus consists of exactly **38 physical audio cases** partitioned into two verified datasets:
- **`real_audio_v1` (N=6):** Authentic human microphone recordings.
- **`benchmark_audio_v1` (N=32):** Standardized acoustic benchmark recordings (8 base phrases × 4 formant-preserving obfuscation strengths).

In addition, an **E2E smoke-test audio file** and a **semantic-conflict challenge dataset (N=10 text-only)** are audited.

### 1.1 Authentic Human Recordings (`real_audio_v1`, N=6)

These 6 files are authentic human microphone recordings captured via browser microphone. They were manually annotated prior to evaluation.

| Case ID | Physical File Path | Format | Size (bytes) | SHA256 Checksum | Ground-Truth Reference Transcript | Domain / Intent | Operational? | Target Tool |
|---|---|---|---|---|---|---|---|---|
| `real_aud_001` | `data/audio/Customers.mpeg` | MPEG audio | 18,144 | `7f11a35750e014f49654beda44a03f455d54fc8595f2adcb44930a2d43784516` | "How many active customers do we have?" | CRM | Yes | `get_crm_data` |
| `real_aud_002` | `data/audio/Average.mpeg` | MPEG audio | 19,440 | `6ec16036a945336d2c39c2abfd6afb3719bd92a874f982ffceb1ff58914d61b9` | "Give me the average daily active users." | Analytics | Yes | `get_analytics` |
| `real_aud_003` | `data/audio/Capital.mpeg` | MPEG audio | 17,280 | `403f67dd12dd0a81bf23fced6d125b2c2a5d875dbdc7b3db07fb4ae5c98a5711` | "What is the capital city of France?" | Direct (General) | No (Distractor) | None (`ABSTAIN`) |
| `real_aud_004` | `data/audio/closed.mpeg` | MPEG audio | 20,088 | `a8f0ca688ec679331620e9e48a5f95a81695f22f1754332868bcc873c094c827` | "List closed support tickets from this week." | Support | Yes | `get_support_tickets` |
| `real_aud_005` | `data/audio/high.mpeg` | MPEG audio | 20,304 | `3684ac82c0135526c9371e5c9b8850b89346b6f0770d16e9d24baaa99566f736` | "Show me all high priority open tickets." | Support | Yes | `get_support_tickets` |
| `real_aud_006` | `data/audio/inactive.mpeg` | MPEG audio | 25,704 | `f2dd5c84685348af3d4d4f671f9b6e38d109a9a88b93be5a13be691cc03e67fc` | "How many inactive customers have opened high priority tickets?" | CRM / Support | Yes | `get_crm_data` |

**Manifest File:** `evaluation/datasets/phase6/real_audio_v1.jsonl`  
**Manifest SHA256:** `45d9712bf9726a7878bd89afa49f1d1e9ac98d4025ceae3721599d1a8955da8b`  
**Integrity Status:** PASSED (Verified via `evaluation/datasets/verify_datasets.py`)  

#### Distinction Regarding `Customers.mpeg` & Smoke-Test Recording
`data/audio/Customers.mpeg` is physically the same file used in the end-to-end integration smoke test (`tests/test_e2e_smoke/test_real_audio_pipeline.py`).
- **Audit Verification:** `Customers.mpeg` is **NOT** a synthetic benchmark audio file; it is an authentic microphone recording of the phrase *"How many active customers do we have?"*.
- It serves dual duty as case `real_aud_001` in `real_audio_v1` and as the fixture for CI smoke testing.
- It is correctly labeled with `provenance: authentic_human_recording` across manifests.

---

### 1.2 Standardized Benchmark Audio (`benchmark_audio_v1`, N=32)

Synthesized benchmark speech covering 8 distinct database and distractor prompts across 4 levels of formant-preserving obfuscation (`none`, `mild`, `medium`, `strong`).

| Phrase Index | Reference Text | Intent Domain | Operational? | Audio File Pattern | Count |
|---|---|---|---|---|---|
| Phrase 0 | "How many active customers do we have?" | CRM | Yes | `benchmark_audio/phrase_0_{none,mild,medium,strong}.wav` | 4 |
| Phrase 1 | "Show me all inactive customers." | CRM | Yes | `benchmark_audio/phrase_1_{none,mild,medium,strong}.wav` | 4 |
| Phrase 2 | "List all open support tickets." | Support | Yes | `benchmark_audio/phrase_2_{none,mild,medium,strong}.wav` | 4 |
| Phrase 3 | "Show me critical priority tickets." | Support | Yes | `benchmark_audio/phrase_3_{none,mild,medium,strong}.wav` | 4 |
| Phrase 4 | "Get user activity analytics." | Analytics | Yes | `benchmark_audio/phrase_4_{none,mild,medium,strong}.wav` | 4 |
| Phrase 5 | "Show daily active users." | Analytics | Yes | `benchmark_audio/phrase_5_{none,mild,medium,strong}.wav` | 4 |
| Phrase 6 | "Show weekly retention rate." | Analytics | Yes | `benchmark_audio/phrase_6_{none,mild,medium,strong}.wav` | 4 |
| Phrase 7 | "What is the weather in Seattle?" | Direct (Distractor) | No (Distractor) | `benchmark_audio/phrase_7_{none,mild,medium,strong}.wav` | 4 |

**Total Benchmark Files:** $8 \times 4 = 32$ WAV audio files.  
**Manifest File:** `evaluation/datasets/phase6/benchmark_audio_v1.jsonl`  
**Manifest SHA256:** `9fd559decfe9acb17fbdf612d60262b73ddcd313cb77d139b6c1d8ea888afc4f`  
**Integrity Status:** PASSED (All 32 physical WAV files exist and match SHA256 checksums).

---

### 1.3 Semantic Conflict Challenge Dataset (`semantic_conflict_v1`, N=10)

Added to rigorously test selective abstention against linguistic edge cases where entity keywords are present but tool execution is prohibited or modified:

| Case ID | Pair ID | Semantic Challenge Category | Reference Text | Expected Intent | Operational? | Expected Decision |
|---|---|---|---|---|---|---|
| `sem_conf_001` | `pair_01` | Positive Command | "Show me all active customers in the system." | `crm` | Yes | `EXECUTE` |
| `sem_conf_002` | `pair_01` | Negated Instruction | "Do not show me any active customers right now." | `direct` | No | `ABSTAIN` |
| `sem_conf_003` | `pair_02` | Operational Command | "List all open support tickets." | `support` | Yes | `EXECUTE` |
| `sem_conf_004` | `pair_02` | Mention vs Command | "Open support tickets are becoming a real headache for our team." | `direct` | No | `ABSTAIN` |
| `sem_conf_005` | `pair_03` | Operational Query | "Retrieve the daily active users for analytics." | `analytics` | Yes | `EXECUTE` |
| `sem_conf_006` | `pair_03` | Hypothetical Inquiry | "What if we were to query daily active users tomorrow instead?" | `direct` | No | `ABSTAIN` |
| `sem_conf_007` | `pair_04` | Explicit Command | "Show me closed support tickets." | `support` | Yes | `EXECUTE` |
| `sem_conf_008` | `pair_04` | Ambiguous / Underspecified | "Something about tickets, maybe check them or whatever." | `direct` | No | `ABSTAIN` |
| `sem_conf_009` | `pair_05` | Direct Command | "Pull records for inactive customers." | `crm` | Yes | `EXECUTE` |
| `sem_conf_010` | `pair_05` | Conversational Cancellation | "Pull records for inactive customers, wait no, cancel that, never mind." | `direct` | No | `ABSTAIN` |

**Provenance:** `text_challenge` (text transcripts only, `audio_path: null`).  
**Manifest SHA256:** `ca2e65cc961818253869e7522673a94cca0238b04ba92bbe46f948175b6b96c3`  
**Integrity Status:** PASSED.

---

## 2. Audit of the Paired Evaluation Engine & Metric Definitions

We inspected `evaluation/runners/run_paired_evaluation.py`, `evaluation/metrics/wilson_ci.py`, and the resulting run outputs (`f196279a`, `e22e9b0f`, `consolidated_phase6_summary.json`).

### 2.1 Baseline Abstention Bypass Verification
- In `run_paired_evaluation.py` lines 102–110:
  ```python
  # Baseline condition:
  res_base = orchestrator.process_query(
      text=transcript,
      enable_abstention=False,
      ...
  )
  # Abstention condition:
  res_abs = orchestrator.process_query(
      text=transcript,
      enable_abstention=True,
      ...
  )
  ```
- **Finding:** The baseline genuinely bypasses abstention by passing `enable_abstention=False` directly to the production orchestrator while preserving identical upstream ASR transcripts, obfuscator output, database state, and tool schemas.
- **ASR Sharing:** Both conditions consume the exact same acoustic transcription result (`run_paired_evaluation.py` line 98: `transcript = asr_service.transcribe(audio_bytes)` is called once per case and shared across both conditions).

### 2.2 Mathematical Rigour of Metric Definitions & Denominators

| Metric | Mathematical Formula | Evaluated Denominator | Distractor Treatment | Wilson Score 95% CI |
|---|---|---|---|---|
| **Overall Coverage** | $\frac{N_{\text{executed}}}{N_{\text{total}}}$ | $N_{\text{total}}$ (All queries) | Distractors executing increase coverage (undesirably). | Calculated using Wilson continuity score. |
| **Operational Coverage** | $\frac{N_{\text{executed, operational}}}{N_{\text{operational}}}$ | $N_{\text{operational}}$ ($N=33$ in Phase 6) | Distractors are excluded from the denominator. | Calculated via Wilson CI. |
| **Distractor Coverage** | $\frac{N_{\text{executed, distractor}}}{N_{\text{distractor}}}$ | $N_{\text{distractor}}$ ($N=5$ in Phase 6) | Operational queries excluded. Baseline and Abstention both achieved 0.0% here. | Calculated via Wilson CI. |
| **Selective Risk** | $\frac{N_{\text{errors among executed}}}{N_{\text{executed}}}$ | $N_{\text{executed}}$ ($N=33$) | If an unhandled distractor executes with an error, it is counted in the numerator. | Calculated via Wilson CI. |
| **False-Positive Tool Execution (FPR)** | $\frac{N_{\text{executed, distractor}}}{N_{\text{distractor}}}$ | $N_{\text{distractor}}$ ($N=5$) | **Strictly $N_{\text{distractor}}$**. Operational queries cannot pollute this denominator. | Calculated via Wilson CI. |
| **Missed Valid Requests (FNR)** | $\frac{N_{\text{abstained, operational}}}{N_{\text{operational}}}$ | $N_{\text{operational}}$ ($N=33$) | Distractors cannot pollute this denominator. | Calculated via Wilson CI. |
| **Overall Task Success** | $\frac{N_{\text{correct\_exec}} + N_{\text{safe\_abstain}}}{N_{\text{total}}}$ | $N_{\text{total}}$ ($N=38$) | **Distractor safe rejection counts as task success; distractor execution counts as failure.** | Calculated via Wilson CI. |

#### Denominator Audit Verdict:
1. **Distractor separation is mathematically correct:** Distractors safely abstaining **DO NOT** count as operational task executions. They are strictly segregated into the distractor denominator ($N=5$).
2. **Task success denominator:** For operational queries, success requires correct tool selection and valid arguments. For non-operational/distractor queries, success requires *safe non-execution* (abstention or direct conversational response).
3. **Reference transcript provenance:** Reference transcripts were manually authored in the frozen manifests before running the evaluation. They were **NOT** derived from Whisper predictions or cached model outputs.

---

## 3. Challenge Suite Verification: Audio vs. Text

The repository contains several distinct evaluation suites across its phases. They must be clearly distinguished:

| Suite Name | Modality | Sample Size ($N$) | Abstention Evaluated? | Genuine Human Mic Audio? | Success Rate |
|---|---|---|---|---|---|
| **Phase 4.6 Decontaminated Challenge** | Text only | 50 | Yes | No (text prompts) | **68.0%** (decontaminated) |
| **Phase 4.6 Contaminated Challenge (Historical)** | Text only | 50 | Yes | No (text prompts) | **84.0%** (contaminated by train/test leakage) |
| **Phase 5 Generalization Benchmark** | Text only | 150 | Yes | No (text prompts) | **86.7%** (Coverage 91.3%, Selective Risk 5.1%) |
| **Phase 5 Distractor Suite** | Text only | 20 | Yes | No (text prompts) | Baseline FPR **85.0%** $\rightarrow$ Abstention FPR **0.0%** |
| **Phase 6 Authentic Human Audio (`real_audio_v1`)** | MPEG Audio | 6 | **YES** | **YES (Personal microphone recordings)** | Baseline **100.0%** vs Abstention **100.0%** |
| **Phase 6 Standardized Benchmark Audio (`benchmark_audio_v1`)** | WAV Audio | 32 | **YES** | No (Standardized synthesized & shifted speech) | Baseline **100.0%** vs Abstention **100.0%** |
| **Phase 6 Semantic Conflict Suite (`semantic_conflict_v1`)** | Text only | 10 | Planned | No (Text challenge) | Ground-truth frozen ($N=10$) |

### Key Clarification on Personal Microphone Recordings:
- **Were personal microphone recordings evaluated against abstention?**  
  **YES.** The 6 authentic personal microphone recordings in `data/audio/*.mpeg` (`real_audio_v1`) were evaluated through the entire paired evaluation pipeline in Run `f196279a` and consolidated in `consolidated_phase6_summary.json`.
- The evaluation confirmed:
  - 5 operational CRM/Analytics/Support queries correctly transcribed by Whisper (`WER = 0.0%`), routed, and executed with correct database parameters.
  - 1 distractor query (`Capital.mpeg`: *"What is the capital city of France?"*) correctly recognized as non-operational, bypassing database tool invocation (`abstention_decision: DIRECT`, `executed: False`).

---

## 4. Frontend Evaluation Lab Status

The Evaluation Lab has been implemented in the primary frontend (`voice_chat.html` and `app/voice_chat.html`):
- **Live Data Fetching:** Consumes `/evaluation/datasets`, `/evaluation/runs`, `/evaluation/runs/{id}/summary`, `/evaluation/runs/{id}/cases`, and `/evaluation/audio/{case_id}`. No metrics are hardcoded.
- **Side-by-side Comparative Panels:** Displays Baseline vs. Abstention with sample counts and Wilson 95% Confidence Intervals.
- **Audio Playback:** Direct `<audio controls>` streaming for all 38 audio cases.
- **Provenance Badges:** Clear green badges for `🎤 Authentic Human Microphone Recording`, purple badges for `🔊 Standardized Benchmark Audio`, and blue badges for `📝 Text Challenge Suite`.

---

## 5. Summary of Verified, Unsupported, and Qualified Claims

### Verified Claims:
1. **Dual Evaluation Conditions:** `run_paired_evaluation.py` executes paired evaluations where baseline genuinely turns off abstention (`enable_abstention=False`) while maintaining identical ASR text and tools.
2. **Cryptographic Integrity:** All 38 audio cases, manifests, and historical frozen test suites have matching SHA256 checksums verified by `evaluation/datasets/verify_datasets.py`.
3. **Distractor Rejection:** Distractor queries do not falsely execute tools when abstention is active.
4. **WER Ground Truth Independence:** Reference transcripts were manually defined in JSONL manifests, not generated by ASR.

### Qualified / Contextualized Claims:
1. **Sample Size ($N=6$ for authentic audio):** The authentic human recording suite has $N=6$. While Whisper achieved 0.0% WER and the pipeline achieved 100% task success, the 95% Wilson confidence interval is $[61.0\%, 100.0\%]$. Scaling to $N=100$ following `collection_manifest_schema.json` is required for statistical power $>90\%$.
2. **Contaminated vs. Decontaminated Scores:** The historical Phase 4.6 claim of 84.0% was from a contaminated challenge split; the true decontaminated score is 68.0%. The Evaluation Lab explicitly surfaces this distinction.

### Unsupported Claims Prevented:
- We **do not** claim that the 32 benchmark WAV files are authentic human recordings; they are correctly labeled as formant-shifted benchmark audio.
- We **do not** claim that `semantic_conflict_v1` is an audio benchmark; it is registered as a text-only challenge suite.
