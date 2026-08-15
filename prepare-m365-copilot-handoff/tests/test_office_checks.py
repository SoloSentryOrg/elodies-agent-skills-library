from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from handoff_core.office_checks import validate_word_package


CONTENT_TYPES = b'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
</Types>'''


def styles(locale: str) -> bytes:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults><w:rPrDefault><w:rPr><w:lang w:val="{locale}" w:eastAsia="{locale}" w:bidi="{locale}"/></w:rPr></w:rPrDefault></w:docDefaults>
  <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:lang w:val="{locale}" w:eastAsia="{locale}" w:bidi="{locale}"/></w:rPr></w:style>
</w:styles>'''.encode()


def document(locale: str | None, field_instruction: str | None = None, *, complex_field: bool = False) -> bytes:
    language = "" if locale is None else f'<w:rPr><w:lang w:val="{locale}" w:eastAsia="{locale}" w:bidi="{locale}"/></w:rPr>'
    if field_instruction is None:
        field = ""
    elif complex_field:
        midpoint = len(field_instruction) // 2
        field = f'<w:r><w:instrText>{field_instruction[:midpoint]}</w:instrText></w:r><w:r><w:instrText>{field_instruction[midpoint:]}</w:instrText></w:r>'
    else:
        field = f'<w:fldSimple w:instr="{field_instruction}"/>'
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r>{language}<w:t>Synthetic</w:t></w:r>{field}</w:p></w:body></w:document>'''.encode()


def settings(locale: str) -> bytes:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:themeFontLang w:val="{locale}"/></w:settings>'''.encode()


def relationships(external: bool, active_x: bool = False) -> bytes:
    item = '<Relationship Id="rId1" Type="http://example.invalid/type" Target="https://example.invalid" TargetMode="External"/>' if external else ""
    if active_x:
        item += '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/control" Target="activeX/activeX1.xml"/>'
    return f'''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{item}</Relationships>'''.encode()


class WordPackageGateTests(unittest.TestCase):
    def make_package(self, locale: str, run_locale: str | None, *, external: bool = False, macro: bool = False, field_instruction: str | None = None, complex_field: bool = False, header_instruction: str | None = None, compression_bomb: bool = False, active_x: bool = False, active_content_type: bool = False) -> Path:
        self.counter += 1
        path = Path(self.temp.name) / f"fixture-{self.counter}.docx"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
            content_types = CONTENT_TYPES
            if active_content_type:
                content_types = content_types.replace(
                    b"</Types>",
                    b'<Override PartName="/word/document.xml" ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/></Types>',
                )
            package.writestr("[Content_Types].xml", content_types)
            package.writestr("word/document.xml", document(run_locale, field_instruction, complex_field=complex_field))
            package.writestr("word/styles.xml", styles(locale))
            package.writestr("word/settings.xml", settings(locale))
            package.writestr("word/_rels/document.xml.rels", relationships(external, active_x))
            if active_x:
                package.writestr("word/activeX/activeX1.xml", b'<ax:ocx xmlns:ax="urn:synthetic"/>')
            if header_instruction is not None:
                package.writestr("word/header1.xml", document("en-GB", header_instruction))
            if compression_bomb:
                package.writestr("word/highly-compressed.xml", b"0" * (1024 * 1024))
            if macro:
                package.writestr("word/vbaProject.bin", b"synthetic")
        return path

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.counter = 0

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_explicit_en_gb_defaults_styles_and_runs_pass(self) -> None:
        self.assertEqual(validate_word_package(self.make_package("en-GB", "en-GB")), [])

    def test_en_us_missing_run_language_macro_and_external_relationship_fail(self) -> None:
        scenarios = [
            self.make_package("en-US", "en-US"),
            self.make_package("en-GB", None),
            self.make_package("en-GB", "en-GB", macro=True),
            self.make_package("en-GB", "en-GB", external=True),
        ]
        expected = ["HND008", "HND008", "HND005", "HND005"]
        for path, code in zip(scenarios, expected):
            self.assertIn(code, {item.code for item in validate_word_package(path)})

    def test_simple_and_split_complex_dde_fields_fail_closed(self) -> None:
        simple = self.make_package("en-GB", "en-GB", field_instruction="DDEAUTO synthetic test")
        complex_field = self.make_package(
            "en-GB", "en-GB", field_instruction="DDE synthetic test", complex_field=True
        )
        for path in (simple, complex_field):
            self.assertIn("HND005", {item.code for item in validate_word_package(path)})

    def test_non_dde_field_remains_accepted(self) -> None:
        package = self.make_package("en-GB", "en-GB", field_instruction="PAGE")
        self.assertEqual(validate_word_package(package), [])

    def test_dde_in_header_story_fails_closed(self) -> None:
        package = self.make_package("en-GB", "en-GB", header_instruction="DDEAUTO synthetic test")
        self.assertIn("HND005", {item.code for item in validate_word_package(package)})

    def test_zip_ratio_failure_aborts_before_member_reads(self) -> None:
        package = self.make_package("en-GB", "en-GB", compression_bomb=True)
        from unittest import mock

        with mock.patch("zipfile.ZipFile.read", side_effect=AssertionError("member reads must not begin")):
            errors = validate_word_package(package)
        self.assertIn("HND013", {item.code for item in errors})

    def test_activex_parts_relationships_and_active_content_types_fail_closed(self) -> None:
        scenarios = [
            self.make_package("en-GB", "en-GB", active_x=True),
            self.make_package("en-GB", "en-GB", active_content_type=True),
        ]
        for package in scenarios:
            self.assertIn("HND005", {item.code for item in validate_word_package(package)})


if __name__ == "__main__":
    unittest.main()
