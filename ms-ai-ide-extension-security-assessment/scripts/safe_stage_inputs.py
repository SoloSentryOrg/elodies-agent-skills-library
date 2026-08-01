#!/usr/bin/env python3
"""Read integrity-bound assessment stage inputs without pathname races."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from portable_fs import bounded_read, require_real_directory


@dataclass(frozen=True)
class ValidatedClaim:
    claim_id: str
    value: str
    evidence_ids: tuple[str, ...]
    source_stages: tuple[int, ...]
    evidence_state: str
    confidence: str
    limitations: str


@dataclass(frozen=True)
class ValidatedStageBundle:
    assessment: str
    target: str
    version: str
    claims: dict[str, ValidatedClaim]

    def claim_text(self, claim_id: str) -> str:
        try:
            return self.claims[claim_id].value
        except KeyError as exc:
            raise ValueError(f"required validated claim is missing: {claim_id}") from exc


def _secure_directory_flags() -> int:
    if os.name == "nt":
        return os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if (
        not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "O_NOFOLLOW")
        or os.open not in os.supports_dir_fd
    ):
        raise ValueError(
            "secure descriptor-relative stage reads are unsupported on this platform"
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _read_bounded_regular_file_at(
    root_descriptor: int,
    display_root: Path,
    relative_value: str,
    maximum_bytes: int,
) -> tuple[Path, bytes]:
    relative = Path(relative_value)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in ("", ".", "..") for part in relative.parts)
    ):
        raise ValueError(f"unsafe relative path: {relative_value!r}")

    if os.name == "nt":
        root = require_real_directory(display_root)
        candidate = root.joinpath(*relative.parts)
        try:
            candidate.resolve(strict=True).relative_to(root)
        except ValueError as exc:
            raise ValueError(f"unsafe stage input: {relative_value}") from exc
        data, _ = bounded_read(candidate, maximum_bytes)
        return candidate, data

    directory_flags = _secure_directory_flags()
    file_flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
        file_flags |= os.O_CLOEXEC

    opened_directories: list[int] = []
    try:
        current_fd = os.dup(root_descriptor)
        opened_directories.append(current_fd)
        for component in relative.parts[:-1]:
            current_fd = os.open(component, directory_flags, dir_fd=current_fd)
            opened_directories.append(current_fd)
        file_descriptor = os.open(relative.parts[-1], file_flags, dir_fd=current_fd)
        try:
            before = os.fstat(file_descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError(f"stage input is not a regular file: {relative_value}")
            if before.st_size > maximum_bytes:
                raise ValueError(
                    f"stage input exceeds {maximum_bytes} bytes: {relative_value}"
                )
            with os.fdopen(file_descriptor, "rb", closefd=False) as handle:
                data = handle.read(maximum_bytes + 1)
            after = os.fstat(file_descriptor)
            stable_identity = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            if stable_identity != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError(f"stage input changed while reading: {relative_value}")
            if len(data) > maximum_bytes or len(data) != after.st_size:
                raise ValueError(
                    f"stage input exceeds bounds or changed while reading: {relative_value}"
                )
        finally:
            os.close(file_descriptor)
    except OSError as exc:
        raise ValueError(f"unsafe stage input: {relative_value}") from exc
    finally:
        for descriptor in reversed(opened_directories):
            os.close(descriptor)
    return display_root / relative, data


def read_bounded_regular_file(
    root: Path, relative_value: str, maximum_bytes: int
) -> tuple[Path, bytes]:
    display_root = root.absolute()
    if os.name == "nt":
        return _read_bounded_regular_file_at(-1, display_root, relative_value, maximum_bytes)
    try:
        root_descriptor = os.open(display_root, _secure_directory_flags())
    except OSError as exc:
        raise ValueError(f"unsafe stage root: {display_root}") from exc
    try:
        return _read_bounded_regular_file_at(
            root_descriptor, display_root, relative_value, maximum_bytes
        )
    finally:
        os.close(root_descriptor)


def _validated_claims(
    manifest: dict[str, object],
    claim_payload: object,
) -> ValidatedStageBundle:
    if not isinstance(claim_payload, dict):
        raise ValueError("validated claim manifest must be a JSON object")
    if claim_payload.get("schema_version") != 1:
        raise ValueError("unsupported validated claim schema")
    for field in ("assessment", "target", "version"):
        value = claim_payload.get(field)
        if not isinstance(value, str) or not value or value != manifest.get(field):
            raise ValueError(f"claim manifest {field} does not match stage manifest")
    if claim_payload.get("analyst_validation") != "Validated":
        raise ValueError("claim manifest is not analyst validated")

    raw_claims = claim_payload.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise ValueError("claim manifest must contain validated claims")
    allowed_states = {
        "Verified",
        "Inferred",
        "Not observed",
        "Not applicable",
        "Unknown",
        "Blocked",
    }
    required_fields = {
        "id",
        "type",
        "value",
        "evidence_ids",
        "source_stages",
        "evidence_state",
        "confidence",
        "limitations",
    }
    claims: dict[str, ValidatedClaim] = {}
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, dict) or set(raw_claim) != required_fields:
            raise ValueError("claim record has missing or unexpected fields")
        claim_id = raw_claim.get("id")
        value = raw_claim.get("value")
        evidence_ids = raw_claim.get("evidence_ids")
        source_stages = raw_claim.get("source_stages")
        evidence_state = raw_claim.get("evidence_state")
        confidence = raw_claim.get("confidence")
        limitations = raw_claim.get("limitations")
        if (
            not isinstance(claim_id, str)
            or not re.fullmatch(r"[a-z][a-z0-9_.-]{2,127}", claim_id)
            or claim_id in claims
        ):
            raise ValueError(f"invalid or duplicate claim id: {claim_id!r}")
        if (
            raw_claim.get("type") != "text"
            or not isinstance(value, str)
            or not value
            or len(value.encode("utf-8")) > 16 * 1024
            or "\x00" in value
        ):
            raise ValueError(f"invalid claim value: {claim_id}")
        if (
            not isinstance(evidence_ids, list)
            or not evidence_ids
            or any(
                not isinstance(item, str)
                or not re.fullmatch(r"EVD-[A-Z0-9-]{3,64}", item)
                for item in evidence_ids
            )
        ):
            raise ValueError(f"invalid claim evidence ids: {claim_id}")
        if (
            not isinstance(source_stages, list)
            or not source_stages
            or any(
                not isinstance(item, int) or isinstance(item, bool) or item not in range(1, 16)
                for item in source_stages
            )
            or len(set(source_stages)) != len(source_stages)
        ):
            raise ValueError(f"invalid claim source stages: {claim_id}")
        if evidence_state not in allowed_states:
            raise ValueError(f"invalid claim evidence state: {claim_id}")
        if not isinstance(confidence, str) or not confidence:
            raise ValueError(f"invalid claim confidence: {claim_id}")
        if not isinstance(limitations, str):
            raise ValueError(f"invalid claim limitations: {claim_id}")
        claims[claim_id] = ValidatedClaim(
            claim_id=claim_id,
            value=value,
            evidence_ids=tuple(evidence_ids),
            source_stages=tuple(source_stages),
            evidence_state=evidence_state,
            confidence=confidence,
            limitations=limitations,
        )
    return ValidatedStageBundle(
        assessment=claim_payload["assessment"],
        target=claim_payload["target"],
        version=claim_payload["version"],
        claims=claims,
    )


def consume_validated_stages(folder: Path) -> ValidatedStageBundle:
    root = folder.absolute()
    try:
        if os.name == "nt":
            root = require_real_directory(root)
            root_descriptor = -1
        else:
            root_descriptor = os.open(root, _secure_directory_flags())
    except (OSError, ValueError) as exc:
        raise ValueError(f"unsafe stage root: {root}") from exc
    try:
        _, manifest_bytes = _read_bounded_regular_file_at(
            root_descriptor, root, "stage-manifest.json", 1024 * 1024
        )
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid stage manifest JSON") from exc
        if not isinstance(manifest, dict):
            raise ValueError("stage manifest must be a JSON object")
        stages = manifest.get("stages")
        if (
            not isinstance(stages, list)
            or any(not isinstance(item, dict) for item in stages)
        ):
            raise ValueError("stage manifest stages must be an array of objects")
        if [item.get("stage") for item in stages] != list(range(1, 16)):
            raise ValueError(f"incomplete stage manifest: {folder}")
        for item in stages:
            value = item.get("file")
            if not isinstance(value, str) or not value:
                raise ValueError(f"invalid stage file value: {value!r}")
            path, stage_bytes = _read_bounded_regular_file_at(
                root_descriptor, root, value, 4 * 1024 * 1024
            )
            expected_digest = item.get("sha256")
            actual_digest = hashlib.sha256(stage_bytes).hexdigest()
            if (
                not isinstance(expected_digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
                or actual_digest != expected_digest
            ):
                raise ValueError(f"stage digest mismatch: {path}")
            content = stage_bytes.decode("utf-8", errors="strict")
            if (
                item.get("status") != "Validated"
                or "Analyst validation status: Validated" not in content
            ):
                raise ValueError(f"unvalidated stage: {path}")
        claim_entry = manifest.get("claims")
        if not isinstance(claim_entry, dict):
            raise ValueError("stage manifest lacks a validated claim manifest")
        claim_file = claim_entry.get("file")
        if not isinstance(claim_file, str) or not claim_file:
            raise ValueError("invalid validated claim manifest file")
        claim_path, claim_bytes = _read_bounded_regular_file_at(
            root_descriptor, root, claim_file, 1024 * 1024
        )
        expected_claim_digest = claim_entry.get("sha256")
        actual_claim_digest = hashlib.sha256(claim_bytes).hexdigest()
        if (
            claim_entry.get("status") != "Validated"
            or not isinstance(expected_claim_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_claim_digest)
            or actual_claim_digest != expected_claim_digest
        ):
            raise ValueError(f"claim manifest digest mismatch: {claim_path}")
        try:
            claim_payload = json.loads(claim_bytes.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid claim manifest JSON: {claim_path}") from exc
        return _validated_claims(manifest, claim_payload)
    finally:
        if root_descriptor >= 0:
            os.close(root_descriptor)
