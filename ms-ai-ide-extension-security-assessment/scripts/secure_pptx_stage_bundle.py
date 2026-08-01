#!/usr/bin/env python3
"""Read PowerPoint build inputs through descriptor-relative, no-follow paths."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

from safe_stage_inputs import _read_bounded_regular_file_at, _secure_directory_flags
from portable_fs import is_link_or_reparse, require_real_directory


MAX_STAGE_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_DOCX_BYTES = 128 * 1024 * 1024


def _direct_child(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty filename")
    path = Path(value)
    if path.is_absolute() or len(path.parts) != 1 or path.parts[0] in (".", ".."):
        raise ValueError(f"{field} must be a direct child of the stage root")
    return value


def _read_absolute_regular_file(path: Path, maximum_bytes: int) -> bytes:
    absolute = path.absolute()
    if not absolute.is_absolute() or not absolute.parts:
        raise ValueError("authoritative input must be an absolute path")
    if os.name == "nt":
        _, data = _read_bounded_regular_file_at(
            -1,
            require_real_directory(Path(absolute.anchor)),
            str(Path(*absolute.parts[1:])),
            maximum_bytes,
        )
        return data
    root_descriptor = os.open(Path(absolute.anchor), _secure_directory_flags())
    try:
        relative = str(Path(*absolute.parts[1:]))
        _, data = _read_bounded_regular_file_at(
            root_descriptor,
            Path(absolute.anchor),
            relative,
            maximum_bytes,
        )
        return data
    finally:
        os.close(root_descriptor)


def _encoded(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _canonical_sha256(value: object) -> str:
    data = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def build_bundle(
    stage_root: Path,
    authoritative_docx: Path | None,
    authoritative_build_manifest: Path | None,
    word_qa_record: Path | None,
) -> dict[str, object]:
    root = stage_root.absolute()
    if os.name == "nt":
        root = require_real_directory(root)
        root_descriptor = -1
    else:
        root_descriptor = os.open(root, _secure_directory_flags())
    try:
        _, manifest_bytes = _read_bounded_regular_file_at(
            root_descriptor,
            root,
            "stage-manifest.json",
            MAX_MANIFEST_BYTES,
        )
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("stage manifest is invalid UTF-8 JSON") from exc
        if not isinstance(manifest, dict):
            raise ValueError("stage manifest must be a JSON object")
        stages = manifest.get("stages")
        if not isinstance(stages, list) or len(stages) != 15:
            raise ValueError("stage manifest must contain exactly fifteen stages")

        stage_records: list[dict[str, object]] = []
        names = {"stage-manifest.json"}
        for index, entry in enumerate(stages):
            if not isinstance(entry, dict):
                raise ValueError(f"stage {index + 1} entry must be an object")
            filename = _direct_child(entry.get("file"), f"stage {index + 1} file")
            if filename in names:
                raise ValueError(f"duplicate stage input filename: {filename}")
            names.add(filename)
            _, data = _read_bounded_regular_file_at(
                root_descriptor,
                root,
                filename,
                MAX_STAGE_BYTES,
            )
            try:
                content = data.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ValueError(f"stage {index + 1} is not UTF-8 text") from exc
            stage_records.append(
                {
                    "file": filename,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "analyst_validated": "Analyst validation status: Validated" in content,
                }
            )

        encoded_inputs: dict[str, str] = {}
        for key, limit in (("claims", MAX_MANIFEST_BYTES), ("report_model", MAX_STAGE_BYTES)):
            entry = manifest.get(key)
            if not isinstance(entry, dict):
                raise ValueError(f"stage manifest {key} entry must be an object")
            filename = _direct_child(entry.get("file"), f"stage manifest {key} file")
            if filename in names:
                raise ValueError(f"duplicate stage input filename: {filename}")
            names.add(filename)
            _, data = _read_bounded_regular_file_at(root_descriptor, root, filename, limit)
            encoded_inputs[key] = _encoded(data)
    finally:
        if root_descriptor >= 0:
            os.close(root_descriptor)

    result: dict[str, object] = {
        "schema_version": 1,
        "stage_root": str(root),
        "manifest": _encoded(manifest_bytes),
        "stages": stage_records,
        **encoded_inputs,
    }
    authoritative = (
        authoritative_docx,
        authoritative_build_manifest,
        word_qa_record,
    )
    if any(item is not None for item in authoritative):
        if any(item is None for item in authoritative):
            raise ValueError("all authoritative Word inputs must be supplied together")
        assert authoritative_docx is not None
        assert authoritative_build_manifest is not None
        assert word_qa_record is not None
        docx_bytes = _read_absolute_regular_file(authoritative_docx, MAX_DOCX_BYTES)
        build_bytes = _read_absolute_regular_file(
            authoritative_build_manifest, MAX_MANIFEST_BYTES
        )
        qa_bytes = _read_absolute_regular_file(word_qa_record, MAX_MANIFEST_BYTES)
        try:
            qa_payload = json.loads(qa_bytes.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("authoritative Word QA record is invalid UTF-8 JSON") from exc
        if not isinstance(qa_payload, dict) or not isinstance(
            qa_payload.get("word"), dict
        ):
            raise ValueError("authoritative Word QA record must contain a word object")
        result["authoritative_word"] = {
            "docx_path": str(authoritative_docx.absolute()),
            "docx_sha256": hashlib.sha256(docx_bytes).hexdigest(),
            "build_manifest_path": str(authoritative_build_manifest.absolute()),
            "build_manifest_sha256": hashlib.sha256(build_bytes).hexdigest(),
            "build_manifest": _encoded(build_bytes),
            "qa_record_path": str(word_qa_record.absolute()),
            "word_subrecord_sha256": _canonical_sha256(qa_payload["word"]),
            "qa_record": _encoded(qa_bytes),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--stage-root", required=True, type=Path)
    parser.add_argument("--authoritative-docx", type=Path)
    parser.add_argument("--authoritative-build-manifest", type=Path)
    parser.add_argument("--word-qa-record", type=Path)
    args = parser.parse_args()
    workspace_root = args.workspace_root.absolute()
    metadata = workspace_root.lstat()
    if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("workspace root must be a real directory")
    workspace_root = workspace_root.resolve(strict=True)
    bounded: dict[str, Path | None] = {}
    for field, value, label in (
        ("stage_root", args.stage_root, "stage root"),
        ("authoritative_docx", args.authoritative_docx, "authoritative DOCX"),
        (
            "authoritative_build_manifest",
            args.authoritative_build_manifest,
            "authoritative build manifest",
        ),
        ("word_qa_record", args.word_qa_record, "Word QA record"),
    ):
        if value is None:
            bounded[field] = None
            continue
        absolute = value.absolute()
        metadata = absolute.lstat()
        if is_link_or_reparse(metadata):
            raise ValueError(f"{label} must not be a symlink")
        resolved = absolute.resolve(strict=True)
        try:
            resolved.relative_to(workspace_root)
        except ValueError as exc:
            raise ValueError(f"{label} must remain inside the workspace root") from exc
        bounded[field] = resolved
    payload = build_bundle(
        bounded["stage_root"],
        bounded["authoritative_docx"],
        bounded["authoritative_build_manifest"],
        bounded["word_qa_record"],
    )
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"secure_pptx_stage_bundle: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
