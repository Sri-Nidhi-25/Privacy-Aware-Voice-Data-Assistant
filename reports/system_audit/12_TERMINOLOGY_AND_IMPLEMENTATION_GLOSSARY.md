# Report 12 — Terminology & Implementation Coverage Glossary

**Audit Document:** `reports/system_audit/12_TERMINOLOGY_AND_IMPLEMENTATION_GLOSSARY.md`  
**HEAD Commit:** `5b20a3a`  
**Scope:** 50+ Core AI Systems Engineering & Reliability Concepts  
**Auditor Epistemic Stance:** Grounded mapping between industry terminology and actual repository implementation  

---

## 1. Concept Coverage Map & Glossary

The table below maps standard AI and systems engineering terminology directly to the repository implementation:

| Term | Plain-Language Meaning | Why It Matters Here | Current Coverage | Exact Source Evidence | Maturity (0–5) | What Is Missing / Remaining Gap |
|---|---|---|---|---|---|---|
| **AI / LLM Evaluation** | Measuring AI model performance against ground-truth benchmarks. | Core mission of the project's evaluation harness. | **Measured** | `evaluation/runners/run_paired_evaluation.py` | **4** | Multi-seed variance CI checks. |
| **Evaluation Harness** | Code that executes benchmarks, scores outputs, and computes metrics. | Enables reproducible measurement of pipeline stages. | **Operationalized** | `evaluation/runners/run_paired_evaluation.py` | **4** | Automated CI integration. |
| **Software Test Harness** | Test framework validating deterministic code assertions. | Prevents code regressions in business rules. | **Tested** | `tests/` (152 pytest cases) | **3** | Continuous integration pipeline (`.github/`). |
| **Observability** | Ability to infer internal system state from external outputs. | Pinpoints which stage caused a failure. | **Tested** | `app/routers/voice.py:latencies_ms`, Turn Inspector | **3** | Distributed tracing (OpenTelemetry). |
| **Tracing / Spans** | Recording timing and metadata for sub-operations in a request. | Diagnoses latency bottlenecks across models. | **Implemented** | `app/services/llm_orchestrator.py:L670-L750` | **3** | W3C traceparent headers; span export. |
| **Telemetry** | Automated collection and transmission of operational measurements. | Monitors health and usage trends. | **Partially Implemented** | `metadata` dictionary returned in HTTP response | **2** | Centralized metric aggregation (Prometheus). |
| **Reliability** | Probability that the system functions correctly over time. | Core thesis: prevent hallucinations and crashes. | **Measured** | `tests/test_invariants.py`, `failure_localization.py` | **3** | Exponential backoff and circuit breakers. |
| **Robustness** | Ability to maintain performance under acoustic or semantic shifts. | Pipeline must handle shifted audio and distractors. | **Measured** | `benchmark_obfuscation.py:results.csv` | **3** | Multi-accent and noisy human speech tests. |
| **Generalization** | Performance on unseen queries outside training/prompt templates. | Tests whether intent routing works beyond keywords. | **Measured (Text)** | `experiments/phase5/generalization/summary.json` | **3** | Audio generalization on unseen human speakers. |
| **Hallucination** | Model generating unsupported or fabricated statements. | Prevented via zero-fabrication connectors. | **Tested** | `app/services/llm_orchestrator.py:L572-L585` | **3** | Semantic drift validation on summarization. |
| **Grounding** | Constraining model answers strictly to verified source data. | Queries must only report real CRM/ticket data. | **Implemented** | `app/connectors/*.py` | **3** | Document-level grounding (RAG is absent). |
| **RAG (Retrieval-Augmented Gen)** | Embedding and retrieving unstructured text chunks into prompts. | Clarifies that system queries structured APIs, not RAG. | **Absent** | Confirmed absent from dependencies and source | **0** | Entire RAG pipeline (if needed in future). |
| **Tool / Function Calling** | Model emitting structured JSON to invoke backend functions. | Connects voice queries to domain databases. | **Operationalized** | `app/services/llm_orchestrator.py:TOOLS` | **3** | Self-correction loop on invalid arguments. |
| **AI Agent / Orchestration** | Autonomous workflow managing multi-step reasoning and tools. | Coordinates STT $\to$ router $\to$ LLM $\to$ connector $\to$ TTS. | **Operationalized** | `app/services/llm_orchestrator.py:LLMOrchestrator` | **3** | Multi-hop autonomous planning. |
| **Selective Abstention** | Model withholding execution when confidence is low or query is OOD. | Prevents false-positive tool executions on distractors. | **Measured** | `app/services/abstention_router.py:evaluate_abstention` | **2** | Syntactic negation, mention, and hypothetical rules. |
| **Selective Risk** | Error rate calculated strictly over executed queries. | Primary metric for safe selective prediction. | **Operationalized** | `evaluation/runners/run_paired_evaluation.py:L287` | **4** | Dynamic risk-coverage threshold tuning. |
| **Calibration / Confidence** | Alignment between predicted probability and actual correctness. | Abstention threshold tuning ($0.50$). | **Partially Implemented** | `abstention_confidence` field in metadata | **2** | Empirical ECE (Expected Calibration Error) curves. |
| **Clarification** | Prompting user for more info when input is underspecified. | Separates ambiguous inputs from clear rejections. | **Measured** | `sem_conf_aud_008`, `clarification_failure` metric | **2** | Interactive conversational multi-turn follow-up. |
| **Intent Classification** | Categorizing user utterance into functional domains. | Routes to CRM, Support, Analytics, or Chat. | **Implemented** | `app/services/intent_router.py:classify_intent` | **2** | Robust embedding classifier (currently keyword regex). |
| **Argument Validation** | Enforcing typing and schema boundaries on LLM tool arguments. | Guarantees invalid JSON never reaches database. | **Operationalized** | `app/services/llm_orchestrator.py:_validate_args` | **4** | LLM error reflection and argument retry. |
| **Idempotency** | Repeating an operation without changing side-effects. | Prevents duplicate ticket creation on retries. | **Partially Implemented** | Read-only connectors; single-turn tool deduplication | **2** | `Idempotency-Key` HTTP header and write deduplication. |
| **Retry & Backoff** | Repeating failed operations with bounded delays. | Handles transient connector file locking. | **Implemented** | `app/services/llm_orchestrator.py:L553-L570` | **2** | Exponential backoff and random jitter. |
| **Circuit Breaker** | Tripping to fast-fail when a dependency is down. | Protects system when Ollama daemon crashes. | **Absent** | None in codebase | **0** | Threshold-based breaker on Ollama client. |
| **Timeout Handling** | Halting long-running operations after a fixed duration. | Prevents hanging client connections. | **Implemented** | `app/config.py:LLM_TIMEOUT_SECONDS = 120.0` | **3** | Granular per-stage STT and Vocoder timeouts. |
| **Graceful Degradation** | Maintaining partial functionality during component outages. | TTS failure returns text answer without crashing. | **Implemented** | `app/routers/voice.py:voice_query` (try/except) | **3** | Local offline TTS fallback engine. |
| **Fault Isolation** | Containing errors within their originating stage. | Vocoder crash falls back to clean audio. | **Implemented** | `app/voice/obfuscator.py:obfuscate` | **3** | Process-level isolation for CPU inference. |
| **Regression Testing** | Verifying fixed bugs do not re-emerge in future releases. | Protects against metric and stage misattributions. | **Tested** | `tests/test_phase6/test_phase61_evaluator.py` | **3** | Automated CI regression gate. |
| **Metamorphic Testing** | Testing invariants under transformed inputs (formant shifts). | Verifies transcription consistency across pitch shifts. | **Measured** | `benchmark_audio/results.csv` | **3** | Automated metamorphic test harness in pytest. |
| **Oracle-Free Testing** | Testing invariant properties without knowing the exact output. | Invariant tests verifying no tool call on low confidence. | **Tested** | `tests/test_invariants.py` | **3** | Broader property-based testing (Hypothesis). |
| **Data Contamination** | Benchmark examples present in model pretraining or prompts. | Prevents artificial inflation of evaluation scores. | **Tested** | Independent ground-truth reference transcripts | **3** | N-gram overlap audit against training sets. |
| **Distribution Shift** | Model encountering acoustic or linguistic domain variations. | Formant-shifted benchmark audio and semantic edge cases. | **Measured** | `phase5_generalization`, `semantic_conflict_audio_v1` | **3** | Real-world background noise and multi-talker audio. |
| **OOD Detection** | Detecting when user query is outside system capability. | Directs general conversational questions away from tools. | **Implemented** | `app/services/abstention_router.py:Decision.DIRECT` | **2** | Embedding-distance OOD score. |
| **Human-in-the-Loop** | Operator reviewing ambiguous or high-risk actions. | Required before executing high-risk writes. | **Absent** | None in codebase | **0** | Approval workflow for sensitive tool execution. |
| **CI / CD** | Automated build, test, and release verification. | Guarantees master branch stability. | **Absent** | No `.github/workflows` directory | **0** | GitHub Actions testing and linting workflow. |
| **Production Readiness** | System meeting operational criteria for real-world deployment. | Evaluates whether code can run beyond developer laptop. | **Partially Implemented** | Dockerfile, health endpoints, exception masking | **2** | Rate limits, auth enforcement, non-root user. |
| **SLO / SLA** | Explicit reliability and latency targets. | Establishes acceptable performance thresholds. | **Absent** | No defined SLO targets in documentation | **0** | Target SLOs (e.g. 99% success, p95 latency < 8s). |
| **p50 / p95 / p99 Latency** | Statistical percentiles of operational latency. | Accurately models tail latency for users. | **Partially Implemented** | Mean latencies reported; percentiles not calculated | **2** | Percentile latency tracking in evaluation summary. |
| **Reproducibility** | Ability to recreate exact experimental findings. | Foundation of scientific credibility. | **Operationalized** | Frozen datasets, SHA256 manifests, reproducible runner | **4** | Deterministic random seed pinning in Ollama. |
| **Data Provenance** | Documented origin and custody chain of all test assets. | Distinguishes human microphone speech from neural TTS. | **Operationalized** | `evaluation/datasets/phase6/manifest.json` | **4** | Recording metadata (microphone hardware, SNR). |
| **Voice Obfuscation** | Perturbing acoustic features to reduce re-identification. | Formant-preserving spectral warping via WORLD vocoder. | **Measured** | `app/voice/obfuscator.py`, `eval_speaker_similarity.py` | **3** | Adversarial speaker verification testing. |
| **Threat Modeling** | Structured identification of security risks and attack vectors. | Protects against injection, DoS, and data leakage. | **Partially Implemented** | Magic byte validation, CORS headers | **2** | Formal STRIDE threat assessment. |
| **Least Privilege** | Restricting tool and data access strictly to required scope. | Connectors have read-only permissions on static files. | **Implemented** | `app/connectors/*.py` | **3** | Role-based access control (RBAC) per API key. |
| **Prompt Injection** | User input manipulating LLM to bypass system instructions. | Guarding tool context against malicious data. | **Absent** | Raw connector data injected into prompt without escaping | **1** | XML data encapsulation and injection filtering. |
| **Auditability** | Maintaining an immutable record of decisions and tool calls. | Reconstructs past actions during incident reviews. | **Tested** | `evaluation/results/*.jsonl`, Turn Inspector | **3** | Tamper-evident persistent audit log. |

---

## 2. Direct Disambiguation of Industry Buzzwords

```
+-------------------------------------------------------------------------------+
| Buzzword                | Reality in This Repository                          |
+-------------------------------------------------------------------------------+
| "Autonomous Agent"      | Multi-step LLM function-calling orchestrator with   |
|                         | bounded 2-turn execution (tool call -> answer).     |
| "RAG System"            | NOT RAG. Structured API tool querying against JSON. |
| "Voice Anonymization"   | Acoustic pitch/formant shifting (cosine drop 1-13%).|
|                         | Biometric speaker verification is NOT defeated.     |
| "Enterprise-Grade"      | Advanced research prototype with excellent invariant|
|                         | tests, but lacking CI/CD, rate limits, and Redis.   |
| "Self-Correcting"       | LLM phonetic correction pass with lexical guard     |
|                         | (falls back to raw transcript if entity altered).   |
+-------------------------------------------------------------------------------+
```
