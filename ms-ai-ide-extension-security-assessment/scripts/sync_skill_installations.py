#!/usr/bin/env python3
"""Atomically synchronize a validated complete skill into personal clients."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import stat
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from build_release_manifest import COMMIT_RE, ReleaseManifestError, _read_regular, _validate_archive
from validate_skill_package import MANIFEST_NAME, PackageError, SOURCE_REF, validate_package
from portable_fs import is_link_or_reparse, require_real_directory


class SyncError(ValueError):
    """Raised when a destination cannot be updated safely."""


def _real_parent(destination: Path) -> Path:
    parent = destination.parent
    try:
        metadata = parent.lstat()
    except FileNotFoundError as exc:
        raise SyncError(f"destination parent does not exist: {parent}") from exc
    if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise SyncError(f"destination parent must be a real directory: {parent}")
    try:
        return require_real_directory(parent)
    except ValueError as exc:
        raise SyncError(str(exc)) from exc


def _copy_package(source: Path, staged: Path) -> None:
    def ignore(_: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in {"__pycache__", ".DS_Store"} or name.endswith(".pyc")
        }

    shutil.copytree(source, staged, symlinks=True, ignore=ignore)


def sync_installations(
    source: Path,
    destinations: list[Path],
    release_manifest: Path,
    release_archive: Path,
    expected_version: str,
    expected_source_commit: str,
) -> list[dict[str, str | None]]:
    try:
        source = require_real_directory(source)
    except (OSError, ValueError) as exc:
        raise SyncError("source must be a real non-symlink, non-reparse directory") from exc
    manifest = validate_package(source, expected_version)
    release = json.loads(_read_regular(release_manifest, 4 * 1024 * 1024))
    archive_bytes = _read_regular(release_archive)
    archive_digest = hashlib.sha256(archive_bytes).hexdigest()
    _validate_archive(archive_bytes, source, manifest)
    package_manifest_digest = hashlib.sha256(
        _read_regular(source / MANIFEST_NAME, 4 * 1024 * 1024)
    ).hexdigest()
    source_identity = release.get("source")
    archive_identity = release.get("archive")
    if (
        release.get("schema_version") != 1
        or release.get("skill") != manifest["skill"]
        or release.get("version") != manifest["version"]
        or not isinstance(source_identity, dict)
        or source_identity.get("repository") != manifest["source"]["repository"]
        or source_identity.get("ref") != SOURCE_REF
        or not isinstance(source_identity.get("commit"), str)
        or not COMMIT_RE.fullmatch(source_identity["commit"])
        or source_identity.get("commit") != expected_source_commit
        or release.get("package_manifest_sha256") != package_manifest_digest
        or not isinstance(archive_identity, dict)
        or archive_identity.get("file") != release_archive.name
        or archive_identity.get("size") != len(archive_bytes)
        or archive_identity.get("sha256") != archive_digest
    ):
        raise SyncError("release manifest does not bind the supplied package and archive")
    if not destinations:
        raise SyncError("at least one destination is required")
    resolved: list[Path] = []
    for candidate in destinations:
        if candidate.name != "ms-ai-ide-extension-security-assessment":
            raise SyncError(f"unexpected destination name: {candidate}")
        parent = _real_parent(candidate)
        destination = parent / candidate.name
        if destination.exists() or destination.is_symlink():
            metadata = destination.lstat()
            if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise SyncError(f"destination must be a real directory: {destination}")
        resolved.append(destination)
    if len(set(resolved)) != len(resolved):
        raise SyncError("duplicate destinations are not permitted")

    staged: list[tuple[Path, Path]] = []
    completed: list[tuple[Path, Path | None]] = []
    results: list[dict[str, str | None]] = []
    try:
        for destination in resolved:
            staging_parent = Path(
                tempfile.mkdtemp(prefix=f".{destination.name}.stage-", dir=destination.parent)
            )
            require_real_directory(staging_parent)
            staged_path = staging_parent / destination.name
            _copy_package(source, staged_path)
            validate_package(staged_path, str(manifest["version"]))
            staged.append((staged_path, staging_parent))

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        for destination, (staged_path, _) in zip(resolved, staged, strict=True):
            backup: Path | None = None
            if destination.exists():
                backup = destination.with_name(
                    f"{destination.name}.backup-{timestamp}-{secrets.token_hex(4)}"
                )
                os.replace(destination, backup)
            try:
                os.replace(staged_path, destination)
            except Exception:
                if backup is not None:
                    os.replace(backup, destination)
                raise
            completed.append((destination, backup))
            results.append(
                {
                    "destination": str(destination),
                    "backup": None if backup is None else str(backup),
                    "version": str(manifest["version"]),
                }
            )
        for destination, _ in completed:
            validate_package(destination, str(manifest["version"]))
        return results
    except Exception:
        for destination, backup in reversed(completed):
            quarantine = destination.with_name(
                f".{destination.name}.rollback-{secrets.token_hex(4)}"
            )
            if destination.exists():
                os.replace(destination, quarantine)
            if backup is not None and backup.exists():
                os.replace(backup, destination)
            # Retain the quarantined failed installation for recoverability and
            # to avoid recursively deleting a path that could have been raced.
        raise
    finally:
        for _, staging_parent in staged:
            if staging_parent.exists():
                shutil.rmtree(staging_parent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, action="append", type=Path)
    parser.add_argument("--release-manifest", required=True, type=Path)
    parser.add_argument("--release-archive", required=True, type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    args = parser.parse_args(argv)
    try:
        result = sync_installations(
            args.source,
            args.destination,
            args.release_manifest,
            args.release_archive,
            args.expected_version,
            args.expected_source_commit,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (
        OSError,
        PackageError,
        ReleaseManifestError,
        SyncError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
