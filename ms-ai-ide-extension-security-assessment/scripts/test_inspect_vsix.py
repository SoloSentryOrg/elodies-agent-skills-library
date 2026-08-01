from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import portable_fs  # noqa: E402
from inspect_vsix import (  # noqa: E402
    VsixError,
    _write_inventory_exclusive,
    extract_vsix,
    inspect_vsix,
    main,
)


class VsixInspectionTests(unittest.TestCase):
    def _fixture(self, root: Path, extra: tuple[str, bytes] | None = None) -> Path:
        path = root / "fixture.vsix"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
            package.writestr("extension/package.json", '{"name":"fixture","version":"1.0.0"}')
            package.writestr("extension/index.js", "console.log('static fixture')")
            if extra:
                package.writestr(extra[0], extra[1])
        return path

    def test_inventory_and_safe_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            result, entries = inspect_vsix(path)
            output = root / "out"
            extract_vsix(path, output, entries, str(result["archive_sha256"]))
            self.assertEqual(result["entry_count"], 2)
            self.assertTrue((output / "extension/package.json").is_file())
            self.assertTrue(result["files"][1]["executable_or_script"])

    def test_accepts_visual_studio_vsix_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "visual-studio.vsix"
            manifest = b'''<?xml version="1.0" encoding="utf-8"?>
            <PackageManifest xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
              <Metadata><Identity Id="example.visualstudio" Version="1.2.3" Publisher="Example"/><DisplayName>Example extension</DisplayName><Description>Fixture</Description></Metadata>
              <Installation><InstallationTarget Id="Microsoft.VisualStudio.Community" Version="[17.0,18.0)"/></Installation>
              <Assets><Asset Type="Microsoft.VisualStudio.VsPackage" Path="payload.pkgdef"/></Assets>
            </PackageManifest>'''
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
                package.writestr("extension.vsixmanifest", manifest)
                package.writestr("payload.pkgdef", b"fixture")
            result, _ = inspect_vsix(path)
            self.assertEqual(result["manifest_kind"], "visual-studio")
            self.assertIsNone(result["package_manifest"])
            self.assertEqual(result["visual_studio_manifest"]["identity"]["Id"], "example.visualstudio")

    def test_rejects_archive_changed_after_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            result, entries = inspect_vsix(path)
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
                package.writestr("extension/package.json", '{"name":"fixture","version":"1.0.1"}')
                package.writestr("extension/index.js", "changed")
            with self.assertRaisesRegex(VsixError, "changed"):
                extract_vsix(path, root / "out", entries, str(result["archive_sha256"]))

    def test_rejects_traversal_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root, ("../escape.txt", b"unsafe"))
            with self.assertRaisesRegex(VsixError, "unsafe VSIX member"):
                inspect_vsix(path)
            self.assertFalse((root / "escape.txt").exists())

    def test_rejects_symlink_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            link = root / "linked.vsix"
            link.symlink_to(path)
            with self.assertRaisesRegex(VsixError, "non-symlink"):
                inspect_vsix(link)

    def test_rejects_path_replaced_between_lstat_and_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            original = root / "original.vsix"
            replacement = root / "replacement.vsix"
            with zipfile.ZipFile(replacement, "w", zipfile.ZIP_DEFLATED) as package:
                package.writestr("extension/package.json", '{"name":"replacement","version":"2.0.0"}')
            real_open = os.open
            real_windows_open = portable_fs._windows_descriptor
            raced = False

            def replace_before_open(
                target: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                nonlocal raced
                if not raced and Path(target) == path.resolve() and flags & os.O_ACCMODE == os.O_RDONLY:
                    raced = True
                    path.rename(original)
                    replacement.rename(path)
                return real_open(target, flags, *args, **kwargs)

            def replace_before_windows_open(
                target: Path, *, write: bool, create_new: bool
            ) -> int:
                nonlocal raced
                if not raced and target == path.resolve() and not write:
                    raced = True
                    path.rename(original)
                    replacement.rename(path)
                return real_windows_open(target, write=write, create_new=create_new)

            patcher = (
                mock.patch("portable_fs._windows_descriptor", side_effect=replace_before_windows_open)
                if os.name == "nt"
                else mock.patch("inspect_vsix.os.open", side_effect=replace_before_open)
            )
            with patcher, self.assertRaisesRegex(VsixError, "path changed"):
                inspect_vsix(path)

    def test_archive_descriptor_survives_path_swap_after_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            original = root / "opened-original.vsix"
            replacement = root / "replacement.vsix"
            with zipfile.ZipFile(replacement, "w", zipfile.ZIP_DEFLATED) as package:
                package.writestr("extension/package.json", '{"name":"replacement","version":"2.0.0"}')
            real_open = os.open
            real_windows_open = portable_fs._windows_descriptor
            raced = False

            def replace_after_open(
                target: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                nonlocal raced
                descriptor = real_open(target, flags, *args, **kwargs)
                if not raced and Path(target) == path.resolve() and flags & os.O_ACCMODE == os.O_RDONLY:
                    raced = True
                    path.rename(original)
                    replacement.rename(path)
                return descriptor

            def replace_after_windows_open(
                target: Path, *, write: bool, create_new: bool
            ) -> int:
                nonlocal raced
                descriptor = real_windows_open(target, write=write, create_new=create_new)
                if not raced and target == path.resolve() and not write:
                    raced = True
                    path.rename(original)
                    replacement.rename(path)
                return descriptor

            patcher = (
                mock.patch("portable_fs._windows_descriptor", side_effect=replace_after_windows_open)
                if os.name == "nt"
                else mock.patch("inspect_vsix.os.open", side_effect=replace_after_open)
            )
            with patcher:
                result, _ = inspect_vsix(path)
            self.assertEqual(result["package_manifest"]["name"], "fixture")

    def test_extraction_descriptor_survives_path_swap_after_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            result, entries = inspect_vsix(path)
            original = root / "opened-original.vsix"
            replacement = root / "replacement.vsix"
            with zipfile.ZipFile(replacement, "w", zipfile.ZIP_DEFLATED) as package:
                package.writestr("extension/package.json", '{"name":"replacement","version":"2.0.0"}')
            real_open = os.open
            real_windows_open = portable_fs._windows_descriptor
            raced = False

            def replace_after_open(
                target: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                nonlocal raced
                descriptor = real_open(target, flags, *args, **kwargs)
                if not raced and Path(target) == path.resolve() and flags & os.O_ACCMODE == os.O_RDONLY:
                    raced = True
                    path.rename(original)
                    replacement.rename(path)
                return descriptor

            def replace_after_windows_open(
                target: Path, *, write: bool, create_new: bool
            ) -> int:
                nonlocal raced
                descriptor = real_windows_open(target, write=write, create_new=create_new)
                if not raced and target == path.resolve() and not write:
                    raced = True
                    path.rename(original)
                    replacement.rename(path)
                return descriptor

            output = root / "out"
            patcher = (
                mock.patch("portable_fs._windows_descriptor", side_effect=replace_after_windows_open)
                if os.name == "nt"
                else mock.patch("inspect_vsix.os.open", side_effect=replace_after_open)
            )
            with patcher:
                extract_vsix(path, output, entries, str(result["archive_sha256"]))
            self.assertIn('"name":"fixture"', (output / "extension/package.json").read_text())

    def test_rejects_extracted_member_digest_mismatch_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            result, entries = inspect_vsix(path)
            entry, member, _ = entries[0]
            entries[0] = (entry, member, "0" * 64)
            output = root / "out"
            with self.assertRaisesRegex(VsixError, "member digest mismatch"):
                extract_vsix(path, output, entries, str(result["archive_sha256"]))
            self.assertFalse(output.exists())

    def test_inventory_write_is_exclusive_and_preserves_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "inventory.json"
            output.write_text("keep\n", encoding="utf-8")
            with self.assertRaisesRegex(VsixError, "must not already exist"):
                _write_inventory_exclusive(output, "replace\n")
            self.assertEqual(output.read_text(encoding="utf-8"), "keep\n")

    def test_inventory_write_rejects_symlink_and_preserves_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text("keep\n", encoding="utf-8")
            output = root / "inventory.json"
            output.symlink_to(target)
            with self.assertRaisesRegex(VsixError, "must not already exist"):
                _write_inventory_exclusive(output, "replace\n")
            self.assertTrue(output.is_symlink())
            self.assertEqual(target.read_text(encoding="utf-8"), "keep\n")

    def test_cli_does_not_resolve_symlink_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            link = root / "linked.vsix"
            link.symlink_to(path)
            inventory = root / "inventory.json"
            with self.assertRaisesRegex(VsixError, "non-symlink"):
                main(
                    [
                        "--workspace-root",
                        str(root),
                        str(link),
                        "--inventory",
                        str(inventory),
                    ]
                )
            self.assertFalse(inventory.exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics")
    def test_windows_junction_rejected_for_archive_and_extraction_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            path = self._fixture(target)
            junction = root / "junction"
            created = subprocess.run(
                ["cmd", "/d", "/c", "mklink", "/J", str(junction), str(target)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(created.returncode, 0, created.stderr or created.stdout)
            with self.assertRaisesRegex(VsixError, "reparse|non-symlink"):
                inspect_vsix(junction / path.name)
            result, entries = inspect_vsix(path)
            with self.assertRaisesRegex((VsixError, ValueError), "reparse|junction"):
                extract_vsix(path, junction / "out", entries, str(result["archive_sha256"]))


if __name__ == "__main__":
    unittest.main()
