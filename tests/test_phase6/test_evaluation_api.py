"""
tests/test_phase6/test_evaluation_api.py
==========================================
Integration tests for the Evaluation Lab backend API endpoints.
Verifies dataset listing, run querying, metrics summary, case streaming,
and audio serving.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_list_datasets(client):
    response = client.get("/evaluation/datasets")
    assert response.status_code == 200
    data = response.json()
    assert "datasets" in data
    ds_map = {d["dataset_id"]: d for d in data["datasets"]}
    
    # Assert expected datasets are present
    assert "real_audio_v1" in ds_map
    assert "benchmark_audio_v1" in ds_map
    assert "semantic_conflict_v1" in ds_map
    assert "phase5_text_generalization" in ds_map
    # Phase 6.1 semantic-conflict audio dataset
    assert "semantic_conflict_audio_v1" in ds_map, (
        "semantic_conflict_audio_v1 missing — check manifest.json and evaluation.py file_map"
    )

    # Assert provenance labels
    assert ds_map["real_audio_v1"]["provenance_type"] == "authentic_human_recording"
    assert ds_map["benchmark_audio_v1"]["provenance_type"] == "benchmark_phrase_recording"
    assert ds_map["semantic_conflict_v1"]["provenance_type"] == "text_challenge"
    assert ds_map["phase5_text_generalization"]["provenance_type"] == "text_transcript_only"
    assert ds_map["semantic_conflict_audio_v1"]["provenance_type"] == "standardized_benchmark_recording"

    # Assert sample sizes
    assert ds_map["real_audio_v1"]["sample_size"] == 6
    assert ds_map["benchmark_audio_v1"]["sample_size"] == 32
    assert ds_map["semantic_conflict_v1"]["sample_size"] == 10
    assert ds_map["semantic_conflict_audio_v1"]["sample_size"] == 10


def test_get_dataset_cases(client):
    # Authentic human recordings
    response = client.get("/evaluation/datasets/real_audio_v1/cases")
    assert response.status_code == 200
    data = response.json()
    assert data["case_count"] == 6
    case_ids = [c["case_id"] for c in data["cases"]]
    assert "real_aud_001" in case_ids
    assert "real_aud_006" in case_ids

    # Semantic conflict challenge cases (text-only)
    resp_sc = client.get("/evaluation/datasets/semantic_conflict_v1/cases")
    assert resp_sc.status_code == 200
    sc_data = resp_sc.json()
    assert sc_data["case_count"] == 10
    sc_ids = [c["case_id"] for c in sc_data["cases"]]
    assert "sem_conf_001" in sc_ids
    assert "sem_conf_010" in sc_ids

    # Phase 6.1 semantic conflict audio cases
    resp_sca = client.get("/evaluation/datasets/semantic_conflict_audio_v1/cases")
    assert resp_sca.status_code == 200
    sca_data = resp_sca.json()
    assert sca_data["case_count"] == 10
    sca_ids = [c["case_id"] for c in sca_data["cases"]]
    assert "sem_conf_aud_001" in sca_ids
    assert "sem_conf_aud_010" in sca_ids

    # 404 on invalid dataset
    resp_404 = client.get("/evaluation/datasets/non_existent_dataset/cases")
    assert resp_404.status_code == 404


def test_list_runs(client):
    response = client.get("/evaluation/runs")
    assert response.status_code == 200
    data = response.json()
    assert "runs" in data
    run_ids = [r["run_id"] for r in data["runs"]]
    assert "consolidated_phase6" in run_ids
    assert "f196279a" in run_ids or "e22e9b0f" in run_ids

    # Phase 6.1 pilot run must also appear
    phase61_runs = [r for r in data["runs"] if r.get("phase_label") == "phase6_1"]
    assert len(phase61_runs) >= 1, (
        "No Phase 6.1 runs returned by /evaluation/runs. "
        "Expected at least pilot run 88cd8262."
    )
    # Phase 6 runs should carry phase6 label
    consolidated = next((r for r in data["runs"] if r["run_id"] == "consolidated_phase6"), None)
    assert consolidated is not None
    assert consolidated.get("phase_label") == "phase6"


def test_get_run_summary(client):
    # Consolidated run
    response = client.get("/evaluation/runs/consolidated_phase6/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total_cases_evaluated"] == 38
    assert data["real_human_audio_cases"] == 6
    assert data["benchmark_voice_cases"] == 32
    assert "baseline_metrics" in data
    assert "abstention_metrics" in data

    # 404 on nonexistent run
    resp_404 = client.get("/evaluation/runs/nonexistent_run_id/summary")
    assert resp_404.status_code == 404


def test_get_run_cases(client):
    response = client.get("/evaluation/runs/consolidated_phase6/cases")
    assert response.status_code == 200
    data = response.json()
    assert data["total_records"] == 76  # 38 baseline + 38 abstention
    assert len(data["records"]) > 0

    # Test condition filter
    resp_base = client.get("/evaluation/runs/consolidated_phase6/cases?condition=baseline")
    assert resp_base.status_code == 200
    assert resp_base.json()["total_records"] == 38

    resp_abs = client.get("/evaluation/runs/consolidated_phase6/cases?condition=abstention")
    assert resp_abs.status_code == 200
    assert resp_abs.json()["total_records"] == 38


def test_serve_case_audio(client):
    # Authentic human recording
    response = client.get("/evaluation/audio/real_aud_001")
    assert response.status_code == 200
    assert "audio" in response.headers.get("content-type", "")
    assert len(response.content) > 1000

    # Benchmark audio
    resp_bench = client.get("/evaluation/audio/bench_aud_p0_none")
    assert resp_bench.status_code == 200
    assert "audio" in resp_bench.headers.get("content-type", "")
    assert len(resp_bench.content) > 1000

    # Phase 6.1 semantic conflict audio
    resp_sc = client.get("/evaluation/audio/sem_conf_aud_001")
    assert resp_sc.status_code == 200, (
        "sem_conf_aud_001 audio not served — check semantic_conflict_audio_v1 is in file_map"
    )
    assert "audio" in resp_sc.headers.get("content-type", "")
    assert len(resp_sc.content) > 500

    # Nonexistent case
    resp_404 = client.get("/evaluation/audio/nonexistent_case_999")
    assert resp_404.status_code == 404
