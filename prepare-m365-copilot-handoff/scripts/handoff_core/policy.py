"""Fail-closed schema, path, content, and profile policy."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

from .canonical import normalise


SKILL_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = SKILL_ROOT / "schemas"
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))
}
PLACEHOLDER_RE = re.compile(r"\{\{[^{}]+\}\}|\b(?:TODO|TBD)\b|lorem ipsum", re.IGNORECASE)
INJECTION_RE = re.compile(
    r"\b(?:ignore (?:all |any )?(?:previous|prior) instructions|system prompt|developer message|"
    r"bypass (?:approval|policy|security)|reveal (?:secrets?|credentials?|tokens?))\b",
    re.IGNORECASE,
)
SECRET_PATTERNS = {
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    "credential query parameter": re.compile(r"[?&](?:access_token|token|sig|signature|api[_-]?key)=", re.IGNORECASE),
}


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    message: str
    context: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class HandoffError(Exception):
    def __init__(self, diagnostics: Iterable[Diagnostic]):
        self.diagnostics = list(diagnostics)
        super().__init__("; ".join(f"{item.code}: {item.message}" for item in self.diagnostics))


def diagnostic(code: str, message: str, context: str | None = None, severity: str = "error") -> Diagnostic:
    return Diagnostic(code=code, severity=severity, message=message, context=context)


def load_json(path: Path, *, maximum_bytes: int = 10 * 1024 * 1024) -> Any:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise HandoffError([diagnostic("HND002", "input must be a regular non-symlink file", path.name)])
    if metadata.st_size > maximum_bytes:
        raise HandoffError([diagnostic("HND004", "JSON input exceeds the file-size limit", path.name)])
    try:
        return normalise(json.loads(path.read_text(encoding="utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HandoffError([diagnostic("HND001", "JSON parse or canonicalisation failed", path.name)]) from exc


def load_schema(name: str) -> dict[str, Any]:
    raw = load_json(SCHEMAS / name)
    if not isinstance(raw, dict):
        raise HandoffError([diagnostic("HND001", "schema root must be an object", name)])
    try:
        Draft202012Validator.check_schema(raw)
    except Exception as exc:
        raise HandoffError([diagnostic("HND001", "invalid bundled JSON Schema", name)]) from exc
    return raw


def validate_schema(instance: Any, schema_name: str, context: str) -> list[Diagnostic]:
    validator = Draft202012Validator(load_schema(schema_name), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path))
    return [
        diagnostic(
            "HND001",
            error.message,
            context + ("/" + "/".join(str(part) for part in error.absolute_path) if error.absolute_path else ""),
        )
        for error in errors
    ]


def safe_relative_path(value: str, *, context: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise HandoffError([diagnostic("HND002", "path must be a non-empty relative POSIX path", context)])
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(part in ("", ".", "..") for part in path.parts):
        raise HandoffError([diagnostic("HND002", "path is absolute, ambiguous, or contains traversal", context)])
    for component in path.parts:
        stem = component.split(".", 1)[0].upper()
        if component.endswith((" ", ".")) or ":" in component or stem in WINDOWS_RESERVED:
            raise HandoffError([diagnostic("HND002", "path is unsafe on a supported host", context)])
    return path


def resolve_workspace_file(workspace: Path, relative: str, *, context: str) -> Path:
    rel = safe_relative_path(relative, context=context)
    root = workspace.resolve(strict=True)
    if stat.S_ISLNK(workspace.lstat().st_mode):
        raise HandoffError([diagnostic("HND002", "workspace must not be a symlink", context)])
    cursor = root
    for component in rel.parts:
        cursor = cursor / component
        try:
            metadata = cursor.lstat()
        except FileNotFoundError as exc:
            raise HandoffError([diagnostic("HND002", "input path does not exist", context)]) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise HandoffError([diagnostic("HND002", "input path contains a symlink", context)])
    resolved = cursor.resolve(strict=True)
    if os.path.commonpath((str(root), str(resolved))) != str(root) or not resolved.is_file():
        raise HandoffError([diagnostic("HND002", "input path escaped the workspace or is not a file", context)])
    return resolved


def iter_strings(value: Any, pointer: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield pointer or "/", value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_strings(item, f"{pointer}/{index}")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from iter_strings(item, f"{pointer}/{key}")


def scan_content(value: Any, *, context: str, reject_placeholders: bool = True) -> tuple[list[Diagnostic], list[Diagnostic]]:
    errors: list[Diagnostic] = []
    warnings: list[Diagnostic] = []
    for pointer, text in iter_strings(value):
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(diagnostic("HND005", f"potential {label} detected", f"{context}{pointer}"))
        if reject_placeholders and PLACEHOLDER_RE.search(text):
            errors.append(diagnostic("HND007", "unresolved placeholder detected", f"{context}{pointer}"))
        if INJECTION_RE.search(text):
            warnings.append(
                diagnostic(
                    "HNDW010",
                    "potential instruction-injection text retained as untrusted content",
                    f"{context}{pointer}",
                    "warning",
                )
            )
    return errors, warnings


def profile_map(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    errors: list[Diagnostic] = []
    for index, profile in enumerate(registry.get("profiles", [])):
        key = profile.get("template_profile_id")
        if key in profiles:
            errors.append(diagnostic("HND009", "duplicate template profile ID", f"profiles/{index}"))
        elif isinstance(key, str):
            profiles[key] = profile
    if errors:
        raise HandoffError(errors)
    return profiles


def validate_payload_semantics(
    payload: dict[str, Any],
    profile: dict[str, Any],
    source_ids: set[str],
    *,
    context: str,
) -> tuple[list[Diagnostic], list[Diagnostic]]:
    errors, warnings = scan_content(payload, context=context)
    section_ids: set[str] = set()
    slot_ids: list[str] = []
    block_ids: set[str] = set()
    for section in payload.get("sections", []):
        section_id = section.get("section_id")
        if section_id in section_ids:
            errors.append(diagnostic("HND007", "duplicate section ID", context))
        section_ids.add(section_id)
        slot_ids.append(section.get("slot_id"))
        for block in section.get("blocks", []):
            block_id = block.get("block_id")
            if block_id in block_ids:
                errors.append(diagnostic("HND007", "duplicate block ID", context))
            block_ids.add(block_id)
            if block.get("type") == "table":
                width = len(block.get("headers", []))
                if any(len(row) != width for row in block.get("rows", [])):
                    errors.append(diagnostic("HND006", "table row width does not match header width", block_id))
            if block.get("type") == "figure":
                errors.append(diagnostic("HND007", "figure assets are deferred beyond the Phase 1 slice", block_id))
            for source_id in block.get("source_ids", []):
                if source_id not in source_ids:
                    errors.append(diagnostic("HND006", "block references an unknown source ID", block_id))
    if len(slot_ids) != len(set(slot_ids)):
        errors.append(diagnostic("HND006", "semantic slot IDs must be unique", context))
    missing = sorted(set(profile.get("required_slots", [])) - set(slot_ids))
    if missing:
        errors.append(diagnostic("HND006", f"required template slots missing: {', '.join(missing)}", context))
    allowed = set(profile.get("required_slots", [])) | set(profile.get("optional_slots", []))
    unexpected = sorted(set(slot_ids) - allowed)
    if unexpected:
        errors.append(diagnostic("HND009", f"payload uses slots absent from template profile: {', '.join(unexpected)}", context))
    return errors, warnings
