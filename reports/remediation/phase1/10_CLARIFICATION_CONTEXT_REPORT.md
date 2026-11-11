# Phase 1 Remediation — Step 4: One-Turn Clarification Context Carry-Forward Report

**Date:** 2026-11-04  
**Status:** COMPLETE  
**Verdict:** `CLARIFICATION CONTEXT IMPLEMENTED`  
**Scope:** Implemented a minimal, bounded, single-turn clarification context carry-forward mechanism for short follow-up answers after `Decision.CLARIFY`. Strict session isolation, process-local memory bounds, and semantic safety boundaries are enforced. Arbitrary conversation history and multi-turn conversational memory are explicitly prohibited.

---

## 1. Existing Session & Context Architecture Discovered

Prior to this implementation:
- **`Decision.CLARIFY` Lifecycle:** The evidence-grounded abstention engine (`app/services/abstention_router.py`) correctly identified underspecified requests (e.g. *"Something about tickets, maybe check them or whatever"*) and assigned `Decision.CLARIFY`. However, the system had zero memory: the assistant asked for clarification, but the immediate follow-up response (e.g. *"Show open ones"*) had no context. Because *"Show open ones"* lacks an explicit domain entity noun, it was routed to `Decision.DIRECT` (conversational response without tool execution) or failed to execute.
- **Session ID Propagation:** `/voice/query` and `/voice/query/raw` received an optional `session_id` string from the frontend client. This ID was used solely for ephemeral audio caching in `AudioStore` (`app/voice/audio_store.py`) and audio cleanup via `/voice/session/cleanup`.
- **Orchestrator Signature:** `LLMOrchestrator.process_query(user_text, enable_abstention)` did not accept `session_id`, meaning the orchestrator was completely stateless across invocations.
- **Absence of Memory:** The codebase maintained no session conversation history, scratchpad, or dialogue memory.

---

## 2. Design of Bounded Clarification Context

To resolve short follow-up modifiers without opening up attack surfaces or introducing uncontrolled conversational drift, the carry-forward system is strictly bounded by seven core invariants:

```
User Turn 1: "Something about tickets, check them or whatever."
   │
   ▼
Abstention Router: Decision.CLARIFY (matched_domains=['support'])
   │
   ▼
ClarificationContextStore.store_pending(session_id, target_tool="get_support_tickets")
   │
   ▼
Assistant Turn 1: "Could you please clarify your request? Found 1 potential domain..."
   │
   ▼
User Turn 2: "Show open ones."
   │
   ▼
ClarificationContextStore.consume_pending(session_id) [ATOMIC POP]
   │
   ├── Pending found & valid (age < 120s)?
   │     │
   │     ├── Negation / cancellation check: ("do not...", "cancel that...") ──► REJECT (Return None)
   │     ├── Domain entity conflict check: (mentions "customer" or "dau")   ──► REJECT (Return None)
   │     └── Explicit schema modifier match: ("open" -> status="open")     ──► RESOLVE: "show open support tickets"
   │                                                                                    │
   │                                                                                    ▼
   │                                                                        evaluate_abstention(resolved_query)
   │                                                                                    │
   │                                                                                    ▼
   │                                                                            Decision.EXECUTE
   │                                                                                    │
   │                                                                                    ▼
   │                                                                        get_support_tickets(status="open")
   │
   └── Pending consumed/expired: subsequent requests have ZERO carry-forward!
```

### Invariants Enforced:
1. **Strict Session Scoping:** Stored and indexed strictly by `session_id`. Anonymous requests (`session_id=None` or empty string) **never** store or consume context.
2. **Minimal Schema Only (`PendingClarification`):**
   - `session_id: str`
   - `target_tool: str`
   - `matched_domains: List[str]`
   - `reason: str`
   - `created_at: float`
   - `expires_at: float` (TTL = 120 seconds)
   *Invariant:* Full user transcripts, raw inputs, and arbitrary conversation history are **never** stored.
3. **Bounded Capacity (At Most 1 Pending Per Session):** Storing a new pending clarification immediately overwrites any previous pending context for that session.
4. **Single-Turn Consumption (Atomic Pop):** `consume_pending(session_id)` uses a `threading.Lock` to atomically retrieve and delete the pending context. It can be consumed at most once. Turn 3 cannot reuse Turn 1's context.
5. **Strict Session Isolation:** Session A cannot inspect, consume, or affect Session B's context under any circumstances.
6. **Explicit Schema Modifiers Only:** Only low-ambiguity modifiers matching registered tool schema enums/types are resolved (see Section 3). Ambiguous text (e.g. *"Maybe some, I don't know"*) does not resolve into a tool call.
7. **Semantic Execution Safety Invariants Preserved:**
   - Negations (`NEGATED_DIRECTIVES`) and conversational cancellations (`CONVERSATIONAL_CANCELLATIONS`) in the follow-up text abort context resolution and trigger `Decision.ABSTAIN`.
   - All resolved tool calls pass through `validate_decision()`, `_validate_args()`, and `_coerce_args()`.

---

## 3. Supported Tool Schemas & Follow-Up Modifiers

The resolver (`resolve_followup`) explicitly supports schema parameters for the three operational domains:

| Target Tool | Parameter | Supported Modifiers / Regular Expressions |
| :--- | :--- | :--- |
| **`get_support_tickets`** | `status` | `"open"`, `"unresolved"`, `"pending"`, `"active"` $\to$ `"open"`<br>`"closed"`, `"resolved"` $\to$ `"closed"` |
| | `priority` | `"high"`, `"urgent"`, `"critical"` $\to$ `"high"`<br>`"medium"`, `"normal"` $\to$ `"medium"`<br>`"low"` $\to$ `"low"` |
| | `limit` | `"limit <N>"`, `"top <N>"`, `"first <N>"` $\to$ `int(N)` (capped at 100) |
| **`get_crm_data`** | `status` | `"active"`, `"current"` $\to$ `"active"`<br>`"inactive"`, `"churned"`, `"lapsed"` $\to$ `"inactive"` |
| | `limit` | `"limit <N>"`, `"top <N>"` $\to$ `int(N)` (capped at 100) |
| **`get_analytics`** | `metric` | `"daily active users"`, `"dau"`, `"active users"` $\to$ `"daily_active_users"` |
| | `days` | `"last <N> days"`, `"past <N> days"` $\to$ `int(N)` (capped at 365) |

If the user utterance contains a cross-domain entity (e.g. pending context is `support`, but user says *"Show active customers"*), the pending context is safely discarded and the query executes as a fresh, independent CRM request.

---

## 4. Implementation Details

### Files Created / Modified:
1. **`app/services/clarification_context.py` (Created):**
   - `PendingClarification` dataclass.
   - `ClarificationContextStore` thread-safe singleton managing process-local pending states.
   - `resolve_followup()`: Pattern-based schema modifier extraction with negation/cancellation rejection.
2. **`app/services/llm_orchestrator.py` (Updated):**
   - Signature updated: `process_query(user_text, enable_abstention=True, session_id=None)`.
   - Turn execution checks `clarification_store.consume_pending(session_id)` at the start of query processing.
   - If pending context resolves cleanly, natural query is reconstructed and passed through `evaluate_abstention()`.
   - If the request yields `Decision.CLARIFY`, the orchestrator calls `clarification_store.store_pending(session_id, ...)`.
   - When tool execution is authorized, the candidate tool call is passed through `_execute_tool_calls()`.
3. **`app/routers/voice.py` (Updated):**
   - Passes incoming `session_id` to `orchestrator.process_query()`.
   - Cleans up clarification context in `/voice/session/cleanup` via `clarification_store.clear_session(session_id)`.
4. **`tests/test_clarification_context.py` (Created):**
   - 12 comprehensive unit and API integration tests.

---

## 5. Verification & Test Evidence

### 1. Clarification Context Test Suite (`tests/test_clarification_context.py`)
```powershell
.\venv\Scripts\python.exe -m pytest tests/test_clarification_context.py -v
```
**Output:**
```
============================= test session starts =============================
platform win32 -- Python 3.11.3, pytest-9.1.1, pluggy-1.6.0
collected 12 items

tests/test_clarification_context.py::TestOneTurnClarificationContext::test_clarify_creates_pending_context PASSED [  8%]
tests/test_clarification_context.py::TestOneTurnClarificationContext::test_valid_explicit_modifier_resolves_pending_intent PASSED [ 16%]
tests/test_clarification_context.py::TestOneTurnClarificationContext::test_valid_explicit_modifier_crm_active PASSED [ 25%]
tests/test_clarification_context.py::TestOneTurnClarificationContext::test_ambiguous_followup_does_not_execute_tool PASSED [ 33%]
tests/test_clarification_context.py::TestOneTurnClarificationContext::test_unrelated_request_clears_pending_context PASSED [ 41%]
tests/test_clarification_context.py::TestOneTurnClarificationContext::test_context_consumed_after_one_followup PASSED [ 50%]
tests/test_clarification_context.py::TestOneTurnClarificationContext::test_context_expiration_ttl PASSED [ 58%]
tests/test_clarification_context.py::TestOneTurnClarificationContext::test_session_isolation_prevents_cross_session_leak PASSED [ 66%]
tests/test_clarification_context.py::TestOneTurnClarificationContext::test_missing_session_id_does_not_share_context PASSED [ 75%]
tests/test_clarification_context.py::TestOneTurnClarificationContext::test_existing_abstention_and_validation_boundaries_enforced PASSED [ 83%]
tests/test_clarification_context.py::TestOneTurnClarificationContext::test_existing_normal_single_turn_requests_unaffected PASSED [ 91%]
tests/test_clarification_context.py::TestOneTurnClarificationContext::test_session_cleanup_endpoint_clears_clarification_context PASSED [100%]

======================== 12 passed, 1 warning in 0.22s ========================
```

### 2. Feature Regression Test Suites
```powershell
.\venv\Scripts\python.exe -m pytest tests/test_local_tts.py tests/test_obfuscation_inspector.py tests/test_vad.py tests/test_remediation_phase1.py tests/test_adversarial_verification.py -v
```
**Output:**
```
====================== 124 passed, 5 warnings in 13.98s =======================
```

### 3. Full Repository Test Suite
```powershell
.\venv\Scripts\python.exe -m pytest -q --tb=short
```
**Output:**
```
301 passed, 12 warnings in 87.69s (0:01:27)
```

---

## 6. Documented Limitations

1. **Process-Local Memory Boundary:**
   - `ClarificationContextStore` is an in-memory Python singleton. In a multi-worker ASGI deployment (e.g. `uvicorn --workers 4`), follow-up requests routed to a different worker process without sticky sessions/session affinity will not observe the pending context.
   - *Design rationale:* Consistent with the privacy architecture of the repository (zero permanent database persistence of user dialogue).
2. **Single-Turn Bound:**
   - Multi-turn conversational memory, topic tracking across 3+ turns, or anaphora resolution for general pronouns are intentionally unsupported.
3. **Zero General Knowledge Memory:**
   - Context carry-forward is restricted strictly to operational database tool domains (`get_crm_data`, `get_support_tickets`, `get_analytics`). General knowledge and non-database queries never create or consume clarification state.
