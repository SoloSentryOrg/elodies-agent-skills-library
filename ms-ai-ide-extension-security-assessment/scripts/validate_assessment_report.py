#!/usr/bin/env python3
"""Fail-closed structural validation for authoritative assessment DOCX files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC = "http://purl.org/dc/elements/1.1/"

NS = {"w": W, "r": R, "pr": PR, "cp": CP, "dc": DC}
WORD_RE = re.compile(r"\b[\w'-]+\b", re.UNICODE)
REF_RE = re.compile(r"\bREF-(\d{3})\b")
FINDING_RE = re.compile(r"\b(?:F|HT|TF|RISK)-\d{3}\b", re.IGNORECASE)

MIN_WORDS = 4_000
MIN_HEADINGS = 40
MIN_TABLES = 15
MIN_IMAGES = 1
MIN_REFERENCES = 12
MIN_INTERNAL_REFERENCE_LINKS = 12
MIN_EXTERNAL_LINKS = 12
MAX_PACKAGE_BYTES = 50 * 1024 * 1024
MAX_PACKAGE_ENTRIES = 2_000
MAX_ENTRY_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1_000

REQUIRED_HEADING_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("document control", ("document control",)),
    ("revision history", ("revision history",)),
    ("contents", ("contents", "table of contents")),
    ("executive summary", ("executive summary",)),
    ("purpose and function overview", ("purpose function overview",)),
    ("scope and methodology", ("scope assumptions methodology",)),
    ("product identity and version", ("product identity version", "product identity and version")),
    ("VS Code part", ("part i vs code", "vs code assessment")),
    ("Visual Studio part", ("part ii visual studio", "visual studio assessment")),
    ("installed Agent Skills part", ("part iii installed agent skills", "installed agent skills")),
    ("cross-IDE comparison", ("cross ide comparison",)),
    ("consolidated supply chain", ("consolidated supply chain",)),
    ("consolidated privacy", ("consolidated privacy", "privacy data protection assessment")),
    ("enterprise controls roadmap", ("enterprise controls roadmap",)),
    ("detection and monitoring plan", ("detection opportunities monitoring plan", "detection opportunities and monitoring plan", "detection monitoring plan")),
    ("consolidated risk register", ("consolidated risk register",)),
    ("residual risk and approval", ("residual risk approval recommendation", "residual risk and approval recommendation")),
    ("limitations and confidence", ("limitations confidence", "limitations and confidence", "limitations and confidence levels")),
    ("evidence register", ("evidence register",)),
    ("references", ("references",)),
    ("appendices", ("appendices", "appendix")),
    ("glossary", ("glossary",)),
)

IDE_REQUIRED_CONCEPTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("decision", ("decision", "approval")),
    ("purpose", ("purpose", "function")),
    ("architecture", ("architecture",)),
    ("trust boundaries", ("trust boundary", "trust boundaries")),
    ("data flows", ("data flow", "data flows")),
    ("installation and uninstall", ("installation manifest", "uninstall")),
    ("runtime and activation", ("runtime", "activation")),
    ("network", ("network",)),
    ("authentication", ("authentication",)),
    ("telemetry", ("telemetry",)),
    ("privacy", ("privacy",)),
    ("MCP and Agent Skills", ("mcp", "agent skill")),
    ("supply chain", ("supply chain", "dependencies")),
    ("threats and findings", ("threat", "finding")),
    ("framework disposition", ("framework", "owasp")),
    ("controls and detection", ("control", "detection")),
    ("residual risk", ("residual risk",)),
    ("confidence", ("confidence",)),
    ("limitations", ("limitation",)),
    ("evidence", ("evidence",)),
    ("verification", ("verification",)),
)


@dataclass(frozen=True)
class Paragraph:
    style: str
    text: str


@dataclass(frozen=True)
class ReportMetrics:
    sha256: str
    words: int
    headings: int
    tables: int
    images: int
    reference_bookmarks: int
    internal_reference_links: int
    external_links: int
    findings: int
    executive_bullets: int
    has_header: bool
    has_footer: bool
    has_page_field: bool


@dataclass(frozen=True)
class ValidationResult:
    report: str
    passed: bool
    metrics: ReportMetrics | None
    failures: tuple[str, ...]


class InvalidDocumentError(ValueError):
    """Raised when the input is not a readable Word DOCX package."""


def normalize(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _read_xml(package: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        return ET.fromstring(package.read(name))
    except KeyError as exc:
        raise InvalidDocumentError(f"missing required DOCX part: {name}") from exc
    except ET.ParseError as exc:
        raise InvalidDocumentError(f"invalid XML in DOCX part: {name}") from exc


def _validate_package_bounds(
    path: Path,
    package: zipfile.ZipFile,
) -> tuple[str, ...]:
    failures: list[str] = []
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        failures.append(f"DOCX package exceeds {MAX_PACKAGE_BYTES} bytes")
    entries = package.infolist()
    if len(entries) > MAX_PACKAGE_ENTRIES:
        failures.append(f"DOCX package has more than {MAX_PACKAGE_ENTRIES} entries")
    names = [entry.filename for entry in entries]
    if len(names) != len(set(names)):
        failures.append("DOCX package contains duplicate entry names")
    total = 0
    for entry in entries:
        total += entry.file_size
        if entry.file_size > MAX_ENTRY_BYTES:
            failures.append(
                f"DOCX part exceeds {MAX_ENTRY_BYTES} bytes: {entry.filename}"
            )
        if entry.compress_size == 0:
            ratio = float("inf") if entry.file_size else 1
        else:
            ratio = entry.file_size / entry.compress_size
        if ratio > MAX_COMPRESSION_RATIO:
            failures.append(
                "DOCX part compression ratio exceeds "
                f"{MAX_COMPRESSION_RATIO}: {entry.filename}"
            )
    if total > MAX_UNCOMPRESSED_BYTES:
        failures.append(
            f"DOCX uncompressed content exceeds {MAX_UNCOMPRESSED_BYTES} bytes"
        )
    return tuple(sorted(set(failures)))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _element_text(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{{{W}}}t"))


def _paragraphs(document: ET.Element) -> list[Paragraph]:
    output: list[Paragraph] = []
    for paragraph in document.iter(f"{{{W}}}p"):
        style_node = paragraph.find(f"./{{{W}}}pPr/{{{W}}}pStyle")
        style = style_node.get(f"{{{W}}}val", "") if style_node is not None else ""
        output.append(Paragraph(style=style, text=_element_text(paragraph).strip()))
    return output


def _first_heading_index(paragraphs: list[Paragraph], alternatives: Iterable[str]) -> int | None:
    normalized = tuple(normalize(item) for item in alternatives)
    for index, paragraph in enumerate(paragraphs):
        if not paragraph.style.casefold().startswith("heading"):
            continue
        text = normalize(paragraph.text)
        if any(candidate in text for candidate in normalized):
            return index
    return None


def _part_text(paragraphs: list[Paragraph], start_terms: tuple[str, ...], end_terms: tuple[str, ...]) -> str:
    start = _first_heading_index(paragraphs, start_terms)
    if start is None:
        return ""
    end = _first_heading_index(paragraphs[start + 1 :], end_terms)
    end_index = len(paragraphs) if end is None else start + 1 + end
    return normalize(" ".join(item.text for item in paragraphs[start:end_index]))


def _missing_concepts(part_text: str) -> list[str]:
    out_of_scope = any(marker in part_text[:500] for marker in ("out of scope", "not applicable", "unsupported"))
    if out_of_scope:
        required_status = ("decision", "evidence", "limitation", "verification")
        return [item for item in required_status if item not in part_text]
    missing: list[str] = []
    for label, alternatives in IDE_REQUIRED_CONCEPTS:
        if not any(normalize(item) in part_text for item in alternatives):
            missing.append(label)
    return missing


def _core_property(root: ET.Element, namespace: str, local_name: str) -> str:
    node = root.find(f"{{{namespace}}}{local_name}")
    return (node.text or "").strip() if node is not None else ""


def _metadata_is_generic(value: str) -> bool:
    if not value:
        return True
    normalized = normalize(value)
    allowed = (
        "solosentry",
        "solosentry assessment environment",
        "assessment automation",
        "security assessment automation",
    )
    return normalized in allowed


def validate_report(path: Path) -> ValidationResult:
    failures: list[str] = []
    if path.suffix.casefold() != ".docx" or not path.is_file():
        return ValidationResult(str(path), False, None, ("input must be an existing .docx file",))
    if path.is_symlink():
        return ValidationResult(str(path), False, None, ("DOCX symlinks are prohibited",))
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        return ValidationResult(
            str(path),
            False,
            None,
            (f"DOCX package exceeds {MAX_PACKAGE_BYTES} bytes",),
        )

    digest = _sha256(path)
    try:
        with zipfile.ZipFile(path) as package:
            bounds_failures = _validate_package_bounds(path, package)
            if bounds_failures:
                return ValidationResult(str(path), False, None, bounds_failures)
            document = _read_xml(package, "word/document.xml")
            relationships = _read_xml(package, "word/_rels/document.xml.rels")
            core = _read_xml(package, "docProps/core.xml")
            names = set(package.namelist())
            paragraphs = _paragraphs(document)
            headings = [item for item in paragraphs if item.style.casefold().startswith("heading") and item.text]
            heading_text = [normalize(item.text) for item in headings]
            full_text = " ".join(
                (node.text or "").strip()
                for node in document.iter(f"{{{W}}}t")
                if (node.text or "").strip()
            )
            normalized_text = normalize(full_text)

            tables = len(list(document.iter(f"{{{W}}}tbl")))
            images = len([name for name in names if name.startswith("word/media/") and not name.endswith("/")])
            bookmarks = {
                node.get(f"{{{W}}}name", "")
                for node in document.iter(f"{{{W}}}bookmarkStart")
                if node.get(f"{{{W}}}name", "").startswith("REF_")
            }
            linked_refs: list[str] = []
            for link in document.iter(f"{{{W}}}hyperlink"):
                anchor = link.get(f"{{{W}}}anchor", "")
                if anchor.startswith("REF_") and REF_RE.search(_element_text(link)):
                    linked_refs.append(anchor)

            external_links = 0
            for relation in relationships:
                relation_type = relation.get("Type", "")
                if relation_type.endswith("/hyperlink") and relation.get("TargetMode") == "External":
                    external_links += 1

            has_header = any(name.startswith("word/header") and name.endswith(".xml") for name in names)
            has_footer = any(name.startswith("word/footer") and name.endswith(".xml") for name in names)
            field_text: list[str] = []
            for name in names:
                if name.startswith("word/") and name.endswith(".xml"):
                    try:
                        root = ET.fromstring(package.read(name))
                    except ET.ParseError:
                        continue
                    field_text.extend(node.text or "" for node in root.iter(f"{{{W}}}instrText"))
            has_page_field = any(re.search(r"\bPAGE\b", item, re.IGNORECASE) for item in field_text)

            executive_start = _first_heading_index(paragraphs, ("executive summary",))
            executive_bullets = 0
            if executive_start is not None:
                for paragraph in paragraphs[executive_start + 1 :]:
                    if paragraph.style.casefold().startswith("heading1"):
                        break
                    if "listbullet" in paragraph.style.casefold() and paragraph.text:
                        executive_bullets += 1

            metrics = ReportMetrics(
                sha256=digest,
                words=len(WORD_RE.findall(full_text)),
                headings=len(headings),
                tables=tables,
                images=images,
                reference_bookmarks=len(bookmarks),
                internal_reference_links=len(linked_refs),
                external_links=external_links,
                findings=len({match.group(0).casefold() for match in FINDING_RE.finditer(full_text)}),
                executive_bullets=executive_bullets,
                has_header=has_header,
                has_footer=has_footer,
                has_page_field=has_page_field,
            )

            floors = (
                (metrics.words >= MIN_WORDS, f"word count {metrics.words} is below {MIN_WORDS}"),
                (metrics.headings >= MIN_HEADINGS, f"heading count {metrics.headings} is below {MIN_HEADINGS}"),
                (metrics.tables >= MIN_TABLES, f"table count {metrics.tables} is below {MIN_TABLES}"),
                (metrics.images >= MIN_IMAGES, "at least one figure or diagram is required"),
                (metrics.reference_bookmarks >= MIN_REFERENCES, f"reference bookmark count {metrics.reference_bookmarks} is below {MIN_REFERENCES}"),
                (metrics.internal_reference_links >= MIN_INTERNAL_REFERENCE_LINKS, f"internal REF link count {metrics.internal_reference_links} is below {MIN_INTERNAL_REFERENCE_LINKS}"),
                (metrics.external_links >= MIN_EXTERNAL_LINKS, f"external reference link count {metrics.external_links} is below {MIN_EXTERNAL_LINKS}"),
                (metrics.findings >= 1, "at least one finding or explicit risk record is required"),
                (metrics.executive_bullets >= 5, f"executive outcome bullet count {metrics.executive_bullets} is below 5"),
                (metrics.has_header, "document header is required"),
                (metrics.has_footer, "document footer is required"),
                (metrics.has_page_field, "PAGE field is required in the DOCX package"),
            )
            failures.extend(message for passed, message in floors if not passed)

            for label, alternatives in REQUIRED_HEADING_GROUPS:
                normalized_alternatives = tuple(normalize(item) for item in alternatives)
                if not any(any(candidate in heading for candidate in normalized_alternatives) for heading in heading_text):
                    failures.append(f"missing required heading: {label}")

            vscode = _part_text(paragraphs, ("part i vs code", "vs code assessment"), ("part ii visual studio", "visual studio assessment"))
            visual_studio = _part_text(paragraphs, ("part ii visual studio", "visual studio assessment"), ("part iii installed agent skills",))
            for label, part in (("VS Code", vscode), ("Visual Studio", visual_studio)):
                if not part:
                    failures.append(f"missing {label} self-contained assessment block")
                    continue
                missing = _missing_concepts(part)
                if missing:
                    failures.append(f"{label} block missing concepts: {', '.join(missing)}")

            if len(bookmarks) != len(list(node for node in document.iter(f"{{{W}}}bookmarkStart") if node.get(f"{{{W}}}name", "").startswith("REF_"))):
                failures.append("duplicate REF bookmark names detected")
            missing_targets = sorted(set(linked_refs) - bookmarks)
            if missing_targets:
                failures.append(f"internal REF links target missing bookmarks: {', '.join(missing_targets)}")

            required_concepts = (
                ("static analysis", ("static analysis", "static artefact inspection", "static package inspection")),
                ("malware", ("malware",)),
                ("runtime", ("runtime",)),
                ("privacy", ("privacy",)),
                ("verified", ("verified",)),
                ("inferred", ("inferred",)),
                ("not observed", ("not observed",)),
                ("not applicable", ("not applicable",)),
                ("unknown", ("unknown",)),
                ("verification test", ("verification test", "host verification", "verification procedure")),
                ("target date", ("target date", "0 30 days", "31 90 days", "milestone")),
                ("control strength", ("control strength",)),
                ("confidence", ("confidence",)),
            )
            for label, alternatives in required_concepts:
                if not any(normalize(item) in normalized_text for item in alternatives):
                    failures.append(f"missing required assessment concept: {label}")

            for legend_phrase in ("1 4 low", "5 9 moderate", "10 16 high", "17 25 critical", "residual", "treatment", "owner"):
                if normalize(legend_phrase) not in normalized_text:
                    failures.append(f"risk-register legend is missing: {legend_phrase}")

            creator = _core_property(core, DC, "creator")
            last_modified_by = _core_property(core, CP, "lastModifiedBy")
            if not _metadata_is_generic(creator):
                failures.append("creator metadata must be blank or a generic assessment identity")
            if not _metadata_is_generic(last_modified_by):
                failures.append("lastModifiedBy metadata must be blank or a generic assessment identity")

    except (zipfile.BadZipFile, InvalidDocumentError) as exc:
        return ValidationResult(str(path), False, None, (str(exc),))

    return ValidationResult(str(path), not failures, metrics, tuple(sorted(set(failures))))


def _print_human(result: ValidationResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    print(f"{status}: {result.report}")
    if result.metrics is not None:
        for key, value in asdict(result.metrics).items():
            print(f"  {key}: {value}")
    for failure in result.failures:
        print(f"  ERROR: {failure}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    results = [validate_report(path) for path in args.reports]
    if args.as_json:
        print(json.dumps([asdict(item) for item in results], indent=2))
    else:
        for result in results:
            _print_human(result)
    return 0 if all(item.passed for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
