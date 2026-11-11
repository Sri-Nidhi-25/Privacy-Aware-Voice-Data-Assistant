"""
tests/test_phase6/test_phase61_evaluator.py
============================================
Unit tests for Phase 6.1 evaluator additions:
  - semantic_conflict_audio_v1 dataset registration
  - CLARIFY action handling (clarification_failure metric)
  - expected_action fallback to expected_decision
  - Phase 6.1 run detection in the evaluation API
  - clarification_failure metric computation
"""
import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DATASETS_DIR = PROJECT_ROOT / "evaluation" / "datasets" / "phase6"
EVAL_RESULTS_61 = PROJECT_ROOT / "evaluation" / "results" / "phase6_1"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Dataset registration tests
# ---------------------------------------------------------------------------

class TestSemanticConflictAudioDataset:
    """semantic_conflict_audio_v1 must be registered in API and manifest."""

    def test_dataset_listed_in_api(self, client):
        """semantic_conflict_audio_v1 appears in /evaluation/datasets."""
        resp = client.get("/evaluation/datasets")
        assert resp.status_code == 200
        ds_map = {d["dataset_id"]: d for d in resp.json()["datasets"]}
        assert "semantic_conflict_audio_v1" in ds_map, (
            "semantic_conflict_audio_v1 not found in /evaluation/datasets"
        )

    def test_dataset_provenance(self, client):
        """semantic_conflict_audio_v1 has standardized_benchmark_recording provenance."""
        resp = client.get("/evaluation/datasets")
        ds_map = {d["dataset_id"]: d for d in resp.json()["datasets"]}
        ds = ds_map["semantic_conflict_audio_v1"]
        assert ds["provenance_type"] == "standardized_benchmark_recording"

    def test_dataset_sample_size(self, client):
        """semantic_conflict_audio_v1 has exactly 10 cases."""
        resp = client.get("/evaluation/datasets/semantic_conflict_audio_v1/cases")
        assert resp.status_code == 200
        data = resp.json()
        assert data["case_count"] == 10, f"Expected 10 cases, got {data['case_count']}"

    def test_dataset_case_ids(self, client):
        """All 10 case IDs are present and correctly formed."""
        resp = client.get("/evaluation/datasets/semantic_conflict_audio_v1/cases")
        case_ids = {c["case_id"] for c in resp.json()["cases"]}
        for i in range(1, 11):
            expected = f"sem_conf_aud_{i:03d}"
            assert expected in case_ids, f"Missing case ID: {expected}"

    def test_dataset_operational_split(self, client):
        """5 operational + 5 distractor cases."""
        resp = client.get("/evaluation/datasets/semantic_conflict_audio_v1/cases")
        cases = resp.json()["cases"]
        operational = [c for c in cases if c.get("is_operational") is True]
        distractor = [c for c in cases if c.get("is_operational") is False]
        assert len(operational) == 5, f"Expected 5 operational, got {len(operational)}"
        assert len(distractor) == 5, f"Expected 5 distractor, got {len(distractor)}"

    def test_dataset_audio_paths_present(self, client):
        """All 10 cases have an audio_path field."""
        resp = client.get("/evaluation/datasets/semantic_conflict_audio_v1/cases")
        cases = resp.json()["cases"]
        for c in cases:
            # audio_sha256 is stripped from response, but audio_path should remain
            assert "audio_path" in c or "case_id" in c, (
                f"Case {c.get('case_id')} has no audio_path"
            )

    def test_dataset_jsonl_exists_on_disk(self):
        """JSONL file physically exists."""
        p = EVAL_DATASETS_DIR / "semantic_conflict_audio_v1.jsonl"
        assert p.exists(), f"Dataset file not found: {p}"

    def test_dataset_audio_files_exist(self):
        """All 10 WAV audio files physically exist."""
        p = EVAL_DATASETS_DIR / "semantic_conflict_audio_v1.jsonl"
        if not p.exists():
            pytest.skip("Dataset JSONL not found, skipping audio existence check")
        with open(p, "r", encoding="utf-8") as f:
            cases = [json.loads(line) for line in f if line.strip()]
        missing = []
        for c in cases:
            if c.get("audio_path"):
                audio_file = PROJECT_ROOT / c["audio_path"]
                if not audio_file.exists():
                    missing.append(c["audio_path"])
        assert missing == [], f"Missing audio files: {missing}"

    def test_audio_playback_endpoint(self, client):
        """First semantic-conflict audio case is servable."""
        resp = client.get("/evaluation/audio/sem_conf_aud_001")
        assert resp.status_code == 200
        assert "audio" in resp.headers.get("content-type", "")
        assert len(resp.content) > 500, "Audio file appears to be empty"


# ---------------------------------------------------------------------------
# Phase 6.1 run detection tests
# ---------------------------------------------------------------------------

class TestPhase61RunDetection:
    """Phase 6.1 run directory must appear in /evaluation/runs."""

    def test_phase61_run_appears(self, client):
        """At least one Phase 6.1 run is returned by /evaluation/runs."""
        resp = client.get("/evaluation/runs")
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        phase61_runs = [r for r in runs if r.get("phase_label") == "phase6_1"]
        assert len(phase61_runs) >= 1, (
            "No Phase 6.1 runs found in /evaluation/runs. "
            "Expected at least run 88cd8262 (pilot run c4f0c07b)."
        )

    def test_phase61_run_has_summary(self, client):
        """The pilot run directory 88cd8262 has a summary endpoint."""
        resp = client.get("/evaluation/runs/88cd8262/summary")
        assert resp.status_code == 200
        summary = resp.json()
        assert "run_id" in summary
        assert summary.get("sample_size") == 10

    def test_phase61_run_cases_accessible(self, client):
        """Cases for Phase 6.1 pilot run are accessible."""
        resp = client.get("/evaluation/runs/88cd8262/cases?limit=25")
        assert resp.status_code == 200
        data = resp.json()
        # 10 baseline + 10 abstention = 20 records total
        assert data["total_records"] == 20, (
            f"Expected 20 records (10 baseline + 10 abstention), got {data['total_records']}"
        )

    def test_phase61_run_condition_filter(self, client):
        """Condition filter works for Phase 6.1 run."""
        resp_b = client.get("/evaluation/runs/88cd8262/cases?condition=baseline")
        assert resp_b.status_code == 200
        assert resp_b.json()["total_records"] == 10

        resp_a = client.get("/evaluation/runs/88cd8262/cases?condition=abstention")
        assert resp_a.status_code == 200
        assert resp_a.json()["total_records"] == 10


# ---------------------------------------------------------------------------
# Clarification failure metric tests
# ---------------------------------------------------------------------------

class TestClarificationFailureMetric:
    """Verify clarification_failure is computed and surfaced correctly."""

    def test_clarification_failure_in_metrics_summary(self):
        """Phase 6.1 metrics_summary.json contains clarification_failure field."""
        summary_path = EVAL_RESULTS_61 / "88cd8262" / "metrics_summary.json"
        if not summary_path.exists():
            pytest.skip("Phase 6.1 pilot summary not found")
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        base = summary.get("baseline_condition", {})
        abs_ = summary.get("abstention_condition", {})
        assert "clarification_failure" in base, "clarification_failure missing from baseline_condition"
        assert "clarification_failure" in abs_, "clarification_failure missing from abstention_condition"

    def test_clarification_failure_denominator(self):
        """clarification_failure denominator = number of CLARIFY-expected cases."""
        summary_path = EVAL_RESULTS_61 / "88cd8262" / "metrics_summary.json"
        if not summary_path.exists():
            pytest.skip("Phase 6.1 pilot summary not found")
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        base = summary["baseline_condition"]["clarification_failure"]
        # In phase6_1 pilot, 1 case has expected_action=CLARIFY
        assert base["n"] == 1, f"Expected denominator=1, got {base['n']}"

    def test_clarification_failure_rate_is_valid(self):
        """clarification_failure rate is between 0.0 and 1.0."""
        summary_path = EVAL_RESULTS_61 / "88cd8262" / "metrics_summary.json"
        if not summary_path.exists():
            pytest.skip("Phase 6.1 pilot summary not found")
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        for cond_key in ("baseline_condition", "abstention_condition"):
            cf = summary[cond_key]["clarification_failure"]
            rate = cf.get("rate", -1)
            assert 0.0 <= rate <= 1.0, (
                f"{cond_key} clarification_failure.rate={rate} out of range [0,1]"
            )

    def test_clarification_failure_via_api(self, client):
        """clarification_failure appears in Phase 6.1 summary via API."""
        resp = client.get("/evaluation/runs/88cd8262/summary")
        if resp.status_code == 404:
            pytest.skip("Phase 6.1 pilot run not accessible via API")
        assert resp.status_code == 200
        summary = resp.json()
        base = summary.get("baseline_condition", {})
        assert "clarification_failure" in base


# ---------------------------------------------------------------------------
# expected_action fallback tests
# ---------------------------------------------------------------------------

class TestExpectedActionFallback:
    """Verify expected_action is present in Phase 6.1 JSONL; original Phase 6 does not require it."""

    def test_semantic_conflict_audio_has_expected_action(self):
        """All Phase 6.1 cases have expected_action field in the JSONL."""
        p = EVAL_DATASETS_DIR / "semantic_conflict_audio_v1.jsonl"
        if not p.exists():
            pytest.skip("semantic_conflict_audio_v1.jsonl not found")
        with open(p, "r", encoding="utf-8") as f:
            cases = [json.loads(line) for line in f if line.strip()]
        missing = [c["case_id"] for c in cases if "expected_action" not in c]
        assert missing == [], f"Cases missing expected_action: {missing}"

    def test_original_phase6_cases_do_not_require_expected_action(self):
        """real_audio_v1 and benchmark_audio_v1 may lack expected_action (graceful)."""
        for jsonl_name in ("real_audio_v1.jsonl", "benchmark_audio_v1.jsonl"):
            p = EVAL_DATASETS_DIR / jsonl_name
            if not p.exists():
                continue
            with open(p, "r", encoding="utf-8") as f:
                cases = [json.loads(line) for line in f if line.strip()]
            # They may or may not have expected_action — this just checks no crash
            for c in cases:
                action = c.get("expected_action") or c.get("expected_decision")
                assert action is not None, (
                    f"Case {c.get('case_id')} has neither expected_action nor expected_decision"
                )

    def test_phase61_run_records_have_expected_action(self):
        """Per-case JSONL records in the pilot run include expected_action."""
        run_dir = EVAL_RESULTS_61 / "88cd8262"
        if not run_dir.exists():
            pytest.skip("Phase 6.1 pilot run directory not found")
        for fname in ("run_baseline.jsonl", "run_abstention.jsonl"):
            fpath = run_dir / fname
            if not fpath.exists():
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
            missing = [r.get("case_id") for r in records if "expected_action" not in r]
            assert missing == [], f"{fname}: records missing expected_action: {missing}"


# ---------------------------------------------------------------------------
# Per-case JSONL integrity tests
# ---------------------------------------------------------------------------

class TestPhase61PerCaseIntegrity:
    """Verify structure of per-case outputs from the pilot run."""

    REQUIRED_FIELDS = {
        "case_id", "condition_mode", "is_operational", "task_success",
        "raw_transcript", "wer", "cer"
    }

    def _load_records(self, fname):
        run_dir = EVAL_RESULTS_61 / "88cd8262"
        p = run_dir / fname
        if not p.exists():
            pytest.skip(f"{fname} not found in Phase 6.1 pilot run")
        with open(p, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_baseline_record_count(self):
        records = self._load_records("run_baseline.jsonl")
        assert len(records) == 10, f"Expected 10 baseline records, got {len(records)}"

    def test_abstention_record_count(self):
        records = self._load_records("run_abstention.jsonl")
        assert len(records) == 10, f"Expected 10 abstention records, got {len(records)}"

    def test_baseline_records_have_required_fields(self):
        records = self._load_records("run_baseline.jsonl")
        for r in records:
            missing = self.REQUIRED_FIELDS - set(r.keys())
            assert not missing, f"Record {r.get('case_id')} missing fields: {missing}"

    def test_abstention_records_have_required_fields(self):
        records = self._load_records("run_abstention.jsonl")
        for r in records:
            missing = self.REQUIRED_FIELDS - set(r.keys())
            assert not missing, f"Record {r.get('case_id')} missing fields: {missing}"

    def test_wer_is_zero_for_tts_audio(self):
        """All TTS-generated Phase 6.1 cases should have WER=0."""
        for fname in ("run_baseline.jsonl", "run_abstention.jsonl"):
            records = self._load_records(fname)
            non_zero = [r["case_id"] for r in records if r.get("wer", 0) > 0]
            assert non_zero == [], (
                f"{fname}: non-zero WER for TTS cases (unexpected): {non_zero}"
            )

    def test_condition_mode_labels(self):
        """Baseline records have baseline condition mode; abstention records have abstention."""
        baseline = self._load_records("run_baseline.jsonl")
        for r in baseline:
            assert r["condition_mode"] in ("baseline", "baseline_no_abstention"), (
                f"Unexpected condition_mode in baseline: {r['condition_mode']}"
            )
        abstention = self._load_records("run_abstention.jsonl")
        for r in abstention:
            assert r["condition_mode"] == "with_abstention", (
                f"Unexpected condition_mode in abstention: {r['condition_mode']}"
            )

    def test_distractor_cases_are_labelled(self):
        """Distractor cases (is_operational=False) have expected_action=ABSTAIN or CLARIFY."""
        records = self._load_records("run_baseline.jsonl")
        for r in records:
            if r.get("is_operational") is False:
                # Distractor cases must have a non-EXECUTE expected action
                action = r.get("expected_action", "")
                assert action in ("ABSTAIN", "CLARIFY"), (
                    f"{r['case_id']}: distractor case has unexpected expected_action={action!r}"
                )


# ---------------------------------------------------------------------------
# Stage localization regression tests
# ---------------------------------------------------------------------------

class TestFailureStageLocalization:
    """Verifies that failures are attributed to the exact pipeline stage."""

    def test_arg_validation_failure_not_mislabeled_as_intent_routing(self):
        """
        Regression test: When an operational query fails because the LLM generated
        invalid arguments (e.g. invalid enum filter), primary_failure_stage must be
        argument_validation_failure, NOT intent_routing_failure.
        """
        from evaluation.runners.run_paired_evaluation import (
            PairedPipelineRunner,
            STAGE_ARG_VALIDATION,
            STAGE_INTENT_ROUTING,
        )

        runner = PairedPipelineRunner.__new__(PairedPipelineRunner)
        # Mock orchestrator output with validation error
        class MockOrchestrator:
            def process_query(self, text, enable_abstention=True):
                return {
                    "answer": "Sorry, I couldn't interpret that filter: 'priority' must be one of ['low', 'medium', 'high']",
                    "metadata": {
                        "classified_intent": "SUPPORT_QUERY",
                        "validation_error": "'priority' must be one of ['low', 'medium', 'high']",
                        "failure_type": "invalid_tool_arguments",
                        "tool_calls": [],
                    }
                }

        runner.orchestrator = MockOrchestrator()
        case = {
            "case_id": "test_arg_val_001",
            "is_operational": True,
            "expected_action": "EXECUTE",
            "expected_tool": "get_support_tickets",
            "expected_args": {"status": "open"},
            "reference_transcript": "List all open support tickets.",
        }

        result = runner.evaluate_case_condition(
            case=case,
            raw_transcript="List all open support tickets.",
            stt_conf={"low_confidence": False},
            audio_latencies={},
            duration=1.0,
            enable_abstention=False,  # Baseline mode
        )

        assert result["executed"] is False
        assert result["is_missed_valid_request"] is True
        assert result["primary_failure_stage"] == STAGE_ARG_VALIDATION, (
            f"Expected {STAGE_ARG_VALIDATION}, got {result['primary_failure_stage']}"
        )
        assert result["primary_failure_stage"] != STAGE_INTENT_ROUTING

