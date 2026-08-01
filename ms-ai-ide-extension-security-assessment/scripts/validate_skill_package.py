#!/usr/bin/env python3
"""Validate or manifest the complete portable assessment-skill package."""

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

VERSION_RE = re.compile(r'^  version: "(?P<version>\d+\.\d+\.\d+)"$', re.MULTILINE)
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_NAMES = {".env"}
IGNORED_GENERATED_NAMES = {".DS_Store", "__pycache__"}
REQUIRED_PATHS = {
    "SKILL.md",
    "agents/openai.yaml",
    "references/portable-execution.md",
    "scripts/build_assessment_docx.py",
    "scripts/build_assessment_pptx.mjs",
    "scripts/build_release_archive.py",
    "scripts/create_artifact_runtime_receipt.mjs",
    "scripts/create_pptx_montage.py",
    "scripts/allowed-docx-custom-xml.json",
    "scripts/build_release_manifest.py",
    "scripts/create_word_qa_contact_sheets.py",
    "scripts/inspect_vsix.py",
    "scripts/portable_fs.py",
    "scripts/initialize_stage_bundle.py",
    "scripts/finalize_office_qa.py",
    "scripts/render_presentations_with_powerpoint.applescript",
    "scripts/render_presentations_with_powerpoint.ps1",
    "scripts/render_reports_with_word.applescript",
    "scripts/render_reports_with_word.ps1",
    "scripts/requirements.lock",
    "scripts/requirements.in",
    "scripts/runtime-requirements.json",
    "scripts/safe_stage_inputs.py",
    "scripts/secure_pptx_stage_bundle.py",
    "scripts/stage_office_artifact.py",
    "scripts/sync_skill_installations.py",
    "scripts/test_build_assessment_docx.py",
    "scripts/test_build_assessment_pptx.py",
    "scripts/test_create_word_qa_contact_sheets.py",
    "scripts/test_inspect_vsix.py",
    "scripts/test_portable_package.py",
    "scripts/test_portable_fs.py",
    "scripts/test_portable_security_contracts.py",
    "scripts/test_validate_assessment_layout.py",
    "scripts/test_validate_assessment_report.py",
    "scripts/validate_assessment_layout.py",
    "scripts/validate_assessment_pptx.py",
    "scripts/validate_assessment_report.py",
    "scripts/validate_pptx_runtime_acceptance.py",
    "scripts/validate_skill_package.py",
    "schemas/report-model.schema.json",
    "schemas/stage-manifest.schema.json",
    "schemas/validated-claims.schema.json",
    "pptx-runtime-acceptance.json",
}
MANIFEST_NAME = "package-manifest.json"
SOURCE_REPOSITORY = "https://github.com/SoloSentryOrg/elodies-agent-skills-library"
SOURCE_REF = "ms-ai-ide-extension-security-assessment-v1.4.1"
MAX_FILE_BYTES = 16 * 1024 * 1024


class PackageError(ValueError):
    """Raised when the distributed package violates its contract."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(bounded_read(path, MAX_FILE_BYTES)[0]).hexdigest()


def package_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in IGNORED_GENERATED_NAMES for part in relative.parts) or path.suffix == ".pyc":
            continue
        if path.name in FORBIDDEN_NAMES or path.suffix == ".pyc":
            raise PackageError(f"forbidden package path: {relative}")
        metadata = path.lstat()
        if is_link_or_reparse(metadata):
            raise PackageError(f"symlink is not permitted: {relative}")
        if path.is_dir():
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise PackageError(f"non-regular package entry: {relative}")
        if metadata.st_size > MAX_FILE_BYTES:
            raise PackageError(f"oversized package file: {relative}")
        if relative.as_posix() != MANIFEST_NAME:
            files.append(path)
    files.sort(
        key=lambda item: (
            item.relative_to(root).as_posix().casefold(),
            item.relative_to(root).as_posix(),
        )
    )
    return files


def _version(root: Path) -> str:
    text = (root / "SKILL.md").read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    if match is None:
        raise PackageError("SKILL.md lacks a quoted semantic metadata.version")
    return match.group("version")


def build_manifest(root: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "skill": "ms-ai-ide-extension-security-assessment",
        "version": _version(root),
        "source": {"repository": SOURCE_REPOSITORY, "ref": SOURCE_REF},
        "files": [
            {
                "path": path.relative_to(root).as_posix(),
                "size": len(bounded_read(path, MAX_FILE_BYTES)[0]),
                "sha256": _sha256(path),
            }
            for path in package_files(root)
        ],
    }


def _validate_links(root: Path, files: list[Path]) -> None:
    for path in files:
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        for target in LINK_RE.findall(text):
            if target.startswith(("https://", "http://", "mailto:", "#")):
                continue
            clean = target.split("#", 1)[0]
            if not clean:
                continue
            destination = (path.parent / clean).resolve()
            try:
                destination.relative_to(root)
            except ValueError as exc:
                raise PackageError(f"link escapes package: {path.name}: {target}") from exc
            if not destination.is_file():
                raise PackageError(f"broken local link: {path.name}: {target}")


def validate_package(
    root: Path,
    expected_version: str | None = None,
    *,
    require_manifest: bool = True,
) -> dict[str, object]:
    absolute = Path(os.path.abspath(os.fspath(root)))
    metadata = absolute.lstat()
    if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise PackageError("package root must be a real directory")
    root = absolute.resolve(strict=True)
    missing = sorted(path for path in REQUIRED_PATHS if not (root / path).is_file())
    if missing:
        raise PackageError(f"missing required package files: {', '.join(missing)}")
    version = _version(root)
    if expected_version is not None and version != expected_version:
        raise PackageError(f"expected version {expected_version}, found {version}")
    files = package_files(root)
    _validate_links(root, files)
    prohibited = (
        "SoloSentryOrg/" + "VS-VSC-MCP-SecurityAssessments",
        "/Users/" + "elodiemirza/",
    )
    for path in files:
        if path.suffix.lower() not in {".md", ".py", ".json", ".yaml", ".yml", ".mjs", ".applescript", ".ps1", ".lock", ".in"}:
            continue
        text = path.read_text(encoding="utf-8", errors="strict")
        for marker in prohibited:
            if marker in text:
                raise PackageError(f"private or local path marker in {path.relative_to(root)}")
    expected = build_manifest(root)
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        if require_manifest:
            raise PackageError("package manifest is required")
    elif require_manifest:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest != expected:
            raise PackageError("package manifest does not match package contents")
    return expected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expected-version")
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    try:
        manifest = validate_package(
            root,
            args.expected_version,
            require_manifest=not args.write_manifest,
        )
        if args.write_manifest:
            path = root / MANIFEST_NAME
            temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            try:
                with open_exclusive_write(temporary) as stream:
                    stream.write((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
                os.replace(temporary, path)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
            validate_package(root, args.expected_version)
        print(f"PASS: portable skill package {manifest['version']} is valid")
        return 0
    except (OSError, PackageError, json.JSONDecodeError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
