"""
evaluation/runners/run_paired_evaluation.py
===========================================
Phase 6 Paired Baseline-versus-Abstention Real-Audio Reliability Evaluator.

Executes identical frozen real-audio and benchmark cases through both:
1. Baseline Condition: Production routing and execution with abstention disabled.
2. Abstention Condition: Production routing and execution with Phase 5 selective abstention enabled.

Calculates:
- Coverage (overall, operational, distractor, ambiguous)
- Selective Risk (error rate among executed cases)
- False-Positive Tool Execution Rate
- Missed Valid Requests (separated by failure cause)
- Task Success Rate (against ground truth)
- Failure Localization across 12 explicit stages
- Wilson 95% Confidence Intervals for all primary binomial proportions
"""
import argparse
import json
import logging
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.services.llm_orchestrator import LLMOrchestrator
from app.voice.audio_validation import validate_and_load
from app.voice.obfuscator import FormantPreservingObfuscator
from app.voice.stt import STTEngine
from evaluation.metrics.transcription import compute_wer, compute_cer
from evaluation.metrics.wilson_ci import wilson_score_interval, format_proportion_ci
from evaluation.provenance import get_git_commit, get_python_version, make_run_id

logger = logging.getLogger(__name__)

# 12 Explicit Pipeline Stages for Failure Localization
STAGE_INPUT_VALIDATION = "input_validation_failure"
STAGE_AUDIO_PREPROCESSING = "audio_preprocessing_failure"
STAGE_ASR_TRANSCRIPTION = "asr_transcription_failure"
STAGE_CORRECTION_SEMANTIC_CHANGE = "correction_induced_semantic_change"
STAGE_INTENT_ROUTING = "intent_routing_failure"
STAGE_ABSTENTION_FP = "abstention_false_positive"
STAGE_ABSTENTION_FN = "abstention_false_negative"
STAGE_CLARIFICATION_FAILURE = "clarification_failure"
STAGE_ARG_VALIDATION = "argument_validation_failure"
STAGE_TOOL_SELECTION = "tool_selection_failure"
STAGE_CONNECTOR_EXECUTION = "connector_execution_failure"
STAGE_RESPONSE_GENERATION = "response_generation_failure"
STAGE_TTS = "tts_failure"
STAGE_INFRASTRUCTURE = "infrastructure_failure"


class PairedPipelineRunner:
    def __init__(self):
        print("Initializing Paired Pipeline Runner components...", flush=True)
        self.obfuscator = FormantPreservingObfuscator(
            semitone_shift=4.0,
            jitter=1.5,
        )
        self.stt = STTEngine(model_name=settings.STT_MODEL)
        self.orchestrator = LLMOrchestrator(model=settings.OLLAMA_MODEL)
        self.asr_cache: Dict[str, Tuple[str, Dict[str, Any], int]] = {}
        print("Components ready.", flush=True)

    def process_audio(self, audio_path: Path, case_id: str) -> Tuple[Optional[str], Dict[str, Any], Dict[str, int], float]:
        """
        Validates, obfuscates, and transcribes audio once per case.
        Both baseline and abstention conditions share the exact same ASR output.
        """
        latencies: Dict[str, int] = {}
        t0 = time.perf_counter()

        # 1. Audio Validation
        t_val = time.perf_counter()
        file_size = audio_path.stat().st_size
        y, sr, duration = validate_and_load(audio_path, file_size)
        latencies["validation_ms"] = int((time.perf_counter() - t_val) * 1000)

        # 2. Obfuscation
        t_obf = time.perf_counter()
        tmp_obf = audio_path.parent / f"tmp_obf_{case_id}.wav"
        try:
            self.obfuscator.obfuscate(audio_path, tmp_obf)
            target_audio = tmp_obf
        except Exception as e:
            target_audio = audio_path
        latencies["obfuscation_ms"] = int((time.perf_counter() - t_obf) * 1000)

        # 3. Whisper STT (cached per case_id)
        if case_id in self.asr_cache:
            raw_transcript, conf, stt_lat = self.asr_cache[case_id]
            latencies["stt_ms"] = stt_lat
        else:
            t_stt = time.perf_counter()
            try:
                raw_transcript, conf = self.stt.transcribe_with_confidence(target_audio)
            except Exception as e:
                raw_transcript = ""
                conf = {"avg_logprob": -999.0, "no_speech_prob": 1.0, "low_confidence": True}
            stt_lat = int((time.perf_counter() - t_stt) * 1000)
            latencies["stt_ms"] = stt_lat
            self.asr_cache[case_id] = (raw_transcript, conf, stt_lat)

        tmp_obf.unlink(missing_ok=True)
        return raw_transcript, conf, latencies, duration

    def evaluate_case_condition(
        self,
        case: Dict[str, Any],
        raw_transcript: str,
        stt_conf: Dict[str, Any],
        audio_latencies: Dict[str, int],
        duration: float,
        enable_abstention: bool,
    ) -> Dict[str, Any]:
        case_id = case["case_id"]
        ref_text = case.get("reference_transcript", "")
        is_operational = case.get("is_operational", True)
        expected_tool = case.get("expected_tool")
        expected_args = case.get("expected_args", {})
        expected_decision = case.get("expected_decision", "EXECUTE" if is_operational else "ABSTAIN")
        expected_action = case.get("expected_action", expected_decision)

        latencies = dict(audio_latencies)
        t_orch_start = time.perf_counter()

        # Orchestration (Correction -> Routing -> Abstention -> Tool Selection -> Connector Execution)
        orch_res = self.orchestrator.process_query(
            raw_transcript,
            enable_abstention=enable_abstention,
        )
        orch_lat = int((time.perf_counter() - t_orch_start) * 1000)
        latencies["orchestration_ms"] = orch_lat
        latencies["total_ms"] = latencies.get("validation_ms", 0) + latencies.get("obfuscation_ms", 0) + latencies.get("stt_ms", 0) + orch_lat

        meta = orch_res.get("metadata", {})
        corrected_transcript = meta.get("corrected_transcript", raw_transcript)
        classified_intent = meta.get("classified_intent", "unknown")
        abstention_decision = meta.get("abstention_decision", "EXECUTE" if not enable_abstention else "ABSTAIN")
        abstention_reason = meta.get("abstention_reason")
        abstention_conf = meta.get("abstention_confidence", 1.0)

        tool_calls = meta.get("tool_calls", [])
        executed_tool = None
        executed_args = {}
        if tool_calls:
            first_call = tool_calls[0]
            rev_map = {"crm": "get_crm_data", "support": "get_support_tickets", "analytics": "get_analytics"}
            executed_tool = rev_map.get(first_call.get("source"), first_call.get("source"))
            executed_args = first_call.get("args", {})

        executed = executed_tool is not None
        answer_text = orch_res.get("answer", "")

        # Compute ASR metrics
        wer = compute_wer(ref_text, raw_transcript) if ref_text else 0.0
        cer = compute_cer(ref_text, raw_transcript) if ref_text else 0.0

        # Ground truth task evaluation
        is_correct_execution = False
        task_success = False
        is_false_positive_execution = False
        is_missed_valid_request = False
        primary_failure_stage: Optional[str] = None
        secondary_failure_stage: Optional[str] = None

        if expected_action == "EXECUTE":
            # Operational request evaluation
            if executed:
                tool_match = (executed_tool == expected_tool)
                # Check args match if expected
                args_match = True
                if expected_args:
                    for k, v in expected_args.items():
                        if executed_args.get(k) != v and executed_args.get(k) != str(v):
                            args_match = False
                if tool_match and args_match:
                    is_correct_execution = True
                    task_success = True
                else:
                    if not tool_match:
                        primary_failure_stage = STAGE_TOOL_SELECTION
                    else:
                        primary_failure_stage = STAGE_ARG_VALIDATION
            else:
                # Failed to execute operational request
                is_missed_valid_request = True
                if enable_abstention and abstention_decision in ("ABSTAIN", "CLARIFY"):
                    primary_failure_stage = STAGE_ABSTENTION_FP
                elif wer > 0.40:
                    primary_failure_stage = STAGE_ASR_TRANSCRIPTION
                elif meta.get("failure_type") == "invalid_tool_arguments" or meta.get("validation_error") or "couldn't interpret that filter" in answer_text:
                    primary_failure_stage = STAGE_ARG_VALIDATION
                elif meta.get("failure_type") == "llm_tool_call_timeout":
                    primary_failure_stage = STAGE_INFRASTRUCTURE
                elif meta.get("failure_type") == "connector_failed":
                    primary_failure_stage = STAGE_CONNECTOR_EXECUTION
                else:
                    primary_failure_stage = STAGE_INTENT_ROUTING
        elif expected_action == "CLARIFY":
            # Underspecified / Ambiguous input requiring clarification
            if executed:
                is_false_positive_execution = True
                is_correct_execution = False
                task_success = False
                primary_failure_stage = STAGE_CLARIFICATION_FAILURE
            else:
                # Safely asked for clarification or abstained from ungrounded tool execution
                is_correct_execution = False
                task_success = True
        else:
            # Distractor / Non-operational request evaluation (ABSTAIN)
            if executed:
                # False-positive execution!
                is_false_positive_execution = True
                is_correct_execution = False
                task_success = False
                if enable_abstention and abstention_decision == "EXECUTE":
                    primary_failure_stage = STAGE_ABSTENTION_FN
                else:
                    primary_failure_stage = STAGE_INTENT_ROUTING
            else:
                # Safely rejected / abstained
                is_correct_execution = False
                task_success = True  # Safe outcome achieved

        # Check for ASR root cause
        if primary_failure_stage in (STAGE_INTENT_ROUTING, STAGE_TOOL_SELECTION, STAGE_ABSTENTION_FP, STAGE_CLARIFICATION_FAILURE) and wer >= 0.50:
            secondary_failure_stage = primary_failure_stage
            primary_failure_stage = STAGE_ASR_TRANSCRIPTION

        return {
            "case_id": case_id,
            "condition_mode": "with_abstention" if enable_abstention else "baseline_no_abstention",
            "audio_path": case.get("audio_path"),
            "provenance": case.get("provenance"),
            "reference_transcript": ref_text,
            "raw_transcript": raw_transcript,
            "corrected_transcript": corrected_transcript,
            "wer": round(wer, 4),
            "cer": round(cer, 4),
            "is_operational": is_operational,
            "expected_tool": expected_tool,
            "expected_args": expected_args,
            "expected_decision": expected_decision,
            "expected_action": expected_action,
            "classified_intent": classified_intent,
            "abstention_decision": abstention_decision,
            "abstention_confidence": abstention_conf,
            "abstention_reason": abstention_reason,
            "executed_tool": executed_tool,
            "executed_args": executed_args,
            "executed": executed,
            "is_correct_execution": is_correct_execution,
            "is_false_positive_execution": is_false_positive_execution,
            "is_missed_valid_request": is_missed_valid_request,
            "task_success": task_success,
            "primary_failure_stage": primary_failure_stage,
            "secondary_failure_stage": secondary_failure_stage,
            "latencies_ms": latencies,
            "answer_text": answer_text,
        }


def compute_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    n_total = len(records)
    if n_total == 0:
        return {}

    op_records = [r for r in records if r["is_operational"]]
    dist_records = [r for r in records if not r["is_operational"]]
    executed_records = [r for r in records if r["executed"]]

    n_op = len(op_records)
    n_dist = len(dist_records)
    n_exec = len(executed_records)

    # Coverage
    coverage_overall = n_exec / n_total if n_total > 0 else 0.0
    coverage_op = sum(1 for r in op_records if r["executed"]) / n_op if n_op > 0 else 0.0
    coverage_dist = sum(1 for r in dist_records if r["executed"]) / n_dist if n_dist > 0 else 0.0

    # Selective Risk: incorrect executions / executed cases
    n_incorrect_exec = sum(1 for r in executed_records if not r["is_correct_execution"])
    risk = n_incorrect_exec / n_exec if n_exec > 0 else 0.0

    # False-Positive Tool Execution Rate
    n_fp = sum(1 for r in dist_records if r["executed"])
    fp_rate = n_fp / n_dist if n_dist > 0 else 0.0

    # Clarification Failures
    clarify_records = [r for r in records if r.get("expected_action") == "CLARIFY"]
    n_clarify = len(clarify_records)
    n_clarify_fail = sum(1 for r in clarify_records if r["executed"])
    clarify_fail_rate = n_clarify_fail / n_clarify if n_clarify > 0 else 0.0

    # Missed Valid Requests
    missed_op = [r for r in op_records if r["is_missed_valid_request"]]
    n_missed = len(missed_op)
    missed_rate = n_missed / n_op if n_op > 0 else 0.0

    missed_by_stage = {}
    for r in missed_op:
        stage = r.get("primary_failure_stage") or "unspecified"
        missed_by_stage[stage] = missed_by_stage.get(stage, 0) + 1

    # Task Success
    n_success = sum(1 for r in records if r["task_success"])
    task_success_rate = n_success / n_total if n_total > 0 else 0.0

    # ASR WER / CER
    wers = [r["wer"] for r in records if r.get("wer") is not None]
    cers = [r["cer"] for r in records if r.get("cer") is not None]
    mean_wer = float(np.mean(wers)) if wers else 0.0
    mean_cer = float(np.mean(cers)) if cers else 0.0

    # Failure counts
    failure_counts = {}
    for r in records:
        f = r.get("primary_failure_stage")
        if f:
            failure_counts[f] = failure_counts.get(f, 0) + 1

    return {
        "n_total": n_total,
        "n_operational": n_op,
        "n_distractor": n_dist,
        "n_executed": n_exec,
        "coverage": {
            "overall": {"k": n_exec, "n": n_total, "rate": round(coverage_overall, 4), "formatted": format_proportion_ci(n_exec, n_total)},
            "operational": {"k": sum(1 for r in op_records if r["executed"]), "n": n_op, "rate": round(coverage_op, 4), "formatted": format_proportion_ci(sum(1 for r in op_records if r["executed"]), n_op)},
            "distractor": {"k": sum(1 for r in dist_records if r["executed"]), "n": n_dist, "rate": round(coverage_dist, 4), "formatted": format_proportion_ci(sum(1 for r in dist_records if r["executed"]), n_dist)},
        },
        "selective_risk": {
            "k": n_incorrect_exec,
            "n": n_exec,
            "rate": round(risk, 4),
            "formatted": format_proportion_ci(n_incorrect_exec, n_exec) if n_exec > 0 else "0/0 (N/A)",
        },
        "selective_accuracy": {
            "k": n_exec - n_incorrect_exec,
            "n": n_exec,
            "rate": round(1.0 - risk, 4) if n_exec > 0 else 0.0,
            "formatted": format_proportion_ci(n_exec - n_incorrect_exec, n_exec) if n_exec > 0 else "0/0 (N/A)",
        },
        "false_positive_tool_execution": {
            "k": n_fp,
            "n": n_dist,
            "rate": round(fp_rate, 4),
            "formatted": format_proportion_ci(n_fp, n_dist),
        },
        "clarification_failure": {
            "k": n_clarify_fail,
            "n": n_clarify,
            "rate": round(clarify_fail_rate, 4) if n_clarify > 0 else 0.0,
            "formatted": format_proportion_ci(n_clarify_fail, n_clarify) if n_clarify > 0 else "0/0 (N/A)",
        },
        "missed_valid_requests": {
            "k": n_missed,
            "n": n_op,
            "rate": round(missed_rate, 4),
            "formatted": format_proportion_ci(n_missed, n_op),
            "breakdown_by_stage": missed_by_stage,
        },
        "task_success": {
            "k": n_success,
            "n": n_total,
            "rate": round(task_success_rate, 4),
            "formatted": format_proportion_ci(n_success, n_total),
        },
        "asr_metrics": {
            "mean_wer": round(mean_wer, 4),
            "mean_cer": round(mean_cer, 4),
        },
        "failure_stage_counts": failure_counts,
    }


def run_paired_evaluation(
    dataset_paths: List[Path],
    output_dir: Path,
    quick: bool = False,
) -> Dict[str, Any]:
    run_id = make_run_id()
    timestamp = datetime.now(timezone.utc).isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)

    runner = PairedPipelineRunner()
    all_cases: List[Dict[str, Any]] = []

    for dp in dataset_paths:
        if not dp.exists():
            print(f"Warning: Dataset path {dp} does not exist, skipping.", flush=True)
            continue
        with open(dp, "r", encoding="utf-8") as f:
            cases = [json.loads(line) for line in f if line.strip()]
            all_cases.extend(cases)

    if quick:
        all_cases = all_cases[:4]

    print("\n" + "=" * 90)
    print(f"STARTING PHASE 6 PAIRED REAL-AUDIO EVALUATION (run_id={run_id})")
    print(f"Total Cases to Evaluate: {len(all_cases)} (evaluated in both Baseline and Abstention conditions)")
    print("=" * 90)

    baseline_records: List[Dict[str, Any]] = []
    abstention_records: List[Dict[str, Any]] = []

    for idx, case in enumerate(all_cases, 1):
        cid = case["case_id"]
        aud_rel = case["audio_path"]
        aud_p = PROJECT_ROOT / aud_rel
        print(f"[{idx}/{len(all_cases)}] Processing {cid} ({aud_p.name})...", flush=True)

        # 1. Process audio once (shared ASR)
        raw_transcript, conf, latencies, duration = runner.process_audio(aud_p, cid)

        # 2. Condition 1: Baseline (Abstention Disabled)
        rec_base = runner.evaluate_case_condition(
            case=case,
            raw_transcript=raw_transcript,
            stt_conf=conf,
            audio_latencies=latencies,
            duration=duration,
            enable_abstention=False,
        )
        baseline_records.append(rec_base)

        # 3. Condition 2: Abstention (Abstention Enabled)
        rec_abs = runner.evaluate_case_condition(
            case=case,
            raw_transcript=raw_transcript,
            stt_conf=conf,
            audio_latencies=latencies,
            duration=duration,
            enable_abstention=True,
        )
        abstention_records.append(rec_abs)

    # Serialize raw JSONL results
    base_file = output_dir / "run_baseline.jsonl"
    abs_file = output_dir / "run_abstention.jsonl"
    with open(base_file, "w", encoding="utf-8") as f:
        for r in baseline_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(abs_file, "w", encoding="utf-8") as f:
        for r in abstention_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Compute comparative metrics
    metrics_base = compute_metrics(baseline_records)
    metrics_abs = compute_metrics(abstention_records)

    summary = {
        "run_id": run_id,
        "timestamp": timestamp,
        "git_commit": get_git_commit(),
        "python_version": get_python_version(),
        "datasets_evaluated": [str(p) for p in dataset_paths],
        "sample_size": len(all_cases),
        "baseline_condition": metrics_base,
        "abstention_condition": metrics_abs,
    }

    summary_file = output_dir / "metrics_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    failure_file = output_dir / "failure_localization.json"
    with open(failure_file, "w", encoding="utf-8") as f:
        json.dump({
            "baseline_failures": metrics_base.get("failure_stage_counts", {}),
            "abstention_failures": metrics_abs.get("failure_stage_counts", {}),
            "baseline_missed_breakdown": metrics_base.get("missed_valid_requests", {}).get("breakdown_by_stage", {}),
            "abstention_missed_breakdown": metrics_abs.get("missed_valid_requests", {}).get("breakdown_by_stage", {}),
        }, f, indent=2)

    print("\n" + "=" * 95)
    print(f"PHASE 6 PAIRED EVALUATION SUMMARY RESULTS (N={len(all_cases)})")
    print(f"{'Metric':<32} | {'Baseline (No Abstention)':<28} | {'With Selective Abstention':<28}")
    print("-" * 95)
    print(f"{'Overall Coverage':<32} | {metrics_base['coverage']['overall']['formatted']:<28} | {metrics_abs['coverage']['overall']['formatted']:<28}")
    print(f"{'Operational Coverage':<32} | {metrics_base['coverage']['operational']['formatted']:<28} | {metrics_abs['coverage']['operational']['formatted']:<28}")
    print(f"{'Distractor Coverage (Leakage)':<32} | {metrics_base['coverage']['distractor']['formatted']:<28} | {metrics_abs['coverage']['distractor']['formatted']:<28}")
    print(f"{'Selective Risk (Executed Errors)':<32} | {metrics_base['selective_risk']['formatted']:<28} | {metrics_abs['selective_risk']['formatted']:<28}")
    print(f"{'False-Positive Tool Executions':<32} | {metrics_base['false_positive_tool_execution']['formatted']:<28} | {metrics_abs['false_positive_tool_execution']['formatted']:<28}")
    print(f"{'Missed Valid Requests':<32} | {metrics_base['missed_valid_requests']['formatted']:<28} | {metrics_abs['missed_valid_requests']['formatted']:<28}")
    print(f"{'End-to-End Task Success':<32} | {metrics_base['task_success']['formatted']:<28} | {metrics_abs['task_success']['formatted']:<28}")
    print(f"{'Mean Whisper WER':<32} | {metrics_base['asr_metrics']['mean_wer']*100:.1f}%{'':<22} | {metrics_abs['asr_metrics']['mean_wer']*100:.1f}%{'':<22}")
    print("=" * 95 + "\n")
    print(f"Artifacts saved in {output_dir}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Run Phase 6 / 6.1 Paired Real-Audio Evaluation")
    parser.add_argument("--real-only", action="store_true", help="Evaluate only authentic human recordings (N=6)")
    parser.add_argument("--benchmark", action="store_true", help="Evaluate benchmark voice phrases (N=32)")
    parser.add_argument("--semantic-audio", action="store_true", help="Evaluate Phase 6.1 semantic-conflict audio (N=10)")
    parser.add_argument("--dataset", type=str, default=None, help="Path to custom dataset JSONL")
    parser.add_argument("--quick", action="store_true", help="Run 4 cases sanity check")
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args()

    run_id = make_run_id()
    if args.dataset:
        datasets = [Path(args.dataset)]
        default_sub = "custom"
    elif args.semantic_audio:
        datasets = [PROJECT_ROOT / "evaluation" / "datasets" / "phase6" / "semantic_conflict_audio_v1.jsonl"]
        default_sub = "phase6_1"
    elif args.real_only:
        datasets = [PROJECT_ROOT / "evaluation" / "datasets" / "phase6" / "real_audio_v1.jsonl"]
        default_sub = "phase6"
    elif args.benchmark:
        datasets = [PROJECT_ROOT / "evaluation" / "datasets" / "phase6" / "benchmark_audio_v1.jsonl"]
        default_sub = "phase6"
    else:
        # Default: evaluate authentic human recordings and benchmark audio
        datasets = [
            PROJECT_ROOT / "evaluation" / "datasets" / "phase6" / "real_audio_v1.jsonl",
            PROJECT_ROOT / "evaluation" / "datasets" / "phase6" / "benchmark_audio_v1.jsonl",
        ]
        default_sub = "phase6"

    out_dir = Path(args.output_dir) if args.output_dir else PROJECT_ROOT / "evaluation" / "results" / default_sub / run_id
    run_paired_evaluation(datasets, out_dir, quick=args.quick)


if __name__ == "__main__":
    main()
