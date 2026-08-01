#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create immutable release evidence binding a package, archive, ref, and commit."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

from validate_skill_package import MANIFEST_NAME, SOURCE_REF, validate_package
from portable_fs import bounded_read, is_link_or_reparse, open_exclusive_write


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class ReleaseManifestError(ValueError):
    """Raised when immutable release inputs are unsafe or inconsistent."""


def _read_regular(path: Path, maximum: int = 256 * 1024 * 1024) -> bytes:
    try:
        return bounded_read(path, maximum)[0]
    except ValueError as exc:
        raise ReleaseManifestError(str(exc)) from exc


def _create_release_manifest_payload(source: Path, archive: Path, source_commit: str) -> dict[str, object]:
    if not COMMIT_RE.fullmatch(source_commit):
        raise ReleaseManifestError("source commit must be a full lowercase Git SHA")
    package = validate_package(source)
    package_manifest = _read_regular(source / MANIFEST_NAME, 4 * 1024 * 1024)
    archive_bytes = _read_regular(archive)
    _validate_archive(archive_bytes, source, package)
    return {
        "schema_version": 1,
        "skill": package["skill"],
        "version": package["version"],
        "source": {
            "repository": package["source"]["repository"],
            "ref": SOURCE_REF,
            "commit": source_commit,
        },
        "package_manifest_sha256": hashlib.sha256(package_manifest).hexdigest(),
        "archive": {
            "file": archive.name,
            "size": len(archive_bytes),
            "sha256": hashlib.sha256(archive_bytes).hexdigest(),
        },
    }


def _git(repository_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository_root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat"},
    )
    if result.returncode != 0:
        raise ReleaseManifestError(f"Git provenance check failed: {result.stderr.strip()}")
    return result.stdout.strip()


def create_release_manifest(
    source: Path,
    archive: Path,
    source_commit: str,
    repository_root: Path,
) -> dict[str, object]:
    """Bind a release only when a clean tagged Git tree produced the package."""
    if not COMMIT_RE.fullmatch(source_commit):
        raise ReleaseManifestError("source commit must be a full lowercase Git SHA")
    root_metadata = repository_root.absolute().lstat()
    if is_link_or_reparse(root_metadata) or not stat.S_ISDIR(root_metadata.st_mode):
        raise ReleaseManifestError("repository root must be a real directory")
    repository_root = repository_root.resolve(strict=True)
    source_metadata = source.absolute().lstat()
    if is_link_or_reparse(source_metadata) or not stat.S_ISDIR(source_metadata.st_mode):
        raise ReleaseManifestError("package source must be a real directory")
    source = source.resolve(strict=True)
    try:
        relative_source = source.relative_to(repository_root).as_posix()
    except ValueError as exc:
        raise ReleaseManifestError("package source must remain inside the repository") from exc
    if _git(repository_root, "rev-parse", "HEAD") != source_commit:
        raise ReleaseManifestError("source commit does not match repository HEAD")
    if _git(repository_root, "rev-parse", f"refs/tags/{SOURCE_REF}^{{commit}}") != source_commit:
        raise ReleaseManifestError("release tag does not resolve to the source commit")
    origin = _git(repository_root, "remote", "get-url", "origin").removesuffix(".git")
    if origin not in (
        "https://github.com/SoloSentryOrg/elodies-agent-skills-library",
        "git@github.com:SoloSentryOrg/elodies-agent-skills-library",
    ):
        raise ReleaseManifestError("repository origin does not match the package source identity")
    if _git(repository_root, "status", "--porcelain=v1", "--untracked-files=all", "--", relative_source):
        raise ReleaseManifestError("package source has tracked or untracked changes")
    package = validate_package(source)
    expected = {
        f"{relative_source}/{entry['path']}" for entry in package["files"]
    } | {f"{relative_source}/{MANIFEST_NAME}"}
    tracked = set(filter(None, _git(repository_root, "ls-files", "-z", "--", relative_source).split("\0")))
    if tracked != expected:
        raise ReleaseManifestError("tagged repository files do not exactly match the package manifest")
    return _create_release_manifest_payload(source, archive, source_commit)


def _validate_archive(
    archive_bytes: bytes, source: Path, package: dict[str, object]
) -> None:
    """Require the release ZIP to contain exactly the validated package tree."""
    expected = {
        f"{source.name}/{entry['path']}": (int(entry["size"]), str(entry["sha256"]))
        for entry in package["files"]
    }
    manifest_bytes = _read_regular(source / MANIFEST_NAME, 4 * 1024 * 1024)
    expected[f"{source.name}/{MANIFEST_NAME}"] = (
        len(manifest_bytes),
        hashlib.sha256(manifest_bytes).hexdigest(),
    )
    try:
        package_zip = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise ReleaseManifestError("release archive must be a valid ZIP") from exc
    observed: dict[str, tuple[int, str]] = {}
    with package_zip:
        entries = package_zip.infolist()
        if len(entries) > len(expected) * 3 + 16:
            raise ReleaseManifestError("release archive contains excessive entries")
        if len({entry.filename for entry in entries}) != len(entries):
            raise ReleaseManifestError("release archive contains duplicate entries")
        for entry in entries:
            if "\\" in entry.filename or "\x00" in entry.filename:
                raise ReleaseManifestError("release archive contains an unsafe path")
            member = PurePosixPath(entry.filename.rstrip("/"))
            if member.is_absolute() or any(part in ("", ".", "..") for part in member.parts):
                raise ReleaseManifestError("release archive contains an unsafe path")
            mode = entry.external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ReleaseManifestError("release archive contains a symlink or special entry")
            if entry.is_dir():
                continue
            if entry.filename not in expected:
                raise ReleaseManifestError(f"release archive contains an unexpected file: {entry.filename}")
            expected_size, expected_sha256 = expected[entry.filename]
            if entry.file_size != expected_size:
                raise ReleaseManifestError(
                    f"release archive size differs from the package manifest: {entry.filename}"
                )
            ratio = (
                float("inf")
                if entry.compress_size == 0 and entry.file_size
                else entry.file_size / max(entry.compress_size, 1)
            )
            if ratio > 1000:
                raise ReleaseManifestError(
                    f"release archive expansion ratio is excessive: {entry.filename}"
                )
            digest = hashlib.sha256()
            observed_size = 0
            with package_zip.open(entry) as member:
                while True:
                    chunk = member.read(min(1024 * 1024, expected_size - observed_size + 1))
                    if not chunk:
                        break
                    observed_size += len(chunk)
                    if observed_size > expected_size:
                        raise ReleaseManifestError(
                            f"release archive member exceeds its declared package size: {entry.filename}"
                        )
                    digest.update(chunk)
            if observed_size != expected_size or digest.hexdigest() != expected_sha256:
                raise ReleaseManifestError(
                    f"release archive member digest differs from the package manifest: {entry.filename}"
                )
            observed[entry.filename] = (observed_size, digest.hexdigest())
    if observed != expected:
        missing = sorted(set(expected) - set(observed))
        raise ReleaseManifestError(f"release archive does not exactly match the package manifest; missing={missing[:5]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        payload = create_release_manifest(
            args.source, args.archive, args.source_commit, args.repository_root
        )
        with open_exclusive_write(args.output) as stream:
            data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        print(f"PASS: release manifest binds {payload['source']['commit']}")
        return 0
    except (OSError, ReleaseManifestError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
