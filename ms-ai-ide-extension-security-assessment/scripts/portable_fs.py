#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Cross-platform fail-closed filesystem primitives used by portable helpers."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import BinaryIO

WINDOWS_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def is_reparse(metadata: os.stat_result) -> bool:
    return bool(getattr(metadata, "st_file_attributes", 0) & WINDOWS_REPARSE_ATTRIBUTE)


def is_link_or_reparse(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or is_reparse(metadata)


def _reject_windows_lexical_reparse_ancestors(absolute: Path) -> None:
    """Reject junctions before ``resolve()`` erases their lexical identity."""

    if os.name != "nt":
        return
    cursor = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        cursor /= component
        try:
            observed = cursor.lstat()
        except FileNotFoundError:
            break
        if is_link_or_reparse(observed):
            raise ValueError(f"path component is a symlink, junction, or reparse point: {cursor}")


def require_real_directory(path: Path) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    _reject_windows_lexical_reparse_ancestors(absolute)
    metadata = absolute.lstat()
    if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"directory must not be a symlink, junction, or reparse point: {absolute}")
    resolved = absolute.resolve(strict=True)
    if os.name == "nt":
        after = absolute.lstat()
        if (
            is_link_or_reparse(after)
            or not stat.S_ISDIR(after.st_mode)
            or (metadata.st_dev, metadata.st_ino) != (after.st_dev, after.st_ino)
        ):
            raise ValueError(f"directory changed identity during validation: {absolute}")
        # Windows can expose a legitimate path through an 8.3 alias (for
        # example RUNNER~1 on GitHub-hosted runners).  Return the resolved long
        # path only after the lexical path and directory identity have both
        # been rechecked.  Subsequent handle-path comparison then distinguishes
        # harmless alias normalisation from an actual junction/rename escape.
        return resolved
    return resolved


def require_regular_file(path: Path) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    _reject_windows_lexical_reparse_ancestors(absolute)
    parent = require_real_directory(absolute.parent)
    canonical = parent / absolute.name
    metadata = canonical.lstat()
    if is_link_or_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"file must be a regular non-symlink, non-reparse file: {canonical}")
    return canonical


def _normalise_windows_handle_path(value: str) -> str:
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return os.path.normcase(os.path.normpath(value))


def _windows_descriptor(path: Path, *, write: bool, create_new: bool) -> int:
    """Open a Windows leaf with reparse traversal disabled at the handle."""

    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    access = (0x40000000 | 0x00010000) if write else 0x80000000  # GENERIC_WRITE + DELETE / GENERIC_READ
    share = 0 if write else 0x00000001 | 0x00000002 | 0x00000004
    disposition = 1 if create_new else 3  # CREATE_NEW / OPEN_EXISTING
    flags = 0x00200000 | 0x00000080  # OPEN_REPARSE_POINT | NORMAL
    invalid = wintypes.HANDLE(-1).value
    handle = create_file(str(path), access, share, None, disposition, flags, None)
    if handle == invalid:
        error = ctypes.get_last_error()
        if create_new and error in (80, 183):
            raise FileExistsError(error, os.strerror(error), str(path))
        raise OSError(error, os.strerror(error), str(path))
    try:
        get_final_path = kernel32.GetFinalPathNameByHandleW
        get_final_path.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
        get_final_path.restype = wintypes.DWORD
        required = get_final_path(handle, None, 0, 0)
        buffer = ctypes.create_unicode_buffer(required + 1)
        written = get_final_path(handle, buffer, len(buffer), 0)
        expected = _normalise_windows_handle_path(str(path))
        observed = _normalise_windows_handle_path(buffer.value) if written else ""
        if not written or observed != expected:
            if create_new:
                class FileDispositionInfo(ctypes.Structure):
                    _fields_ = [("DeleteFile", wintypes.BOOL)]

                disposition_info = FileDispositionInfo(True)
                set_information = kernel32.SetFileInformationByHandle
                set_information.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD)
                set_information.restype = wintypes.BOOL
                if not set_information(handle, 4, ctypes.byref(disposition_info), ctypes.sizeof(disposition_info)):
                    error = ctypes.get_last_error()
                    raise OSError(error, os.strerror(error))
            raise ValueError(f"opened Windows path escaped or changed its validated parent: {path}")
        descriptor_flags = getattr(os, "O_BINARY", 0) | (os.O_WRONLY if write else os.O_RDONLY)
        descriptor = msvcrt.open_osfhandle(handle, descriptor_flags)
        handle = None
        return descriptor
    except Exception:
        if handle is not None:
            kernel32.CloseHandle(handle)
        raise


def _windows_mark_descriptor_delete(descriptor: int) -> None:
    """Delete a task-created file by handle when path identity is no longer safe."""

    import ctypes
    import msvcrt
    from ctypes import wintypes

    class FileDispositionInfo(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOL)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD)
    set_information.restype = wintypes.BOOL
    disposition_info = FileDispositionInfo(True)
    if not set_information(
        msvcrt.get_osfhandle(descriptor),
        4,
        ctypes.byref(disposition_info),
        ctypes.sizeof(disposition_info),
    ):
        error = ctypes.get_last_error()
        raise OSError(error, os.strerror(error))


def open_regular_read(path: Path) -> tuple[BinaryIO, os.stat_result]:
    absolute = require_regular_file(path)
    before = absolute.lstat()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = (
        _windows_descriptor(absolute, write=False, create_new=False)
        if os.name == "nt"
        else os.open(absolute, flags)
    )
    try:
        observed = os.fstat(descriptor)
        if is_link_or_reparse(observed) or not stat.S_ISREG(observed.st_mode) or (before.st_dev, before.st_ino) != (observed.st_dev, observed.st_ino):
            raise ValueError(f"file path changed identity while opening: {absolute}")
        return os.fdopen(descriptor, "rb", closefd=True), observed
    except Exception:
        os.close(descriptor)
        raise


def open_exclusive_write(path: Path, mode: int = 0o600) -> BinaryIO:
    absolute = Path(os.path.abspath(os.fspath(path)))
    parent = require_real_directory(absolute.parent)
    parent_before = parent.lstat()
    absolute = parent / absolute.name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = (
        _windows_descriptor(absolute, write=True, create_new=True)
        if os.name == "nt"
        else os.open(absolute, flags, mode)
    )
    observed: os.stat_result | None = None
    try:
        observed = os.fstat(descriptor)
        parent_after = require_real_directory(absolute.parent).lstat()
        if (
            is_link_or_reparse(observed)
            or not stat.S_ISREG(observed.st_mode)
            or (parent_before.st_dev, parent_before.st_ino) != (parent_after.st_dev, parent_after.st_ino)
        ):
            raise ValueError(f"exclusive output or its parent changed identity: {absolute}")
        return os.fdopen(descriptor, "wb", closefd=True)
    except Exception:
        cleanup_error: Exception | None = None
        if os.name == "nt":
            try:
                _windows_mark_descriptor_delete(descriptor)
            except Exception as exc:
                cleanup_error = exc
        os.close(descriptor)
        try:
            current = absolute.lstat()
            if (
                observed is not None
                and not is_link_or_reparse(current)
                and stat.S_ISREG(current.st_mode)
                and (current.st_dev, current.st_ino) == (observed.st_dev, observed.st_ino)
            ):
                absolute.unlink()
        except OSError:
            pass
        if cleanup_error is not None:
            raise RuntimeError("failed to delete task-owned Windows output by handle") from cleanup_error
        raise


def bounded_read(path: Path, maximum: int) -> tuple[bytes, os.stat_result]:
    stream, before = open_regular_read(path)
    with stream:
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    if len(data) > maximum:
        raise ValueError(f"file exceeds {maximum} bytes: {path}")
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ) or len(data) != before.st_size:
        raise ValueError(f"file changed while being read: {path}")
    return data, after
