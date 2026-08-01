#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build a deterministic ZIP containing exactly the validated skill package."""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

from build_release_manifest import _read_regular
from validate_skill_package import MANIFEST_NAME, validate_package
from portable_fs import bounded_read


def create_archive(source: Path, output: Path) -> None:
    source = source.resolve(strict=True)
    manifest = validate_package(source)
    parent = output.parent.resolve(strict=True)
    temporary = parent / f".{output.name}.{os.getpid()}.tmp"
    try:
        with zipfile.ZipFile(temporary, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            paths = [str(entry["path"]) for entry in manifest["files"]] + [MANIFEST_NAME]
            for relative in sorted(paths):
                data = _read_regular(source / relative, 16 * 1024 * 1024)
                info = zipfile.ZipInfo(f"{source.name}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100600 << 16
                info.create_system = 3
                archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        descriptor = os.open(temporary, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
        os.link(temporary, parent / output.name)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        create_archive(args.source, args.output)
        print(f"PASS: created release archive {args.output}")
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
