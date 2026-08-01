#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create a new, non-authoritative fifteen-stage assessment input skeleton."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

from portable_fs import open_exclusive_write, require_real_directory

RUN_KEY = re.compile(r"^\d{4}-\d{2}-\d{2}-v\d+\.\d+$")
STAGE_NAMES = (
    "intake-readiness", "evidence-plan", "acquisition-provenance",
    "static-inspection", "ide-installation-manifests", "architecture-data-flows",
    "runtime-observations", "malware-supply-chain", "sbom-vulnerability-triage",
    "mcp-agent-skills", "privacy-regulatory", "framework-mappings",
    "finding-records", "controls-detection", "claim-evidence-report-qa",
)


def _write(root: Path, name: str, data: bytes) -> str:
    with open_exclusive_write(root / name) as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def initialize(root: Path, assessment: str, target: str, version: str, run_key: str) -> None:
    if not RUN_KEY.fullmatch(run_key):
        raise ValueError("run key must use YYYY-MM-DD-vMAJOR.MINOR")
    absolute = Path(os.path.abspath(os.fspath(root)))
    parent = require_real_directory(absolute.parent)
    os.mkdir(parent / absolute.name, 0o700)
    root = require_real_directory(parent / absolute.name)
    try:
        stages = []
        for number, name in enumerate(STAGE_NAMES, 1):
            filename = f"stage-{number:02d}-{name}.md"
            content = (
                f"# Stage {number}: {name.replace('-', ' ').title()}\n\n"
                f"Assessment: {assessment}\nTarget: {target}\nVersion: {version}\n"
                f"Run key: {run_key}\nStatus classification: Incomplete\n"
                "Analyst validation status: Incomplete\n\n"
                "Inputs: TODO\nMethod and tool version: TODO\nLimitations: TODO\nResults: TODO\n"
            ).encode("utf-8")
            stages.append({"stage": number, "name": name, "file": filename, "status": "Incomplete", "sha256": _write(root, filename, content)})
        claims = {
            "schema_version": 1, "assessment": assessment, "target": target,
            "version": version, "analyst_validation": "Incomplete", "claims": [{
                "id": "assessment.placeholder", "type": "text",
                "value": "Replace this placeholder with an analyst-validated claim.",
                "evidence_ids": ["EVD-TODO-001"], "source_stages": [1],
                "evidence_state": "Unknown", "confidence": "Low",
                "limitations": "Placeholder only; not analyst validated.",
            }],
        }
        claims_data = (json.dumps(claims, indent=2, sort_keys=True) + "\n").encode()
        claims_sha = _write(root, "validated-claims.json", claims_data)
        evidence = [
            {"id": f"EVD-TODO-{index:03d}", "title": f"Placeholder evidence {index}", "source": "TODO", "method": "TODO", "state": "Unknown", "limitation": "Replace before validation."}
            for index in range(1, 6)
        ]
        references = [
            {"id": f"REF-{index:03d}", "title": f"Placeholder primary source {index}", "publisher": "TODO", "url": f"https://example.com/replace/{index}", "accessed": run_key[:10], "applicability": "Replace before validation."}
            for index in range(1, 13)
        ]
        sections = [
            {"id": f"section.{index:02d}", "heading": f"Placeholder section {index}", "level": 1, "paragraphs": [], "bullets": [], "tables": []}
            for index in range(1, 21)
        ]
        outcomes = [f"Replace executive outcome {index}. REF-{index:03d}" for index in range(1, 6)]
        conditions = ["Replace this approval condition before validation. REF-001"]
        model = {
            "schema_version": 2, "assessment": assessment, "target": target,
            "publisher": "TODO", "extension_id": "todo.replace", "version": version,
            "run_key": run_key, "assessment_date": run_key[:10], "document_version": run_key.rsplit("-v", 1)[1],
            "classification": "PUBLIC", "decision": "Defer pending evidence",
            "overall_residual_risk": "High",
            "review_trigger": "Replace the review trigger before validation. REF-001",
            "ide_scope": ["VS Code"], "executive_outcomes": outcomes,
            "approval_conditions": conditions, "sections": sections,
            "findings": [{"id": "F-001", "title": "Placeholder finding", "scope": "VS Code", "scenario": "Replace the scenario. REF-001", "evidence_ids": "EVD-TODO-001", "likelihood": "1", "impact": "1", "inherent": "1 Low", "controls": "Replace controls.", "control_strength": "Unknown", "residual_likelihood": "1", "residual_impact": "1", "residual": "1 Low", "recommendation": "Replace recommendation. REF-001", "owner": "TODO", "priority": "P3", "target_date": "Before deployment", "verification": "Replace verification.", "mappings": "TODO", "confidence": "Low"}],
            "evidence": evidence, "references": references,
            "glossary": [{"term": f"Placeholder term {index}", "definition": "Replace before validation."} for index in range(1, 6)],
            "figure": {"title": "Placeholder trust boundaries", "alt_text": "Replace this accessible description. REF-001", "nodes": ["IDE host", "Extension", "Service"], "edges": [["IDE host", "Extension", "invokes"], ["Extension", "Service", "HTTPS"]]},
            "derivative_sources": {"cover": ["EVD-TODO-001", "REF-001"], "executive_outcomes": [[f"EVD-TODO-{index:03d}", f"REF-{index:03d}"] for index in range(1, 6)], "approval_conditions": [["EVD-TODO-001", "REF-001"]], "figure": ["EVD-TODO-001", "REF-001"], "findings": {"F-001": ["EVD-TODO-001", "REF-001"]}, "decision": ["EVD-TODO-001", "REF-001"], "review_trigger": ["EVD-TODO-001", "REF-001"]},
        }
        model_data = (json.dumps(model, indent=2, sort_keys=True) + "\n").encode()
        model_sha = _write(root, "report-model.json", model_data)
        manifest = {
            "schema_version": 1, "assessment": assessment, "target": target,
            "version": version, "run_key": run_key, "status": "Incomplete",
            "stages": stages,
            "claims": {"file": "validated-claims.json", "status": "Incomplete", "sha256": claims_sha},
            "report_model": {"file": "report-model.json", "status": "Incomplete", "sha256": model_sha},
        }
        _write(root, "stage-manifest.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    except Exception:
        # Retain the task-owned incomplete directory for safe diagnosis; never
        # recursively delete a path that another process could have raced.
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--assessment", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--run-key", required=True)
    args = parser.parse_args(argv)
    try:
        initialize(args.root, args.assessment.strip(), args.target.strip(), args.version.strip(), args.run_key)
        print(f"Created incomplete stage bundle at {args.root}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
