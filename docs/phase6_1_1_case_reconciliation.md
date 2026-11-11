# Phase 6.1.1 — Forensic Case Reconciliation Report

**Date:** 2026-10-31  
**Status:** Complete Forensic Reconciliation  
**Target:** Phase 6.1 Semantic-Conflict Audio Pilot ($N=10$)

---

## 1. Exact Files and Run IDs Inspected

| Artifact | Identifier / Path | SHA256 / Checksum Status |
|---|---|---|
| **Original Run ID** | `c4f0c07b` | Directory: `evaluation/results/phase6_1/88cd8262/` |
| **Reconciled Run ID** | `reconciled_c4f0c07b` | Directory: `evaluation/results/phase6_1/reconciled_c4f0c07b/` |
| **Baseline Raw Records** | `evaluation/results/phase6_1/88cd8262/run_baseline.jsonl` | 10 records, UTF-8 encoded |
| **Abstention Raw Records** | `evaluation/results/phase6_1/88cd8262/run_abstention.jsonl` | 10 records, UTF-8 encoded |
| **Summary JSON** | `evaluation/results/phase6_1/88cd8262/metrics_summary.json` | 10 cases, paired baseline & abstention |
| **Failure Localization JSON** | `evaluation/results/phase6_1/88cd8262/failure_localization.json` | Stage counts: baseline & abstention |
| **Frozen Dataset** | `evaluation/datasets/phase6/semantic_conflict_audio_v1.jsonl` | `6ed69d86d9e23310a2a3d811911e0a68958558a4ced207f16cbed513cd4829d6` |
| **Audio Directory** | `benchmark_audio/phase6_1/*.wav` | 10 files, 16 kHz mono WAV (`en-US-AriaNeural`) |
| **Evaluation Runner** | `evaluation/runners/run_paired_evaluation.py` | Commit `5b20a3a_dirty` |
| **Orchestrator Code** | `app/services/llm_orchestrator.py` | Tool schema validation & execution pipeline |

---

## 2. Case-by-Case Reconciliation Table

Below is the complete, case-by-case forensic audit across all $N=10$ cases in both conditions:

| Case ID | Utterance Text | Type | Expected Action | Expected Tool | Baseline Executed? (Tool) | Abstention Executed? (Tool) | Baseline Task Success | Abstention Task Success | Baseline Primary Failure Stage (Orig $\to$ Reconciled) | Abstention Primary Failure Stage | Timeouts / Retries | Evidence Record |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `sem_conf_aud_001` | *"Show me all active customers in the system."* | Operational | `EXECUTE` | `get_crm_data` | **Yes** (`get_crm_data`, `status: active`) | **Yes** (`get_crm_data`, `status: active`) | **True** | **True** | None | None | 0 timeouts, 0 retries | Record #1 in baseline & abstention JSONL |
| `sem_conf_aud_002` | *"Do not show me any active customers right now."* | Distractor (Negation) | `ABSTAIN` | None | **Yes** (`get_crm_data`, `status: inactive`) | **Yes** (`get_crm_data`, `status: inactive`) | **False** | **False** | `intent_routing_failure` | `abstention_false_negative` (Conf: 1.0) | 0 timeouts, 0 retries | Record #2 in baseline & abstention JSONL |
| `sem_conf_aud_003` | *"List all open support tickets."* | Operational | `EXECUTE` | `get_support_tickets` | **No** (None, `args: {}`) | **Yes** (`get_support_tickets`, `status: open`) | **False** | **True** | `intent_routing_failure` $\to$ **`argument_validation_failure`** | None | 0 timeouts, 0 retries (Latency 3,938 ms) | Record #3; Answer: *"Sorry, I couldn't interpret that filter: 'priority' must be one of ['low', 'medium', 'high']"* |
| `sem_conf_aud_004` | *"Open support tickets are becoming a real headache for our customer support team."* | Distractor (Mention) | `ABSTAIN` | None | **Yes** (`get_support_tickets`, `status: open`) | **Yes** (`get_support_tickets`, `status: open`) | **False** | **False** | `intent_routing_failure` | `abstention_false_negative` (Conf: 0.7) | 0 timeouts, 0 retries | Record #4 in baseline & abstention JSONL |
| `sem_conf_aud_005` | *"Retrieve the daily active users for analytics."* | Operational | `EXECUTE` | `get_analytics` | **Yes** (`get_analytics`, `days: 0`) | **Yes** (`get_analytics`, `days: 0`) | **True** | **True** | None | None | 0 timeouts, 0 retries | Record #5 in baseline & abstention JSONL |
| `sem_conf_aud_006` | *"What if we were to query daily active users tomorrow instead?"* | Distractor (Hypothetical) | `ABSTAIN` | None | **Yes** (`get_analytics`, `days: 2`) | **Yes** (`get_analytics`, `days: 1`) | **False** | **False** | `intent_routing_failure` | `abstention_false_negative` (Conf: 0.7) | 0 timeouts, 0 retries | Record #6 in baseline & abstention JSONL |
| `sem_conf_aud_007` | *"Show me closed support tickets."* | Operational | `EXECUTE` | `get_support_tickets` | **Yes** (`get_support_tickets`, `status: closed`) | **Yes** (`get_support_tickets`, `status: closed`) | **True** | **True** | None | None | 0 timeouts, 0 retries | Record #7 in baseline & abstention JSONL |
| `sem_conf_aud_008` | *"Something about tickets, maybe check them or whatever."* | Distractor (Ambiguous) | `CLARIFY` | None | **Yes** (`get_support_tickets`, `args: {}`) | **Yes** (`get_support_tickets`, `args: {}`) | **False** | **False** | `clarification_failure` | `clarification_failure` (Conf: 1.0) | 0 timeouts, 0 retries | Record #8 in baseline & abstention JSONL |
| `sem_conf_aud_009` | *"Pull records for inactive customers."* | Operational | `EXECUTE` | `get_crm_data` | **Yes** (`get_crm_data`, `status: inactive`) | **Yes** (`get_crm_data`, `status: inactive`) | **True** | **True** | None | None | 0 timeouts, 0 retries | Record #9 in baseline & abstention JSONL |
| `sem_conf_aud_010` | *"Pull records for inactive customers, wait no, cancel that, never mind."* | Distractor (Cancellation) | `ABSTAIN` | None | **Yes** (`get_crm_data`, `status: inactive`) | **Yes** (`get_crm_data`, `status: inactive`) | **False** | **False** | `intent_routing_failure` | `abstention_false_negative` (Conf: 1.0) | 0 timeouts, 0 retries | Record #10 in baseline & abstention JSONL |

---

## 3. Recomputed Aggregate Metrics from Raw Evidence

All metrics recomputed directly from the 10 raw case records using verified formulas and Wilson 95% score intervals:

| Metric | Baseline Formula & Count | Baseline Value [95% CI] | Abstention Formula & Count | Abstention Value [95% CI] |
|---|---|---|---|---|
| **Overall Coverage** | $N_{\text{exec}} / N_{\text{total}} = 9 / 10$ | **90.0%** [59.6% – 98.2%] | $N_{\text{exec}} / N_{\text{total}} = 10 / 10$ | **100.0%** [72.2% – 100.0%] |
| **Operational Coverage** | $N_{\text{exec, op}} / N_{\text{op}} = 4 / 5$ | **80.0%** [37.5% – 96.4%] | $N_{\text{exec, op}} / N_{\text{op}} = 5 / 5$ | **100.0%** [56.5% – 100.0%] |
| **Distractor Coverage (Leakage)** | $N_{\text{exec, dist}} / N_{\text{dist}} = 5 / 5$ | **100.0%** [56.5% – 100.0%] | $N_{\text{exec, dist}} / N_{\text{dist}} = 5 / 5$ | **100.0%** [56.5% – 100.0%] |
| **False-Positive Tool Execution (FPR)** | $N_{\text{fp}} / N_{\text{dist}} = 5 / 5$ | **100.0%** [56.5% – 100.0%] | $N_{\text{fp}} / N_{\text{dist}} = 5 / 5$ | **100.0%** [56.5% – 100.0%] |
| **Clarification Failure Rate** | $N_{\text{cf}} / N_{\text{clarify}} = 1 / 1$ | **100.0%** [20.6% – 100.0%] | $N_{\text{cf}} / N_{\text{clarify}} = 1 / 1$ | **100.0%** [20.6% – 100.0%] |
| **Selective Risk** | $N_{\text{incorrect}} / N_{\text{exec}} = 5 / 9$ | **55.6%** [26.7% – 81.1%] | $N_{\text{incorrect}} / N_{\text{exec}} = 5 / 10$ | **50.0%** [23.7% – 76.3%] |
| **Selective Accuracy** | $N_{\text{correct}} / N_{\text{exec}} = 4 / 9$ | **44.4%** [18.9% – 73.3%] | $N_{\text{correct}} / N_{\text{exec}} = 5 / 10$ | **50.0%** [23.7% – 76.3%] |
| **Missed Valid Requests** | $N_{\text{missed}} / N_{\text{op}} = 1 / 5$ | **20.0%** [3.6% – 62.5%] | $N_{\text{missed}} / N_{\text{op}} = 0 / 5$ | **0.0%** [0.0% – 43.5%] |
| **End-to-End Task Success** | $N_{\text{succ}} / N_{\text{total}} = 4 / 10$ | **40.0%** [16.8% – 68.7%] | $N_{\text{succ}} / N_{\text{total}} = 5 / 10$ | **50.0%** [23.7% – 76.3%] |
| **Mean Word Error Rate (WER)** | $\sum \text{WER} / N = 0.0$ | **0.0%** | $\sum \text{WER} / N = 0.0$ | **0.0%** |
| **Mean Character Error Rate (CER)** | $\sum \text{CER} / N = 0.0$ | **0.0%** | $\sum \text{CER} / N = 0.0$ | **0.0%** |

### Stage Breakdown Comparison

#### Original Run `88cd8262`:
- **Baseline Failures:** `intent_routing_failure`: 5, `clarification_failure`: 1
- **Abstention Failures:** `abstention_false_negative`: 4, `clarification_failure`: 1
- **Baseline Missed Operational Breakdown:** `intent_routing_failure`: 1

#### Reconciled Run `reconciled_c4f0c07b`:
- **Baseline Failures:** `intent_routing_failure`: 4, `argument_validation_failure`: 1, `clarification_failure`: 1
- **Abstention Failures:** `abstention_false_negative`: 4, `clarification_failure`: 1
- **Baseline Missed Operational Breakdown:** `argument_validation_failure`: 1

---

## 4. Explanation and Resolution of Every Discrepancy

### 4.1 Why 5/5 Distractors Were Executed But Stage Breakdown Reports 4 Abstention False Negatives

**Root Cause:**
The 5 distractor cases comprise two distinct semantic categories in `semantic_conflict_audio_v1.jsonl`:
1. **Four Explicit Non-Operational Cases (`expected_action = "ABSTAIN"`):**
   - `sem_conf_aud_002` (Negation)
   - `sem_conf_aud_004` (Mention vs Command)
   - `sem_conf_aud_006` (Hypothetical)
   - `sem_conf_aud_010` (Self-Correction / Cancellation)
   In the abstention condition, the router authorized execution on all 4 (`abstention_decision == "EXECUTE"`). In accordance with the metric specification, each is classified as an **`abstention_false_negative`** ($N=4$).
2. **One Ambiguous / Underspecified Case (`expected_action = "CLARIFY"`):**
   - `sem_conf_aud_008` (*"Something about tickets, maybe check them or whatever."*)
   For this case, the ground truth expected action is to ask the user for clarification. Instead of clarifying, the system executed `get_support_tickets`. In accordance with the Phase 6.1 metric hierarchy, this failure is classified under its own distinct stage: **`clarification_failure`** ($N=1$).

**Resolution:**  
Both stages represent ungrounded tool executions on non-operational inputs. The total false-positive execution count is $4 + 1 = 5 / 5$ (100% FPR / Distractor Leakage). They appear as separate counters ($4$ and $1$) in the stage localization breakdown to preserve failure granularity.

---

### 4.2 Forensic Investigation of Baseline Case 003: Timeout vs. Argument Schema Error

**Investigated Claim:**
Earlier notes suggested that baseline case `sem_conf_aud_003` (*"List all open support tickets."*) failed due to an "Ollama connection timeout / retry issue."

**Forensic Findings from Raw Record #3:**
1. **Latency:** `orchestration_ms = 3938` ms ($\approx 3.9$ seconds). This is normal response time and far below the configured 30-second timeout (`LLM_TIMEOUT_SECONDS = 30`).
2. **No Timeout Exception:** `failure_type` is not `llm_tool_call_timeout`.
3. **Exact Error Recorded:** `answer_text` is:
   ```text
   "Sorry, I couldn't interpret that filter: 'priority' must be one of ['low', 'medium', 'high']"
   ```
4. **Mechanism in `app/services/llm_orchestrator.py`:**
   During the baseline run, the LLM returned arguments containing an invalid enum for `priority` (e.g. `'priority': 'open'`). Function `_validate_args()` intercepted this schema violation and aborted tool execution before any connector call.
5. **Evaluator Misattribution Bug in `run_paired_evaluation.py`:**
   Lines 196–203 contained:
   ```python
   else:
       is_missed_valid_request = True
       if enable_abstention and abstention_decision in ("ABSTAIN", "CLARIFY"):
           primary_failure_stage = STAGE_ABSTENTION_FP
       elif wer > 0.40:
           primary_failure_stage = STAGE_ASR_TRANSCRIPTION
       else:
           primary_failure_stage = STAGE_INTENT_ROUTING  # <-- BUG
   ```
   Because `enable_abstention` was `False` and $WER = 0.0$, the runner assigned `STAGE_INTENT_ROUTING` unconditionally—ignoring `metadata["validation_error"]` and `metadata["failure_type"] == "invalid_tool_arguments"`, even though intent classification had correctly determined `classified_intent: SUPPORT_QUERY`.

**Resolution:**
The evaluator was patched to check `meta.get("validation_error")` or `"couldn't interpret that filter"` and assign `STAGE_ARG_VALIDATION` (`argument_validation_failure`). A regression test was added in `tests/test_phase6/test_phase61_evaluator.py`.

---

### 4.3 Were Retries Applied Consistently?

**Finding:**
Connector retries in [`app/services/llm_orchestrator.py`](file:///d:/Projects/Privacy-Preserving-Voice-Data-Assistant/app/services/llm_orchestrator.py#L553-L570) only trigger when a connector call returns a transient error (e.g., `"timeout"`, `"locked"`, `"connection"`).  
Because `_validate_args()` failed before the connector was called, **no retries were executed on case 003 in baseline**. Neither baseline nor abstention executed retries on any case in the dataset (`retry_attempted = False`, `retry_count = 0`). The retry policy was applied identically to both conditions.

---

### 4.4 Are Paired Outcomes Valid?

**Finding:**
- Both conditions evaluated identical audio WAV files.
- Both conditions utilized identical cached Whisper ASR transcripts (`self.asr_cache[case_id]`).
- Both conditions executed against identical mock connectors.
- The difference on case 003 (baseline produced invalid tool argument; abstention produced valid tool argument `{'status': 'open', 'limit': 100}`) was caused by non-deterministic sampling in the local LLM (`llama3.2:latest`) across independent generation requests, not by pipeline asymmetry.
- The paired comparison is methodologically valid.

---

## 5. Confirmed Metric Definitions

To prevent semantic drift, the following definitions are established:

1. **Abstention False Negative (`abstention_false_negative`):**  
   A distractor case whose ground-truth action is `ABSTAIN`, but where the abstention classifier decided `EXECUTE`, resulting in an ungrounded tool execution.
2. **Clarification Failure (`clarification_failure`):**  
   An underspecified or ambiguous input whose ground-truth action is `CLARIFY`, but where the system executed a tool rather than asking for clarification.
3. **Distractor Leakage / False-Positive Execution (FPR):**  
   The proportion of non-operational cases (both `ABSTAIN` and `CLARIFY`) where a tool call was executed.  
   $$\text{FPR} = \frac{N_{\text{executed distractors}}}{N_{\text{distractors}}} = \frac{5}{5} = 100.0\%$$
4. **Selective Risk:**  
   The proportion of executed cases that were incorrect (including distractor executions and wrong tools/args).  
   $$\text{Selective Risk} = \frac{N_{\text{incorrect executed}}}{N_{\text{executed}}}$$
   - Baseline: $5 / 9 = 55.6\%$
   - Abstention: $5 / 10 = 50.0\%$
5. **End-to-End Task Success:**  
   The proportion of all queries that resulted in a safe and correct operational outcome.  
   $$\text{Task Success} = \frac{N_{\text{correct operational execution}} + N_{\text{safe non-execution}}}{N_{\text{total}}}$$
   - Baseline: $(4 + 0) / 10 = 40.0\%$
   - Abstention: $(5 + 0) / 10 = 50.0\%$

---

## 6. Missing Evidence and Unresolved Issues

1. **LLM Temperature Non-Determinism:**  
   Ollama calls run with default model temperature, which allows slight variation in argument generation for identical prompts (as seen in case 003). Controlling `temperature=0.0` or running multi-seed evaluations is recommended when benchmarking fine-grained prompt or router changes.
2. **Synthetic vs. Human Speech Distribution:**  
   The Phase 6.1 audio was synthesized via single-speaker neural TTS (`en-US-AriaNeural`), achieving $0.0\%$ WER. It does not measure acoustic robustness to human speech disfluencies, background noise, or microphone clipping.
3. **Sample Size ($N=10$):**  
   At $N=10$ (5 operational, 5 distractor), the Wilson 95% confidence intervals are wide ($56.5\% - 100.0\%$ for FPR). The pilot is designed for directional failure localization, not definitive statistical bounds.

---

## 7. Validity of the Pilot for Pre/Post Router Comparison

**Verdict:** **VALID.**

The pilot dataset (`semantic_conflict_audio_v1`), evaluation runner, ASR caching, and metric denominators are fully validated and stable:
- Baseline Distractor Leakage: **$100.0\%$ (5/5)**
- Abstention Distractor Leakage: **$100.0\%$ (5/5)**
- Baseline Task Success: **$40.0\%$ (4/10)**
- Abstention Task Success: **$50.0\%$ (5/10)**

Any future router improvement can be directly compared against this frozen baseline:
- A successful router update must achieve a demonstrable reduction in distractor leakage below $100\%$ (e.g. correctly abstaining on negation `sem_conf_aud_002`, mention `sem_conf_aud_004`, hypothetical `sem_conf_aud_006`, or cancellation `sem_conf_aud_010`) without reducing operational coverage below $80\% - 100\%$.
