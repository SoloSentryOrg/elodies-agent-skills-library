#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create a digest-bound native Office QA record and immutable closeout manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

from portable_fs import bounded_read, is_link_or_reparse, open_exclusive_write

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _read(path: Path, maximum: int = 2 * 1024 * 1024) -> bytes:
    return bounded_read(path, maximum)[0]


def _write(path: Path, payload: object) -> bytes:
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    with open_exclusive_write(path) as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return data


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--build-manifest", required=True, type=Path)
    parser.add_argument("--qa-record", required=True, type=Path)
    parser.add_argument("--closeout-manifest", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--input-sha256", required=True)
    parser.add_argument("--application", required=True, choices=("word", "powerpoint"))
    parser.add_argument("--page-count", type=int)
    parser.add_argument("--slide-count", type=int)
    parser.add_argument("--every-page-inspected", action="store_true")
    parser.add_argument("--every-slide-inspected", action="store_true")
    parser.add_argument("--contents-starts-on-fresh-page", action="store_true")
    parser.add_argument("--accessibility-passed", action="store_true")
    parser.add_argument("--privacy-passed", action="store_true")
    args = parser.parse_args(argv)
    try:
        workspace_metadata = args.workspace_root.absolute().lstat()
        if is_link_or_reparse(workspace_metadata) or not stat.S_ISDIR(workspace_metadata.st_mode):
            raise ValueError("workspace root must be a real directory")
        workspace_root = args.workspace_root.resolve(strict=True)
        bounded_paths = (args.build_manifest, args.qa_record, args.closeout_manifest, args.input)
        for value in bounded_paths:
            candidate = value.absolute()
            resolved = (candidate.resolve(strict=True) if candidate.exists() else candidate.parent.resolve(strict=True) / candidate.name)
            try:
                resolved.relative_to(workspace_root)
            except ValueError as exc:
                raise ValueError(f"path must remain inside workspace root: {value}") from exc
        if not SHA256_RE.fullmatch(args.input_sha256):
            raise ValueError("input SHA-256 is invalid")
        input_data = _read(args.input, 256 * 1024 * 1024)
        if _sha(input_data) != args.input_sha256:
            raise ValueError("Office QA input digest mismatch")
        build_data = _read(args.build_manifest)
        build = json.loads(build_data.decode("utf-8", errors="strict"))
        if not isinstance(build, dict) or not build.get("assessment") or not build.get("run_key"):
            raise ValueError("build manifest identity is incomplete")
        build_output = build.get("output")
        input_relative = args.input.resolve(strict=True).relative_to(workspace_root).as_posix()
        if isinstance(build_output, str):
            declared_file = build_output
            declared_sha256 = build.get("output_sha256")
        elif isinstance(build_output, dict):
            declared_file = build_output.get("file")
            declared_sha256 = build_output.get("sha256")
        else:
            raise ValueError("build manifest output binding is incomplete")
        expected_file = input_relative if isinstance(build_output, str) else args.input.name
        if declared_file != expected_file or declared_sha256 != args.input_sha256:
            raise ValueError("Office QA input does not match the build manifest output binding")
        if not args.accessibility_passed or not args.privacy_passed:
            raise ValueError("accessibility and privacy checks must both pass")
        if args.application == "word":
            if not args.every_page_inspected or not args.contents_starts_on_fresh_page or not args.page_count or args.page_count < 1:
                raise ValueError("Word closeout requires every-page inspection, a fresh-page contents result, and page count")
            subrecord = {"input_file": args.input.name, "input_sha256": args.input_sha256, "page_count": args.page_count, "contents_starts_on_fresh_page": True, "every_page_inspected": True, "accessibility_passed": True, "privacy_passed": True, "result": "Passed"}
        else:
            if not args.every_slide_inspected or not args.slide_count or args.slide_count < 1:
                raise ValueError("PowerPoint closeout requires every-slide inspection and slide count")
            subrecord = {"input_file": args.input.name, "input_sha256": args.input_sha256, "slide_count": args.slide_count, "every_slide_inspected": True, "accessibility_passed": True, "privacy_passed": True, "result": "Passed"}
        qa = {"schema_version": 1, "assessment": build.get("target", build["assessment"]), "run_key": build["run_key"], "status": "Passed", args.application: subrecord}
        qa_data = _write(args.qa_record, qa)
        closeout = dict(build)
        closeout_key = f"native_{args.application}_closeout"
        qa_resolved = args.qa_record.absolute().parent.resolve(strict=True) / args.qa_record.name
        qa_relative = qa_resolved.relative_to(workspace_root).as_posix()
        closeout[closeout_key] = {"status": "Passed", "qa_record": qa_relative, "qa_record_sha256": _sha(qa_data), f"{args.application}_subrecord_sha256": _sha(json.dumps(subrecord, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode())}
        _write(args.closeout_manifest, closeout)
        print(f"PASS: {args.application} QA closeout created")
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
