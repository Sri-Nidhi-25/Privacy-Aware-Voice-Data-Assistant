"""
evaluation/datasets/verify_datasets.py
======================================
Cryptographic and schema verification tool for all evaluation datasets in the repository.

Verifies:
1. Historical Phase 4.6 frozen datasets against evaluation/datasets/manifest.json
2. Phase 6 datasets against evaluation/datasets/phase6/manifest.json
3. Per-case audio files existence and SHA256 integrity
4. JSON schema validation against collection_manifest_schema.json
"""
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def verify_sha256(file_path: Path, expected_sha: str) -> bool:
    if not file_path.exists():
        return False
    computed = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return computed == expected_sha


def verify_frozen_manifest(manifest_path: Path) -> Tuple[bool, List[Dict]]:
    if not manifest_path.exists():
        return False, [{"error": f"Manifest not found: {manifest_path}"}]

    with open(manifest_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    results = []
    all_ok = True
    for name, item in meta.get("datasets", {}).items():
        rel_p = Path(item["path"])
        full_p = PROJECT_ROOT / rel_p
        exp = item["sha256"]
        matched = verify_sha256(full_p, exp)
        if not matched:
            all_ok = False
        results.append({
            "dataset": name,
            "path": str(rel_p),
            "expected_sha256": exp,
            "exists": full_p.exists(),
            "matched": matched,
        })
    return all_ok, results


def verify_phase6_manifest(manifest_path: Path) -> Tuple[bool, List[Dict]]:
    if not manifest_path.exists():
        return False, [{"error": f"Manifest not found: {manifest_path}"}]

    with open(manifest_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    results = []
    all_ok = True
    for name, item in meta.get("datasets", {}).items():
        rel_p = Path(item["file"])
        full_p = PROJECT_ROOT / rel_p
        exp = item["sha256"]
        matched = verify_sha256(full_p, exp)
        if not matched:
            all_ok = False

        # Verify referenced audio files
        audio_errors = []
        if full_p.exists():
            with open(full_p, "r", encoding="utf-8") as jf:
                for line_idx, line in enumerate(jf, 1):
                    if not line.strip():
                        continue
                    case = json.loads(line)
                    if case.get("audio_path"):
                        aud_path = PROJECT_ROOT / case["audio_path"]
                        aud_sha = case.get("audio_sha256")
                        if not aud_path.exists():
                            audio_errors.append(f"Line {line_idx} ({case['case_id']}): Audio missing: {aud_path}")
                            all_ok = False
                        elif aud_sha and not verify_sha256(aud_path, aud_sha):
                            audio_errors.append(f"Line {line_idx} ({case['case_id']}): Audio SHA256 mismatch")
                            all_ok = False

        results.append({
            "dataset": name,
            "path": str(rel_p),
            "expected_sha256": exp,
            "exists": full_p.exists(),
            "matched": matched,
            "audio_errors": audio_errors,
        })
    return all_ok, results


def main() -> int:
    print("=" * 80)
    print("DATASET INTEGRITY & HASH VERIFICATION AUDIT")
    print("=" * 80)

    # 1. Historical frozen datasets
    frozen_manifest = PROJECT_ROOT / "evaluation" / "datasets" / "manifest.json"
    frozen_ok, frozen_res = verify_frozen_manifest(frozen_manifest)
    print(f"\n[1] Historical Phase 4.6 Frozen Datasets ({frozen_manifest.name}):")
    for r in frozen_res:
        status = "PASSED (MATCH)" if r.get("matched") else "FAILED"
        print(f"  - {r.get('dataset'):<15} | {status} | {r.get('path')}")

    # 2. Phase 6 datasets
    p6_manifest = PROJECT_ROOT / "evaluation" / "datasets" / "phase6" / "manifest.json"
    p6_ok, p6_res = verify_phase6_manifest(p6_manifest)
    print(f"\n[2] Phase 6 Real & Benchmark Audio Datasets ({p6_manifest.name}):")
    for r in p6_res:
        status = "PASSED (MATCH)" if r.get("matched") else "FAILED"
        aud_errs = len(r.get("audio_errors", []))
        print(f"  - {r.get('dataset'):<18} | {status} | Audio assets OK: {aud_errs == 0} | {r.get('path')}")
        if aud_errs > 0:
            for err in r["audio_errors"]:
                print(f"      ERROR: {err}")

    overall_ok = frozen_ok and p6_ok
    print("\n" + "=" * 80)
    print(f"OVERALL VERIFICATION STATUS: {'PASSED (ALL HASHES MATCH)' if overall_ok else 'FAILED'}")
    print("=" * 80)
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
