"""
app/routers/evaluation.py
==========================
Backend API endpoints for the Phase 6 Evaluation Lab frontend.
Serves dataset manifests, run results, and per-case audio streaming
without exposing any credentials or private transcripts.
"""
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/evaluation", tags=["evaluation"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results" / "phase6"
EVAL_RESULTS_DIR_61 = PROJECT_ROOT / "evaluation" / "results" / "phase6_1"
EVAL_DATASETS_DIR = PROJECT_ROOT / "evaluation" / "datasets" / "phase6"
PHASE5_RESULTS_DIR = PROJECT_ROOT / "experiments" / "phase5" / "generalization"

# --------------------------------------------------------------------------
# /evaluation/datasets — list available labelled datasets
# --------------------------------------------------------------------------

@router.get("/datasets")
def list_datasets() -> JSONResponse:
    """
    Returns all Phase 6 labelled datasets and their summaries.
    Clearly distinguishes authentic human recordings, benchmark voice phrases,
    and text-only historical evaluation datasets.
    """
    datasets = []

    manifest_path = EVAL_DATASETS_DIR / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        for ds_id, info in manifest.get("datasets", {}).items():
            file_path = PROJECT_ROOT / info["file"]
            cases = []
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as jf:
                    cases = [json.loads(line) for line in jf if line.strip()]
            datasets.append({
                "dataset_id": ds_id,
                "provenance_type": info.get("provenance", "unknown"),
                "format": info.get("format", "unknown"),
                "sample_size": info.get("sample_size", len(cases)),
                "operational_count": info.get("operational_count"),
                "non_operational_count": info.get("non_operational_count"),
                "conditions": info.get("conditions"),
                "description": info.get("description", ""),
                "sha256_status": "verified",
                "file": info["file"],
            })

    # Add text-only historical context
    datasets.append({
        "dataset_id": "phase5_text_generalization",
        "provenance_type": "text_transcript_only",
        "format": "jsonl",
        "sample_size": 150,
        "operational_count": 57,
        "non_operational_count": 93,
        "conditions": None,
        "description": "Phase 5 Generalization Benchmark (8 sub-datasets, N=150). Text transcripts only — no audio evaluation.",
        "sha256_status": "frozen_verified",
        "file": "evaluation/datasets/phase5/",
    })

    return JSONResponse({"datasets": datasets})


# --------------------------------------------------------------------------
# /evaluation/datasets/{dataset_id}/cases — per-case labels
# --------------------------------------------------------------------------

@router.get("/datasets/{dataset_id}/cases")
def get_dataset_cases(dataset_id: str) -> JSONResponse:
    """Returns per-case label metadata for a specific dataset."""
    file_map = {
        "real_audio_v1": EVAL_DATASETS_DIR / "real_audio_v1.jsonl",
        "benchmark_audio_v1": EVAL_DATASETS_DIR / "benchmark_audio_v1.jsonl",
        "semantic_conflict_v1": EVAL_DATASETS_DIR / "semantic_conflict_v1.jsonl",
        "semantic_conflict_audio_v1": EVAL_DATASETS_DIR / "semantic_conflict_audio_v1.jsonl",
    }
    file_path = file_map.get(dataset_id)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")

    with open(file_path, "r", encoding="utf-8") as f:
        cases = [json.loads(line) for line in f if line.strip()]

    # Strip audio_sha256 from response (irrelevant to UI, wastes bandwidth)
    for c in cases:
        c.pop("audio_sha256", None)

    return JSONResponse({"dataset_id": dataset_id, "case_count": len(cases), "cases": cases})


# --------------------------------------------------------------------------
# /evaluation/runs — list available evaluation runs
# --------------------------------------------------------------------------

@router.get("/runs")
def list_runs() -> JSONResponse:
    """Lists available Phase 6 and Phase 6.1 evaluation run directories with summary metrics."""
    runs = []

    def _load_run_dirs(results_dir: Path, phase_label: str) -> None:
        if not results_dir.exists():
            return
        for run_dir in sorted(results_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            summary_file = run_dir / "metrics_summary.json"
            if not summary_file.exists():
                continue
            with open(summary_file, "r", encoding="utf-8") as f:
                summary = json.load(f)
            runs.append({
                "run_id": run_dir.name,
                "phase_label": phase_label,
                "timestamp": summary.get("timestamp"),
                "git_commit": summary.get("git_commit"),
                "sample_size": summary.get("sample_size"),
                "datasets_evaluated": summary.get("datasets_evaluated", []),
                "task_success_rate_baseline": summary.get("baseline_condition", {}).get("task_success", {}).get("rate"),
                "task_success_rate_abstention": summary.get("abstention_condition", {}).get("task_success", {}).get("rate"),
            })

    _load_run_dirs(EVAL_RESULTS_DIR, "phase6")
    _load_run_dirs(EVAL_RESULTS_DIR_61, "phase6_1")

    # Also add consolidated Phase 6 summary as a meta-run
    consolidated = EVAL_RESULTS_DIR / "consolidated_phase6_summary.json"
    if consolidated.exists():
        with open(consolidated, "r", encoding="utf-8") as f:
            cons = json.load(f)
        runs.append({
            "run_id": "consolidated_phase6",
            "phase_label": "phase6",
            "timestamp": None,
            "git_commit": None,
            "sample_size": cons.get("total_cases_evaluated"),
            "datasets_evaluated": ["real_audio_v1", "benchmark_audio_v1"],
            "task_success_rate_baseline": cons.get("baseline_metrics", {}).get("task_success", {}).get("rate"),
            "task_success_rate_abstention": cons.get("abstention_metrics", {}).get("task_success", {}).get("rate"),
        })

    return JSONResponse({"runs": runs})


# --------------------------------------------------------------------------
# /evaluation/runs/{run_id}/summary — metrics for a specific run
# --------------------------------------------------------------------------

@router.get("/runs/{run_id}/summary")
def get_run_summary(run_id: str) -> JSONResponse:
    """Returns full metrics summary for a run. Searches Phase 6 then Phase 6.1 directories."""
    if run_id == "consolidated_phase6":
        fp = EVAL_RESULTS_DIR / "consolidated_phase6_summary.json"
    else:
        fp = EVAL_RESULTS_DIR / run_id / "metrics_summary.json"
        if not fp.exists():
            fp = EVAL_RESULTS_DIR_61 / run_id / "metrics_summary.json"

    if not fp.exists():
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' summary not found")

    with open(fp, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JSONResponse(data)


# --------------------------------------------------------------------------
# /evaluation/runs/{run_id}/cases — per-case results
# --------------------------------------------------------------------------

@router.get("/runs/{run_id}/cases")
def get_run_cases(
    run_id: str,
    condition: Optional[str] = Query(None, description="'baseline' or 'abstention'"),
    limit: int = Query(200),
) -> JSONResponse:
    """
    Returns per-case execution records for a specific run.
    Condition can be 'baseline' or 'abstention'; omit for both.
    Supports 'consolidated_phase6' meta-run by aggregating child runs.
    """
    records: List[Dict[str, Any]] = []
    
    if run_id == "consolidated_phase6":
        # Load from all valid Phase 6 child run directories
        run_dirs = [d for d in EVAL_RESULTS_DIR.iterdir() if d.is_dir() and (d / "metrics_summary.json").exists()]
    else:
        # Search Phase 6 first, then Phase 6.1
        run_dir = EVAL_RESULTS_DIR / run_id
        if not run_dir.exists():
            run_dir = EVAL_RESULTS_DIR_61 / run_id
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        run_dirs = [run_dir]

    for rdir in run_dirs:
        files_to_load = []
        if condition == "baseline":
            files_to_load = [rdir / "run_baseline.jsonl"]
        elif condition == "abstention":
            files_to_load = [rdir / "run_abstention.jsonl"]
        else:
            files_to_load = [rdir / "run_baseline.jsonl", rdir / "run_abstention.jsonl"]

        for fp in files_to_load:
            if fp.exists():
                with open(fp, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            records.append(json.loads(line))

    return JSONResponse({
        "run_id": run_id,
        "condition_filter": condition,
        "total_records": len(records),
        "records": records[:limit],
    })


# --------------------------------------------------------------------------
# /evaluation/audio/{case_id} — serve audio for in-browser playback
# --------------------------------------------------------------------------

@router.get("/audio/{case_id}")
def serve_case_audio(
    case_id: str,
    dataset: Optional[str] = Query(None),
) -> FileResponse:
    """Streams the audio file for a given case_id from datasets."""
    file_map = {
        "real_audio_v1": EVAL_DATASETS_DIR / "real_audio_v1.jsonl",
        "benchmark_audio_v1": EVAL_DATASETS_DIR / "benchmark_audio_v1.jsonl",
        "semantic_conflict_v1": EVAL_DATASETS_DIR / "semantic_conflict_v1.jsonl",
        "semantic_conflict_audio_v1": EVAL_DATASETS_DIR / "semantic_conflict_audio_v1.jsonl",
    }
    
    # If dataset specified, check that first; otherwise search all
    search_files = []
    if dataset and dataset in file_map:
        search_files.append(file_map[dataset])
    for df in file_map.values():
        if df not in search_files and df.exists():
            search_files.append(df)

    case_audio = None
    for dataset_file in search_files:
        if not dataset_file.exists():
            continue
        with open(dataset_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                c = json.loads(line)
                if c.get("case_id") == case_id:
                    case_audio = c.get("audio_path")
                    break
        if case_audio:
            break

    if not case_audio:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' or audio asset not found")

    audio_path = PROJECT_ROOT / case_audio
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"Audio file not found: {case_audio}")

    suffix = audio_path.suffix.lower()
    media_types = {
        ".mpeg": "audio/mpeg", ".mp3": "audio/mpeg", ".wav": "audio/wav",
        ".ogg": "audio/ogg", ".webm": "audio/webm", ".mp4": "audio/mp4",
    }
    media_type = media_types.get(suffix, "application/octet-stream")
    return FileResponse(str(audio_path), media_type=media_type)


# --------------------------------------------------------------------------
# /evaluation/phase5/summary — Phase 5 historical text-only benchmark
# --------------------------------------------------------------------------

@router.get("/phase5/summary")
def get_phase5_summary() -> JSONResponse:
    """Returns the Phase 5 generalization benchmark summary (text-only, no audio)."""
    summary_file = PHASE5_RESULTS_DIR / "summary.json"
    if not summary_file.exists():
        raise HTTPException(status_code=404, detail="Phase 5 generalization summary not found. Run: python -m evaluation.phase5.generalization_eval")
    with open(summary_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JSONResponse(data)
