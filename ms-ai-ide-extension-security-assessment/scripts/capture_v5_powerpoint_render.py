#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bind an exact private v5 candidate to one successful native PowerPoint export.

The existing Office adapter owns document open/export/close. This coordinator
checks its exact invocation and output identity; it does not measure PDF text,
publish a presentation, or attest visual or human acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import subprocess
import sys
import time
from pathlib import Path

from native_pptx_text import MAX_PDF_BYTES
from portable_fs import bounded_read, open_exclusive_write, require_real_directory
from verify_v5_candidate import MAX_REQUEST, _read, prepare

SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_ADAPTER_OUTPUT = 16 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_PYTHON_BYTES = 64 * 1024 * 1024
ADAPTER_TIMEOUT_SECONDS = 180


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_directory(path: Path) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    canonical = require_real_directory(absolute)
    if absolute != canonical:
        raise ValueError("QA path contains a symlink or noncanonical component")
    return canonical


def _private_request(path: Path) -> bytes:
    parent = require_real_directory(path.parent)
    if (parent.stat().st_mode & 0o777) != 0o700:
        raise ValueError("native request requires a private POSIX directory")
    return _read(parent / path.name, MAX_REQUEST)


def _run_adapter(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Drain both trusted adapter pipes with explicit byte and time limits."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    selector = selectors.DefaultSelector()
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + ADAPTER_TIMEOUT_SECONDS
    try:
        assert process.stdout is not None and process.stderr is not None
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, data=name)
        while selector.get_map() or process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, ADAPTER_TIMEOUT_SECONDS)
            for key, _ in selector.select(timeout=min(remaining, 0.25)):
                try:
                    block = os.read(key.fileobj.fileno(), 4096)
                except BlockingIOError:
                    continue
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                buffer = buffers[key.data]
                buffer.extend(block)
                if len(buffer) > MAX_ADAPTER_OUTPUT:
                    raise ValueError("native PowerPoint adapter output exceeds bounds")
        return subprocess.CompletedProcess(
            command, process.wait(timeout=max(0, deadline - time.monotonic())),
            buffers["stdout"].decode("utf-8", errors="strict"),
            buffers["stderr"].decode("utf-8", errors="strict"),
        )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        selector.close()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def capture(root: Path, candidate_dir: Path, request_path: Path, qa_input: Path,
            python_executable: Path, *, request_sha256: str,
            host_platform: str | None = None) -> dict[str, object]:
    """Return technical provenance only after the reviewed adapter succeeds."""
    if (host_platform or sys.platform) != "darwin" or os.name != "posix":
        raise ValueError("native PowerPoint capture requires a macOS host")
    if not SHA256.fullmatch(request_sha256):
        raise ValueError("expected request digest is invalid")
    root = require_real_directory(root)
    request = prepare(root, candidate_dir)
    canonical_request = (json.dumps(request, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True) + "\n").encode("ascii")
    if (_private_request(request_path) != canonical_request
            or _sha(canonical_request) != request_sha256):
        raise ValueError("native request differs from current candidate")

    input_dir = _canonical_directory(qa_input.parent)
    qa_root = _canonical_directory(input_dir.parent)
    rendered = _canonical_directory(qa_root / "rendered")
    if (input_dir.name != "input" or qa_root.name != "PowerPoint-QA"
            or rendered.parent != qa_root or qa_input.name != "candidate.pptx"):
        raise ValueError("native QA paths do not match the stable adapter contract")
    staged_input = input_dir / "candidate.pptx"
    staged_bytes = bounded_read(staged_input, 64 * 1024 * 1024)[0]
    if _sha(staged_bytes) != request["candidate_pptx_sha256"]:
        raise ValueError("staged PowerPoint input differs from candidate")
    expected_pdf = rendered / "candidate-powerpoint-full.pdf"
    if expected_pdf.exists() or expected_pdf.is_symlink():
        raise ValueError("native output already exists")

    adapter = root / "scripts/render_presentations_with_powerpoint.applescript"
    stager = root / "scripts/stage_office_artifact.py"
    coordinator = root / "scripts/capture_v5_powerpoint_render.py"
    source_hashes = {
        "adapter_sha256": _sha(bounded_read(adapter, MAX_SOURCE_BYTES)[0]),
        "stager_sha256": _sha(bounded_read(stager, MAX_SOURCE_BYTES)[0]),
        "coordinator_sha256": _sha(bounded_read(coordinator, MAX_SOURCE_BYTES)[0]),
    }
    bindings = request["source_bindings"]
    if (source_hashes["adapter_sha256"] != bindings["scripts/render_presentations_with_powerpoint.applescript"]
            or source_hashes["stager_sha256"] != bindings["scripts/stage_office_artifact.py"]):
        raise ValueError("native adapter sources differ from candidate bindings")
    python_requested = Path(os.path.abspath(os.fspath(python_executable)))
    python = _canonical_directory(python_requested.parent) / python_requested.name
    if not python.is_file() or python.is_symlink() or not os.access(python, os.X_OK):
        raise ValueError("native Python must be an executable regular file")
    python_sha256 = _sha(bounded_read(python, MAX_PYTHON_BYTES)[0])
    before_stages = {path.name for path in qa_root.glob(".powerpoint-render.*")}
    command = ["/usr/bin/osascript", str(adapter), str(rendered), str(python),
               str(stager), str(staged_input), request["candidate_pptx_sha256"]]
    try:
        result = _run_adapter(command)
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        raise ValueError("native PowerPoint adapter did not complete") from exc
    if result.returncode != 0 or result.stderr:
        raise ValueError("native PowerPoint adapter did not succeed")
    expected_result = f"candidate\t{request['slide_count']}\t{expected_pdf}"
    if result.stdout not in (expected_result, expected_result + "\n"):
        raise ValueError("native PowerPoint adapter reported an unexpected export")
    pdf = bounded_read(expected_pdf, MAX_PDF_BYTES)[0]
    if not pdf.startswith(b"%PDF-") or len(pdf) < 64:
        raise ValueError("native PowerPoint output is not a bounded PDF")
    if ({path.name for path in qa_root.glob(".powerpoint-render.*")}
            != before_stages):
        raise ValueError("native PowerPoint adapter retained a new private stage")
    if (_sha(bounded_read(staged_input, 64 * 1024 * 1024)[0]) != request["candidate_pptx_sha256"]
            or prepare(root, candidate_dir) != request
            or _private_request(request_path) != canonical_request
            or _sha(bounded_read(expected_pdf, MAX_PDF_BYTES)[0]) != _sha(pdf)):
        raise ValueError("native render inputs or output changed during verification")
    if any(_sha(bounded_read(path, MAX_SOURCE_BYTES)[0]) != source_hashes[key] for key, path in (
        ("adapter_sha256", adapter), ("stager_sha256", stager),
        ("coordinator_sha256", coordinator),
    )):
        raise ValueError("native render source changed during execution")
    if _sha(bounded_read(python, MAX_PYTHON_BYTES)[0]) != python_sha256:
        raise ValueError("native Python changed during execution")
    return {
        "schema": "solosentry.pptx.v5-native-render/v1",
        "status": "Native adapter verified; measurement and acceptance pending",
        "candidate_manifest_sha256": request["candidate_manifest_sha256"],
        "candidate_pptx_sha256": request["candidate_pptx_sha256"],
        "measurement_request_sha256": request_sha256,
        "native_pdf_sha256": _sha(pdf),
        "native_pdf_file": expected_pdf.name,
        "adapter_reported_slide_count": request["slide_count"],
        "platform": "darwin",
        "exact_document_closed": True,
        "native_python_sha256": python_sha256,
        "human_acceptance": "Pending",
        **source_hashes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--request-sha256", required=True)
    parser.add_argument("--qa-input", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = Path(os.path.abspath(os.fspath(args.output)))
        parent = _canonical_directory(output.parent)
        if (parent.stat().st_mode & 0o777) != 0o700:
            raise ValueError("native provenance output requires a private POSIX directory")
        if output.exists() or output.is_symlink():
            raise ValueError("native provenance output already exists")
        receipt = capture(args.root, args.candidate_dir, args.request, args.qa_input,
                          args.python, request_sha256=args.request_sha256)
        raw = (json.dumps(receipt, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True) + "\n").encode("ascii")
        with open_exclusive_write(output, mode=0o400) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        print(f"PENDING: native adapter provenance {output}; sha256={_sha(raw)}")
        return 0
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        print(f"ERROR: native provenance rejected ({type(exc).__name__})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
