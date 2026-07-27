#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("validate_assessment_report.py")
SPEC = importlib.util.spec_from_file_location("assessment_validator", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AssessmentReportValidatorTests(unittest.TestCase):
    def test_normalize_handles_punctuation_and_case(self) -> None:
        self.assertEqual(MODULE.normalize("Part II — Visual Studio"), "part ii visual studio")

    def test_missing_docx_fails_closed(self) -> None:
        result = MODULE.validate_report(Path("missing.docx"))
        self.assertFalse(result.passed)
        self.assertIn("existing .docx", result.failures[0])

    def test_invalid_package_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "invalid.docx")
            path.write_bytes(b"not a zip")
            result = MODULE.validate_report(path)
        self.assertFalse(result.passed)
        self.assertIsNone(result.metrics)

    def test_missing_required_part_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "minimal.docx")
            with zipfile.ZipFile(path, "w") as package:
                package.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>',
                )
            result = MODULE.validate_report(path)
        self.assertFalse(result.passed)
        self.assertIn("missing required DOCX part", result.failures[0])

    def test_oversized_zip_part_fails_before_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "oversized.docx")
            with zipfile.ZipFile(
                path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as package:
                package.writestr("word/document.xml", b"A" * 4096)
            with mock.patch.object(MODULE, "MAX_ENTRY_BYTES", 1024):
                result = MODULE.validate_report(path)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("DOCX part exceeds" in failure for failure in result.failures)
        )

    def test_symlinked_docx_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory, "target.docx")
            target.write_bytes(b"not a zip")
            link = Path(directory, "link.docx")
            link.symlink_to(target)
            result = MODULE.validate_report(link)
        self.assertFalse(result.passed)
        self.assertIn("symlinks", result.failures[0])


if __name__ == "__main__":
    unittest.main()
