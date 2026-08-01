#!/usr/bin/env python3
"""Safely inventory and optionally extract a VSIX without executing its content."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from xml.etree import ElementTree

from portable_fs import (
    is_link_or_reparse,
    open_exclusive_write,
    open_regular_read,
    require_real_directory,
)

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_ENTRIES = 100_000
MAX_ENTRY_BYTES = 256 * 1024 * 1024
MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
MAX_RATIO = 1_000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
EXECUTABLE_SUFFIXES = {
    ".exe", ".dll", ".dylib", ".so", ".node", ".wasm", ".jar", ".class",
    ".ps1", ".bat", ".cmd", ".sh", ".py", ".rb", ".pl", ".js", ".mjs",
    ".cjs", ".ts",
}


class VsixError(ValueError):
    """Raised when a VSIX is unsafe or outside inspection bounds."""


def _sha256_stream(source: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _open_archive(path: Path) -> Iterator[tuple[BinaryIO, os.stat_result]]:
    """Open a path once, without following links, and bind it to its lstat."""
    try:
        source, observed = open_regular_read(path)
    except ValueError as exc:
        raise VsixError(str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        raise VsixError("VSIX could not be opened as a non-symlink, non-reparse file") from exc
    with source:
        yield source, observed


def _write_inventory_exclusive(path: Path, payload: str) -> None:
    """Create an inventory atomically without following or replacing a leaf."""
    try:
        parent = path.parent.lstat()
    except FileNotFoundError as exc:
        raise VsixError("inventory output parent must exist") from exc
    if is_link_or_reparse(parent) or not stat.S_ISDIR(parent.st_mode):
        raise VsixError("inventory output parent must be a real directory")
    try:
        stream = open_exclusive_write(path)
    except FileExistsError as exc:
        raise VsixError("inventory output must not already exist") from exc
    with stream:
        stream.write(payload.encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def _extract_vsix_windows(
    path: Path,
    destination: Path,
    validated: list[tuple[zipfile.ZipInfo, PurePosixPath, str | None]],
    expected_sha256: str,
) -> None:
    parent = require_real_directory(destination.parent)
    root = parent / destination.name
    os.mkdir(root, 0o700)
    root_identity = root.lstat()
    try:
        with _open_archive(path) as (source, archive_stat):
            if archive_stat.st_size > MAX_ARCHIVE_BYTES or _sha256_stream(source) != expected_sha256:
                raise VsixError("VSIX changed between inspection and extraction")
            source.seek(0)
            with zipfile.ZipFile(source) as package:
                observed = [(item.filename, item.CRC, item.file_size, item.compress_size) for item in package.infolist()]
                expected = [(item.filename, item.CRC, item.file_size, item.compress_size) for item, _, _ in validated]
                if observed != expected:
                    raise VsixError("VSIX member metadata changed between inspection and extraction")
                for entry, member, expected_member_sha256 in validated:
                    target = root.joinpath(*member.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    require_real_directory(target.parent)
                    if entry.is_dir():
                        target.mkdir(exist_ok=True)
                        require_real_directory(target)
                        continue
                    digest = hashlib.sha256()
                    written = 0
                    with package.open(entry) as member_source, open_exclusive_write(target) as output:
                        for chunk in iter(lambda: member_source.read(1024 * 1024), b""):
                            output.write(chunk)
                            digest.update(chunk)
                            written += len(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    if written != entry.file_size or digest.hexdigest() != expected_member_sha256:
                        raise VsixError(f"extracted VSIX member digest mismatch: {entry.filename}")
    except Exception:
        try:
            current = root.lstat()
            if not is_link_or_reparse(current) and (current.st_dev, current.st_ino) == (root_identity.st_dev, root_identity.st_ino):
                shutil.rmtree(root)
        except OSError:
            pass
        raise


def _safe_name(value: str) -> PurePosixPath:
    if "\\" in value or "\x00" in value:
        raise VsixError(f"unsafe VSIX member name: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise VsixError(f"unsafe VSIX member path: {value!r}")
    return path


def inspect_vsix(path: Path) -> tuple[dict[str, object], list[tuple[zipfile.ZipInfo, PurePosixPath, str | None]]]:
    with _open_archive(path) as (source, archive_stat):
        if archive_stat.st_size > MAX_ARCHIVE_BYTES:
            raise VsixError("VSIX exceeds archive size bound")
        archive_hash = _sha256_stream(source)
        source.seek(0)
        with zipfile.ZipFile(source) as package:
            entries = package.infolist()
            if not entries or len(entries) > MAX_ENTRIES:
                raise VsixError("VSIX entry count is empty or excessive")
            if len({entry.filename for entry in entries}) != len(entries):
                raise VsixError("VSIX contains duplicate entry names")
            expanded = 0
            validated: list[tuple[zipfile.ZipInfo, PurePosixPath, str | None]] = []
            inventory: list[dict[str, object]] = []
            package_manifest: dict[str, object] | None = None
            visual_studio_manifest: dict[str, object] | None = None
            for entry in entries:
                member = _safe_name(entry.filename.rstrip("/"))
                mode = entry.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if entry.flag_bits & 0x1:
                    raise VsixError(f"encrypted VSIX member is prohibited: {entry.filename}")
                if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise VsixError(f"symlink or special VSIX member is prohibited: {entry.filename}")
                if entry.file_size > MAX_ENTRY_BYTES:
                    raise VsixError(f"VSIX member is oversized: {entry.filename}")
                ratio = (
                    float("inf")
                    if entry.compress_size == 0 and entry.file_size
                    else entry.file_size / max(entry.compress_size, 1)
                )
                if ratio > MAX_RATIO:
                    raise VsixError(f"VSIX member expansion ratio is excessive: {entry.filename}")
                expanded += entry.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise VsixError("VSIX expanded size exceeds bound")
                if entry.is_dir():
                    validated.append((entry, member, None))
                    continue
                digest = hashlib.sha256()
                with package.open(entry) as member_source:
                    for chunk in iter(lambda: member_source.read(1024 * 1024), b""):
                        digest.update(chunk)
                member_sha256 = digest.hexdigest()
                inventory.append({
                    "path": str(member),
                    "size": entry.file_size,
                    "sha256": member_sha256,
                    "executable_or_script": member.suffix.casefold() in EXECUTABLE_SUFFIXES,
                })
                validated.append((entry, member, member_sha256))
                if str(member).casefold() == "extension/package.json":
                    if entry.file_size > MAX_MANIFEST_BYTES:
                        raise VsixError("extension/package.json is oversized")
                    try:
                        payload = json.loads(package.read(entry).decode("utf-8", errors="strict"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise VsixError("extension/package.json is invalid") from exc
                    if not isinstance(payload, dict):
                        raise VsixError("extension/package.json must be an object")
                    package_manifest = payload
                if str(member).casefold().endswith("extension.vsixmanifest"):
                    if entry.file_size > MAX_MANIFEST_BYTES:
                        raise VsixError("Visual Studio VSIX manifest is oversized")
                    manifest_data = package.read(entry)
                    if b"<!DOCTYPE" in manifest_data.upper() or b"<!ENTITY" in manifest_data.upper():
                        raise VsixError("Visual Studio VSIX manifest contains prohibited DTD content")
                    try:
                        root = ElementTree.fromstring(manifest_data)
                    except ElementTree.ParseError as exc:
                        raise VsixError("Visual Studio VSIX manifest is invalid XML") from exc
                    def local(element: ElementTree.Element) -> str:
                        return element.tag.rsplit("}", 1)[-1]
                    identity = next((item for item in root.iter() if local(item) == "Identity"), None)
                    if identity is None or not identity.attrib.get("Id") or not identity.attrib.get("Version"):
                        raise VsixError("Visual Studio VSIX manifest lacks extension identity")
                    visual_studio_manifest = {
                        "identity": dict(sorted(identity.attrib.items())),
                        "display_name": next(((item.text or "").strip() for item in root.iter() if local(item) == "DisplayName"), ""),
                        "description": next(((item.text or "").strip() for item in root.iter() if local(item) == "Description"), ""),
                        "installation_targets": [dict(sorted(item.attrib.items())) for item in root.iter() if local(item) == "InstallationTarget"],
                        "assets": [dict(sorted(item.attrib.items())) for item in root.iter() if local(item) == "Asset"],
                    }
            if package_manifest is None and visual_studio_manifest is None:
                raise VsixError("VSIX lacks a VS Code package.json or Visual Studio extension.vsixmanifest")
            result = {
                "schema_version": 1,
                "archive": path.name,
                "archive_size": archive_stat.st_size,
                "archive_sha256": archive_hash,
                "entry_count": len(entries),
                "expanded_bytes": expanded,
                "archive_anomalies": [],
                "manifest_kind": "vs-code" if package_manifest is not None else "visual-studio",
                "package_manifest": package_manifest,
                "visual_studio_manifest": visual_studio_manifest,
                "files": inventory,
            }
    return result, validated


def _open_child_directory(parent_fd: int, name: str, *, create: bool) -> int:
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise VsixError(f"unsafe extraction directory component: {name!r}") from exc
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise VsixError(f"unsafe extraction directory component: {name!r}")
    return descriptor


def _remove_owned_tree(directory_fd: int) -> None:
    """Remove entries beneath a task-owned directory without following links."""
    for name in os.listdir(directory_fd):
        observed = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(observed.st_mode):
            child_fd = _open_child_directory(directory_fd, name, create=False)
            try:
                _remove_owned_tree(child_fd)
            finally:
                os.close(child_fd)
            os.rmdir(name, dir_fd=directory_fd)
        else:
            os.unlink(name, dir_fd=directory_fd)


def extract_vsix(path: Path, destination: Path, validated: list[tuple[zipfile.ZipInfo, PurePosixPath, str | None]], expected_sha256: str) -> None:
    if os.name == "nt":
        _extract_vsix_windows(path, destination, validated, expected_sha256)
        return
    try:
        canonical_parent = destination.parent.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise VsixError("extraction destination parent must exist") from exc
    if not destination.name or destination.name in (".", ".."):
        raise VsixError("extraction destination must have a safe leaf name")
    parent_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    parent_fd = os.open(canonical_parent, parent_flags)
    destination_fd = -1
    destination_identity: tuple[int, int] | None = None
    try:
        try:
            os.mkdir(destination.name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise VsixError("extraction destination must not already exist") from exc
        destination_fd = _open_child_directory(parent_fd, destination.name, create=False)
        root_stat = os.fstat(destination_fd)
        destination_identity = (root_stat.st_dev, root_stat.st_ino)
        with _open_archive(path) as (source, archive_stat):
            if archive_stat.st_size > MAX_ARCHIVE_BYTES:
                raise VsixError("VSIX exceeds archive size bound")
            if _sha256_stream(source) != expected_sha256:
                raise VsixError("VSIX changed between inspection and extraction")
            source.seek(0)
            with zipfile.ZipFile(source) as package:
                current = package.infolist()
                expected = [
                    (item.filename, item.CRC, item.file_size, item.compress_size)
                    for item, _, _ in validated
                ]
                observed = [
                    (item.filename, item.CRC, item.file_size, item.compress_size)
                    for item in current
                ]
                if observed != expected:
                    raise VsixError("VSIX member metadata changed between inspection and extraction")
                for entry, member, expected_member_sha256 in validated:
                    current_fd = os.dup(destination_fd)
                    try:
                        for component in member.parts[:-1]:
                            next_fd = _open_child_directory(current_fd, component, create=True)
                            os.close(current_fd)
                            current_fd = next_fd
                        leaf = member.parts[-1]
                        if entry.is_dir():
                            directory_fd = _open_child_directory(current_fd, leaf, create=True)
                            os.close(directory_fd)
                            continue
                        digest = hashlib.sha256()
                        written = 0
                        output_flags = (
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL
                            | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
                        )
                        descriptor = os.open(leaf, output_flags, 0o600, dir_fd=current_fd)
                        with package.open(entry) as member_source, os.fdopen(descriptor, "wb") as target:
                            for chunk in iter(lambda: member_source.read(1024 * 1024), b""):
                                target.write(chunk)
                                digest.update(chunk)
                                written += len(chunk)
                            target.flush()
                            os.fsync(target.fileno())
                        if written != entry.file_size or digest.hexdigest() != expected_member_sha256:
                            raise VsixError(f"extracted VSIX member digest mismatch: {entry.filename}")
                    finally:
                        os.close(current_fd)
    except Exception:
        if destination_fd >= 0:
            try:
                _remove_owned_tree(destination_fd)
            except OSError:
                pass
        if destination_identity is not None:
            try:
                current = os.stat(destination.name, dir_fd=parent_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == destination_identity:
                    os.rmdir(destination.name, dir_fd=parent_fd)
            except OSError:
                pass
        raise
    finally:
        if destination_fd >= 0:
            os.close(destination_fd)
        os.close(parent_fd)


def _workspace_root(value: Path) -> Path:
    try:
        return require_real_directory(value)
    except ValueError as exc:
        raise VsixError("workspace root must be a real non-reparse directory") from exc


def _within_workspace(
    value: Path, workspace_root: Path, label: str, *, must_exist: bool
) -> Path:
    absolute = Path(os.path.abspath(os.fspath(value)))
    if must_exist:
        metadata = absolute.lstat()
        if is_link_or_reparse(metadata):
            raise VsixError(f"{label} must be a regular non-symlink path")
        resolved = absolute.resolve(strict=True)
    else:
        resolved = absolute.parent.resolve(strict=True) / absolute.name
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise VsixError(f"{label} must remain inside the workspace root") from exc
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("vsix", type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--extract", type=Path)
    args = parser.parse_args(argv)
    workspace_root = _workspace_root(args.workspace_root)
    vsix = _within_workspace(args.vsix, workspace_root, "VSIX", must_exist=True)
    inventory = _within_workspace(
        args.inventory, workspace_root, "inventory", must_exist=False
    )
    extract = (
        None
        if args.extract is None
        else _within_workspace(
            args.extract,
            workspace_root,
            "extraction destination",
            must_exist=False,
        )
    )
    result, validated = inspect_vsix(vsix)
    _write_inventory_exclusive(inventory, json.dumps(result, indent=2, sort_keys=True) + "\n")
    if extract:
        extract_vsix(vsix, extract, validated, str(result["archive_sha256"]))
    print(f"Inspected {result['entry_count']} entries; sha256={result['archive_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
