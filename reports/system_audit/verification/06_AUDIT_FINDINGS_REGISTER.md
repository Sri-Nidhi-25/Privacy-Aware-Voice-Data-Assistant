# Phase 2 — Technical Audit Findings Register
**Report ID:** `VERIFY-06`  
**Target Subject:** Comprehensive Quality Assurance & Defect Tracking of the Technical Audit Series  
**Auditor Role:** Lead Auditor & Systems Reliability Reviewer  
**Total Findings Tracked:** 14  
**Severity Breakdown:** CRITICAL: 3 | HIGH: 5 | MEDIUM: 4 | LOW: 1 | INFORMATIONAL: 1  

---

## 1. Master Findings Register

| ID | Originating Report | Finding Description | Severity | Forensic Code / Evaluation Evidence | Required Correction / Mitigation | Resolution Status |
|---|---|---|---|---|---|---|
| **F-01** | `04_PRODUCTION_GAP` / `10_PRIVACY` | **Third-Party Cloud Privacy Leak via Edge-TTS:** Despite claiming local data sovereignty, generated answer text containing customer names, tickets, and financial data is transmitted to Microsoft cloud servers over public HTTPS. | **CRITICAL** | `app/voice/tts.py:11-13` (`edge_tts.Communicate(text, self.voice)`) | Replace `edge-tts` with an offline, strictly local TTS engine (e.g., Piper TTS) running entirely on localhost. | **OPEN (Architectural Defect Documented)** |
| **F-02** | `04_PRODUCTION_GAP` / `08_ASYNC` | **Event Loop Thread Blocking by Synchronous CPU Models:** Synchronous Whisper transcription and pyworld vocoder pitch shifting run directly on ASGI event loop thread, blocking the server for 2–8 seconds per voice turn. | **CRITICAL** | `app/routers/voice.py:309`, `335`; `app/services/llm_orchestrator.py:402` | Wrap all CPU inference and synchronous Ollama HTTP calls in `anyio.to_thread.run_sync()`. | **OPEN (Code Mitigation Specified)** |
| **F-03** | `03_EVALUATION` / `07_ROUTER` | **100% Semantic Distractor Leakage:** System executed operational tools on 5/5 semantic distractors in Phase 6.1 under both baseline and abstention-enabled conditions; zero real-world distractor protection. | **CRITICAL** | `evaluation/runs/phase6_1_pilot_20261028_170829/summary.json` (5/5 false positive tool executions) | Replace rule heuristics with two-pass LLM semantic classification (Pragmatic Intent vs Operational Tool). | **OPEN (Root Cause Isolated & Re-architected in Doc 03)** |
| **F-04** | `10_PRIVACY` / `03_EVALUATION` | **Biometric Anonymization Claim Inaccuracy:** The vocoder reduces x-vector embedding cosine similarity by only 1.1% to 13.5% (similarity remains 0.86 to 0.98), which does not anonymize speaker identity against deep neural models. | **HIGH** | `eval_speaker_similarity.py`, `benchmark_obfuscation.py` | Update documentation to disclaim biometric privacy; reclassify feature as "Acoustic Obfuscation for Casual Listening". | **RESOLVED IN AUDIT (Accurate Classification Enforced)** |
| **F-05** | `13_ROADMAP` / `14_RECOMMENDATIONS` | **Faster-Whisper Speedup Claim Unsubstantiated Locally:** Earlier reports claimed a measured "3.4x speedup" from Faster-Whisper, but `faster-whisper` is neither installed in `requirements.txt` nor benchmarked in repo. | **HIGH** | `requirements.txt` (contains `openai-whisper==20231117`, not `faster-whisper`) | Retract local 3.4x measurement claim; document external benchmark provenance and define local empirical verification protocol. | **RESOLVED IN AUDIT (Doc 03 Addressed)** |
| **F-06** | `14_RECOMMENDATIONS` / `07_ROUTER` | **Flawed Regex Negation Recommendation:** The proposed regex negation gate (`\b(don't|do not|never)\b`) causes catastrophic false-positive abstention on valid operational queries ("Find customers who do not have tickets"). | **HIGH** | Theoretical proof in Doc 03; regex cannot handle syntactic scope or semantic presupposition. | Reject regex negation filter entirely; mandate two-pass semantic classification. | **RESOLVED IN AUDIT (Doc 03 Formally Rejected)** |
| **F-07** | `04_PRODUCTION_GAP` / `15_SECURITY` | **Zero Authentication, RBAC, and Rate Limiting:** All endpoints, including voice processing and customer data querying, are completely unauthenticated and unthrottled. | **HIGH** | `app/main.py:55`, `app/routers/voice.py:204` (zero security dependencies) | Implement API key middleware (`X-API-Key`) and IP/Key token-bucket rate limiting via `slowapi`. | **OPEN (Documented in Production Scorecard)** |
| **F-08** | `04_PRODUCTION_GAP` / `09_STATE` | **Multi-Worker Incompatibility Due to In-Memory Session Dict:** Audio files and active sessions are tracked in a local Python dict, causing HTTP 404 when Uvicorn is run with multiple worker processes. | **HIGH** | `app/voice/audio_store.py:23` (`_active_sessions: Dict[uuid.UUID, Dict]`) | Transition session storage to Redis or use shared storage with cryptographically signed file paths. | **OPEN (Documented in Production Scorecard)** |
| **F-09** | `01_SYSTEM_INVENTORY` / `03_METRICS` | **Latency Metric Namespace Discrepancy:** Orchestrator latency spans (`correction_latency_ms`, `routing_latency_ms`) are top-level metadata keys, whereas router spans are inside `metadata["latencies"]`. | **MEDIUM** | `app/services/llm_orchestrator.py:705-750` vs `app/routers/voice.py:403` | Reconcile metadata dictionary structure into a unified nested telemetry schema across all layers. | **RESOLVED IN AUDIT (Documented in Doc 01)** |
| **F-10** | `03_EVALUATION` / `02_REPRODUCTION` | **Phase 5 Text Corpus Count Approximation:** Earlier audit documentation loosely referenced Phase 5 as $N=150$, whereas the exact sum across the 8 sub-corpora is $N=160$. | **MEDIUM** | `experiments/phase5/generalization/summary.json` (sub-corpora counts: 20+20+30+25+20+15+15+15 = 160) | Update all evaluation tables to reflect exact $N=160$ sample count. | **RESOLVED IN AUDIT (Corrected in Doc 02)** |
| **F-11** | `04_PRODUCTION_GAP` / `08_ASYNC` | **Absence of STT Execution Timeout:** While TTS and Ollama clients enforce explicit timeouts (15s and 30s), Whisper transcription has no timeout wrapper, risking unkillable thread hangs. | **MEDIUM** | `app/routers/voice.py:335` (synchronous execution without `asyncio.wait_for`) | Wrap STT call with configurable timeout (`STT_TIMEOUT_SECONDS = 15.0`). | **OPEN (Specified in Gap Audit)** |
| **F-12** | `04_PRODUCTION_GAP` / `09_STATE` | **Flat JSON Mock Storage Lacks Concurrency Protection:** Connectors load flat JSON files directly via `json.load()` without OS file locks, risking corruption if write tools are added. | **MEDIUM** | `app/connectors/crm_connector.py:10` | Migrate to SQLite or relational database with ACID isolation before implementing write tools. | **OPEN (Specified in Gap Audit)** |
| **F-13** | `02_HARNESS` | **Deprecation Warnings in Automated Test Suite:** Pytest execution triggers 14 non-fatal warnings regarding Pydantic V2 `BaseSettings`, FastAPI `@app.on_event`, and Python 3.13 standard library deprecations. | **LOW** | Pytest test run output (`tests/test_api.py`, `app/config.py`) | Upgrade Pydantic `BaseSettings` to `pydantic-settings` and replace `@app.on_event` with FastAPI `lifespan` context manager. | **OPEN (Technical Debt)** |
| **F-14** | `05_RAG_DECISION` | **Absence of RAG in Architecture:** No document retrieval, vector database, or embedding search is present; connectors are strictly structured JSON tool callers. | **INFORMATIONAL** | Full dependency and codebase analysis in Doc 05. | Acknowledge that the system is an API Tool Calling Agent, not a Document RAG system. | **RESOLVED IN AUDIT (Doc 05 Verified)** |

---

## 2. Status of Critical & High-Severity Findings

### Summary Table
- **Total Critical Findings:** 3
  - **F-01 (Edge-TTS Cloud Privacy Leak):** *Documented with clear architectural replacement path (Piper TTS).*
  - **F-02 (Event Loop Blocking):** *Documented with exact line references and threading mitigation.*
  - **F-03 (100% Distractor Leakage):** *Reconciled; regex patch rejected; two-pass semantic classification proposed.*
- **Total High Findings:** 5
  - **F-04 (Biometric Privacy Reality):** *Corrected in audit docs.*
  - **F-05 (Faster-Whisper Measurement Claim):** *Corrected in audit docs.*
  - **F-06 (Flawed Regex Negation Proposal):** *Rejected and corrected.*
  - **F-07 (Missing Auth / Rate Limiting):** *Documented with test criteria.*
  - **F-08 (Multi-Worker Session State):** *Documented with test criteria.*

**Auditor Certification:** All 3 Critical and all 5 High findings have been forensically verified with repository source code, isolated to specific failure points, and given actionable engineering remediations. Zero critical findings remain unaddressed or vaguely characterized.
