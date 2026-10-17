#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate immutable host-runtime acceptance evidence for the PPTX helper."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from portable_fs import bounded_read

BOUND_FILES = (
    "scripts/build_assessment_pptx.mjs",
    "scripts/create_artifact_runtime_receipt.mjs",
    "scripts/stable_regular_file.mjs",
    "scripts/native_pptx_text.py",
    "scripts/test_native_pptx_text.py",
    "scripts/render_presentations_with_powerpoint.applescript",
    "scripts/render_presentations_with_powerpoint.ps1",
    "scripts/stage_office_artifact.py",
    "scripts/test_powerpoint_path_identity.py",
    "scripts/create_pptx_montage.py",
    "scripts/portable_fs.py",
    "scripts/requirements.lock",
    "scripts/secure_pptx_stage_bundle.py",
    "scripts/validate_assessment_pptx.py",
    "scripts/test_build_assessment_pptx.py",
    "scripts/verify_v5_candidate.py",
    "scripts/measure_v5_candidate.py",
)
V5_ACCEPTANCE_FILES = tuple(dict.fromkeys((*BOUND_FILES,
    "scripts/capture_v5_powerpoint_render.py",
    "scripts/reconcile_v5_native_evidence.py",
    "scripts/finalize_v5_private_pptx.py",
    "scripts/accept_v5_runtime.py",
    "scripts/validate_pptx_runtime_acceptance.py",
)))
SHA = re.compile(r"^[0-9a-f]{64}$")
V5_HASH_FIELDS = (
    "artifact_runtime_receipt_sha256", "candidate_manifest_sha256",
    "candidate_pptx_sha256", "technical_reconciliation_sha256",
    "render_record_sha256", "measurement_record_sha256",
    "parser_policy_sha256", "native_pdf_sha256", "build_manifest_sha256",
    "finalization_sha256", "output_sha256",
)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("PPTX runtime acceptance has duplicate JSON keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"PPTX runtime acceptance contains non-finite {value}")


def _validate_v5(root: Path, payload: dict[str, object]) -> dict[str, object]:
    expected = {
        "schema_version", "status", "test", "platform", "native_office_platform",
        "artifact_tool_version", "slide_count", "notes_count", "measured_frames",
        "source_bindings", "production_publication", "human_acceptance",
        "business_acceptance", "residual_risk_acceptance", *V5_HASH_FIELDS,
    }
    if (set(payload) != expected or payload["status"] != "Passed"
            or payload["test"] != "accept_v5_private_runtime"
            or payload["platform"] != "linux"
            or payload["native_office_platform"] != "darwin"
            or not isinstance(payload["artifact_tool_version"], str)
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", payload["artifact_tool_version"])):
        raise ValueError("v5 PPTX runtime acceptance identity is invalid")
    slides = payload["slide_count"]
    frames = payload["measured_frames"]
    if (type(slides) is not int or not 7 <= slides <= 100
            or type(payload["notes_count"]) is not int or payload["notes_count"] != slides
            or type(frames) is not int or not slides <= frames <= 4096):
        raise ValueError("v5 PPTX runtime acceptance coverage is insufficient")
    if any(payload[field] != "Pending" for field in
           ("production_publication", "human_acceptance", "business_acceptance",
            "residual_risk_acceptance")):
        raise ValueError("v5 PPTX runtime acceptance includes an unsupported decision")
    for field in V5_HASH_FIELDS:
        if not isinstance(payload[field], str) or not SHA.fullmatch(payload[field]):
            raise ValueError(f"v5 PPTX runtime acceptance {field} is invalid")
    if payload["output_sha256"] != payload["candidate_pptx_sha256"]:
        raise ValueError("v5 PPTX output differs from the native-measured candidate")
    bindings = payload["source_bindings"]
    if not isinstance(bindings, dict) or set(bindings) != set(V5_ACCEPTANCE_FILES):
        raise ValueError("v5 PPTX runtime acceptance source bindings are incomplete")
    for relative in V5_ACCEPTANCE_FILES:
        digest = hashlib.sha256(bounded_read(root / relative, 2 * 1024 * 1024)[0]).hexdigest()
        if bindings[relative] != digest:
            raise ValueError(f"v5 PPTX runtime acceptance is stale for {relative}")
    return payload


def validate(root: Path, acceptance: Path) -> dict[str, object]:
    payload = json.loads(bounded_read(acceptance, 2 * 1024 * 1024)[0].decode("utf-8"),
                         object_pairs_hook=_unique, parse_constant=_reject_constant)
    if not isinstance(payload, dict):
        raise TypeError("PPTX runtime acceptance must be an object")
    if payload.get("schema_version") == 2:
        return _validate_v5(root, payload)
    if payload.get("schema_version") != 1 or payload.get("status") != "Passed" or payload.get("test") != "test_builds_editable_pptx_with_sources_and_renders":
        raise ValueError("PPTX runtime acceptance identity or status is invalid")
    if payload.get("platform") != "darwin" or not isinstance(payload.get("artifact_tool_version"), str):
        raise ValueError("PPTX runtime acceptance lacks the required native host/runtime identity")
    if not isinstance(payload.get("slide_count"), int) or payload["slide_count"] < 7:
        raise ValueError("PPTX runtime acceptance slide coverage is insufficient")
    for field in ("artifact_runtime_receipt_sha256", "output_sha256"):
        if not SHA.fullmatch(str(payload.get(field, ""))):
            raise ValueError(f"PPTX runtime acceptance {field} is invalid")
    bindings = payload.get("source_bindings")
    if not isinstance(bindings, dict) or set(bindings) != set(BOUND_FILES):
        raise ValueError("PPTX runtime acceptance source bindings are incomplete")
    for relative in BOUND_FILES:
        digest = hashlib.sha256(bounded_read(root / relative, 2 * 1024 * 1024)[0]).hexdigest()
        if bindings[relative] != digest:
            raise ValueError(f"PPTX runtime acceptance is stale for {relative}")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--acceptance", type=Path, default=Path(__file__).resolve().parents[1] / "pptx-runtime-acceptance.json")
    args = parser.parse_args(argv)
    try:
        payload = validate(args.root, args.acceptance)
        print(f"PASS: PPTX runtime acceptance binds {payload['slide_count']} slides with artifact-tool {payload['artifact_tool_version']}")
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
