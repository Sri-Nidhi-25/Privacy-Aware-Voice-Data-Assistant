# Privacy-Aware Voice Data Assistant

A privacy-aware, voice-first agentic data assistant combining acoustic voice obfuscation, offline automatic speech recognition (Whisper), domain transcript correction, selective evidence-grounded abstention, multi-domain tool-calling, pluggable state storage (Memory / Redis), and privacy-bounded text-to-speech synthesis.

---

## Architecture: Full Pipeline

```text
Audio Upload (WAV, MP3, WebM, OGG, MPEG)
  |
  v
1. Audio Validation
     Size limit, duration checks, decodability check (pydub/ffmpeg)
     -> Rejects corrupt, silent, or oversized files before any processing
  |
  v
2. Voice Obfuscation (FormantPreservingObfuscator -- WORLD Vocoder)
     Perturbs F0 (fundamental frequency) and applies McAdams spectral envelope warping
     (alpha in [0.88, 1.12]) to shift formant resonance locations (simulating altered vocal tract geometry).
     Intensities: mild (+/-2 st) | medium (+/-4 st) | strong (+/-6 st) | very_strong (+/-8 st)
     Randomized jitter ensures consecutive requests from the same speaker produce distinct acoustic fingerprints.
     Achieves -12.2% speaker cosine similarity drop on Wav2Vec2 x-vectors while preserving 99.5% Whisper accuracy.
  |
  v
3. Speech-to-Text (OpenAI Whisper -- local, offline)
     Transcribes the obfuscated audio. Returns acoustic confidence signals:
     avg_logprob, no_speech_prob, compression_ratio.
     Low-confidence results (avg_logprob < -1.0) trigger early abstention.
  |
  v
4. Correction Guard (LLM pass via Ollama)
     Fixes domain-specific transcription errors:
     "high priority" vs "hai priority", "inactive" vs "in active", etc.
     Enforces overlap and refusal guardrails -- rejects corrections that
     alter intent or introduce hallucinations.
  |
  v
5. Intent Routing & Clarification Context
     Classifies the corrected transcript into one of:
       crm_query | support_query | analytics_query | multi_domain | unknown
     Tracks follow-up multi-turn clarification sessions via pluggable storage.
  |
  v
6. Selective Abstention Engine (Evidence-Grounded Abstention)
     Decouples Domain Entity Evidence (E_domain) from Operational Speech-Act
     Evidence (E_op) and Distractor Penalty (D_dist):
       EXECUTE : High domain + high operational evidence, low distractor penalty
       ABSTAIN : Domain vocabulary present but missing operational evidence,
                 or high distractor penalty (narrative, conversational, cross-domain)
       DIRECT  : No domain vocabulary -- routed straight to LLM for a direct answer
     Eliminates tool false-positive execution on semantic distractors:
     Reduces distractor FPR from 85% -> 0% with 86.7% held-out routing accuracy.
  |
  v
7. Tool Execution (LLM Orchestrator -> Connectors)
     The LLM selects and calls the appropriate validated tool:
       get_crm_data        -> data/customers.json
       get_support_tickets -> data/support_tickets.json
       get_analytics_data  -> data/analytics.json
     Tool arguments are strictly coerced and validated against Pydantic schemas.
     Multi-domain queries (e.g. "inactive customers with open tickets") perform
     an inner join by customer_id across CRM + Support results.
     Results capped at MAX_RESULTS (default 10) for speech readability.
  |
  v
8. Pluggable Audio & Session Storage (Memory / Redis)
     Ephemeral audio buffers (obfuscated audio & TTS responses) and multi-turn
     clarification sessions are saved with strict TTLs (default 300s).
     Configurable via STORAGE_BACKEND:
       - memory: Ephemeral in-process store with TTL thread
       - redis:  Distributed async Redis 7 store with fail-fast ping
  |
  v
9. TTS Synthesis & Privacy Boundary (Local SAPI5 / Remote Edge-TTS)
     Strict Privacy Invariant: Database-derived responses (is_sensitive=True)
     are blocked from remote cloud TTS (Edge-TTS) unless explicitly permitted.
     On Windows, offline System.Speech.Synthesis (SAPI5) generates voice locally.
  |
  v
API JSON Response
  * answer_text          -- plain text answer
  * answer_audio_url     -- URL to synthesised audio (authenticated burn-after-reading stream)
  * obfuscated_audio_url -- URL to obfuscated WAV (for inspection)
  * transcript           -- corrected STT transcript
  * metadata             -- request_id, sources, result count, abstention decision,
                           obfuscation shift/alpha, STT confidence, per-stage latency
```

---

## Project Structure

```text
.
|-- app/
|   |-- config.py                  # SettingsConfigDict (Pydantic V2), hot-reload, aliases
|   |-- failure.py                 # Central FailureType enum + PipelineError
|   |-- main.py                    # FastAPI app, CORS, error handlers, static file mount
|   |-- connectors/
|   |   |-- base.py                # BaseConnector, freshness evaluation
|   |   |-- crm_connector.py       # Reads data/customers.json, filters status/tier
|   |   |-- support_connector.py   # Reads data/support_tickets.json, filters priority/status
|   |   `-- analytics_connector.py # Reads data/analytics.json, DAU trends, averages
|   |-- models/
|   |   |-- common.py              # DataResponse, Metadata Pydantic schemas
|   |   `-- voice.py               # VoiceQueryResponse, AudioValidation schemas
|   |-- routers/
|   |   |-- health.py              # GET /health/live, GET /health/ready (deep probe)
|   |   |-- data.py                # GET /data/{source} -- direct data debug endpoint
|   |   |-- evaluation.py          # GET /evaluation/* -- Evaluation Lab dashboard API
|   |   `-- voice.py               # POST /voice/query -- main pipeline endpoint
|   |-- services/
|   |   |-- abstention_router.py   # Evidence-grounded abstention engine (EXECUTE/ABSTAIN/DIRECT)
|   |   |-- business_rules.py      # Voice result limits (MAX_RESULTS cap)
|   |   |-- clarification_context.py # Multi-turn clarification store adapter
|   |   |-- correction_guard.py    # LLM-based domain transcript correction
|   |   |-- intent_router.py       # Classifies transcript into domain intent
|   |   |-- llm_orchestrator.py    # Tool selection, arg validation, connector dispatch
|   |   `-- voice_optimizer.py     # Compresses large result sets for voice
|   |-- storage/
|   |   |-- base.py                # BaseAudioStore & BaseClarificationStore abstract interfaces
|   |   |-- factory.py             # get_audio_store() / get_clarification_store() with fail-fast
|   |   |-- memory.py              # In-memory ephemeral store with TTL cleaner
|   |   `-- redis.py               # Distributed Redis store (redis.asyncio) with key expiration
|   |-- utils/
|   |   |-- logging.py             # Structured JSON logging, ISO-8601 timestamps
|   |   `-- security.py            # API key validation middleware
|   `-- voice/
|       |-- audio_store.py         # Ephemeral store bridge
|       |-- audio_validation.py    # File size, duration, decodability checks
|       |-- obfuscator.py          # FormantPreservingObfuscator (WORLD) + VoiceObfuscator
|       |-- stt.py                 # STTEngine -- Whisper with confidence signals
|       `-- tts.py                 # Offline local SAPI5 & Remote Edge-TTS with privacy boundary
|-- data/
|   |-- customers.json             # Mock CRM records
|   |-- support_tickets.json       # Mock support tickets
|   |-- analytics.json             # Mock daily active user analytics
|   |-- questions_and_answers.md   # Ground-truth queries, expected routing & answers
|   `-- audio/                     # Canonical benchmark MPEG audio samples
|-- evaluation/                    # Evaluation suite & benchmark runners
|   |-- datasets/                  # Dev, challenge, distractor, adversarial test cases
|   |-- metrics/                   # WER, CER, speaker similarity, routing fidelity
|   `-- results/                   # Phase 6 & Phase 6.1 benchmark run outputs
|-- reports/                       # Architecture audit, remediation, and design documents
|-- scripts/
|   `-- eval_speaker_similarity.py # Wav2Vec2 x-vector neural speaker verification script
|-- tests/                         # Comprehensive pytest suite (330+ unit & integration tests)
|-- voice_chat.html                # Browser UI & Live Evaluation Lab dashboard
|-- .env.example                   # Environment variable template
|-- .dockerignore                  # Docker build exclusions
|-- Dockerfile                     # Multi-stage production container build
|-- docker-compose.yml             # Orchestrates app + Redis 7 service
|-- pytest.ini                     # Pytest configuration (asyncio_mode = auto)
|-- requirements.txt               # Production runtime dependencies
`-- requirements-dev.txt           # Evaluation & research dependencies (torch, transformers)
```

---

## Setup & Running the Application

### Prerequisites
- Python 3.10+
- [Ollama](https://ollama.ai) with `llama3.2:latest` pulled
- `ffmpeg` on PATH (used by pydub/librosa for audio decoding)
- (Optional) Docker & Docker Compose for containerized Redis & app deployment

### 1. Create and activate virtual environment
```powershell
python -m venv venv
.\venv\Scripts\activate
```

### 2. Install dependencies
```powershell
# Runtime dependencies
pip install -r requirements.txt

# Development, testing & evaluation dependencies (optional)
pip install -r requirements-dev.txt
```

### 3. Configure environment
```powershell
Copy-Item .env.example .env
```

Edit `.env` with your desired settings:
```env
API_KEY=dev-insecure-key
OBFUSCATION_STRENGTH=mild
STT_MODEL=base
OLLAMA_MODEL=llama3.2:latest
LLM_TIMEOUT_SECONDS=120.0
STORAGE_BACKEND=memory         # memory | redis
REDIS_URL=redis://localhost:6379/0
TTS_PROVIDER=remote
ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA=false
```

### 4. Start the server
```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open **http://127.0.0.1:8000/** in your browser to access the Voice Assistant & Live Evaluation Lab.

---

## Docker Deployment (with Redis)

The project includes a production-ready `docker-compose.yml` that runs the FastAPI application alongside an isolated Redis 7 container:

```powershell
# 1. Validate docker compose configuration
docker compose config

# 2. Build and launch services in background
docker compose up -d --build

# 3. View status and logs
docker compose ps
docker compose logs -f app
```

The app service automatically waits for Redis health checks to pass before binding to port `8000`.

---

## Configuration Reference (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | *(required)* | Server API key. UI uses `dev-insecure-key`. |
| `OBFUSCATION_STRENGTH` | `mild` | Global default obfuscation intensity (`mild`, `medium`, `strong`, `very_strong`). |
| `STT_MODEL` | `base` | Whisper model name (`tiny`, `base`, `small`, `medium`, `large`). |
| `OLLAMA_MODEL` | `llama3.2:latest` | Ollama model for correction guard + tool selection. |
| `STORAGE_BACKEND` | `memory` | Storage implementation: `memory` (ephemeral dict) or `redis` (Redis 7). |
| `REDIS_URL` | `redis://localhost:6379/0` | Connection string for Redis instance. |
| `AUDIO_STORE_TTL_SECONDS` | `300` | Expiration time for temporary audio buffers and session keys. |
| `MAX_RESULTS` | `10` | Maximum records returned to the voice pipeline per query. |
| `TTS_PROVIDER` | `remote` | TTS provider: `local` (offline Windows SAPI5), `remote` (Edge-TTS), or `disabled`. |
| `ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA` | `false` | Privacy boundary: blocks sending operational/PII data to cloud TTS. |
| `ALLOWED_ORIGINS` | `http://127.0.0.1:8000` | CORS allowed origins. |

---

## Privacy Architecture: Dual-Layer Defense

### 1. Acoustic Anonymization (Formant-Preserving Obfuscation)
Conventional pitch-shifting alters vocal frequency but leaves vocal-tract resonances (formants) exposed to speaker verification models. Our `FormantPreservingObfuscator`:
1. **F0 Perturbation:** Shifts fundamental frequency across configurable semitones (+/-2 to +/-8 st) with random Gaussian jitter.
2. **Spectral Envelope Warping:** Applies a McAdams coefficient (alpha in [0.88, 1.12]) via the WORLD vocoder (`pyworld`), warping the frequency axis of the vocal-tract filter.
3. **Biometric Disruption:** Achieves a **-12.2% drop** in cosine similarity against the Wav2Vec2 x-vector SUPERB benchmark while maintaining a **99.5% Whisper transcription accuracy (WER 0.005)**.

### 2. Evidence-Grounded Selective Abstention
Prevents unintended execution and data leakage when handling adversarial or out-of-domain queries:
- **Distractor FPR:** Reduced from **85% -> 0%** when tested against adversarial distractors.
- **Held-Out Generalization:** **86.7%** routing accuracy on previously unseen queries.
- **Pre-Execution Failure Predictor:** Evaluates query confidence with **97.7% Precision**, **87.8% Recall**, and **2.4% FPR** before executing database queries.

### 3. TTS Privacy Boundary
- Responses containing database records (CRM, tickets, analytics) are marked `is_sensitive=True`.
- When `ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA=false`, sensitive responses will **never** leave the host to cloud TTS endpoints (`edge-tts`). On Windows, offline local SAPI5 synthesis is used; in cloud environments, playback safely degrades to text.

---

## Evaluation Lab & Benchmarks

The web UI contains an integrated **Live Evaluation Lab** (backed by `/evaluation/*` endpoints) allowing interactive inspection of pre-computed benchmark runs and live audio streams.

### Benchmark 1: Acoustic Obfuscation & STT Fidelity
Run the benchmark across 8 canonical business query phrases:
```powershell
python benchmark_obfuscation.py --seed 42 --strengths none,mild,medium,strong,very_strong
```

| Strength | Avg WER | Avg CER | Avg Alpha | Avg Obf Latency | Routing OK% |
|----------|---------|---------|-----------|-----------------|-------------|
| `none`   | 0.000   | 0.000   | 1.000     | 0.0 ms          | 100.0%      |
| `mild`   | 0.000   | 0.000   | 1.004     | ~1100 ms        | 100.0%      |
| `medium` | 0.000   | 0.000   | 0.972     | ~642 ms         | 100.0%      |
| `strong` | 0.021   | 0.004   | 0.958     | ~660 ms         | 100.0%      |
| **OVERALL** | **0.005** | **0.001** | --     | **~600 ms**     | **100.0%**  |

### Benchmark 2: Neural Speaker Verification (Wav2Vec2 x-vector)
Measures biometric identity disruption using Meta's `anton-l/wav2vec2-base-superb-sv` model:
```powershell
python scripts/eval_speaker_similarity.py
```

| Tier | Avg Cosine Similarity | Avg Similarity Drop | Interpretation |
|------|-----------------------|---------------------|----------------|
| `none` | 1.0000 | 0.00% | Unaltered speaker identity |
| `mild` | 0.9768 | 2.32% | Slight pitch variance |
| `medium` | 0.9454 | 5.46% | Detectable identity change |
| `strong` | 0.9151 | 8.49% | Significant biometric disruption |
| `strong_with_tempo` | 0.8780 | 12.20% | Biometric signature obscured |

---

## Running Tests

Run the full pytest suite:
```powershell
# Run all tests
pytest tests/ -v

# Run with real Redis (when Redis is running)
pytest tests/test_store_abstractions.py -v
```

The test suite covers:
- **Storage Abstractions:** Redis & Memory parity, TTL enforcement, fail-fast pings.
- **Audio Validation:** Size limits, duration caps, corrupt audio handling.
- **Acoustic Obfuscation:** WORLD vocoder pitch and McAdams formant warping.
- **Abstention & Invariants:** E-domain / E-op scoring, distractor rejection, parameter validation.
- **API & End-to-End Pipeline:** Multi-domain joins, tool dispatching, and streaming audio.
