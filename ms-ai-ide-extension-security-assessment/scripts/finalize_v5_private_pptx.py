#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Prepare a private v5 PowerPoint output from freshly verified native evidence.

The output is an exact copy of the measured candidate. This step records
technical closeout only; it does not publish a report or grant human acceptance.
Run on the approved Linux parser host with the same immutable private inputs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from portable_fs import open_exclusive_write, require_real_directory
from reconcile_v5_native_evidence import SHA256, _sha, reconcile
from verify_v5_candidate import MAX_FILE, _json, _read, prepare

RECONCILIATION_KEYS = {
    "schema", "technical_validation", "native_powerpoint_closeout",
    "production_publication", "human_acceptance", "business_acceptance",
    "residual_risk_acceptance", "candidate_manifest_sha256",
    "candidate_pptx_sha256", "measurement_request_sha256",
    "native_pdf_sha256", "render_record_sha256",
    "measurement_record_sha256", "parser_policy_sha256",
    "parser_identity_sha256", "reconciler_sha256", "slide_count",
    "measured_frames",
}


def _write_private(path: Path, data: bytes) -> None:
    with open_exclusive_write(path, mode=0o400) as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def finalize(root: Path, candidate_dir: Path, request_path: Path, pdf_path: Path,
             render_path: Path, measurement_path: Path, parser_path: Path,
             python_executable: Path, reconciliation_path: Path,
             output_dir: Path) -> dict[str, object]:
    """Reconcile source, renderer and parser again before creating any output."""
    root = require_real_directory(root)
    if (root / "scripts/finalize_v5_private_pptx.py") != Path(__file__).resolve(strict=True):
        raise ValueError("finalizer root differs from the executing source")
    reconciliation_bytes = _read(reconciliation_path, 16 * 1024)
    saved = _json(reconciliation_bytes)
    if not isinstance(saved, dict) or set(saved) != RECONCILIATION_KEYS:
        raise ValueError("technical reconciliation shape is invalid")
    for field in ("candidate_manifest_sha256", "candidate_pptx_sha256",
                  "measurement_request_sha256", "native_pdf_sha256",
                  "render_record_sha256", "measurement_record_sha256",
                  "parser_policy_sha256", "parser_identity_sha256",
                  "reconciler_sha256"):
        if not isinstance(saved[field], str) or not SHA256.fullmatch(saved[field]):
            raise ValueError("technical reconciliation identity is invalid")
    if (saved["schema"] != "solosentry.pptx.v5-technical-reconciliation/v1"
            or saved["technical_validation"] != "Passed"
            or saved["native_powerpoint_closeout"] != "Verified"
            or any(saved[field] != "Pending" for field in
                   ("production_publication", "human_acceptance",
                    "business_acceptance", "residual_risk_acceptance"))):
        raise ValueError("technical reconciliation state is invalid")
    fresh = reconcile(
        root, candidate_dir, request_path, pdf_path, render_path,
        measurement_path, parser_path, python_executable,
        request_sha256=saved["measurement_request_sha256"],
        pdf_sha256=saved["native_pdf_sha256"],
        render_sha256=saved["render_record_sha256"],
        measurement_sha256=saved["measurement_record_sha256"],
        parser_sha256=saved["parser_policy_sha256"],
    )
    if saved != fresh:
        raise ValueError("technical reconciliation differs from fresh native evidence")
    request = prepare(root, candidate_dir)
    pptx = _read(candidate_dir / "candidate.pptx", MAX_FILE)
    if (_sha(pptx) != fresh["candidate_pptx_sha256"]
            or request["candidate_pptx_sha256"] != fresh["candidate_pptx_sha256"]):
        raise ValueError("candidate PPTX changed after native reconciliation")
    finalizer_source = root / "scripts/finalize_v5_private_pptx.py"
    finalizer_sha256 = _sha(_read(finalizer_source, 2 * 1024 * 1024))
    parent = require_real_directory(output_dir.parent)
    if os.name != "posix" or (parent.stat().st_mode & 0o777) != 0o700:
        raise ValueError("private finalization requires a POSIX 0700 parent")
    target = parent / output_dir.name
    if (target.name in ("", ".", "..")
            or target.is_relative_to(require_real_directory(candidate_dir))):
        raise ValueError("private finalization target is invalid")
    os.mkdir(target, 0o700)
    directory = require_real_directory(target)
    if (directory.stat().st_mode & 0o777) != 0o700:
        raise ValueError("private finalization directory is not 0700")
    output_path = directory / "assessment.pptx"
    _write_private(output_path, pptx)
    output_bytes = _read(output_path, MAX_FILE)
    if output_bytes != pptx:
        raise ValueError("private PowerPoint output changed during finalization")
    if prepare(root, candidate_dir) != request:
        raise ValueError("candidate changed during private finalization")
    if _sha(_read(finalizer_source, 2 * 1024 * 1024)) != finalizer_sha256:
        raise ValueError("finalizer source changed during execution")
    manifest = {
        "schema": "solosentry.pptx.v5-private-finalization/v1",
        "technical_validation": "Passed",
        "native_powerpoint_closeout": "Verified",
        "production_publication": "Pending",
        "human_acceptance": "Pending",
        "business_acceptance": "Pending",
        "residual_risk_acceptance": "Pending",
        "candidate_manifest_sha256": fresh["candidate_manifest_sha256"],
        "technical_reconciliation_sha256": _sha(reconciliation_bytes),
        "finalizer_sha256": finalizer_sha256,
        "native_pdf_sha256": fresh["native_pdf_sha256"],
        "output_sha256": _sha(output_bytes),
        "slide_count": fresh["slide_count"],
        "measured_frames": fresh["measured_frames"],
        "output_file": output_path.name,
    }
    raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    _write_private(directory / "finalization.json", raw)
    if _sha(_read(directory / "finalization.json", 16 * 1024)) != _sha(raw):
        raise ValueError("private finalization manifest changed")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    for name in ("candidate-dir", "request", "native-pdf", "render-record",
                 "measurement-record", "parser-identity", "python",
                 "reconciliation", "output-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = finalize(args.root, args.candidate_dir, args.request,
                          args.native_pdf, args.render_record,
                          args.measurement_record, args.parser_identity,
                          args.python, args.reconciliation, args.output_dir)
        print("PRIVATE TECHNICAL OUTPUT: " + json.dumps({
            "output_dir": str(args.output_dir),
            "output_sha256": result["output_sha256"],
            "production_publication": result["production_publication"],
            "human_acceptance": result["human_acceptance"],
        }, sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: private v5 finalization rejected ({type(exc).__name__})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
