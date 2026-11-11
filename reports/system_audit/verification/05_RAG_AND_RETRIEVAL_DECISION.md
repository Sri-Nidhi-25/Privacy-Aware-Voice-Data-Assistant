# Phase 2 — RAG and Retrieval Architecture Forensic Decision
**Report ID:** `VERIFY-05`  
**Target Subject:** Retrieval-Augmented Generation (RAG) vs. Structured Tool Calling Audit  
**Auditor Role:** Senior AI Systems Architect & Retrieval Specialist  
**Epistemic Conventions:** Claims grounded strictly in codebase inspection, dependency trees, and runtime architecture.

---

## 1. Formal Answers to the 7 Core Retrieval Questions

| # | Retrieval Inquiry | Forensic Reality & Code Evidence | Verdict |
|---|---|---|---|
| **1** | **Does the system actually implement RAG?** | `requirements.txt` contains zero RAG frameworks (`langchain`, `llama-index`, `haystack`) and zero vector stores (`chromadb`, `qdrant`, `faiss`, `pgvector`). Codebase contains zero document chunking, indexing, or semantic retrieval modules. | **NO (COMPLETELY ABSENT)** |
| **2** | **Does it retrieve documents?** | The connectors (`app/connectors/`) strictly read static tabular JSON files (`customers.json`, `support_tickets.json`, `analytics.json`). No unstructured text documents (PDFs, Markdown, Word, HTML, text manuals) are ingested or retrieved. | **NO** |
| **3** | **Does it use embeddings or vector search?** | No embedding models (e.g. `nomic-embed-text`, `bge-small`, `text-embedding-3`) are imported, instantiated, or queried. No cosine similarity or ANN indexing is performed. | **NO** |
| **4** | **Does it retrieve structured records through APIs?** | Yes. The system implements **Function / Tool Calling** via Ollama tool schemas (`app/services/llm_orchestrator.py:164-210`). Tools invoke Python connector classes that filter structured JSON records by exact attributes (`status`, `priority`, `month`, `limit`). | **YES (STRUCTURED TOOL CALLING)** |
| **5** | **Does it maintain conversational memory?** | No. Each HTTP voice request creates an isolated, ephemeral session (`app/routers/voice.py:205`). No conversation history, dialog state tracker, or context buffer is retained across turns. | **NO** |
| **6** | **Does it ground generated answers in retrieved evidence?** | Partial grounding. When a tool call succeeds, the connector returns JSON records which are converted to strings and appended to the Ollama messages list (`app/services/llm_orchestrator.py:840-860`). The LLM synthesizes a response conditioned on this JSON payload. If tool execution fails or abstention triggers, a deterministic fallback message is returned. | **PARTIAL (TOOL-OUTPUT GROUNDING)** |
| **7** | **Does it provide provenance or citations?** | In the turn metadata (`metadata["tool_calls"]`), the API returns the executed tool name and kwargs. However, it provides **zero citations, zero record-level provenance hashes, and zero sentence-level source attributions** in the synthesized response text. | **NO** |

---

## 2. Comparative Retrieval Architecture Analysis

The diagram below clarifies what the system actually does versus what RAG is:

```
CURRENT IMPLEMENTATION: Structured Tool Calling (API Routing)
─────────────────────────────────────────────────────────────────────────────
User Voice ──► Whisper STT ──► LLM Tool Router ──► Execute Python Connector
                                  │                     │
                                  ▼                     ▼
                       get_crm_data(status="active")   Filter JSON records
                                                        │
                                                        ▼
Answer Synthesis ◄── Pass Raw JSON String ──────────────┘

vs.

RETRIEVAL-AUGMENTED GENERATION (RAG): Unstructured Document Retrieval
─────────────────────────────────────────────────────────────────────────────
Unstructured Text ──► Chunker ──► Embedding Model ──► Vector Index (HNSW/IVF)
                                                          │
User Query ─────────► Embed Query ────────────────────────┼──► Top-K Cosine Sim
                                                          │
Answer Synthesis ◄── Inject Passages + Citations ─────────┴──► Reranker (Cross-Enc)
```

### Detailed Architectural Comparison Table

| Architecture Pattern | How It Works | Strengths in Voice Data Assistant Context | Weaknesses in Voice Data Assistant Context | Current Status in Repo | Recommended for Current Scope? |
|---|---|---|---|---|---|
| **Structured Tool Calling** | LLM outputs structured function arguments to query typed APIs/connectors. | Exact schema filtering, deterministic numeric calculations, minimal token overhead, zero embedding hallucination. | Requires predefined tool schemas; cannot handle free-form policy or knowledge queries. | **Fully Implemented** (`llm_orchestrator.py`) | **YES (Primary Paradigm)** |
| **Direct Database / API Access** | Connectors run SQL or REST queries directly against backend operational databases. | ACID transactional guarantees, real-time data freshness, zero mock file dependencies. | Requires connection pooling, network credentials, and parameterized queries. | **Partially Implemented** (reads flat JSON mocks) | **YES (Natural Evolution)** |
| **Keyword Search (BM25 / SQLite FTS5)** | Inverted index matching lexical tokens and keywords with BM25 scoring. | Fast, zero vector compute, deterministic, excellent for ticket summaries and SKU names. | Fails on vocabulary mismatch or semantic paraphrasing. | **Not Implemented** | **YES (High Value for Ticket Search)** |
| **Vector Retrieval (Dense Embeddings)** | Chunks embedded into vector space; top-$k$ retrieved via cosine similarity. | Handles semantic nuance, synonyms, and multilingual conceptual matching. | High compute overhead on CPU, poor numeric precision, "lost in the middle" phenomena. | **Not Implemented** | **NO (Overkill for tabular JSON)** |
| **Hybrid Retrieval (BM25 + Dense + Rerank)** | Combines lexical BM25 candidates with dense vector candidates, sorted by cross-encoder. | State-of-the-art recall across both keyword codes (ticket IDs) and natural descriptions. | Complex indexing pipeline, multiple model dependencies, higher latency budget ($>300$ms). | **Not Implemented** | **NO (Premature Complexity)** |
| **RAG (Retrieval-Augmented Generation)** | End-to-end pipeline: Ingest docs $\to$ Chunk $\to$ Index $\to$ Retrieve $\to$ Re-rank $\to$ Synthesize with citations. | Enables querying unstructured enterprise SOPs, SLA policies, and product documentation. | Highest failure surface: chunk boundary loss, hallucinated attributions, retrieval latency. | **Not Implemented** | **CONDITIONAL (Only if Unstructured Docs Added)** |

---

## 3. The Retrieval Decision: Does This Product Need RAG?

### The Core Architectural Verdict
> **RAG is NOT justified for the current product scope, and should NOT be built at this time.**

### Detailed Architectural Rationale
1. **The current dataset is 100% structured tabular data:**
   - `customers.json` contains 10 structured fields: `customer_id`, `name`, `status`, `tier`, `revenue`, etc.
   - `support_tickets.json` contains structured fields: `ticket_id`, `status`, `priority`, `created_date`, `issue_description`.
   - `analytics.json` contains pre-computed aggregates: `total_revenue`, `active_users`, `churn_rate`.
   
   Applying vector embeddings or RAG to structured records like `"revenue": 14500.50` or `"status": "active"` is an **anti-pattern**. Vector models cannot reliably filter by exact mathematical comparisons (e.g., `revenue > 10000` or `month == "March"`). Structured tool calling with Python/SQL predicates is provably superior in precision, latency, and determinism.

2. **The Voice Pipeline has a tight latency budget:**
   - Current local CPU voice pipeline already takes **3.5 to 7.5 seconds** per turn (Whisper STT: 1.5–3.5s, Llama-3.2: 1.5–3.0s, TTS: 0.5–1.0s).
   - Adding document chunk retrieval, embedding generation (`bge-small` on CPU: ~150ms), vector search (~50ms), and cross-encoder reranking (`ms-marco-MiniLM`: ~300ms) would inject an additional **500–1000ms of latency**, directly degrading conversational voice UX.

3. **Demonstrated User Problem Analysis:**
   - The verified user failure mode in Phase 6.1 is **Distractor Leakage** (the LLM executes tools when given conversational chatter, negations, or hypothetical queries).
   - RAG does not fix distractor leakage; in fact, semantic similarity search increases false-positive retrieval on conversational mentions.

---

## 4. Conditional Specification: Bounded RAG for Future Enterprise Policy

If the product roadmap expands to include **unstructured enterprise documents** (e.g. *Customer Support SLA Policies*, *Warranty Guidelines*, *Refund SOPs*), the following strictly bounded architecture must be implemented:

```
FUTURE BOUNDED RAG PIPELINE SPECIFICATION
─────────────────────────────────────────────────────────────────────────────
[Offline Ingestion]
  Enterprise Policy Markdown / PDFs
     │
     ▼
  Document Chunker (Chunk size: 400 tokens, Overlap: 50 tokens, Markdown Header Aware)
     │
     ▼
  Dense Embedder (bge-small-en-v1.5 / ONNX runtime for CPU efficiency)
     │
     ▼
  Vector Store (SQLite-VSS or Qdrant Embedded - zero external cloud dependency)

[Online Voice Query]
  Spoken Query: "What is our refund policy for inactive VIP accounts?"
     │
     ▼
  Intent Router: Classify as `POLICY_QUERY` (vs `DATA_TOOL_QUERY`)
     │
     ├──► If DATA_TOOL_QUERY ──► Route to CRM/Support Tools (Existing Pipeline)
     │
     └──► If POLICY_QUERY ──►
             │
             ├── 1. Generate Query Vector (bge-small-en-v1.5)
             ├── 2. Vector ANN Search (top-5 candidate chunks)
             ├── 3. BM25 Keyword Search (top-5 candidate chunks)
             ├── 4. Reciprocal Rank Fusion (RRF) -> Top 3 chunks
             ├── 5. Guardrail: Max context injection = 800 tokens
             └── 6. Synthesize answer with explicit markdown citation [DocName#Section]
```

### Detailed Specification Elements
- **Bounded Use Case:** Customer service representative querying internal knowledge base policies ("What is our SLA for priority 1 tickets?").
- **Chunking Strategy:** Semantic Markdown-aware chunking (split at `##` headings, chunk size 400 tokens, 50-token rolling overlap) to preserve policy clause integrity.
- **Embedding Model:** `BAAI/bge-small-en-v1.5` quantized to INT8 via ONNX Runtime (CPU inference latency $<25$ms per query).
- **Retrieval Method:** Hybrid retrieval combining SQLite FTS5 (BM25) with SQLite-VSS (vector similarity) via Reciprocal Rank Fusion ($k=60$).
- **Reranking Decision:** No heavy cross-encoder on CPU (saves 300ms latency); use fast lexical-dense fusion.
- **Citation & Provenance Strategy:** Every chunk injected into context carries an explicit citation token `[REF:doc_id:chunk_idx]`. Orchestrator post-processor parses generated text and rejects any claim lacking direct source overlap.
- **Access Control:** Metadata filtering on tenant ID and department role prior to vector similarity calculation.
- **Freshness & Deletion Strategy:** Atomic re-indexing on file change events (`watchdog`); document hash tracking to avoid re-embedding unmodified files.

### Evaluation Protocol for Future RAG
- **Retrieval Dataset:** $N=50$ human-annotated policy questions paired with exact paragraph ground-truth IDs.
- **Retrieval Metrics:** Recall@3 ($\ge 0.90$), Mean Reciprocal Rank (MRR@3 $\ge 0.85$).
- **Answer-Grounding Evaluation:** RAGAS Faithfulness score ($\ge 0.92$) and Answer Relevance ($\ge 0.88$) evaluated over 50 test turns.
