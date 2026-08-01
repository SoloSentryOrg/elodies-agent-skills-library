#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


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

    def test_external_non_hyperlink_relationship_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "external.docx")
            with zipfile.ZipFile(path, "w") as package:
                package.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>',
                )
                package.writestr(
                    "word/_rels/document.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate" '
                    'Target="https://example.invalid/template.dotm" TargetMode="External"/>'
                    "</Relationships>",
                )
                package.writestr(
                    "docProps/core.xml",
                    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                    'xmlns:dc="http://purl.org/dc/elements/1.1/"/>',
                )
                package.writestr(
                    "[Content_Types].xml",
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
                )
            result = MODULE.validate_report(path)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("external non-hyperlink relationship" in failure for failure in result.failures)
        )

    def test_external_target_mode_is_normalized_and_unknown_mode_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename, target_mode, expected in (
                ("normalized.docx", " ExTeRnAl ", "public HTTPS"),
                ("unknown.docx", "Remote", "invalid TargetMode"),
            ):
                path = root / filename
                with zipfile.ZipFile(path, "w") as package:
                    package.writestr(
                        "word/_rels/document.xml.rels",
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        '<Relationship Id="rId1" '
                        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                        f'Target="http://127.0.0.1/private" TargetMode="{target_mode}"/>'
                        "</Relationships>",
                    )
                with zipfile.ZipFile(path) as package:
                    failures = MODULE._validate_relationships(package)
                self.assertTrue(any(expected in failure for failure in failures), failures)

    def test_embedded_active_part_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "active.docx")
            with zipfile.ZipFile(path, "w") as package:
                package.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>',
                )
                package.writestr(
                    "word/_rels/document.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
                )
                package.writestr(
                    "docProps/core.xml",
                    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                    'xmlns:dc="http://purl.org/dc/elements/1.1/"/>',
                )
                package.writestr(
                    "[Content_Types].xml",
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
                )
                package.writestr("word/embeddings/object1.bin", b"untrusted")
            result = MODULE.validate_report(path)
        self.assertFalse(result.passed)
        self.assertTrue(any("active or embedded" in failure for failure in result.failures))

    def test_macro_content_type_with_unusual_part_name_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "active-content-type.docx")
            with zipfile.ZipFile(path, "w") as package:
                package.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>',
                )
                package.writestr(
                    "word/_rels/document.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
                )
                package.writestr(
                    "docProps/core.xml",
                    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                    'xmlns:dc="http://purl.org/dc/elements/1.1/"/>',
                )
                package.writestr(
                    "[Content_Types].xml",
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Override PartName="/word/unusual.xml" '
                    'ContentType="application/vnd.ms-office.vbaProject"/>'
                    "</Types>",
                )
                package.writestr("word/unusual.xml", b"<inert/>")
            failures = MODULE.validate_docx_publication_safety(path)
        self.assertTrue(any("OOXML content type" in failure for failure in failures))

    def test_hyperlink_with_embedded_credentials_fails_closed(self) -> None:
        self.assertFalse(MODULE._external_target_is_safe("https://user:secret@example.com/"))
        self.assertFalse(MODULE._external_target_is_safe("https://2130706433/private"))
        self.assertFalse(MODULE._external_target_is_safe("https://0x7f000001/private"))
        self.assertFalse(MODULE._external_target_is_safe("https://017700000001/private"))

    def test_hidden_revision_and_extended_private_metadata_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "hidden-private-content.docx")
            with zipfile.ZipFile(path, "w") as package:
                package.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>',
                )
                package.writestr(
                    "word/header1.xml",
                    '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    "<w:ins><w:r><w:t>hidden revision</w:t></w:r></w:ins></w:hdr>",
                )
                package.writestr(
                    "word/_rels/document.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
                )
                package.writestr(
                    "docProps/core.xml",
                    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                    'xmlns:dc="http://purl.org/dc/elements/1.1/"/>',
                )
                package.writestr(
                    "docProps/app.xml",
                    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
                    "<Manager>Named Manager</Manager><Company>Private Company</Company>"
                    "<HyperlinkBase>file:///private/path/</HyperlinkBase></Properties>",
                )
                package.writestr(
                    "[Content_Types].xml",
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
                )
            failures = MODULE.validate_docx_publication_safety(path)
        self.assertTrue(any("header1.xml" in failure for failure in failures))
        self.assertTrue(any("Manager metadata" in failure for failure in failures))
        self.assertTrue(any("Company metadata" in failure for failure in failures))
        self.assertIn("HyperlinkBase metadata must be blank", failures)

    def test_unreviewed_custom_xml_data_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "custom-data.docx")
            with zipfile.ZipFile(path, "w") as package:
                package.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>',
                )
                package.writestr(
                    "word/_rels/document.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
                )
                package.writestr(
                    "docProps/core.xml",
                    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                    'xmlns:dc="http://purl.org/dc/elements/1.1/"/>',
                )
                package.writestr(
                    "[Content_Types].xml",
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
                )
                package.writestr(
                    "customXml/item1.xml",
                    "<private>private.person@example.invalid</private>",
                )
            failures = MODULE.validate_docx_publication_safety(path)
        self.assertIn(
            "unreviewed custom XML content is prohibited: customXml/item1.xml",
            failures,
        )

    def test_custom_xml_allowlist_is_well_formed(self) -> None:
        self.assertEqual(len(MODULE._allowed_custom_xml_digests()), 4)


if __name__ == "__main__":
    unittest.main()
