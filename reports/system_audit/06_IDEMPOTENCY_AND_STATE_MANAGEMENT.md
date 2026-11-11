# Report 06 — Idempotency, State & Side-Effect Safety Audit

**Audit Document:** `reports/system_audit/06_IDEMPOTENCY_AND_STATE_MANAGEMENT.md`  
**HEAD Commit:** `5b20a3a`  
**Status:** Complete Forensic Idempotency & State Architecture Review  

---

## 1. Concept Definition & AI Systems Importance

In distributed systems, **Idempotency** guarantees that performing an operation multiple times produces the identical side-effect as performing it once ($f(f(x)) = f(x)$). In Voice AI systems, network instability frequently triggers client retries, microphone double-clicks, and socket reconnections. If an AI assistant executes non-idempotent operations (such as creating customer support tickets, charging payments, or inserting CRM records) without idempotency controls, duplicate audio submissions can cause severe real-world data corruption:
- Submitting the same audio query twice creates two duplicate support tickets.
- Retrying an unacknowledged tool call charges a customer twice.
- Retrying a batch deletion deletes subsequent valid records.

---

## 2. Side-Effect Inventory of System Operations

Every connector and API endpoint in the repository was inspected for side-effects:

| Operation / Tool | HTTP Route or Symbol | Read / Write | Side-Effect Observed | Duplicate Submission Risk | Current Protection in Code | Evidence File & Symbol | Recommended Production Control |
|---|---|---|---|---|---|---|---|
| **Voice Query Execution** | `POST /voice/query` | Read + Local Write | Writes temporary WAV/MP3 files to `temp_audio/`; updates in-memory `EphemeralAudioStore`. | **High (Disk Bloat)** | `_clean_stale_temp_files()` sweeps files older than 1 hour; `cleanup_session_audio()`. | `app/routers/voice.py:L142-L175` | Require `Idempotency-Key` HTTP header; return cached response if key already completed. |
| **Audio Stream Playback** | `GET /voice/audio/{id}` | Read-Only | Streams binary audio chunk from `temp_audio/`. | **None (Safe)** | Standard read-only file response. | `app/routers/voice.py:stream_audio` | Cache-Control headers with immutable cache tags. |
| **CRM Data Fetch** | `get_crm_data` | **Read-Only** | Queries `data/customers.json` by `status` and `limit`. | **None (Safe)** | In-memory filtering of static JSON list. | `app/connectors/crm_connector.py:fetch_result` | Safe for retries; naturally idempotent. |
| **Support Tickets Fetch** | `get_support_tickets` | **Read-Only** | Queries `data/support_tickets.json` by `status`, `priority`, `limit`. | **None (Safe)** | In-memory filtering of static JSON list. | `app/connectors/support_connector.py:fetch_result` | Safe for retries; naturally idempotent. |
| **Analytics Metric Fetch** | `get_analytics` | **Read-Only** | Queries `data/analytics.json` by `metric` and `days`. | **None (Safe)** | In-memory aggregation of static JSON list. | `app/connectors/analytics_connector.py:fetch_result` | Safe for retries; naturally idempotent. |
| **Evaluation Case Audio** | `GET /evaluation/audio/{id}` | Read-Only | Streams benchmark audio WAV for Evaluation Lab. | **None (Safe)** | Read-only file response. | `app/routers/evaluation.py:serve_case_audio` | Safe for retries; naturally idempotent. |
| **Support Ticket Creation** | `create_support_ticket` | **Write** | **NOT IMPLEMENTED** | **CRITICAL (Future)** | **NONE (Absent)** | No write connector exists in repo. | Deduplication table using SHA256 of user request + client-provided UUID. |

---

## 3. Guarantees: At-Most-Once vs. At-Least-Once

```
+-------------------------------------------------------------------------------+
| System Layer             | Semantic Guarantee | Evidence & Mechanism          |
+-------------------------------------------------------------------------------+
| 1. HTTP Endpoint Level   | At-Least-Once      | No idempotency keys; duplicate|
|                          |                    | uploads execute pipeline twice|
| 2. Connector Query Level | Idempotent (Read)  | Pure read-only mock data      |
| 3. Connector Write Level | NOT IMPLEMENTED    | No write connectors exist     |
| 4. Tool Deduplication    | Effectively-Once   | Orchestrator deduplicates tool|
|                          | (Per Single Turn)  | calls in a single turn (L505) |
+-------------------------------------------------------------------------------+
```

### 3.1 Single-Turn Tool Call Deduplication `[VERIFIED]`
Inspected in [`app/services/llm_orchestrator.py:L505-L519`](file:///d:/Projects/Privacy-Preserving-Voice-Data-Assistant/app/services/llm_orchestrator.py#L505-L519):
```python
# Deduplicate tool calls so identical function calls are not executed multiple times
deduped_tool_calls = []
seen_calls = set()
for call in tool_calls:
    func_name = call.get("function", {}).get("name", "")
    args_raw = call.get("function", {}).get("arguments", {})
    call_sig = (func_name, json.dumps(args_raw, sort_keys=True))
    if call_sig not in seen_calls:
        seen_calls.add(call_sig)
        deduped_tool_calls.append(call)
```
If the LLM emits duplicate tool calls within a single response message (e.g. calling `get_crm_data(status='active')` twice), the orchestrator intercepts the second call, ensuring each unique signature is executed only once per turn.

### 3.2 State Management & Concurrency Hazards

#### EphemeralAudioStore (`app/voice/audio_store.py`) `[VERIFIED]`
Inspected in [`app/voice/audio_store.py:L1-L109`](file:///d:/Projects/Privacy-Preserving-Voice-Data-Assistant/app/voice/audio_store.py#L1-L109):
- **Mechanism:** Stores session records in an in-memory dictionary `self._sessions: Dict[str, Dict]`.
- **Limitation:** In-memory storage is process-bound. If the FastAPI application is deployed across multiple Uvicorn workers (`--workers 4`) or scaled across multiple Docker containers, session state is not shared. A client querying worker A and requesting audio from worker B receives an HTTP 404.
- **Thread Safety:** Python dictionaries benefit from the Global Interpreter Lock (GIL) for atomic read/writes, but there are no explicit `threading.Lock` primitives around session list mutations.

#### Obfuscator Concurrency Isolation `[VERIFIED]`
Inspected in [`app/voice/obfuscator.py:FormantPreservingObfuscator`](file:///d:/Projects/Privacy-Preserving-Voice-Data-Assistant/app/voice/obfuscator.py):
Earlier versions of the obfuscator used a hardcoded temporary file path (`tmp_obf.wav`), creating a race condition if two users uploaded audio simultaneously. The current implementation in `run_paired_evaluation.py:L91` uses per-case temporary paths:
```python
tmp_obf = audio_path.parent / f"tmp_obf_{case_id}.wav"
```
And in `app/routers/voice.py:L330`, it generates unique UUID filenames:
```python
obf_path = os.path.join(temp_dir, f"obf_{session_id}_{os.path.basename(file_path)}")
```
This isolates concurrent obfuscation tasks on disk.

---

## 4. Domain Ratings & Neutral Assessment

| Evaluation Dimension | Rating | Justification & Source Evidence |
|---|---|---|
| **Implementation Maturity** | **Level 2 (Basic Implementation)** | Single-turn tool deduplication is implemented. However, request-level idempotency keys (`Idempotency-Key` header) and distributed state synchronization across workers are absent. |
| **Evidence Confidence** | **High** | Tool deduplication logic verified in `app/services/llm_orchestrator.py:L505-L519`. Read-only nature of connectors verified across `app/connectors/*.py`. |
| **Production Relevance** | **Critical (Future)** | Although safe today because connectors are read-only, adding mutable write tools (e.g. ticket creation) without idempotency keys would be a critical production vulnerability. |
| **Distinctiveness** | **Medium** | Single-turn tool deduplication is good engineering practice; full request-level idempotency is what would elevate it to enterprise grade. |

---

## 5. Recommended 80/20 Improvements

1. **Idempotency-Key Header Support `[PROPOSED]`:**
   - **Action:** Support an optional `Idempotency-Key` header on `/voice/query`. Cache completed responses in an in-memory LRU cache with 60s TTL; if the same key arrives, return the cached result immediately without invoking Whisper or Ollama.
   - **Effort:** 1.5 hours.
   - **Impact:** High. Protects against client duplicate submissions and network retries.
2. **Document Read-Only Safety Explicitly `[PROPOSED]`:**
   - **Action:** Add explicit docstrings in connectors stating that operations are pure reads and safe for retries.
