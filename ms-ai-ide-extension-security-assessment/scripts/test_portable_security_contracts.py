#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Regression tests for portable staging, schema initialization, and Office QA."""

from __future__ import annotations

import hashlib
import json
import copy
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from finalize_office_qa import main as finalize_main  # noqa: E402
from initialize_stage_bundle import initialize  # noqa: E402
from build_assessment_docx import ModelError, validate_report_model  # noqa: E402
from safe_stage_inputs import _validated_claims  # noqa: E402
from stage_office_artifact import stage  # noqa: E402
from stage_office_artifact import _validate_docx  # noqa: E402
from validate_assessment_pptx import PptxValidationError, _public_https, validate_pptx  # noqa: E402


def _docx(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("word/document.xml", "<document/>")
        package.writestr("docProps/core.xml", '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>Security Assessment Automation</dc:creator><cp:lastModifiedBy>Security Assessment Automation</cp:lastModifiedBy></cp:coreProperties>')


def _pptx(path: Path, *, forbidden: bool = False, active_relationship: bool = False) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("ppt/presentation.xml", "<presentation/>")
        package.writestr("ppt/slides/slide1.xml", "<slide/>")
        package.writestr("ppt/notesSlides/notesSlide1.xml", "<notes/>")
        if forbidden:
            package.writestr("ppt/embeddings/object1.bin", b"active")
        if active_relationship:
            package.writestr(
                "ppt/slides/_rels/slide1.xml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject" Target="../media/object.bin"/></Relationships>',
            )


def _pptx_external_relationship(path: Path, target_mode: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("ppt/presentation.xml", "<presentation/>")
        package.writestr("ppt/slides/slide1.xml", "<slide/>")
        package.writestr("ppt/notesSlides/notesSlide1.xml", "<notes/>")
        package.writestr(
            "ppt/slides/_rels/slide1.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
            f'Target="http://127.0.0.1/private" TargetMode="{target_mode}"/>'
            "</Relationships>",
        )


class PortableSecurityContractTests(unittest.TestCase):
    def test_word_adapters_refresh_native_toc_before_render(self) -> None:
        script_root = Path(__file__).resolve().parent
        applescript = (script_root / "render_reports_with_word.applescript").read_text(encoding="utf-8")
        powershell = (script_root / "render_reports_with_word.ps1").read_text(encoding="utf-8")
        self.assertIn("update reportTOC", applescript)
        self.assertIn("update page numbers reportTOC", applescript)
        self.assertIn("$tableOfContents.Update()", powershell)
        self.assertIn("$tableOfContents.UpdatePageNumbers()", powershell)

    def test_public_https_rejects_legacy_numeric_loopback(self) -> None:
        for target in ("https://2130706433/private", "https://0x7f000001/private", "https://017700000001/private"):
            with self.subTest(target=target):
                self.assertFalse(_public_https(target))

    def test_initializer_creates_hash_bound_incomplete_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "stage-output"
            initialize(root, "Example", "Example", "1.2.3", "2026-08-01-v1.0")
            manifest = json.loads((root / "stage-manifest.json").read_text())
            self.assertEqual(len(manifest["stages"]), 15)
            self.assertEqual(manifest["status"], "Incomplete")
            for entry in manifest["stages"]:
                self.assertEqual(hashlib.sha256((root / entry["file"]).read_bytes()).hexdigest(), entry["sha256"])
            model = json.loads((root / "report-model.json").read_text())
            self.assertEqual(validate_report_model(model)["run_key"], "2026-08-01-v1.0")
            claims = json.loads((root / "validated-claims.json").read_text())
            claims["analyst_validation"] = "Validated"
            bundle = _validated_claims(manifest, claims)
            self.assertIn("assessment.placeholder", bundle.claims)

    def test_report_schema_matches_runtime_structural_contract(self) -> None:
        schema = json.loads((SCRIPTS.parent / "schemas" / "report-model.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "stage-output"
            initialize(root, "Example", "Example", "1.2.3", "2026-08-01-v1.0")
            model = json.loads((root / "report-model.json").read_text(encoding="utf-8"))
            self.assertEqual(list(validator.iter_errors(model)), [])
            self.assertEqual(validate_report_model(model)["run_key"], "2026-08-01-v1.0")
            invalid = copy.deepcopy(model)
            invalid["sections"] = [None] * 20
            self.assertTrue(list(validator.iter_errors(invalid)))
            with self.assertRaises(ModelError):
                validate_report_model(invalid)
            mismatched_table = copy.deepcopy(model)
            mismatched_table["sections"][0]["tables"] = [
                {"title": "Mismatch", "columns": ["A", "B"], "rows": [["one"]]}
            ]
            self.assertTrue(list(validator.iter_errors(mismatched_table)))
            with self.assertRaises(ModelError):
                validate_report_model(mismatched_table)

    def test_pptx_validator_rejects_embedded_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            safe = Path(directory) / "safe.pptx"
            unsafe = Path(directory) / "unsafe.pptx"
            _pptx(safe)
            _pptx(unsafe, forbidden=True)
            self.assertEqual(validate_pptx(safe)["slides"], 1)
            with self.assertRaisesRegex(PptxValidationError, "prohibited"):
                validate_pptx(unsafe)

    def test_pptx_validator_rejects_internal_active_relationship(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.pptx"
            _pptx(path, active_relationship=True)
            with self.assertRaisesRegex(PptxValidationError, "active relationship"):
                validate_pptx(path)

    def test_pptx_validator_normalizes_external_target_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.pptx"
            _pptx_external_relationship(path, " ExTeRnAl ")
            with self.assertRaisesRegex(PptxValidationError, "external relationship"):
                validate_pptx(path)

    def test_pptx_validator_rejects_unknown_target_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.pptx"
            _pptx_external_relationship(path, "Remote")
            with self.assertRaisesRegex(PptxValidationError, "invalid TargetMode"):
                validate_pptx(path)

    def test_office_stager_binds_digest_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.docx"
            output = root / "staged.docx"
            _docx(source)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            stage(source, output, digest, "docx")
            self.assertEqual(output.read_bytes(), source.read_bytes())
            with self.assertRaises(FileExistsError):
                stage(source, output, digest, "docx")

    def test_docx_stager_rejects_internal_active_relationship(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "active.docx"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
                package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/hidden.bin" ContentType="application/vnd.ms-office.vbaProject"/></Types>')
                package.writestr("word/document.xml", "<document/>")
                package.writestr("docProps/core.xml", '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>Security Assessment Automation</dc:creator><cp:lastModifiedBy>Security Assessment Automation</cp:lastModifiedBy></cp:coreProperties>')
                package.writestr("word/_rels/document.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/oleObject" Target="hidden.bin"/></Relationships>')
            with self.assertRaisesRegex(ValueError, "prohibited"):
                _validate_docx(path.read_bytes())

    def test_word_closeout_enforces_contents_page_and_privacy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.docx"
            _docx(report)
            digest = hashlib.sha256(report.read_bytes()).hexdigest()
            build = root / "report.build.json"
            build.write_text(json.dumps({"assessment": "Example", "target": "Example", "run_key": "2026-08-01-v1.0", "output": report.name, "output_sha256": digest}))
            qa_dir = root / "evidence"
            qa_dir.mkdir()
            qa = qa_dir / "office-native-qa.json"
            closeout = root / "report.closeout.json"
            common = ["--workspace-root", str(root), "--build-manifest", str(build), "--qa-record", str(qa), "--closeout-manifest", str(closeout), "--input", str(report), "--input-sha256", digest, "--application", "word", "--page-count", "3", "--every-page-inspected", "--accessibility-passed", "--privacy-passed"]
            self.assertEqual(finalize_main(common), 1)
            self.assertFalse(qa.exists())
            self.assertEqual(finalize_main([*common, "--contents-starts-on-fresh-page"]), 0)
            payload = json.loads(closeout.read_text())
            self.assertEqual(payload["native_word_closeout"]["status"], "Passed")
            self.assertEqual(payload["native_word_closeout"]["qa_record"], "evidence/office-native-qa.json")


if __name__ == "__main__":
    unittest.main()
