#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fail-closed structural and privacy validation for generated PPTX files."""

from __future__ import annotations

import argparse
import ipaddress
import io
import os
import re
import socket
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree
from urllib.parse import urlsplit
from portable_fs import bounded_read

MAX_PPTX_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 20_000
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_ENTRY_BYTES = 128 * 1024 * 1024
MAX_RATIO = 1000
FORBIDDEN_PART_MARKERS = (
    "vbaproject",
    "/activex/",
    "/embeddings/",
    "/comments/",
    "/persons/",
    "commentauthors",
    "customxml/",
)
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
REL_TAG = f"{{{REL_NS}}}Relationship"
CORE_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"
SLIDE_RE = re.compile(r"^ppt/slides/slide[1-9][0-9]*\.xml$")
FORBIDDEN_RELATIONSHIP_SUFFIXES = (
    "/oleObject", "/package", "/control", "/vbaProject", "/attachedTemplate",
    "/customXml", "/comments", "/commentAuthors",
)
FORBIDDEN_CONTENT_TYPE_MARKERS = (
    "macroenabled", "vbaproject", "activex", "oleobject", "ms-office.active",
)


class PptxValidationError(ValueError):
    """Raised when a presentation violates the portable release contract."""


def _public_https(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return False
        host = parsed.hostname.rstrip(".").casefold()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            try:
                address = ipaddress.ip_address(socket.inet_aton(host))
            except OSError:
                return True
        return address.is_global
    except ValueError:
        return False


def _read_once(path: Path) -> bytes:
    try:
        return bounded_read(path, MAX_PPTX_BYTES)[0]
    except ValueError as exc:
        raise PptxValidationError(str(exc)) from exc


def _safe_member(name: str) -> PurePosixPath:
    if "\\" in name or "\x00" in name:
        raise PptxValidationError(f"unsafe package member: {name!r}")
    member = PurePosixPath(name.rstrip("/"))
    if member.is_absolute() or not member.parts or any(part in ("", ".", "..") for part in member.parts):
        raise PptxValidationError(f"unsafe package member: {name!r}")
    return member


def _xml(data: bytes, field: str) -> ElementTree.Element:
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise PptxValidationError(f"{field} contains prohibited DTD content")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise PptxValidationError(f"{field} is invalid XML") from exc


def validate_pptx_bytes(data: bytes) -> dict[str, int]:
    try:
        package = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PptxValidationError("PPTX is not a valid ZIP package") from exc
    with package:
        entries = package.infolist()
        if not entries or len(entries) > MAX_ENTRIES:
            raise PptxValidationError("PPTX entry count is empty or excessive")
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise PptxValidationError("PPTX contains duplicate package members")
        expanded = 0
        slides = 0
        notes = 0
        for entry in entries:
            member = _safe_member(entry.filename)
            lower = f"/{str(member).casefold()}"
            if any(marker in lower for marker in FORBIDDEN_PART_MARKERS):
                raise PptxValidationError(f"PPTX contains prohibited active or review content: {member}")
            if entry.flag_bits & 0x1:
                raise PptxValidationError(f"PPTX contains an encrypted member: {member}")
            if entry.file_size > MAX_ENTRY_BYTES:
                raise PptxValidationError(f"PPTX member is oversized: {member}")
            ratio = entry.file_size / max(entry.compress_size, 1)
            if ratio > MAX_RATIO:
                raise PptxValidationError(f"PPTX member expansion ratio is excessive: {member}")
            expanded += entry.file_size
            if expanded > MAX_EXPANDED_BYTES:
                raise PptxValidationError("PPTX expanded size exceeds the bound")
            if SLIDE_RE.fullmatch(str(member)):
                slides += 1
            if str(member).startswith("ppt/notesSlides/notesSlide") and str(member).endswith(".xml"):
                notes += 1
            if str(member).endswith(".rels"):
                root = _xml(package.read(entry), str(member))
                for relationship in root.findall(REL_TAG):
                    target_mode = relationship.attrib.get("TargetMode", "")
                    target = relationship.attrib.get("Target", "")
                    rel_type = relationship.attrib.get("Type", "")
                    if any(rel_type.endswith(suffix) for suffix in FORBIDDEN_RELATIONSHIP_SUFFIXES):
                        raise PptxValidationError(f"PPTX contains a prohibited active relationship: {rel_type}")
                    if target_mode == "External":
                        if not rel_type.endswith("/hyperlink") or not _public_https(target):
                            raise PptxValidationError(f"PPTX contains a prohibited external relationship: {target}")
        required = {"[Content_Types].xml", "ppt/presentation.xml"}
        if not required.issubset(set(names)) or slides < 1:
            raise PptxValidationError("PPTX lacks required presentation parts")
        content_types = _xml(package.read("[Content_Types].xml"), "[Content_Types].xml")
        for item in content_types.iter():
            content_type = item.attrib.get("ContentType", "").casefold()
            extension = item.attrib.get("Extension", "").casefold()
            if any(marker in content_type for marker in FORBIDDEN_CONTENT_TYPE_MARKERS) or extension in {"bin", "vba", "ocx"}:
                raise PptxValidationError("PPTX declares prohibited active or embedded content")
        if notes != slides:
            raise PptxValidationError("every slide must have an evidence-source notes part")
        if "docProps/core.xml" in names:
            core = _xml(package.read("docProps/core.xml"), "docProps/core.xml")
            creator = core.findtext(f"{{{DC_NS}}}creator", default="").strip()
            modified_by = core.findtext(f"{{{CORE_NS}}}lastModifiedBy", default="").strip()
            # The host exporter emits its product identity, not a person or
            # workstation account. Both values are neutral publication metadata.
            allowed = {"", "Security Assessment Automation", "Walnut Exporter"}
            if creator not in allowed or modified_by not in allowed:
                raise PptxValidationError(f"PPTX contains non-neutral author metadata: creator={creator!r}, lastModifiedBy={modified_by!r}")
    return {"slides": slides, "notes": notes, "entries": len(entries)}


def validate_pptx(path: Path) -> dict[str, int]:
    return validate_pptx_bytes(_read_once(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pptx", type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_pptx(args.pptx)
        print(f"PASS: PPTX has {result['slides']} slides, {result['notes']} notes parts, and no prohibited active content")
        return 0
    except (OSError, PptxValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
