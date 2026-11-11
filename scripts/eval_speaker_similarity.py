# -*- coding: utf-8 -*-
"""
eval_speaker_similarity.py
==========================
Evaluates Neural Speaker Verification Cosine Similarity Drop on the
Privacy-Aware Voice Data Assistant.

Uses the pretrained Wav2Vec2 x-vector speaker verification model
(anton-l/wav2vec2-base-superb-sv from the SUPERB benchmark) to compute
deep neural speaker embeddings and quantify the empirical similarity drop:
    Similarity Drop = 1.0 - CosineSimilarity(Embedding(clean), Embedding(obfuscated))

Outputs
-------
  benchmark_audio/speaker_similarity_results.csv
  Tabular summary on stdout
"""
import argparse
import csv
import sys
import time
from pathlib import Path

# Force UTF-8 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import torch
import librosa
from transformers import AutoFeatureExtractor, AutoModelForAudioXVector

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.voice.obfuscator import FormantPreservingObfuscator

MODEL_ID = "anton-l/wav2vec2-base-superb-sv"
BENCHMARK_DIR = PROJECT_ROOT / "benchmark_audio"


def load_model():
    print(f"Loading neural speaker verification model: {MODEL_ID} ...", flush=True)
    fe = AutoFeatureExtractor.from_pretrained(MODEL_ID)
    model = AutoModelForAudioXVector.from_pretrained(MODEL_ID)
    model.eval()
    return fe, model


def compute_embedding(fe, model, audio_path: Path) -> torch.Tensor:
    y, _ = librosa.load(str(audio_path), sr=16000)
    with torch.no_grad():
        inputs = fe(y, sampling_rate=16000, return_tensors="pt")
        emb = model(**inputs).embeddings
        return torch.nn.functional.normalize(emb, dim=-1)


def run_speaker_similarity_eval(
    phrases_count: int = 8,
    strengths: list[str] = None,
    out_csv: Path = BENCHMARK_DIR / "speaker_similarity_results.csv",
):
    if strengths is None:
        strengths = ["none", "mild", "medium", "strong", "strong_with_tempo"]

    fe, model = load_model()
    results = []

    print("\nStarting Neural Speaker Verification Evaluation across tiers...\n")
    print(f"{'Phrase':<10} {'Tier':<18} {'Cosine Sim':>12} {'Sim Drop':>12} {'Shift (st)':>12} {'Alpha':>8} {'Tempo':>8}")
    print("-" * 84)

    shift_map = {
        "none": 0.0,
        "mild": 2.0,
        "medium": 4.0,
        "strong": 6.0,
        "strong_with_tempo": 6.0,
    }

    for idx in range(phrases_count):
        clean_path = BENCHMARK_DIR / f"phrase_{idx}.wav"
        if not clean_path.exists():
            continue

        emb_clean = compute_embedding(fe, model, clean_path)

        for tier in strengths:
            if tier == "none":
                sim = 1.0000
                sim_drop = 0.0000
                shift_val = 0.0
                alpha_val = 1.000
                tempo_val = 1.00
            else:
                semitones = shift_map.get(tier, 4.0)
                obf = FormantPreservingObfuscator(semitone_shift=semitones, randomize=False)
                
                tempo = 1.10 if tier == "strong_with_tempo" else 1.0
                if tier == "mild":
                    obf.vtln_range = (0.95, 0.95)
                elif tier == "medium":
                    obf.vtln_range = (0.92, 0.92)
                else:
                    obf.vtln_range = (0.89, 0.89)

                tmp_wav = BENCHMARK_DIR / f"tmp_sim_{idx}_{tier}.wav"
                shift_applied = obf.obfuscate(clean_path, tmp_wav, tempo_rate=tempo)
                alpha_val = round(obf.last_alpha, 3)
                tempo_val = round(obf.last_tempo_rate, 2)
                shift_val = round(shift_applied, 2)

                emb_obf = compute_embedding(fe, model, tmp_wav)
                sim = torch.cosine_similarity(emb_clean, emb_obf).item()
                sim_drop = max(0.0, 1.0 - sim)
                tmp_wav.unlink(missing_ok=True)

            row = {
                "phrase_idx": idx,
                "tier": tier,
                "cosine_similarity": round(sim, 4),
                "similarity_drop": round(sim_drop, 4),
                "shift_semitones": shift_val,
                "formant_alpha": alpha_val,
                "tempo_rate": tempo_val,
            }
            results.append(row)
            print(f"Phrase {idx:<3} {tier:<18} {sim:>12.4f} {sim_drop:>12.4f} {shift_val:>11.2f}st {alpha_val:>8.3f} {tempo_val:>7.2f}x")

    # Write CSV
    if results:
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)
        print(f"\nDetailed evaluation written to: {out_csv}")

    # Summary table
    print("\n" + "=" * 76)
    print(f"{'Tier':<20} {'Avg Cosine Sim':>16} {'Avg Sim Drop':>14} {'N':>6}")
    print("-" * 76)
    from collections import defaultdict
    grouped = defaultdict(list)
    for r in results:
        grouped[r["tier"]].append(r)

    for tier in strengths:
        rows = grouped.get(tier, [])
        if not rows:
            continue
        avg_sim = sum(r["cosine_similarity"] for r in rows) / len(rows)
        avg_drop = sum(r["similarity_drop"] for r in rows) / len(rows)
        print(f"{tier:<20} {avg_sim:>16.4f} {avg_drop:>13.2%} {len(rows):>6}")
    print("=" * 76)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate Neural Speaker Verification Cosine Similarity Drop")
    parser.add_argument("--phrases", type=int, default=8, help="Number of benchmark phrases (default: 8)")
    args = parser.parse_args()
    run_speaker_similarity_eval(phrases_count=args.phrases)
