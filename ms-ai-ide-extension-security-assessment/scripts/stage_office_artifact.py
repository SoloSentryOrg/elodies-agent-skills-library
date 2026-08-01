#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Digest-bind and safely stage a passive DOCX or PPTX for native Office QA."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import stat
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from validate_assessment_pptx import PptxValidationError, _public_https, validate_pptx_bytes
from validate_assessment_report import _validate_docx_publication_safety_bytes
from portable_fs import bounded_read, is_link_or_reparse, open_exclusive_write

MAX_BYTES = 256 * 1024 * 1024


def _read_once(path: Path) -> bytes:
    return bounded_read(path, MAX_BYTES)[0]


def _validate_docx(data: bytes) -> None:
    failures = _validate_docx_publication_safety_bytes(data)
    if failures:
        raise ValueError(f"DOCX failed passive publication-safety validation: {failures[0]}")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            entries = package.infolist()
            names = set(entry.filename for entry in entries)
            if len(names) != len(entries):
                raise ValueError("DOCX contains duplicate package members")
            required = {"[Content_Types].xml", "word/document.xml"}
            if not required.issubset(names):
                raise ValueError("DOCX lacks required package parts")
            lowered = {name.casefold() for name in names}
            if any("vbaproject" in name or "/activex/" in f"/{name}" or "/embeddings/" in f"/{name}" for name in lowered):
                raise ValueError("DOCX contains prohibited active or embedded content")
            content_types_data = package.read("[Content_Types].xml")
            if b"<!DOCTYPE" in content_types_data.upper() or b"<!ENTITY" in content_types_data.upper():
                raise ValueError("DOCX content types contain prohibited DTD content")
            content_types = ElementTree.fromstring(content_types_data)
            for item in content_types.iter():
                value = item.attrib.get("ContentType", "").casefold()
                extension = item.attrib.get("Extension", "").casefold()
                if any(marker in value for marker in ("macroenabled", "vbaproject", "activex", "oleobject", "ms-office.active")) or extension in {"bin", "vba", "ocx"}:
                    raise ValueError("DOCX declares prohibited active or embedded content")
            for name in names:
                if not name.endswith(".rels"):
                    continue
                relationships_data = package.read(name)
                if b"<!DOCTYPE" in relationships_data.upper() or b"<!ENTITY" in relationships_data.upper():
                    raise ValueError("DOCX relationship contains prohibited DTD content")
                relationships = ElementTree.fromstring(relationships_data)
                for relationship in relationships.iter():
                    if not relationship.tag.endswith("}Relationship"):
                        continue
                    rel_type = relationship.attrib.get("Type", "")
                    target_mode = relationship.attrib.get("TargetMode", "")
                    target = relationship.attrib.get("Target", "")
                    # The authoritative DOCX validator above already applies the
                    # custom-XML allowlist.  Reject active relationships here,
                    # but do not contradict that validated passive custom XML.
                    if any(rel_type.endswith(suffix) for suffix in ("/oleObject", "/package", "/control", "/vbaProject", "/attachedTemplate")):
                        raise ValueError("DOCX contains a prohibited active relationship")
                    if target_mode == "External" and (not rel_type.endswith("/hyperlink") or not _public_https(target)):
                        raise ValueError("DOCX contains a prohibited external relationship")
    except zipfile.BadZipFile as exc:
        raise ValueError("DOCX is not a valid ZIP package") from exc
    except ElementTree.ParseError as exc:
        raise ValueError("DOCX contains invalid package XML") from exc


def stage(source: Path, destination: Path, expected_sha256: str, kind: str) -> None:
    if not __import__("re").fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("expected SHA-256 must be 64 lowercase hexadecimal characters")
    data = _read_once(source)
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("input does not match the expected SHA-256")
    suffix = f".{kind}"
    if source.suffix.casefold() != suffix or destination.suffix.casefold() != suffix:
        raise ValueError(f"source and destination must use the exact {suffix} extension")
    if kind == "docx":
        _validate_docx(data)
    else:
        validate_pptx_bytes(data)
    parent = destination.parent.resolve(strict=True)
    metadata = parent.lstat()
    if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("destination parent must be a real directory")
    with open_exclusive_write(parent / destination.name) as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--kind", required=True, choices=("docx", "pptx"))
    args = parser.parse_args(argv)
    try:
        stage(args.input, args.output, args.expected_sha256, args.kind)
        print(args.output)
        return 0
    except (OSError, ValueError, PptxValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
