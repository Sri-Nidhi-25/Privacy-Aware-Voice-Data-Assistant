# ============================================================
# Privacy-Preserving Voice Data Assistant — Dockerfile
# ============================================================
#
# TTS NOTE:
#   TTS_PROVIDER=local uses Windows SAPI5 (System.Speech.Synthesis)
#   and is NOT available inside this Linux container.
#
#   For containerised deployment, set:
#     TTS_PROVIDER=remote   → uses edge-tts (cloud, non-sensitive text only)
#     TTS_PROVIDER=disabled → skips TTS entirely (transcript-only responses)
#
#   The ALLOW_REMOTE_TTS_FOR_SENSITIVE_DATA setting (default false) is
#   enforced by the application and must remain false in production to
#   prevent private connector results from being sent to cloud TTS.
#
# STORAGE NOTE:
#   This image is designed to run with STORAGE_BACKEND=redis.
#   The companion docker-compose.yml starts a Redis container automatically.
#   For single-container local testing only, STORAGE_BACKEND=memory works
#   but state will NOT persist across container restarts or multiple workers.
# ============================================================

FROM python:3.11-slim

# System dependencies required by librosa, soundfile, pydub, and pyworld
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source (venv, .env, benchmark_audio are in .dockerignore)
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
