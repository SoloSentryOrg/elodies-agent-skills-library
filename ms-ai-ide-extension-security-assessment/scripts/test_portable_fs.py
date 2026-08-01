#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Cross-platform regression tests for portable filesystem primitives."""

from __future__ import annotations

import tempfile
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import portable_fs
from portable_fs import bounded_read, open_exclusive_write, require_real_directory


class PortableFilesystemTests(unittest.TestCase):
    def test_identity_bound_read_and_exclusive_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = require_real_directory(Path(directory))
            output = root / "output.bin"
            with open_exclusive_write(output) as stream:
                stream.write(b"portable")
            data, metadata = bounded_read(output, 64)
            self.assertEqual(data, b"portable")
            self.assertEqual(metadata.st_size, 8)
            with self.assertRaises(FileExistsError):
                open_exclusive_write(output)

    def test_bounded_read_rejects_oversize(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.bin"
            path.write_bytes(b"12345")
            with self.assertRaisesRegex(ValueError, "exceeds"):
                bounded_read(path, 4)

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics")
    def test_windows_junction_ancestors_are_rejected_for_read_and_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            child = target / "child"
            child.mkdir(parents=True)
            (child / "input.bin").write_bytes(b"untrusted")
            junction = root / "junction"
            created = subprocess.run(
                ["cmd", "/d", "/c", "mklink", "/J", str(junction), str(target)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(created.returncode, 0, created.stderr or created.stdout)
            with self.assertRaisesRegex(ValueError, "reparse|junction"):
                require_real_directory(junction / "child")
            with self.assertRaisesRegex(ValueError, "reparse|junction"):
                bounded_read(junction / "child" / "input.bin", 64)
            with self.assertRaisesRegex(ValueError, "reparse|junction"):
                open_exclusive_write(junction / "child" / "output.bin")

    @unittest.skipUnless(os.name == "nt", "Windows junction race semantics")
    def test_windows_parent_swap_to_junction_is_detected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            safe = root / "safe"
            safe.mkdir()
            moved = root / "moved"
            outside = root / "outside"
            outside.mkdir()
            real_open = portable_fs._windows_descriptor

            def race_parent(path: Path, *, write: bool, create_new: bool) -> int:
                safe.rename(moved)
                created = subprocess.run(
                    ["cmd", "/d", "/c", "mklink", "/J", str(safe), str(outside)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(created.returncode, 0, created.stderr or created.stdout)
                return real_open(path, write=write, create_new=create_new)

            with (
                mock.patch("portable_fs._windows_descriptor", side_effect=race_parent),
                self.assertRaisesRegex(ValueError, "escaped|changed"),
            ):
                open_exclusive_write(safe / "output.bin")
            self.assertFalse((outside / "output.bin").exists())

    @unittest.skipUnless(os.name == "nt", "Windows directory-resolution race semantics")
    def test_windows_parent_swap_during_directory_resolution_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            safe = root / "safe"
            safe.mkdir()
            moved = root / "moved"
            outside = root / "outside"
            outside.mkdir()
            real_resolve = Path.resolve
            raced = False

            def race_resolve(candidate: Path, strict: bool = False) -> Path:
                nonlocal raced
                if not raced and candidate == safe:
                    raced = True
                    safe.rename(moved)
                    created = subprocess.run(
                        ["cmd", "/d", "/c", "mklink", "/J", str(safe), str(outside)],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(created.returncode, 0, created.stderr or created.stdout)
                return real_resolve(candidate, strict=strict)

            with (
                mock.patch.object(Path, "resolve", autospec=True, side_effect=race_resolve),
                self.assertRaisesRegex(ValueError, "resolved outside|changed identity"),
            ):
                require_real_directory(safe)

    @unittest.skipUnless(os.name == "nt", "Windows open-handle rename semantics")
    def test_windows_open_output_blocks_parent_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            safe = root / "safe"
            safe.mkdir()
            safe = require_real_directory(safe)
            moved = root / "moved"
            output = safe / "output.bin"
            descriptor = portable_fs._windows_descriptor(
                output,
                write=True,
                create_new=True,
            )
            try:
                with self.assertRaises(PermissionError):
                    safe.rename(moved)
            finally:
                os.close(descriptor)
                output.unlink()
            self.assertTrue(safe.is_dir())
            self.assertFalse(moved.exists())

    @unittest.skipUnless(os.name == "nt", "Windows post-open cleanup semantics")
    def test_windows_post_open_validation_deletes_by_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            safe = root / "safe"
            safe.mkdir()
            output = safe / "output.bin"
            real_validate = portable_fs.require_real_directory
            validation_count = 0

            def fail_post_open_validation(path: Path) -> Path:
                nonlocal validation_count
                validation_count += 1
                if validation_count == 2:
                    raise ValueError("simulated parent identity failure")
                return real_validate(path)

            with (
                mock.patch(
                    "portable_fs.require_real_directory",
                    side_effect=fail_post_open_validation,
                ),
                mock.patch(
                    "portable_fs._windows_mark_descriptor_delete",
                    wraps=portable_fs._windows_mark_descriptor_delete,
                ) as delete_by_handle,
                self.assertRaisesRegex(ValueError, "identity failure"),
            ):
                open_exclusive_write(output)
            delete_by_handle.assert_called_once()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
