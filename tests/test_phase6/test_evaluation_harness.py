"""
tests/test_phase6/test_evaluation_harness.py
============================================
Unit and regression tests for Phase 6 evaluation harness and metrics.
"""
import pytest
from evaluation.runners.run_paired_evaluation import (
    compute_metrics,
    STAGE_ASR_TRANSCRIPTION,
    STAGE_ABSTENTION_FP,
    STAGE_ABSTENTION_FN,
    STAGE_TOOL_SELECTION,
    STAGE_ARG_VALIDATION,
)
from evaluation.datasets.verify_datasets import verify_sha256


def test_metric_denominators_and_calculations():
    # Construct a synthetic paired evaluation batch:
    # 2 operational queries (1 correct execution, 1 missed by abstention)
    # 2 distractor queries (1 safely rejected, 1 false positive execution)
    records = [
        {
            "case_id": "c1",
            "is_operational": True,
            "executed": True,
            "is_correct_execution": True,
            "is_false_positive_execution": False,
            "is_missed_valid_request": False,
            "task_success": True,
            "primary_failure_stage": None,
            "wer": 0.0,
            "cer": 0.0,
        },
        {
            "case_id": "c2",
            "is_operational": True,
            "executed": False,
            "is_correct_execution": False,
            "is_false_positive_execution": False,
            "is_missed_valid_request": True,
            "task_success": False,
            "primary_failure_stage": STAGE_ABSTENTION_FP,
            "wer": 0.05,
            "cer": 0.02,
        },
        {
            "case_id": "c3",
            "is_operational": False,
            "executed": False,
            "is_correct_execution": False,
            "is_false_positive_execution": False,
            "is_missed_valid_request": False,
            "task_success": True,  # Safely rejected!
            "primary_failure_stage": None,
            "wer": 0.0,
            "cer": 0.0,
        },
        {
            "case_id": "c4",
            "is_operational": False,
            "executed": True,
            "is_correct_execution": False,
            "is_false_positive_execution": True,
            "is_missed_valid_request": False,
            "task_success": False,  # Leaked!
            "primary_failure_stage": STAGE_ABSTENTION_FN,
            "wer": 0.0,
            "cer": 0.0,
        },
    ]

    metrics = compute_metrics(records)

    # Total cases: 4
    assert metrics["n_total"] == 4
    assert metrics["n_operational"] == 2
    assert metrics["n_distractor"] == 2
    assert metrics["n_executed"] == 2

    # Overall Coverage: 2/4 = 50%
    assert metrics["coverage"]["overall"]["rate"] == 0.5
    # Operational Coverage: 1/2 = 50%
    assert metrics["coverage"]["operational"]["rate"] == 0.5
    # Distractor Coverage (Leakage): 1/2 = 50%
    assert metrics["coverage"]["distractor"]["rate"] == 0.5

    # Selective Risk: 1 incorrect execution out of 2 executed = 50%
    assert metrics["selective_risk"]["rate"] == 0.5
    assert metrics["selective_risk"]["k"] == 1
    assert metrics["selective_risk"]["n"] == 2

    # False-positive tool execution rate: 1 FP out of 2 distractors = 50%
    assert metrics["false_positive_tool_execution"]["rate"] == 0.5
    assert metrics["false_positive_tool_execution"]["k"] == 1
    assert metrics["false_positive_tool_execution"]["n"] == 2

    # Missed valid requests: 1 missed out of 2 operational = 50%
    assert metrics["missed_valid_requests"]["rate"] == 0.5
    assert metrics["missed_valid_requests"]["k"] == 1
    assert metrics["missed_valid_requests"]["n"] == 2
    assert metrics["missed_valid_requests"]["breakdown_by_stage"] == {STAGE_ABSTENTION_FP: 1}

    # Task success: 2 successes (c1 executed correctly, c3 safely rejected) out of 4 = 50%
    assert metrics["task_success"]["rate"] == 0.5
    assert metrics["task_success"]["k"] == 2
    assert metrics["task_success"]["n"] == 4

    # Failure counts
    assert metrics["failure_stage_counts"] == {
        STAGE_ABSTENTION_FP: 1,
        STAGE_ABSTENTION_FN: 1,
    }


def test_empty_records_handling():
    metrics = compute_metrics([])
    assert metrics == {}


def test_sha256_verifier(tmp_path):
    import hashlib
    f = tmp_path / "test.bin"
    content = b"hello privacy voice evaluation"
    f.write_bytes(content)
    expected_sha = hashlib.sha256(content).hexdigest()

    assert verify_sha256(f, expected_sha) is True
    assert verify_sha256(f, "wrong_hash") is False
    assert verify_sha256(tmp_path / "non_existent.bin", expected_sha) is False
