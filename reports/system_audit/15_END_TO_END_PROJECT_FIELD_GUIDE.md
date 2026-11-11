# Report 15 — End-to-End Project Field Guide & Operator Runbook

**Audit Document:** `reports/system_audit/15_END_TO_END_PROJECT_FIELD_GUIDE.md`  
**HEAD Commit:** `5b20a3a`  
**Purpose:** Comprehensive Local Setup, CLI Workflows, API Testing & Debugging Runbook  

---

## 1. Environment Setup & Prerequisites

### 1.1 System Requirements
- **OS:** Windows 10/11, macOS, or Linux (Ubuntu 22.04+).
- **Python:** Python 3.11 (Python 3.11.3 verified in workspace).
- **System Binaries:** `ffmpeg` and `libsndfile1` must be installed on the system PATH.
- **Ollama Daemon:** Ollama installed and running with `llama3.2:latest` pulled.

### 1.2 Step-by-Step Installation
```powershell
# 1. Clone repository
git clone https://github.com/Sri-Nidhi-25/Privacy-Preserving-Voice-Data-Assistant.git
cd Privacy-Preserving-Voice-Data-Assistant

# 2. Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1  # On Linux/macOS: source venv/bin/activate

# 3. Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Pull Ollama model
ollama pull llama3.2:latest
ollama serve  # Start daemon in background
```

---

## 2. Starting the Application

```powershell
# Start FastAPI application via Uvicorn
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Once started, access the web interface at:  
👉 **`http://127.0.0.1:8000/`**

---

## 3. Running the Test Suites

```powershell
# 1. Run all 152 automated tests
.\venv\Scripts\python.exe -m pytest -q

# 2. Run focused Phase 6 & Phase 6.1 evaluator tests
.\venv\Scripts\python.exe -m pytest tests/test_phase6/ -v

# 3. Run invariant security tests
.\venv\Scripts\python.exe -m pytest tests/test_invariants.py -v

# 4. Run real-audio end-to-end smoke test
.\venv\Scripts\python.exe -m pytest tests/test_e2e_smoke/test_smoke.py -v -s
```

---

## 4. Running the Paired Evaluation Benchmark

To reproduce the Phase 6 and Phase 6.1 paired evaluations directly via CLI:

```powershell
# Run paired evaluation on Phase 6.1 semantic conflict audio (N=10)
.\venv\Scripts\python.exe -m evaluation.runners.run_paired_evaluation `
  --dataset evaluation/datasets/phase6/semantic_conflict_audio_v1.jsonl `
  --out-dir evaluation/results/phase6_1/reproduced_run

# Run full Phase 6 benchmark (N=38: 6 human mic + 32 benchmark audio)
.\venv\Scripts\python.exe -m evaluation.runners.run_paired_evaluation `
  --phase6 `
  --out-dir evaluation/results/phase6/reproduced_run

# Verify dataset integrity and SHA256 hashes
.\venv\Scripts\python.exe evaluation/datasets/verify_datasets.py
```

---

## 5. API Testing with `curl` & PowerShell

### 5.1 Health Check Endpoints
```powershell
# Liveness probe
curl -X GET http://127.0.0.1:8000/health/liveness

# Readiness probe
curl -X GET http://127.0.0.1:8000/health/readiness
```

### 5.2 Querying the Voice Pipeline
```powershell
# Send authentic microphone recording (Customers.mpeg)
curl -X POST http://127.0.0.1:8000/voice/query `
  -H "x-api-key: your-api-key-here" `
  -F "file=@data/audio/Customers.mpeg;type=audio/mpeg"
```

### 5.3 Evaluation Lab API
```powershell
# List all registered datasets
curl -X GET http://127.0.0.1:8000/evaluation/datasets

# List all evaluation runs
curl -X GET http://127.0.0.1:8000/evaluation/runs

# Get summary metrics for a specific run
curl -X GET http://127.0.0.1:8000/evaluation/runs/88cd8262/summary

# Stream audio for a specific benchmark case
curl -X GET http://127.0.0.1:8000/evaluation/audio/sem_conf_aud_001 --output test_audio.wav
```

---

## 6. Navigating the Frontend Evaluation Lab

1. Open `http://127.0.0.1:8000/` in Google Chrome or Firefox.
2. In the top navigation bar, click the **"🔬 Evaluation Lab"** tab.
3. Use the **"Select Dataset"** dropdown to select `semantic_conflict_audio_v1 (N=10)`.
   - The provenance banner displays `🔊 Neural TTS Benchmark Audio (Phase 6.1)`.
4. Use the **"Evaluation Run"** dropdown to select `🧪 Phase 6.1 Pilot — 88cd8262 (N=10)`.
5. Review the **Paired Metric Cards**:
   - Compare Baseline vs With Abstention.
   - Click *"▸ What does this metric mean?"* on any card to view formulas and denominator rules.
6. Scroll down to the **Execution Records Browser**:
   - Filter by `Condition: With Abstention` and `Outcome: Failure`.
   - Click the audio player to listen to the exact synthesized speech.
   - Click the JSON inspector button to view stage-level latencies and tool arguments.

---

## 7. Common Troubleshooting & Error Recipes

### Issue 1: `ConnectionRefusedError: [Errno 111] Connect call failed ('127.0.0.1', 11434)`
- **Root Cause:** Ollama daemon is not running.
- **Fix:** Open a separate terminal and execute `ollama serve`. Verify with `curl http://127.0.0.1:11434/api/tags`.

### Issue 2: `UserWarning: FP16 is not supported on CPU; using FP32 instead`
- **Root Cause:** Whisper STT running on CPU without CUDA.
- **Fix:** Expected behavior; normal warning. Does not impact transcription accuracy.

### Issue 3: `HTTP 400: Failed to decode audio` or `PySoundFile failed`
- **Root Cause:** Missing `ffmpeg` or `libsndfile1` system libraries.
- **Fix:** Install ffmpeg:
  - Windows: `winget install Gyan.FFmpeg`
  - Linux: `sudo apt-get install ffmpeg libsndfile1`

### Issue 4: `Disk Bloat in temp_audio/`
- **Root Cause:** Multiple manual voice queries accumulating audio.
- **Fix:** Execute manual cleanup:
  ```powershell
  python -c "from app.voice.audio_store import EphemeralAudioStore; store=EphemeralAudioStore(); store.cleanup_stale(max_age_seconds=0)"
  ```
