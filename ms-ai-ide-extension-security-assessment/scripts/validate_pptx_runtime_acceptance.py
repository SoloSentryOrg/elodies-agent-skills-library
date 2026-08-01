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

BOUND_FILES = (
    "scripts/build_assessment_pptx.mjs",
    "scripts/create_artifact_runtime_receipt.mjs",
    "scripts/create_pptx_montage.py",
    "scripts/portable_fs.py",
    "scripts/requirements.lock",
    "scripts/secure_pptx_stage_bundle.py",
    "scripts/validate_assessment_pptx.py",
    "scripts/test_build_assessment_pptx.py",
)
SHA = re.compile(r"^[0-9a-f]{64}$")


def validate(root: Path, acceptance: Path) -> dict[str, object]:
    payload = json.loads(acceptance.read_text(encoding="utf-8"))
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
        digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
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
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
