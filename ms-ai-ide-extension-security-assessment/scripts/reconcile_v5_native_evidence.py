#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reconcile a v5 PowerPoint render with a fresh contained PDF measurement.

This records technical verification only. It neither publishes a presentation
nor converts pending human, business, or residual-risk acceptance to Passed.
Run it on an approved Linux parser host with the same private inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from measure_v5_candidate import MAX_PARSER_POLICY_BYTES, _private_file, measure
from native_pptx_text import MAX_PDF_BYTES, MAX_RESULT_BYTES
from portable_fs import open_exclusive_write, require_real_directory
from verify_v5_candidate import MAX_REQUEST, _json, _read, prepare

SHA256 = re.compile(r"^[0-9a-f]{64}$")
RENDER_KEYS = {
    "schema", "status", "candidate_manifest_sha256", "candidate_pptx_sha256",
    "measurement_request_sha256", "native_pdf_sha256", "native_pdf_file",
    "adapter_reported_slide_count", "platform", "exact_document_closed",
    "native_python_sha256", "human_acceptance", "adapter_sha256",
    "stager_sha256", "coordinator_sha256",
}
MEASUREMENT_KEYS = {
    "schema", "status", "candidate_manifest_sha256", "candidate_pptx_sha256",
    "measurement_request_sha256", "native_pdf_sha256", "parser_policy_sha256",
    "parser_identity_sha256", "native_powerpoint_closeout", "human_acceptance",
    "pages",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _expected_digest(value: str, label: str) -> None:
    if not SHA256.fullmatch(value):
        raise ValueError(f"{label} digest is invalid")


def reconcile(root: Path, candidate_dir: Path, request_path: Path, pdf_path: Path,
              render_path: Path, measurement_path: Path, parser_path: Path,
              python_executable: Path, *, request_sha256: str, pdf_sha256: str,
              render_sha256: str, measurement_sha256: str,
              parser_sha256: str) -> dict[str, object]:
    """Re-run the contained parser before recording correlated technical proof."""
    for label, value in (("request", request_sha256), ("PDF", pdf_sha256),
                         ("render", render_sha256), ("measurement", measurement_sha256),
                         ("parser policy", parser_sha256)):
        _expected_digest(value, label)
    root = require_real_directory(root)
    reconciler_source = root / "scripts/reconcile_v5_native_evidence.py"
    reconciler_sha256 = _sha(_read(reconciler_source, 2 * 1024 * 1024))
    request = prepare(root, candidate_dir)
    expected_request = (json.dumps(request, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=True) + "\n").encode("ascii")
    if (_private_file(request_path, MAX_REQUEST) != expected_request
            or _sha(expected_request) != request_sha256):
        raise ValueError("native request differs from the current candidate")
    pdf = _private_file(pdf_path, MAX_PDF_BYTES)
    if not pdf.startswith(b"%PDF-") or _sha(pdf) != pdf_sha256:
        raise ValueError("native PDF differs from expected identity")
    render_raw = _private_file(render_path, 16 * 1024)
    measured_raw = _private_file(measurement_path, MAX_RESULT_BYTES)
    if _sha(render_raw) != render_sha256 or _sha(measured_raw) != measurement_sha256:
        raise ValueError("native record differs from its expected identity")
    render, measured = _json(render_raw), _json(measured_raw)
    if not isinstance(render, dict) or set(render) != RENDER_KEYS:
        raise ValueError("native PowerPoint record shape is invalid")
    if not isinstance(measured, dict) or set(measured) != MEASUREMENT_KEYS:
        raise ValueError("native PDF measurement shape is invalid")
    identity = {
        "candidate_manifest_sha256": request["candidate_manifest_sha256"],
        "candidate_pptx_sha256": request["candidate_pptx_sha256"],
        "measurement_request_sha256": request_sha256,
        "native_pdf_sha256": pdf_sha256,
    }
    if any(render[key] != value or measured[key] != value
           for key, value in identity.items()):
        raise ValueError("native records refer to different candidate or PDF inputs")
    if (render["schema"] != "solosentry.pptx.v5-native-render/v1"
            or render["status"] != "Native adapter verified; measurement and acceptance pending"
            or render["human_acceptance"] != "Pending"
            or render["platform"] != "darwin"
            or render["exact_document_closed"] is not True
            or type(render["adapter_reported_slide_count"]) is not int
            or render["adapter_reported_slide_count"] != request["slide_count"]
            or render["native_pdf_file"] != pdf_path.name
            or not SHA256.fullmatch(str(render["native_python_sha256"]))):
        raise ValueError("native PowerPoint closeout is not verified")
    bindings = request["source_bindings"]
    sources = {
        "adapter_sha256": "scripts/render_presentations_with_powerpoint.applescript",
        "stager_sha256": "scripts/stage_office_artifact.py",
        "coordinator_sha256": "scripts/capture_v5_powerpoint_render.py",
    }
    for key, relative in sources.items():
        current = _sha(_read(root / relative, 2 * 1024 * 1024))
        if render[key] != current or (key != "coordinator_sha256"
                                      and bindings[relative] != current):
            raise ValueError("native PowerPoint source differs from reviewed source")
    parser_raw = _read(parser_path, MAX_PARSER_POLICY_BYTES)
    if (not parser_raw or _sha(parser_raw) != parser_sha256
            or measured["parser_policy_sha256"] != parser_sha256
            or measured["schema"] != "solosentry.pptx.v5-native-measurements/v1"
            or measured["status"] != "Pending native provenance and acceptance"
            or measured["native_powerpoint_closeout"] != "Pending"
            or measured["human_acceptance"] != "Pending"
            or not SHA256.fullmatch(str(measured["parser_identity_sha256"]))):
        raise ValueError("native PDF measurement identity is invalid")
    fresh = measure(root, candidate_dir, request_path, pdf_path, parser_path,
                    python_executable, request_sha256=request_sha256,
                    pdf_sha256=pdf_sha256, parser_sha256=parser_sha256)
    if fresh != measured:
        raise ValueError("stored native measurement differs from fresh contained parsing")
    if (_private_file(request_path, MAX_REQUEST) != expected_request
            or _private_file(pdf_path, MAX_PDF_BYTES) != pdf
            or _private_file(render_path, 16 * 1024) != render_raw
            or _private_file(measurement_path, MAX_RESULT_BYTES) != measured_raw
            or _read(parser_path, MAX_PARSER_POLICY_BYTES) != parser_raw
            or prepare(root, candidate_dir) != request):
        raise ValueError("native evidence changed during reconciliation")
    if any(_sha(_read(root / relative, 2 * 1024 * 1024)) != render[key]
           for key, relative in sources.items()):
        raise ValueError("native PowerPoint source changed during reconciliation")
    if _sha(_read(reconciler_source, 2 * 1024 * 1024)) != reconciler_sha256:
        raise ValueError("reconciler source changed during execution")
    frames = sum(len(page) for page in measured["pages"])
    return {
        "schema": "solosentry.pptx.v5-technical-reconciliation/v1",
        "technical_validation": "Passed",
        "native_powerpoint_closeout": "Verified",
        "production_publication": "Pending",
        "human_acceptance": "Pending",
        "business_acceptance": "Pending",
        "residual_risk_acceptance": "Pending",
        **identity,
        "render_record_sha256": render_sha256,
        "measurement_record_sha256": measurement_sha256,
        "parser_policy_sha256": parser_sha256,
        "parser_identity_sha256": measured["parser_identity_sha256"],
        "reconciler_sha256": reconciler_sha256,
        "slide_count": request["slide_count"],
        "measured_frames": frames,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    for name in ("candidate-dir", "request", "native-pdf", "render-record",
                 "measurement-record", "parser-identity", "python", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("request-sha256", "native-pdf-sha256", "render-sha256",
                 "measurement-sha256", "parser-sha256"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args(argv)
    try:
        output = Path(os.path.abspath(os.fspath(args.output)))
        parent = require_real_directory(output.parent)
        if os.name != "posix" or parent.stat().st_mode & 0o777 != 0o700:
            raise ValueError("technical reconciliation output requires a private POSIX directory")
        if output.exists() or output.is_symlink():
            raise ValueError("technical reconciliation output already exists")
        record = reconcile(args.root, args.candidate_dir, args.request, args.native_pdf,
                           args.render_record, args.measurement_record,
                           args.parser_identity, args.python,
                           request_sha256=args.request_sha256,
                           pdf_sha256=args.native_pdf_sha256,
                           render_sha256=args.render_sha256,
                           measurement_sha256=args.measurement_sha256,
                           parser_sha256=args.parser_sha256)
        raw = (json.dumps(record, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
        with open_exclusive_write(output, mode=0o400) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        print(f"TECHNICAL PASS; publication and human acceptance pending; sha256={_sha(raw)}")
        return 0
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: v5 reconciliation rejected ({type(exc).__name__})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
