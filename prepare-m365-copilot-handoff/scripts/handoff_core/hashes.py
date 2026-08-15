"""Bounded hashing helpers."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, maximum_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    before = path.lstat()
    is_reparse = bool(getattr(before, "st_file_attributes", 0) & 0x400)
    if stat.S_ISLNK(before.st_mode) or is_reparse or not stat.S_ISREG(before.st_mode):
        raise ValueError(f"file must be a regular non-link: {path.name}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb", closefd=True) as stream:
        observed = os.fstat(stream.fileno())
        if not stat.S_ISREG(observed.st_mode) or (before.st_dev, before.st_ino) != (observed.st_dev, observed.st_ino):
            raise ValueError(f"file changed identity while opening: {path.name}")
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > maximum_bytes:
                raise ValueError(f"file exceeds {maximum_bytes} byte limit: {path.name}")
            digest.update(chunk)
    return digest.hexdigest(), total
