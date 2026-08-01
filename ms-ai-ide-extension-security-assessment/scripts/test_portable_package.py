from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from build_release_archive import create_archive
from build_release_manifest import (
    ReleaseManifestError,
    _create_release_manifest_payload,
    _validate_archive,
)
from sync_skill_installations import SyncError, _real_parent, sync_installations
from validate_skill_package import PackageError, package_files, validate_package


ROOT = Path(__file__).resolve().parents[1]


class PortablePackageTests(unittest.TestCase):
    def release_evidence(self, parent: Path) -> tuple[Path, Path]:
        archive = parent / "assessment-skill-1.4.2.zip"
        create_archive(ROOT, archive)
        release_manifest = parent / "release-manifest.json"
        payload = _create_release_manifest_payload(ROOT, archive, "a" * 40)
        release_manifest.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return archive, release_manifest

    def test_real_package_validates(self) -> None:
        manifest = validate_package(ROOT, "1.4.2")
        self.assertEqual(manifest["version"], "1.4.2")
        paths = [entry["path"] for entry in manifest["files"]]
        self.assertEqual(paths, sorted(paths, key=lambda item: (item.casefold(), item)))

    def test_complete_package_sync_is_atomic_and_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            destination = parent / ROOT.name
            destination.mkdir()
            (destination / "prior.txt").write_text("prior\n", encoding="utf-8")
            archive, release_manifest = self.release_evidence(parent)
            result = sync_installations(
                ROOT,
                [destination],
                release_manifest,
                archive,
                "1.4.2",
                "a" * 40,
            )
            self.assertEqual(len(result), 1)
            self.assertTrue((destination / "SKILL.md").is_file())
            backup = Path(str(result[0]["backup"]))
            self.assertEqual((backup / "prior.txt").read_text(encoding="utf-8"), "prior\n")
            validate_package(destination, "1.4.2")
            environment = {
                key: value
                for key, value in os.environ.items()
                if key not in {"PYTHONPATH", "PYTHONHOME"}
            }
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            clean_room = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    str(destination / "scripts"),
                    "-p",
                    "test_build_assessment_docx.py",
                ],
                cwd=parent,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
            self.assertEqual(clean_room.returncode, 0, clean_room.stderr)

    def test_sync_rejects_wrong_destination_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, release_manifest = self.release_evidence(root)
            with self.assertRaisesRegex(SyncError, "unexpected destination name"):
                sync_installations(
                    ROOT,
                    [root / "wrong"],
                    release_manifest,
                    archive,
                    "1.4.2",
                    "a" * 40,
                )

    def test_release_archive_rejects_size_mismatch_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, _ = self.release_evidence(root)
            with zipfile.ZipFile(archive) as source:
                members = [(entry, source.read(entry)) for entry in source.infolist() if not entry.is_dir()]
            first, first_data = members[0]
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as modified:
                for entry, data in members:
                    modified.writestr(entry.filename, data + (b"x" if entry.filename == first.filename else b""))
            package = validate_package(ROOT, "1.4.2")
            with self.assertRaisesRegex(ReleaseManifestError, "size differs"):
                _validate_archive(buffer.getvalue(), ROOT, package)

    def test_validator_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / ROOT.name
            copy.mkdir()
            for required in ("SKILL.md", "agents/openai.yaml"):
                target = copy / required
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("placeholder\n", encoding="utf-8")
            (copy / "escape").symlink_to(ROOT / "SKILL.md")
            with self.assertRaisesRegex(PackageError, "symlink"):
                package_files(copy)

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics")
    def test_sync_rejects_junction_destination_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            junction = root / "junction"
            created = subprocess.run(
                ["cmd", "/d", "/c", "mklink", "/J", str(junction), str(target)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(created.returncode, 0, created.stderr or created.stdout)
            with self.assertRaisesRegex(SyncError, "reparse|junction"):
                _real_parent(junction / ROOT.name)


if __name__ == "__main__":
    unittest.main()
