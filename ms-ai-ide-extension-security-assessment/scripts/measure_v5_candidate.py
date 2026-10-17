# SPDX-License-Identifier: MIT
"""Measure a private v5 candidate PDF without issuing runtime acceptance.

The operator must separately prove that PowerPoint rendered the exact staged
candidate. This handoff binds the supplied PDF and the reviewed parser to the
pending authoring request, then delegates untrusted PDF parsing to the existing
contained worker. It cannot publish a PPTX or create a Passed receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from native_pptx_text import (
    MAX_PDF_BYTES,
    MAX_RESULT_BYTES,
    validate_native_pdf_bounded,
)
from portable_fs import open_exclusive_write, require_real_directory
from verify_v5_candidate import MAX_REQUEST, _json, _read, prepare

SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_PARSER_POLICY_BYTES = 64 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _private_file(path: Path, maximum: int) -> bytes:
    directory = require_real_directory(path.parent)
    if os.name != "posix" or directory.stat().st_mode & 0o777 != 0o700:
        raise ValueError("native measurement input requires a private POSIX directory")
    return _read(directory / path.name, maximum)


def measure(root: Path, candidate_dir: Path, request_path: Path, pdf_path: Path,
            parser_path: Path, python_executable: Path, *, request_sha256: str,
            pdf_sha256: str, parser_sha256: str) -> dict[str, object]:
    """Return measured, source-bound evidence with acceptance explicitly pending."""
    for value in (request_sha256, pdf_sha256, parser_sha256):
        if not SHA256.fullmatch(value):
            raise ValueError("expected measurement digest is invalid")
    request = prepare(root, candidate_dir)
    canonical_request = (json.dumps(request, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True) + "\n").encode("ascii")
    if len(canonical_request) > MAX_REQUEST:
        raise ValueError("native measurement request exceeds bounds")
    request_bytes = _private_file(request_path, MAX_REQUEST)
    if request_bytes != canonical_request or _sha(request_bytes) != request_sha256:
        raise ValueError("native measurement request differs from current candidate")
    pdf = _private_file(pdf_path, MAX_PDF_BYTES)
    if not pdf or _sha(pdf) != pdf_sha256:
        raise ValueError("native PDF differs from expected rendering identity")
    parser_bytes = _read(parser_path, MAX_PARSER_POLICY_BYTES)
    if not parser_bytes or _sha(parser_bytes) != parser_sha256:
        raise ValueError("native parser policy differs from reviewed identity")
    parser_identity = _json(parser_bytes)
    if not isinstance(parser_identity, dict):
        raise TypeError("native parser policy is invalid")
    measured = validate_native_pdf_bounded(pdf, request["authored"],
                                            parser_identity=parser_identity,
                                            python_executable=str(python_executable))
    # The parser validates its own result against the request. Re-read the
    # private inputs and source-bound candidate after the native worker exits.
    if (_private_file(request_path, MAX_REQUEST) != request_bytes
        or _private_file(pdf_path, MAX_PDF_BYTES) != pdf
        or _read(parser_path, MAX_PARSER_POLICY_BYTES) != parser_bytes
        or prepare(root, candidate_dir) != request):
        raise ValueError("measurement inputs changed during native parsing")
    return {
        "schema": "solosentry.pptx.v5-native-measurements/v1",
        "status": "Pending native provenance and acceptance",
        "candidate_pptx_sha256": request["candidate_pptx_sha256"],
        "candidate_manifest_sha256": request["candidate_manifest_sha256"],
        "measurement_request_sha256": request_sha256,
        "native_pdf_sha256": pdf_sha256,
        "parser_policy_sha256": parser_sha256,
        "parser_identity_sha256": measured["parser_identity_sha256"],
        "native_powerpoint_closeout": "Pending",
        "human_acceptance": "Pending",
        "pages": measured["pages"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--request-sha256", required=True)
    parser.add_argument("--native-pdf", type=Path, required=True)
    parser.add_argument("--native-pdf-sha256", required=True)
    parser.add_argument("--parser-identity", type=Path, required=True)
    parser.add_argument("--parser-identity-sha256", required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = args.output.absolute()
        parent = require_real_directory(output.parent)
        if os.name != "posix" or parent.stat().st_mode & 0o777 != 0o700:
            raise ValueError("measurement output requires a private POSIX directory")
        if parent == args.candidate_dir.resolve(strict=True):
            raise ValueError("measurement output must remain outside the candidate directory")
        record = measure(args.root, args.candidate_dir, args.request, args.native_pdf,
                         args.parser_identity, args.python,
                         request_sha256=args.request_sha256,
                         pdf_sha256=args.native_pdf_sha256,
                         parser_sha256=args.parser_identity_sha256)
        raw = (json.dumps(record, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
        if len(raw) > MAX_RESULT_BYTES:
            raise ValueError("native measurement evidence exceeds bounds")
        with open_exclusive_write(output, mode=0o400) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        print(f"PENDING: measured native PDF evidence; sha256={_sha(raw)}")
        return 0
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        # Paths, PDF text and parser messages are private. Report only a fixed
        # failure class; detailed observations belong in private operator QA.
        print(f"ERROR: native measurement rejected ({type(exc).__name__})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
