# Privacy-Aware Voice Data Assistant

A privacy-aware voice query assistant that combines speaker voice obfuscation, automatic speech recognition (Whisper), domain transcript correction, selective abstention, tool-calling, and text-to-speech synthesis.

---

## Architecture: Full Pipeline

```text
Audio Upload (WAV, MP3, WebM, OGG, MPEG)
  â”‚
  â–¼
1. Audio Validation
     Size limit, duration checks, decodability check (pydub/ffmpeg)
     â†’ Rejects corrupt, silent, or oversized files before any processing
  â”‚
  â–¼
2. Voice Obfuscation  (FormantPreservingObfuscator â€” WORLD Vocoder)
     Pitch-shifts the speaker's F0 (fundamental frequency) by a configurable
     semitone amount while preserving spectral envelope, so Whisper STT still
     works accurately on the obfuscated audio.
     Intensities: mild (Â±2 st) | medium (Â±4 st) | strong (Â±6 st) | very_strong (Â±8 st)
     Gaussian jitter is added to the shift so consecutive requests are not identical.
  â”‚
  â–¼
3. Speech-to-Text  (OpenAI Whisper â€” local, offline)
     Transcribes the obfuscated audio. Returns confidence signals:
     avg_logprob, no_speech_prob, compression_ratio.
     Low-confidence results (avg_logprob < -1.0) trigger early abstention.
  â”‚
  â–¼
4. Correction Guard  (LLM pass via Ollama)
     Fixes domain-specific transcription errors:
     "high priority" vs "hai priority", "inactive" vs "in active", etc.
     Includes overlap and refusal guardrails â€” refuses corrections that
     change intent or introduce hallucinations.
  â”‚
  â–¼
5. Intent Routing
     Classifies the corrected transcript into one of:
       crm_query | support_query | analytics_query | multi_domain | unknown
     Uses keyword matching + LLM classification with a fallback chain.
  â”‚
  â–¼
6. Selective Abstention  (Evidence-Grounded Abstention Engine)
     Decouples Domain Entity Evidence (E_domain) from Operational Speech-Act
     Evidence (E_op) and Distractor Penalty (D_dist):
       EXECUTE : High domain + high operational evidence, low distractor penalty
       ABSTAIN : Domain vocabulary present but missing operational evidence,
                 or high distractor penalty (narrative, conversational, cross-domain)
       DIRECT  : No domain vocabulary â€” routed straight to LLM for a plain answer
     Prevents false-positive tool execution on semantic distractors
     (e.g. "What is today's weather like?" must NOT trigger CRM tools).
     Can be toggled on/off per-request from the UI or via query param.
  â”‚
  â–¼
7. Tool Execution  (LLM Orchestrator â†’ Connectors)
     The LLM selects and calls the appropriate tool:
       get_crm_data       â†’ data/customers.json
       get_support_tickets â†’ data/support_tickets.json
       get_analytics_data  â†’ data/analytics.json
     Tool arguments are validated and coerced before any connector is called.
     Invalid arguments are rejected â€” connectors are NEVER called with bad args.
     Multi-domain queries (e.g. "inactive customers with open tickets") perform
     an inner join by customer_id across CRM + Support results.
     Results are capped at 10 records for voice readability; the UI shows
     "10/N records" when the total exceeds the cap.
  â”‚
  â–¼
8. TTS Synthesis  (Edge-TTS â€” en-US-AriaNeural)
     Synthesises the answer text into speech.
     TTS failure is handled gracefully â€” the text answer is always preserved
     in the response even if audio generation fails.
  â”‚
  â–¼
API JSON Response
  â€¢ answer_text          â€” plain text answer
  â€¢ answer_audio_url     â€” URL to synthesised MP3
  â€¢ obfuscated_audio_url â€” URL to obfuscated WAV (for inspection)
  â€¢ transcript           â€” corrected STT transcript
  â€¢ metadata             â€” request_id, sources, result count, abstention decision,
                          obfuscation strength/shift, STT confidence, per-stage latency
```

---

## Project Structure

```text
.
â”œâ”€â”€ app/
â”‚   â”œâ”€â”€ config.py                  # Settings, obfuscation strength aliases, startup validation
â”‚   â”œâ”€â”€ failure.py                 # Central FailureType enum + PipelineError
â”‚   â”œâ”€â”€ main.py                    # FastAPI app, CORS, error handlers, static file mount
â”‚   â”œâ”€â”€ connectors/
â”‚   â”‚   â”œâ”€â”€ base.py                # BaseConnector, freshness evaluation
â”‚   â”‚   â”œâ”€â”€ crm_connector.py       # Reads data/customers.json, filters by status/tier/name
â”‚   â”‚   â”œâ”€â”€ support_connector.py   # Reads data/support_tickets.json, filters by priority/status
â”‚   â”‚   â””â”€â”€ analytics_connector.py # Reads data/analytics.json, DAU trends, averages
â”‚   â”œâ”€â”€ models/
â”‚   â”‚   â”œâ”€â”€ common.py              # DataResponse, Metadata Pydantic schemas
â”‚   â”‚   â””â”€â”€ voice.py               # VoiceQueryResponse schema
â”‚   â”œâ”€â”€ routers/
â”‚   â”‚   â”œâ”€â”€ health.py              # GET /health/live, GET /health/ready
â”‚   â”‚   â”œâ”€â”€ data.py                # GET /data/{source} â€” direct data debug endpoint
â”‚   â”‚   â””â”€â”€ voice.py               # POST /voice/query â€” main pipeline endpoint
â”‚   â”œâ”€â”€ services/
â”‚   â”‚   â”œâ”€â”€ abstention_router.py   # Evidence-grounded abstention engine (EXECUTE/ABSTAIN/DIRECT)
â”‚   â”‚   â”œâ”€â”€ business_rules.py      # Voice result limits (MAX_RESULTS cap)
â”‚   â”‚   â”œâ”€â”€ correction_guard.py    # LLM-based domain transcript correction with guardrails
â”‚   â”‚   â”œâ”€â”€ intent_router.py       # Classifies transcript into domain intent
â”‚   â”‚   â”œâ”€â”€ llm_orchestrator.py    # Tool selection, argument coercion/validation, connector calls
â”‚   â”‚   â””â”€â”€ voice_optimizer.py     # summarize_if_large() â€” compresses large result sets
â”‚   â”œâ”€â”€ utils/
â”‚   â”‚   â”œâ”€â”€ logging.py             # Structured JSON logging, ISO-8601 timestamps
â”‚   â”‚   â””â”€â”€ security.py            # API key validation middleware
â”‚   â””â”€â”€ voice/
â”‚       â”œâ”€â”€ audio_validation.py    # File size, duration, decodability checks
â”‚       â”œâ”€â”€ obfuscator.py          # FormantPreservingObfuscator (WORLD vocoder) + VoiceObfuscator
â”‚       â”œâ”€â”€ stt.py                 # STTEngine â€” Whisper with confidence signals
â”‚       â””â”€â”€ tts.py                 # Edge-TTS synthesis with graceful fallback
â”œâ”€â”€ data/
â”‚   â”œâ”€â”€ customers.json             # Mock CRM records
â”‚   â”œâ”€â”€ support_tickets.json       # Mock support tickets
│   ├── analytics.json             # Mock daily active user analytics
│   └── questions_and_answers.md   # Ground-truth audio queries & expected answers
â”œâ”€â”€ tests/
â”‚   â”œâ”€â”€ conftest.py                # Shared fixtures (WAV file, TestClient)
â”‚   â”œâ”€â”€ test_api.py                # POST /voice/query endpoint tests
â”‚   â”œâ”€â”€ test_audio_validation.py   # Audio validation edge cases
â”‚   â”œâ”€â”€ test_config.py             # Settings, obfuscation strength alias resolution
â”‚   â”œâ”€â”€ test_connectors.py         # CRM / Support / Analytics connector tests
â”‚   â”œâ”€â”€ test_correction.py         # Correction guard LLM pass tests
â”‚   â”œâ”€â”€ test_health.py             # Health probe endpoint tests
â”‚   â”œâ”€â”€ test_invariants.py         # Safety invariants (bad args never reach connectors)
â”‚   â”œâ”€â”€ test_obfuscation.py        # Obfuscator output verification
â”‚   â”œâ”€â”€ test_routing.py            # Intent classification tests
â”‚   â”œâ”€â”€ test_stt.py                # Whisper STT confidence signal tests
â”‚   â”œâ”€â”€ test_tool_validation.py    # Tool arg coercion + validation (limit, priority, status)
â”‚   â””â”€â”€ test_phase5_5/
â”‚       â”œâ”€â”€ test_pipeline_integration.py  # Real obfuscator + STT + LLM integration tests
â”‚       â””â”€â”€ test_abstention_e2e.py        # Abstention router end-to-end with mocks
â”œâ”€â”€ evaluation/
â”‚   â””â”€â”€ benchmark_obfuscation.py   # Benchmark: WER + routing fidelity across obfuscation strengths
â”œâ”€â”€ benchmark_audio/               # Generated outputs from benchmark runs (phrase WAVs, results.csv)
â”œâ”€â”€ temp_audio/                    # Ephemeral per-request audio files (auto-cleaned)
â”œâ”€â”€ voice_chat.html                # Browser UI (served at http://127.0.0.1:8000/)
â”œâ”€â”€ .env                           # Local config (not committed)
â”œâ”€â”€ .env.example                   # Config template
â”œâ”€â”€ requirements.txt               # All dependencies
â”œâ”€â”€ Dockerfile                     # Container build
â””â”€â”€ docker-compose.yml             # App + Ollama sidecar
```

---

## Setup & Running the Application

### Prerequisites
- Python 3.10+
- [Ollama](https://ollama.ai) with `llama3.2:latest` pulled
- `ffmpeg` on PATH (used by pydub/librosa for audio decoding)

### 1. Create and activate virtual environment
```powershell
python -m venv venv
.\venv\Scripts\activate
```

### 2. Install dependencies
```powershell
pip install -r requirements.txt
```

### 3. Configure environment
```powershell
Copy-Item .env.example .env
```

Edit `.env` with your desired settings:
```env
API_KEY=secret-key-change-me
OBFUSCATION_STRENGTH=mild        # mild | medium | strong | high | very_strong
STT_MODEL=small.en
OLLAMA_MODEL=llama3.2:latest
LLM_TIMEOUT_SECONDS=120.0
```

### 4. Start the server
```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open **http://127.0.0.1:8000/** in your browser to use the voice assistant UI.

> The `--reload` flag watches for file changes and restarts automatically during development.

---

## Configuration Reference (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | *(required)* | Server API key. UI uses `dev-insecure-key` which maps to the default. |
| `OBFUSCATION_STRENGTH` | `mild` | Global default obfuscation strength. Can be overridden per-request from the UI dropdown. |
| `STT_MODEL` | `small.en` | Whisper model name (`tiny`, `base`, `small`, `medium`, `large`). |
| `OLLAMA_MODEL` | `llama3.2:latest` | Ollama model for correction guard + tool selection. |
| `LLM_TIMEOUT_SECONDS` | `120.0` | Timeout for Ollama LLM calls. |
| `MAX_RESULTS` | `10` | Maximum records returned to the voice pipeline per query. |
| `TTS_PROVIDER` | `disabled` | TTS provider: `local` (offline SAPI5), `remote` (Edge-TTS), or `disabled`. |
| `LOCAL_TTS_VOICE` | `None` | Optional local SAPI voice name (e.g. `Microsoft David Desktop`, `Microsoft Zira Desktop`). |
| `EDGE_TTS_VOICE` | `en-US-GuyNeural` | Remote Edge-TTS voice (only used if `TTS_PROVIDER=remote` for non-sensitive text). |
| `ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA` | `false` | Strict privacy boundary invariant: blocks transmission of database results to cloud TTS. |
| `ALLOWED_ORIGINS` | `http://127.0.0.1:8000` | CORS allowed origins (comma-separated). |

---

## Offline Local TTS & Privacy Boundary

The assistant enforces a strict privacy boundary for speech synthesis:
- **Sensitive Responses**: Database-derived answers (CRM records, support tickets, analytics) are marked `is_sensitive=True`.
- **Zero Cloud Leakage**: When `ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA=false`, sensitive answers are blocked from being sent to remote cloud TTS (`edge-tts`).
- **Offline Local TTS (`TTS_PROVIDER=local`)**:
  - Uses Windows native `System.Speech.Synthesis` (`SAPI5`), requiring zero external downloads, zero GPU resources, and zero network calls.
  - Generates standard PCM WAV and exports to MP3 matching the client audio streaming endpoint.
  - Offloaded from the ASGI event loop to an asynchronous threadpool via `anyio.to_thread.run_sync()`, preserving server concurrency.
  - Allows sensitive queries to produce audio safely on the local host machine.

---

## Obfuscation Intensities

| Strength | Semitone Shift | Jitter | Alias(es) |
|----------|---------------|--------|-----------|
| `mild` | Â±2 st | 0.5 | â€” |
| `medium` | Â±4 st | 1.0 | â€” |
| `strong` | Â±6 st | 1.0 | `high` |
| `very_strong` | Â±8 st | 1.5 | `verystrong`, `very strong` |

The shift sign (raise/lower pitch) is randomised per request. Gaussian jitter means no two requests produce identical shifts. Obfuscation intensity can be changed:
- **Per-request** via the UI dropdown (persisted in localStorage)
- **Globally** via `OBFUSCATION_STRENGTH` in `.env` (hot-reloaded per request, no restart needed)

---

## API Reference

### Health
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health/live` | Fast liveness check â†’ `{"status": "alive"}` |
| `GET` | `/health/ready` | Deep readiness check (Whisper, Ollama, TTS, data files) â†’ `ready / degraded / unavailable` |
| `GET` | `/health` | Alias for `/health/ready` |

### Data & Audio (Endpoints)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/data/{source}?limit=10` | Returns raw records from `crm`, `support`, or `analytics` |
| `GET` | `/voice/audio/{file_id}` | Authenticated ephemeral audio stream (Burn-After-Reading from RAM buffer) |

### Voice Query
```
POST /voice/query
  ?obfuscation_strength=mild     # optional â€” overrides .env default for this request
  ?enable_abstention=true        # optional â€” default true

Headers:
  api-key: dev-insecure-key

Body (multipart/form-data):
  audio_file: <WAV | MP3 | WebM | OGG | MPEG>
```

**Example with curl:**
```powershell
curl.exe -X POST "http://127.0.0.1:8000/voice/query?enable_abstention=true" `
  -H "api-key: dev-insecure-key" `
  -F "audio_file=@your_query.mpeg;type=audio/mpeg"
```

**Response JSON:**
```json
{
  "answer_text": "Found 3 open high-priority support tickets.",
  "answer_audio_url": "/voice/audio/ans_abc123?api_key=dev-insecure-key",
  "obfuscated_audio_url": "/voice/audio/obf_abc123?api_key=dev-insecure-key",
  "transcript": "How many open high priority tickets are there?",
  "metadata": {
    "request_id": "c7f7663e-72ba-4b53-9d41-3b74ad50c4ce",
    "data_sources_used": ["support"],
    "result_count": 3,
    "abstention_decision": "EXECUTE",
    "abstention_confidence": 1,
    "abstention_reason": "High domain + operational evidence detected.",
    "execution_prevented_by_abstention": false,
    "obfuscation_strength": "mild",
    "obfuscation_details": {
      "strength": "mild",
      "base_semitones": 2.0,
      "actual_shift_semitones": 2.09
    },
    "stt_confidence": {
      "avg_logprob": -0.35,
      "no_speech_prob": 0.01,
      "compression_ratio": 1.1,
      "low_confidence": false
    },
    "latency_ms": {
      "validation": 25,
      "obfuscation": 2100,
      "stt": 5800,
      "correction": 4200,
      "routing": 2,
      "tts": 1500,
      "total": 13627
    }
  }
}
```

---

## Running Tests

```powershell
.\venv\Scripts\python.exe -m pytest tests/ -v
```

Test coverage:

| Test File | What it covers |
|-----------|---------------|
| `test_config.py` | Settings parsing, all obfuscation strength aliases |
| `test_audio_validation.py` | Size limits, duration checks, corrupt file rejection |
| `test_obfuscation.py` | Formant-preserving obfuscator output across all 4 intensities |
| `test_stt.py` | Whisper confidence signal extraction, low-confidence detection |
| `test_correction.py` | Correction guard LLM pass, refusal guardrails |
| `test_routing.py` | Intent classification, `_is_data_query` edge cases |
| `test_tool_validation.py` | Argument coercion (limit, priority, status), invalid arg rejection |
| `test_connectors.py` | CRM / Support / Analytics connector filter logic |
| `test_invariants.py` | Safety invariants â€” invalid tool args never reach connectors |
| `test_health.py` | Health probe liveness and readiness endpoints |
| `test_api.py` | POST /voice/query end-to-end with mocked STT/LLM/TTS |
| `test_phase5_5/` | Pipeline integration + abstention router end-to-end |

---

## Obfuscation Benchmark

Measures Word Error Rate (WER), Character Error Rate (CER), latency, and tool routing fidelity of the active `FormantPreservingObfuscator` (WORLD vocoder F0 pitch shift + McAdams vocal-tract spectral envelope warping) across obfuscation strengths on a fixed set of 8 representative business-query phrases.

**Run the benchmark:**
```powershell
# from the project root
.\venv\Scripts\python.exe benchmark_obfuscation.py --seed 42

# all strengths including very_strong
.\venv\Scripts\python.exe benchmark_obfuscation.py --seed 42 --strengths none,mild,medium,strong,very_strong
```

**Script:** [`benchmark_obfuscation.py`](benchmark_obfuscation.py) (project root)

**Outputs to `benchmark_audio/`:**

| File | Description |
|------|-------------|
| `phrase_N.mp3` | Raw TTS-synthesised audio (edge-tts, en-US-AriaNeural) |
| `phrase_N.wav` | 16 kHz mono WAV |
| `phrase_N_{strength}.wav` | Obfuscated version at each intensity |
| `results.csv` | Full telemetry: WER, CER, actual F0 shift (st), actual VTLN alpha, obf latency, STT latency, and routing fidelity |

**Results (WORLD vocoder + McAdams VTLN formant warp, seed=42, Whisper base, 8 phrases × 4 strengths = 32 runs):**

| Strength | Avg WER | Avg CER | Avg Alpha | Avg Obf Latency | Routing OK% | Actual F0 Shift Range |
|----------|---------|---------|-----------|-----------------|-------------|-----------------------|
| none     | 0.000   | 0.000   | 1.000     | 0.0 ms          | 100.0%      | 0.0 st                |
| mild     | 0.000   | 0.000   | 1.004     | ~1100 ms        | 100.0%      | +1.5 to +2.3 st       |
| medium   | 0.000   | 0.000   | 0.972     | ~642 ms         | 100.0%      | +3.0 to +4.6 st       |
| strong   | 0.021   | 0.004   | 0.958     | ~660 ms         | 100.0%      | +5.4 to +7.0 st       |
| **OVERALL** | **0.005** | **0.001** | —     | **~600 ms**     | **100.0%**  | —                     |

**Dual-Layer Obfuscator:** [`app/voice/obfuscator.py`](app/voice/obfuscator.py). Uses `pyworld` to decompose speech into F0 (pitch), spectral envelope (formants), and aperiodicity. It perturbs F0 and applies a McAdams frequency warping coefficient ($\alpha \in [0.88, 1.12]$) to shift formant resonance locations (simulating altered vocal tract geometry). Across 32 runs, Whisper achieved 99.5% accuracy (0.005 WER, 0.001 CER) with 100% routing fidelity.

---

## Neural Speaker Verification Benchmark

Measures cosine embedding similarity between clean and obfuscated speech using the **Wav2Vec2 x-vector SUPERB** model (`anton-l/wav2vec2-base-superb-sv`), quantifying how much the obfuscator disrupts speaker biometric identity without relying on a cloud service.

**Run the evaluation:**
```powershell
.\venv\Scripts\python.exe scripts/eval_speaker_similarity.py
```

**Script:** [`eval_speaker_similarity.py`](eval_speaker_similarity.py) (project root)

**Results (8 phrases, Wav2Vec2 x-vector SUPERB model):**

| Tier | Avg Cosine Similarity | Avg Similarity Drop | N |
|------|-----------------------|---------------------|---|
| `none` | 1.0000 | 0.00% | 8 |
| `mild` | 0.9768 | 2.32% | 8 |
| `medium` | 0.9454 | 5.46% | 8 |
| `strong` | 0.9151 | 8.49% | 8 |
| `strong_with_tempo` | 0.8780 | 12.20% | 8 |

> **Interpretation:** At `strong` intensity the obfuscator reduces neural speaker-embedding cosine similarity by ~8.5%, and by ~12.2% when tempo-shift is also applied — empirically confirming biometric identity disruption while maintaining 99.5% STT accuracy (WER=0.005).

> **Note on `resemblyzer`:** The `resemblyzer` library (an alternative speaker-embedding tool) requires `webrtcvad`, which needs MSVC++ build tools unavailable in this environment. The `transformers` + `torch` x-vector model was used instead with equivalent discriminative power.

---

## Key Design Decisions

**Why WORLD vocoder instead of simple resampling?**
Simple pitch resampling changes speech duration and distorts formants, making Whisper transcription unreliable. The WORLD vocoder separates F0 (pitch) from spectral envelope, so only pitch is shifted while formants remain intact â€” preserving STT accuracy while still meaningfully obfuscating speaker identity.

**Why Evidence-Grounded Abstention instead of a simple confidence threshold?**
A confidence threshold on the LLM alone causes false positives on distractor queries that mention domain vocabulary casually (e.g. "I used to work in customer support"). The abstention engine separately scores domain evidence (E_domain), operational retrieval intent (E_op), and distractor penalty (D_dist) before deciding whether to execute a tool call.

**Why validate tool arguments before calling connectors?**
The LLM occasionally generates structurally incorrect arguments (e.g. `{"limit": "all"}` for a counting query). Coercing and validating before the connector is called ensures the safety invariant: invalid tool arguments can never reach the data layer.

**Why hot-reload `.env` per request instead of at startup?**
Allows changing `OBFUSCATION_STRENGTH` (or any other setting) in `.env` and having it take effect immediately on the next request without restarting the server â€” useful during development.



