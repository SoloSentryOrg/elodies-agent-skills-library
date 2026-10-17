#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the complete private v5 PPTX technical acceptance on approved Linux.

This executes finalization and checks the resulting deck, build manifest and
source notes. It writes a source-bound technical receipt. Publication and
human, business and residual-risk acceptance remain separate decisions.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import sys
import zipfile
from pathlib import Path

from finalize_v5_private_pptx import finalize
from portable_fs import open_exclusive_write, require_real_directory
from validate_assessment_pptx import validate_pptx_bytes
from validate_pptx_runtime_acceptance import V5_ACCEPTANCE_FILES, _validate_v5
from verify_v5_candidate import MAX_FILE, _json, _read, prepare

NOTE = re.compile(r"^ppt/notesSlides/notesSlide[1-9][0-9]*\.xml$")
DECISIONS = ("production_publication", "human_acceptance",
             "business_acceptance", "residual_risk_acceptance")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _private_output(directory: Path, candidate_dir: Path, result: dict[str, object],
                    request: dict[str, object]) -> tuple[bytes, bytes, bytes, int]:
    directory = require_real_directory(directory)
    if ((directory.stat().st_mode & 0o777) != 0o700
            or {path.name for path in directory.iterdir()} !=
            {"assessment.pptx", "assessment-build.json", "finalization.json"}):
        raise ValueError("private v5 output inventory or mode is invalid")
    raw = {}
    for name, limit in (("assessment.pptx", MAX_FILE),
                        ("assessment-build.json", 2 * 1024 * 1024),
                        ("finalization.json", 16 * 1024)):
        path = directory / name
        if stat.S_IMODE(path.lstat().st_mode) != 0o400:
            raise ValueError("private v5 output file mode is invalid")
        raw[name] = _read(path, limit)
    deck = raw["assessment.pptx"]
    build_raw = raw["assessment-build.json"]
    final_raw = raw["finalization.json"]
    build, final = _json(build_raw), _json(final_raw)
    if not isinstance(build, dict) or not isinstance(final, dict) or final != result:
        raise ValueError("private finalization manifest differs from execution")
    candidate = _json(_read(candidate_dir / "candidate.json", 8 * 1024 * 1024))
    runtime = _json(_read(candidate_dir / "artifact-runtime-receipt.json", 2 * 1024 * 1024))
    if not isinstance(candidate, dict) or not isinstance(runtime, dict):
        raise TypeError("private candidate runtime identity is invalid")
    expected_build = {
        "schema_version", "generator", "runtime_versions",
        "artifact_runtime_receipt_sha256", "inputs", "candidate_manifest_sha256",
        "technical_reconciliation_sha256", "finalizer_sha256", "output",
        "qa_source", "qa_files", "native_pdf_sha256", "technical_validation",
        "native_powerpoint_closeout", *DECISIONS,
    }
    if (set(build) != expected_build or build["schema_version"] != 2
            or build["generator"] !=
            "scripts/build_assessment_pptx.mjs+scripts/finalize_v5_private_pptx.py"
            or build["runtime_versions"] != {
                "node": candidate["runtime"]["node"],
                "artifact_tool": candidate["runtime"]["artifact_tool"],
            }
            or runtime.get("version") != candidate["runtime"]["artifact_tool"]
            or build["artifact_runtime_receipt_sha256"] !=
            candidate["runtime"]["artifact_runtime_receipt_sha256"]
            or build["inputs"] != candidate["inputs"]
            or build["candidate_manifest_sha256"] != request["candidate_manifest_sha256"]
            or build["technical_reconciliation_sha256"] != result["technical_reconciliation_sha256"]
            or build["finalizer_sha256"] != result["finalizer_sha256"]
            or build["output"] != {"file": "assessment.pptx", "sha256": _sha(deck),
                                   "slide_count": result["slide_count"]}
            or build["qa_source"] != "immutable_candidate"
            or build["native_pdf_sha256"] != result["native_pdf_sha256"]
            or build["technical_validation"] != "Passed"
            or build["native_powerpoint_closeout"] != "Verified"
            or any(build[key] != "Pending" or result[key] != "Pending"
                   for key in DECISIONS)
            or _sha(build_raw) != result["build_manifest_sha256"]
            or _sha(deck) != request["candidate_pptx_sha256"]):
        raise ValueError("private v5 build contract is inconsistent")
    files = {item["file"]: item["sha256"] for item in candidate["files"]}
    expected_qa = {"deck.inspect.ndjson"}
    for index in range(1, result["slide_count"] + 1):
        expected_qa.update((f"slide-{index:02d}.png",
                            f"slide-{index:02d}.layout.json"))
    qa = build["qa_files"]
    if (not isinstance(qa, list) or qa !=
            [{"file": name, "sha256": files.get(name)} for name in sorted(expected_qa)]):
        raise ValueError("private v5 QA inventory is incomplete")
    if any(_sha(_read(candidate_dir / name, MAX_FILE)) != files[name]
           for name in expected_qa):
        raise ValueError("private v5 QA file changed after finalization")
    package = validate_pptx_bytes(deck)
    if package["slides"] != result["slide_count"] or package["notes"] != package["slides"]:
        raise ValueError("private v5 slide and source-note coverage differs")
    with zipfile.ZipFile(io.BytesIO(deck)) as archive:
        notes = [entry for entry in archive.infolist() if NOTE.fullmatch(entry.filename)]
        if len(notes) != package["slides"]:
            raise ValueError("private v5 source-note inventory differs")
        for entry in notes:
            if entry.file_size > 2 * 1024 * 1024 or b"[Sources]" not in archive.read(entry):
                raise ValueError("private v5 source notes are missing or unbounded")
    return deck, build_raw, final_raw, package["notes"]


def accept(root: Path, candidate_dir: Path, request_path: Path, pdf_path: Path,
           render_path: Path, measurement_path: Path, parser_path: Path,
           python_executable: Path, reconciliation_path: Path, output_dir: Path,
           acceptance_path: Path) -> dict[str, object]:
    if not sys.platform.startswith("linux") or os.name != "posix":
        raise ValueError("v5 runtime acceptance requires the approved Linux parser host")
    root = require_real_directory(root)
    if root / "scripts/accept_v5_runtime.py" != Path(__file__).resolve(strict=True):
        raise ValueError("acceptance root differs from the executing source")
    result = finalize(root, candidate_dir, request_path, pdf_path, render_path,
                      measurement_path, parser_path, python_executable,
                      reconciliation_path, output_dir)
    request = prepare(root, candidate_dir)
    deck, build_raw, final_raw, notes_count = _private_output(
        output_dir, candidate_dir, result, request)
    reconciliation_raw = _read(reconciliation_path, 16 * 1024)
    reconciliation = _json(reconciliation_raw)
    if (not isinstance(reconciliation, dict)
            or result["technical_reconciliation_sha256"] != _sha(reconciliation_raw)):
        raise ValueError("native reconciliation changed during acceptance")
    source_bindings = {
        relative: _sha(_read(root / relative, 2 * 1024 * 1024))
        for relative in V5_ACCEPTANCE_FILES
    }
    candidate = _json(_read(candidate_dir / "candidate.json", 8 * 1024 * 1024))
    payload = {
        "schema_version": 2,
        "status": "Passed",
        "test": "accept_v5_private_runtime",
        "platform": "linux",
        "native_office_platform": "darwin",
        "artifact_tool_version": candidate["runtime"]["artifact_tool"],
        "artifact_runtime_receipt_sha256": candidate["runtime"]["artifact_runtime_receipt_sha256"],
        "candidate_manifest_sha256": request["candidate_manifest_sha256"],
        "candidate_pptx_sha256": request["candidate_pptx_sha256"],
        "technical_reconciliation_sha256": _sha(reconciliation_raw),
        "render_record_sha256": reconciliation["render_record_sha256"],
        "measurement_record_sha256": reconciliation["measurement_record_sha256"],
        "parser_policy_sha256": reconciliation["parser_policy_sha256"],
        "native_pdf_sha256": reconciliation["native_pdf_sha256"],
        "build_manifest_sha256": _sha(build_raw),
        "finalization_sha256": _sha(final_raw),
        "output_sha256": _sha(deck),
        "slide_count": result["slide_count"],
        "notes_count": notes_count,
        "measured_frames": result["measured_frames"],
        "source_bindings": source_bindings,
        **{key: "Pending" for key in DECISIONS},
    }
    _validate_v5(root, payload)
    if (prepare(root, candidate_dir) != request
            or _read(output_dir / "assessment.pptx", MAX_FILE) != deck
            or _read(output_dir / "assessment-build.json", 2 * 1024 * 1024) != build_raw
            or _read(output_dir / "finalization.json", 16 * 1024) != final_raw
            or any(_sha(_read(root / relative, 2 * 1024 * 1024)) != digest
                   for relative, digest in source_bindings.items())):
        raise ValueError("v5 runtime acceptance inputs changed before receipt")
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    parent = require_real_directory(acceptance_path.parent)
    if (parent.stat().st_mode & 0o777) != 0o700:
        raise ValueError("v5 acceptance receipt requires a private output parent")
    target = parent / acceptance_path.name
    if (target.is_relative_to(require_real_directory(candidate_dir))
            or target.is_relative_to(require_real_directory(output_dir))):
        raise ValueError("v5 acceptance receipt cannot alter immutable evidence")
    with open_exclusive_write(target, mode=0o400) as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if _read(target, 16 * 1024) != raw:
        raise ValueError("v5 acceptance receipt changed after write")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    for name in ("candidate-dir", "request", "native-pdf", "render-record",
                 "measurement-record", "parser-identity", "python",
                 "reconciliation", "output-dir", "acceptance-output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        record = accept(args.root, args.candidate_dir, args.request,
                        args.native_pdf, args.render_record,
                        args.measurement_record, args.parser_identity,
                        args.python, args.reconciliation, args.output_dir,
                        args.acceptance_output)
        print("TECHNICAL ACCEPTANCE PASS: " + json.dumps({
            "slides": record["slide_count"], "notes": record["notes_count"],
            "frames": record["measured_frames"],
            "output_sha256": record["output_sha256"],
            "production_publication": record["production_publication"],
            "human_acceptance": record["human_acceptance"],
        }, sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, TypeError, KeyError,
            zipfile.BadZipFile) as exc:
        print(f"ERROR: v5 runtime acceptance rejected ({type(exc).__name__})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
