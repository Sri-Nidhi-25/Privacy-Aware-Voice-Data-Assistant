# -*- coding: utf-8 -*-
"""
benchmark_obfuscation.py
========================
Standalone benchmark for the active FormantPreservingObfuscator (WORLD vocoder)
from app/voice/obfuscator.py.

Usage
-----
    python benchmark_obfuscation.py [--seed N] [--out-dir DIR] [--strengths s1,s2,...]

What it measures
----------------
For each (phrase, obfuscation_strength) combination the script:
  1. Synthesises clean TTS audio with edge-tts (written once, reused across
     strengths).
  2. Runs FormantPreservingObfuscator.obfuscate() and records the actual
     semitone shift applied.
  3. Transcribes both the original and the obfuscated audio with OpenAI
     Whisper and computes Word Error Rate (WER) for the obfuscated version.
  4. Checks whether the corrected transcript would still route to the correct
     data-query tool (routing fidelity).

Outputs
-------
  benchmark_audio/results.csv  — machine-readable results
  (stdout)                      — human-readable table + summary statistics

Dependencies: all satisfied by requirements.txt (edge-tts, openai-whisper,
pyworld, librosa, jiwer).
"""

import argparse
import asyncio
import csv
import random
import sys
import time
from pathlib import Path

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import whisper

# ---------------------------------------------------------------------------
# Ensure project root is on the path so app.* imports work
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.voice.obfuscator import FormantPreservingObfuscator  # noqa: E402
from app.services.intent_router import classify_intent, is_data_query  # noqa: E402

# ---------------------------------------------------------------------------
# Test corpus — 8 representative business-query phrases covering all 3 domains
# ---------------------------------------------------------------------------
TEST_PHRASES = [
    # (phrase_text, expects_data_query)
    ("Show me all high priority open tickets",               True),
    ("How many active customers do we have",                 True),
    ("What's the daily active users trend for the last seven days", True),
    ("List closed support tickets from this week",           True),
    ("Give me the average daily active users",               True),
    ("How many customers are inactive",                      True),
    ("Show me low priority closed tickets",                  True),
    ("What is today's weather like",                         False),  # intentional OOD
]

STRENGTH_TO_SEMITONES = {
    "none":        0.0,
    "mild":        2.0,
    "medium":      4.0,
    "strong":      6.0,
    "very_strong": 8.0,
}

TTS_VOICE = "en-US-AriaNeural"

# ---------------------------------------------------------------------------
# WER and CER helpers (Levenshtein-based, robust and self-contained)
# ---------------------------------------------------------------------------
def _normalise(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Levenshtein-based WER; returns fraction (0.0 to 1.0+)."""
    ref = _normalise(reference).split()
    hyp = _normalise(hypothesis).split()
    if not ref:
        return 0.0
    n = len(ref)
    m = len(hyp)
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[:]
        dp[0] = i
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[j] = prev[j - 1]
            else:
                dp[j] = 1 + min(prev[j], dp[j - 1], prev[j - 1])
    return round(dp[m] / n, 3)


def char_error_rate(reference: str, hypothesis: str) -> float:
    """Levenshtein-based CER; returns character error fraction."""
    ref = _normalise(reference)
    hyp = _normalise(hypothesis)
    if not ref:
        return 0.0
    n = len(ref)
    m = len(hyp)
    dp = list(range(m + 1))
    for i in range(1, n + 1):
        prev = dp[:]
        dp[0] = i
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[j] = prev[j - 1]
            else:
                dp[j] = 1 + min(prev[j], dp[j - 1], prev[j - 1])
    return round(dp[m] / n, 3)



# ---------------------------------------------------------------------------
# TTS synthesis helper
# ---------------------------------------------------------------------------
async def _synthesize(text: str, out_path: Path) -> None:
    """Synthesise text to MP3 via edge-tts (en-US-AriaNeural)."""
    import edge_tts
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(str(out_path))


# ---------------------------------------------------------------------------
# Main benchmark loop
# ---------------------------------------------------------------------------
def run_benchmark(
    seed: int = 42,
    out_dir: Path = Path("benchmark_audio"),
    strengths: list[str] | None = None,
) -> list[dict]:
    random.seed(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    if strengths is None:
        strengths = ["none", "mild", "medium", "strong"]

    # Load Whisper once — base model is fast and accurate enough for this use-case
    print("Loading Whisper (base) ...", flush=True)
    whisper_model = whisper.load_model("base")

    results: list[dict] = []
    total = len(TEST_PHRASES) * len(strengths)
    done = 0

    for phrase_idx, (phrase, expects_data_query) in enumerate(TEST_PHRASES):
        # ------------------------------------------------------------------
        # Step 1: synthesise clean TTS audio (once per phrase)
        # ------------------------------------------------------------------
        mp3_path = out_dir / f"phrase_{phrase_idx}.mp3"
        wav_path = out_dir / f"phrase_{phrase_idx}.wav"

        if not mp3_path.exists():
            print(f"  [TTS] Synthesising phrase {phrase_idx}: '{phrase[:50]}...'")
            asyncio.run(_synthesize(phrase, mp3_path))

        # Convert to WAV for obfuscation (librosa handles mp3 → float32 natively)
        if not wav_path.exists():
            import librosa
            import soundfile as sf
            y, sr = librosa.load(str(mp3_path), sr=16000, mono=True)
            sf.write(str(wav_path), y, sr)

        # Transcribe the un-obfuscated audio as a reference baseline
        ref_result = whisper_model.transcribe(str(wav_path))
        ref_transcript = ref_result["text"].strip()

        for strength in strengths:
            done += 1
            semitones = STRENGTH_TO_SEMITONES.get(strength, 0.0)
            obf_path = out_dir / f"phrase_{phrase_idx}_{strength}.wav"

            # ------------------------------------------------------------------
            # Step 2: obfuscate  (skip for "none" — keep original wav)
            # ------------------------------------------------------------------
            if strength == "none":
                import shutil
                shutil.copy(str(wav_path), str(obf_path))
                actual_shift = 0.0
                actual_alpha = 1.0
                obf_ms = 0
            else:
                obfuscator = FormantPreservingObfuscator(
                    semitone_shift=semitones,
                    randomize=True,
                    jitter=0.5 if strength == "mild" else 1.0,
                )
                t0 = time.perf_counter()
                actual_shift = obfuscator.obfuscate(wav_path, obf_path)
                obf_ms = int((time.perf_counter() - t0) * 1000)
                actual_alpha = getattr(obfuscator, "last_alpha", 1.0)

            # ------------------------------------------------------------------
            # Step 3: transcribe obfuscated audio
            # ------------------------------------------------------------------
            t_stt = time.perf_counter()
            obf_result = whisper_model.transcribe(str(obf_path))
            stt_ms = int((time.perf_counter() - t_stt) * 1000)
            obf_transcript = obf_result["text"].strip()

            # ------------------------------------------------------------------
            # Step 4: WER & CER
            # ------------------------------------------------------------------
            wer = word_error_rate(phrase, obf_transcript)
            cer = char_error_rate(phrase, obf_transcript)

            # ------------------------------------------------------------------
            # Step 5: routing fidelity
            #   The corrected transcript should route to a data query iff the
            #   original phrase was a data query.
            # ------------------------------------------------------------------
            intent_result = classify_intent(obf_transcript)
            actual_data_query = is_data_query(obf_transcript)
            routing_ok = (actual_data_query == expects_data_query)

            row = {
                "phrase":              phrase,
                "strength":            strength,
                "semitones_requested": semitones,
                "actual_shift_st":     round(actual_shift, 3),
                "actual_alpha_vtln":   round(actual_alpha, 3),
                "obf_latency_ms":      obf_ms,
                "stt_latency_ms":      stt_ms,
                "transcript":          obf_transcript,
                "wer":                 wer,
                "cer":                 cer,
                "expected_data_query": expects_data_query,
                "actual_data_query":   actual_data_query,
                "routing_ok":          routing_ok,
            }
            results.append(row)

            status = "OK" if routing_ok else "FAIL"
            print(
                f"  [{done:>2}/{total}] {status} phrase={phrase_idx} "
                f"strength={strength:12s} shift={actual_shift:+.2f}st alpha={actual_alpha:.3f} "
                f"WER={wer:.3f} CER={cer:.3f} obf={obf_ms}ms"
            )

    return results


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------
def write_csv(results: list[dict], out_path: Path) -> None:
    fields = [
        "phrase", "strength", "semitones_requested", "actual_shift_st",
        "actual_alpha_vtln", "obf_latency_ms", "stt_latency_ms",
        "transcript", "wer", "cer", "expected_data_query", "actual_data_query", "routing_ok",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nResults written to: {out_path}")


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------
def print_summary(results: list[dict]) -> None:
    from collections import defaultdict

    per_strength: dict[str, list] = defaultdict(list)
    for r in results:
        per_strength[r["strength"]].append(r)

    print("\n" + "=" * 80)
    print(f"{'Strength':<14} {'Avg WER':>8} {'Avg CER':>8} {'Avg Alpha':>10} {'Avg Obf(ms)':>12} {'RouteOK%':>9} {'N':>4}")
    print("-" * 80)
    for strength in ["none", "mild", "medium", "strong", "very_strong"]:
        rows = per_strength.get(strength)
        if not rows:
            continue
        avg_wer = sum(r["wer"] for r in rows) / len(rows)
        avg_cer = sum(r["cer"] for r in rows) / len(rows)
        avg_alpha = sum(r["actual_alpha_vtln"] for r in rows) / len(rows)
        avg_obf_ms = sum(r["obf_latency_ms"] for r in rows) / len(rows)
        route_pct = 100 * sum(1 for r in rows if r["routing_ok"]) / len(rows)
        print(f"  {strength:<12} {avg_wer:>8.3f} {avg_cer:>8.3f} {avg_alpha:>10.3f} {avg_obf_ms:>10.1f}ms {route_pct:>8.1f}% {len(rows):>4}")

    overall_wer = sum(r["wer"] for r in results) / len(results) if results else 0
    overall_cer = sum(r["cer"] for r in results) / len(results) if results else 0
    overall_route = 100 * sum(1 for r in results if r["routing_ok"]) / len(results) if results else 0
    print("-" * 80)
    print(f"  {'OVERALL':<12} {overall_wer:>8.3f} {overall_cer:>8.3f} {'-':>10} {'-':>12} {overall_route:>8.1f}% {len(results):>4}")
    print("=" * 80)
    print("\nNotes:")
    print("  • WER / CER: computed vs. ground-truth reference (0.000 = identical).")
    print("  • RouteOK%: whether intent classification accurately routed to data/abstain.")
    print("  • Obfuscator: FormantPreservingObfuscator (WORLD vocoder + McAdams VTLN formant warp).")
    print("  • Whisper model: base.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark FormantPreservingObfuscator (WORLD vocoder) WER + routing fidelity."
    )
    parser.add_argument("--seed",      type=int,   default=42,                   help="Random seed (default 42)")
    parser.add_argument("--out-dir",   type=Path,  default=Path("benchmark_audio"), help="Output directory")
    parser.add_argument(
        "--strengths",
        type=str,
        default="none,mild,medium,strong",
        help="Comma-separated list of strengths to benchmark (default: none,mild,medium,strong)"
    )
    args = parser.parse_args()

    strengths = [s.strip() for s in args.strengths.split(",")]
    invalid = [s for s in strengths if s not in STRENGTH_TO_SEMITONES]
    if invalid:
        parser.error(f"Unknown strength(s): {invalid}. Choose from: {list(STRENGTH_TO_SEMITONES)}")

    print(f"\n{'='*72}")
    print("FormantPreservingObfuscator Benchmark  (WORLD Vocoder — F0-only shift)")
    print(f"{'='*72}")
    print(f"  Seed:      {args.seed}")
    print(f"  Out dir:   {args.out_dir}")
    print(f"  Strengths: {strengths}")
    print(f"  Phrases:   {len(TEST_PHRASES)}")
    print()

    results = run_benchmark(seed=args.seed, out_dir=args.out_dir, strengths=strengths)

    csv_path = args.out_dir / "results.csv"
    write_csv(results, csv_path)
    print_summary(results)


if __name__ == "__main__":
    main()
