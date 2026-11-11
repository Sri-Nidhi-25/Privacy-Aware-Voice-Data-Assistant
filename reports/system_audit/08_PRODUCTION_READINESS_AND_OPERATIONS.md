# Report 08 — Production Readiness & Operations Audit

**Audit Document:** `reports/system_audit/08_PRODUCTION_READINESS_AND_OPERATIONS.md`  
**HEAD Commit:** `5b20a3a`  
**Status:** Comprehensive Operational Readiness Review  
**Auditor Epistemic Stance:** Honest separation between "runs on developer machine" and "operable in production"  

---

## 1. Direct Assessment: Is the System Production-Ready?

**VERDICT: NO.**  
The repository is an advanced, evidence-grounded research and portfolio prototype. While it features sophisticated local evaluation harnesses and invariant guards, it lacks foundational operational capabilities required to deploy, scale, monitor, and maintain a multi-user service in production.

---

## 2. Production Readiness Matrix

The table below audits the 18 critical production dimensions:

| Operational Dimension | Current Status | Repository Evidence | Operational Risk & Failure Mode | Minimum Acceptable Implementation | Priority |
|---|---|---|---|---|---|
| **1. Container Packaging** | `[PARTIALLY VERIFIED]` | `Dockerfile`, `docker-compose.yml` | `Dockerfile` installs `ffmpeg` and `libsndfile1`, but does not download Whisper weights at build time; container startup hangs while downloading weights on first run. | Pre-bake Whisper `small.en` weights into image; non-root user (`USER appuser`). | High |
| **2. Multi-Worker Concurrency** | `[NOT IMPLEMENTED]` | `app/voice/audio_store.py:L1-L109` | `EphemeralAudioStore` uses in-process Python dict. Running with `--workers 4` breaks audio playback across workers. | External Redis session store or sticky sessions. | High |
| **3. CPU Starvation / Async Blocking** | `[VERIFIED]` | `app/routers/voice.py:L340` | Whisper STT and PyWorld vocoder execute synchronously on the FastAPI asyncio thread, blocking all other requests for 2–8 seconds. | Offload CPU-bound inference to `concurrent.futures.ProcessPoolExecutor` or Celery task queue. | High |
| **4. Secrets & Authentication** | `[PARTIALLY VERIFIED]` | `app/config.py:L70-L85`, `app/utils/security.py` | API key validation exists, but if `API_KEY` is not set in `.env`, the system defaults to an insecure dev key and merely logs a warning. | Strict startup validation: crash immediately if `API_KEY` is empty or default placeholder. | Critical |
| **5. Health & Liveness Probes** | `[VERIFIED]` | `app/routers/health.py:L60-L107` | `/health/liveness` returns 200. `/health/readiness` checks Whisper, Ollama, and data files, but **synthesizes audio via Edge-TTS on every check**, consuming external bandwidth and CPU. | Readiness check should check local socket/model memory without synthesizing live audio. | High |
| **6. Rate Limiting & DoS Protection** | `[NOT IMPLEMENTED]` | None | No IP or token bucket rate limiting on `/voice/query`. A client uploading 10 concurrent 25MB WAV files causes complete CPU and memory exhaustion. | `slowapi` or Nginx reverse proxy rate limiting (e.g. 5 requests/min per IP). | High |
| **7. CI/CD Automation** | `[NOT IMPLEMENTED]` | `.github/` directory is absent | Tests must be executed manually. A developer can commit code breaking the test suite without automated gating. | GitHub Actions workflow executing `pytest` and dataset hash verification on push. | High |
| **8. Model Version Pinning** | `[PARTIALLY VERIFIED]` | `app/config.py:OLLAMA_MODEL` | Specifies `llama3.2:latest`. If Ollama updates `latest` tag upstream, model weights and prompt behaviors drift silently. | Pin exact model digest hash (e.g. `llama3.2@sha256:...`). | Medium |
| **9. Log Aggregation & Formatting** | `[PARTIALLY VERIFIED]` | `app/utils/logging.py` | Unstructured string logging to stdout. No JSON formatting, correlation IDs, or log shipping integration. | Structured JSON logger emitting `request_id`, `latency_ms`, and `error_code`. | Medium |
| **10. Metrics & Alerting** | `[NOT IMPLEMENTED]` | None | No Prometheus `/metrics` endpoint; no alerting on error rate spikes, latency p99 degradation, or Ollama timeouts. | `prometheus-fastapi-instrumentator` exposing HTTP and inference latency histograms. | Medium |
| **11. Graceful Shutdown** | `[NOT IMPLEMENTED]` | `app/main.py` | No `@app.on_event("shutdown")` or lifespan cleanup. In-flight requests are terminated abruptly on SIGTERM. | Lifespan handler closing Ollama HTTP client and flushing audio temp files. | Low |
| **12. Data Retention & Sweeper** | `[VERIFIED]` | `app/routers/voice.py:_clean_stale_temp_files` | Files older than 3600s are deleted on query intake. | Sweeper runs inline during user requests rather than as an independent background daemon. | Medium |
| **13. Database Persistence** | `[NOT IMPLEMENTED]` | `app/connectors/*.py` | Connectors read static JSON files. No database connection pooling, migrations, or transactions. | Appropriate for mock prototype; required if real CRM/ticketing is introduced. | Low |
| **14. Environment Isolation** | `[VERIFIED]` | `requirements.txt`, `venv` | Python 3.11 virtual environment; pip dependencies pinned with specific minor versions. | Direct pip dependencies pinned; transitive dependencies unpinned (no `requirements.lock`). | Medium |
| **15. CORS Configuration** | `[VERIFIED]` | `app/config.py:ALLOWED_ORIGINS` | CORS middleware active, configurable via environment variable. Defaults to `*` in development. | Enforce explicit domain list in production. | Low |
| **16. Error Masking / Sanitization** | `[VERIFIED]` | `app/main.py:general_exception_handler` | Unhandled exceptions return generic `"An internal error occurred"` without leaking Python stack traces to clients. | Exemplary implementation; stack traces only logged to server stdout. | N/A |
| **17. Offline Operational Capability** | `[PARTIALLY VERIFIED]` | `app/voice/tts.py` | ASR and LLM are 100% offline. TTS relies on Microsoft Cloud WebSocket; drops offline when internet disconnects. | Support local offline TTS engine (e.g. `piper-tts`) as optional fallback. | Low |
| **18. Backup & Disaster Recovery** | `[NOT IMPLEMENTED]` | None | No backup procedures for `data/` or evaluation results. | Not critical for read-only prototype; required for stateful production systems. | Low |

---

## 3. Operational Comparison: "Works Locally" vs. "Production-Grade"

```
+-------------------------------------------------------------------------------+
| Dimension                 | Works Locally (Today)     | Production-Grade      |
+-------------------------------------------------------------------------------+
| 1. Installation           | clone + pip + ollama run  | Helm / Terraform / IaC|
| 2. Execution              | single developer laptop   | Multi-node K8s cluster|
| 3. Concurrency            | 1 request at a time       | 100+ concurrent users |
| 4. Health Probe           | live TTS synthesis check  | lightweight ping (<5ms)|
| 5. Failure Recovery       | restart terminal          | auto-healing pods     |
| 6. Security Gate          | default dev key allowed   | Vault / OIDC / mTLS   |
| 7. Telemetry              | print / Turn Inspector    | OpenTelemetry / Datadog|
+-------------------------------------------------------------------------------+
```

---

## 4. Domain Ratings & Neutral Assessment

| Evaluation Dimension | Rating | Justification & Source Evidence |
|---|---|---|
| **Implementation Maturity** | **Level 2 (Basic Implementation)** | Dockerfile, docker-compose, and health routes exist, and unhandled exceptions are sanitized. However, blocking CPU inference on the asyncio loop, missing CI, and process-bound state prevent Level 3. |
| **Evidence Confidence** | **High** | Dockerfile, health routes, and config options directly inspected in `Dockerfile`, `app/routers/health.py`, and `app/config.py`. |
| **Production Relevance** | **Critical** | Demonstrating an understanding of production gaps is far more credible than falsely claiming a local prototype is "production-ready." |
| **Distinctiveness** | **Medium** | Standard Docker and health probe setup; the Turn Inspector UI adds unique operational visibility. |

---

## 5. Recommended 80/20 Improvements

1. **Offload Whisper & Vocoder to Threadpool `[PROPOSED]`:**
   - **Action:** Wrap `obfuscator.obfuscate` and `stt.transcribe` in `asyncio.to_thread()`.
   - **Effort:** 30 minutes.
   - **Impact:** Critical. Prevents CPU-bound audio processing from freezing the FastAPI event loop for other concurrent HTTP requests.
2. **Lightweight Readiness Check `[PROPOSED]`:**
   - **Action:** In `app/routers/health.py:_check_tts()`, remove the live `edge_tts.Communicate.save()` call and simply verify that the package is importable and DNS resolves.
   - **Effort:** 15 minutes.
   - **Impact:** High. Eliminates unnecessary external WebSocket overhead during Kubernetes readiness polling.
3. **Strict Secret Enforcement `[PROPOSED]`:**
   - **Action:** In `app/config.py`, raise `ValueError` on startup if `API_KEY` equals `"your-api-key-here"` or is shorter than 16 characters when `ENVIRONMENT != "development"`.
   - **Effort:** 20 minutes.
   - **Impact:** High. Eliminates the default dev key security hole.
