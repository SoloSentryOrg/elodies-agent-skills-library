"""Strict Word OOXML structure, active-content, relationship, and en-GB checks."""

from __future__ import annotations

import re
import stat
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .policy import Diagnostic, diagnostic


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
DDE_FIELD_RE = re.compile(r"\bDDE(?:AUTO)?\b", re.IGNORECASE)
PROHIBITED_RELATIONSHIP_TYPES = ("/activex", "/control", "/controlproperty", "/oleobject", "/package")
PROHIBITED_CONTENT_TYPE_MARKERS = ("activex", "macroenabled", "oleobject", "vbaproject")


def _lang_is_en_gb(element: ET.Element | None) -> bool:
    if element is None:
        return False
    return all(element.get(W + attr) == "en-GB" for attr in ("val", "eastAsia", "bidi"))


def _contains_dde(root: ET.Element) -> bool:
    simple_fields = [field.get(W + "instr", "") for field in root.iter(W + "fldSimple")]
    complex_field_text = "".join(element.text or "" for element in root.iter(W + "instrText"))
    return any(DDE_FIELD_RE.search(value) for value in [*simple_fields, complex_field_text])


def validate_word_package(path: Path, *, maximum_uncompressed: int = 50 * 1024 * 1024) -> list[Diagnostic]:
    errors: list[Diagnostic] = []
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return [diagnostic("HND013", "Word package must be a regular non-symlink file", path.name)]
    if metadata.st_size > maximum_uncompressed:
        return [diagnostic("HND013", "Word package exceeds the compressed-size limit", path.name)]
    try:
        with zipfile.ZipFile(path) as package:
            names = package.namelist()
            if len(names) > 4096:
                return [diagnostic("HND013", "Word package exceeds the ZIP-entry limit", path.name)]
            folded = [name.casefold() for name in names]
            if len(folded) != len(set(folded)):
                errors.append(diagnostic("HND013", "Word package has duplicate case-insensitive ZIP paths", path.name))
            total = 0
            for item in package.infolist():
                total += item.file_size
                if total > maximum_uncompressed:
                    errors.append(diagnostic("HND013", "Word package exceeds the expansion limit", path.name))
                    break
                if item.compress_size and item.file_size / item.compress_size > 100:
                    errors.append(diagnostic("HND013", "Word package exceeds the compression-ratio limit", item.filename))
            if errors:
                return errors
            for name in names:
                lower = name.casefold()
                if lower.endswith("vbaproject.bin") or "/embeddings/" in lower or "/activex/" in lower:
                    errors.append(diagnostic("HND005", "macro or embedded object detected", name))
                if lower.endswith(".rels"):
                    root = ET.fromstring(package.read(name))
                    for relation in root.findall(R + "Relationship"):
                        if relation.get("TargetMode") == "External":
                            errors.append(diagnostic("HND005", "external Office relationship detected", name))
                        relationship_type = relation.get("Type", "").casefold()
                        if any(marker in relationship_type for marker in PROHIBITED_RELATIONSHIP_TYPES):
                            errors.append(diagnostic("HND005", "active or embedded Office relationship detected", name))
                if lower.startswith("word/") and lower.endswith(".xml"):
                    root = ET.fromstring(package.read(name))
                    if _contains_dde(root):
                        errors.append(diagnostic("HND005", "DDE field instruction detected", name))
            required = {"[Content_Types].xml", "word/document.xml", "word/styles.xml", "word/settings.xml"}
            missing = sorted(required - set(names))
            if missing:
                errors.append(diagnostic("HND013", f"Word package parts missing: {', '.join(missing)}", path.name))
                return errors
            content_types = ET.fromstring(package.read("[Content_Types].xml"))
            for element in [*content_types.findall(CT + "Default"), *content_types.findall(CT + "Override")]:
                content_type = element.get("ContentType", "").casefold()
                if any(marker in content_type for marker in PROHIBITED_CONTENT_TYPE_MARKERS):
                    errors.append(diagnostic("HND005", "active or embedded Office content type detected", "[Content_Types].xml"))
            styles = ET.fromstring(package.read("word/styles.xml"))
            defaults = styles.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr/{W}lang")
            if not _lang_is_en_gb(defaults):
                errors.append(diagnostic("HND008", "Word document default language is not fully en-GB", "word/styles.xml"))
            for style in styles.findall(W + "style"):
                if not _lang_is_en_gb(style.find(f"{W}rPr/{W}lang")):
                    errors.append(diagnostic("HND008", "Word style is missing explicit en-GB language", style.get(W + "styleId")))
            settings = ET.fromstring(package.read("word/settings.xml"))
            theme_language = settings.find(W + "themeFontLang")
            if theme_language is None or theme_language.get(W + "val") != "en-GB":
                errors.append(diagnostic("HND008", "Word theme language is not en-GB", "word/settings.xml"))
            document = ET.fromstring(package.read("word/document.xml"))
            for index, run in enumerate(document.iter(W + "r")):
                if not _lang_is_en_gb(run.find(f"{W}rPr/{W}lang")):
                    errors.append(diagnostic("HND008", "Word run is missing explicit en-GB language", f"run/{index}"))
    except (OSError, RuntimeError, zipfile.BadZipFile, ET.ParseError, KeyError):
        errors.append(diagnostic("HND013", "Word package is not valid bounded OOXML", path.name))
    return errors
