"""Build and independently validate immutable handoff packages."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import canonical_json_bytes, normalise
from .hashes import sha256_bytes, sha256_file
from .policy import (
    Diagnostic,
    HandoffError,
    diagnostic,
    load_json,
    profile_map,
    resolve_workspace_file,
    safe_relative_path,
    scan_content,
    validate_payload_semantics,
    validate_schema,
)
from .reports import render_handoff, render_preview, validation_report_bytes


MANIFEST_SCHEMA_URI = "https://schemas.solosentry.example/m365-handoff/v1/handoff-manifest.schema.json"
PRODUCER = {"name": "prepare-m365-copilot-handoff", "version": "1.0.0"}
FIXED_BUILD_CONTROLS = {
    "operation": "create",
    "require_human_approval_before_replace": True,
    "allow_external_publication": False,
    "allow_macros": False,
}
GENERATED_PURPOSES = {"human-handoff", "validation-evidence"}
ALLOWED_TOP_LEVEL = {"handoff-manifest.json", "HANDOFF.md", "payloads", "previews", "evidence"}


def _sorted_diagnostics(items: list[Diagnostic]) -> list[Diagnostic]:
    unique = {(item.code, item.severity, item.message, item.context): item for item in items}
    return sorted(unique.values(), key=lambda item: (item.severity, item.code, item.context or "", item.message))


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def _media_type(path: str) -> str:
    if path.endswith(".json"):
        return "application/json"
    if path.endswith(".md") or path.endswith(".txt"):
        return "text/markdown"
    raise HandoffError([diagnostic("HND004", "unsupported package file type", path)])


def _file_entry(root: Path, relative: str, purpose: str, maximum: int, *, identity: bool) -> dict[str, Any]:
    safe_relative_path(relative, context=relative)
    digest, length = sha256_file(root / relative, maximum)
    return {
        "path": relative,
        "media_type": _media_type(relative),
        "bytes": length,
        "sha256": digest,
        "purpose": purpose,
        "identity_included": identity,
        "security_scan": "pass",
    }


def _identity_object(manifest: dict[str, Any]) -> dict[str, Any]:
    files = [entry for entry in manifest["files"] if entry["identity_included"]]
    return {
        "schema_version": manifest["schema_version"],
        "producer": manifest["producer"],
        "environment": manifest["environment"],
        "classification": manifest["classification"],
        "locale": manifest["locale"],
        "request_summary": manifest["request_summary"],
        "destination": manifest["destination"],
        "trusted_instructions": manifest["trusted_instructions"],
        "artifacts": manifest["artifacts"],
        "files": sorted(files, key=lambda entry: entry["path"]),
    }


def _identity(manifest: dict[str, Any]) -> tuple[str, str]:
    digest = sha256_bytes(canonical_json_bytes(_identity_object(manifest)))
    return f"m365h-{digest[:20]}", f"sha256:{digest}"


def _profile_for_artifact(
    artifact: dict[str, Any], profiles: dict[str, dict[str, Any]], environment: str
) -> dict[str, Any]:
    profile = profiles.get(artifact["template_profile_id"])
    if profile is None:
        raise HandoffError([diagnostic("HND009", "template profile is not registered", artifact["artifact_id"])])
    expected = (
        profile["artifact_kind"] == artifact["kind"]
        and profile["version"] == artifact["template_version"]
        and profile["template_sha256"] == artifact["template_sha256"]
        and profile["environment"] == environment
        and profile["lifecycle_state"] == "approved"
    )
    if not expected:
        raise HandoffError([diagnostic("HND009", "template profile is unapproved, incompatible, or drifted", artifact["artifact_id"])])
    return profile


def _tree_bytes(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def build_package(job_path: Path, workspace: Path, registry_path: Path, output: Path) -> dict[str, Any]:
    if not output.exists() or not output.is_dir() or stat.S_ISLNK(output.lstat().st_mode):
        raise HandoffError([diagnostic("HND002", "output must be an existing non-symlink directory", output.name)])
    job = load_json(job_path)
    registry = load_json(registry_path)
    schema_errors = [
        *validate_schema(job, "job.schema.json", "job"),
        *validate_schema(registry, "template-profile.schema.json", "registry"),
    ]
    if schema_errors:
        raise HandoffError(schema_errors)
    profiles = profile_map(registry)
    policy = registry["policy"]
    maximum = policy["max_individual_file_bytes"]
    source_path = resolve_workspace_file(workspace, job["source_register"], context="source_register")
    source_register = load_json(source_path, maximum_bytes=maximum)
    errors = validate_schema(source_register, "source-register.schema.json", "source_register")
    content_errors, warnings = scan_content(source_register, context="source_register")
    errors.extend(content_errors)
    job_errors, job_warnings = scan_content(
        {
            "request_summary": job["request_summary"],
            "destination": job["destination"],
            "trusted_instructions": FIXED_BUILD_CONTROLS,
        },
        context="job",
    )
    errors.extend(job_errors)
    warnings.extend(job_warnings)
    source_ids = {item["source_id"] for item in source_register.get("sources", [])}
    if len(source_ids) != len(source_register.get("sources", [])):
        errors.append(diagnostic("HND006", "source IDs must be unique", "source_register"))
    for source in source_register.get("sources", []):
        location = source.get("original_location", "")
        if location.startswith("/") or (len(location) > 2 and location[0].isalpha() and location[1:3] in {":/", ":\\"}):
            errors.append(diagnostic("HND005", "source location must not expose an absolute local path", source.get("source_id")))
    artifact_ids: set[str] = set()
    payloads: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for artifact in job["artifacts"]:
        if artifact["artifact_id"] in artifact_ids:
            errors.append(diagnostic("HND006", "artifact IDs must be unique", artifact["artifact_id"]))
        artifact_ids.add(artifact["artifact_id"])
        try:
            output_name = safe_relative_path(artifact["output_filename"], context=artifact["artifact_id"])
            if len(output_name.parts) != 1:
                errors.append(diagnostic("HND002", "output filename must not contain directories", artifact["artifact_id"]))
        except HandoffError as exc:
            errors.extend(exc.diagnostics)
        profile = _profile_for_artifact(artifact, profiles, job["environment"])
        payload_path = resolve_workspace_file(workspace, artifact["payload"], context=artifact["artifact_id"])
        payload = load_json(payload_path, maximum_bytes=maximum)
        errors.extend(validate_schema(payload, "word-content.schema.json", artifact["artifact_id"]))
        if payload.get("artifact_id") != artifact["artifact_id"]:
            errors.append(diagnostic("HND006", "payload artifact ID does not match job", artifact["artifact_id"]))
        semantic_errors, semantic_warnings = validate_payload_semantics(
            payload, profile, source_ids, context=artifact["artifact_id"]
        )
        errors.extend(semantic_errors)
        warnings.extend(semantic_warnings)
        payloads.append((artifact, profile, payload))
    errors = _sorted_diagnostics(errors)
    warnings = _sorted_diagnostics(warnings)
    if errors:
        raise HandoffError(errors)

    temp = Path(tempfile.mkdtemp(prefix=".m365h-build-", dir=output))
    try:
        entries: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        source_relative = "evidence/source-register.json"
        _write(temp / source_relative, canonical_json_bytes(source_register))
        entries.append(_file_entry(temp, source_relative, "source-register", maximum, identity=True))
        for artifact, profile, payload in payloads:
            artifact_id = artifact["artifact_id"]
            payload_relative = f"payloads/{artifact_id}.word.json"
            preview_relative = f"previews/{artifact_id}.md"
            _write(temp / payload_relative, canonical_json_bytes(payload))
            _write(temp / preview_relative, render_preview(payload))
            entries.append(_file_entry(temp, payload_relative, "word-payload", maximum, identity=True))
            entries.append(_file_entry(temp, preview_relative, "preview", maximum, identity=True))
            artifacts.append(
                {
                    "artifact_id": artifact_id,
                    "kind": "word",
                    "operation": "create",
                    "payload": payload_relative,
                    "preview": preview_relative,
                    "output_filename": artifact["output_filename"],
                    "template": {
                        "profile_id": profile["template_profile_id"],
                        "version": profile["version"],
                        "sha256": profile["template_sha256"],
                    },
                    "required_slots": profile["required_slots"],
                    "acceptance_profile": "office-desktop",
                }
            )
        manifest: dict[str, Any] = {
            "$schema": MANIFEST_SCHEMA_URI,
            "schema_version": "1.0",
            "package_id": "m365h-" + "0" * 20,
            "content_digest": "sha256:" + "0" * 64,
            "created_at": job["created_at"],
            "producer": PRODUCER,
            "environment": job["environment"],
            "classification": job["classification"],
            "locale": job["locale"],
            "request_summary": job["request_summary"],
            "destination": job["destination"],
            "trusted_instructions": FIXED_BUILD_CONTROLS,
            "artifacts": artifacts,
            "files": sorted(entries, key=lambda entry: entry["path"]),
            "sources": source_register["sources"],
            "validation": {
                "status": "pass",
                "json_report": "evidence/validation-report.json",
                "text_report": "evidence/validation-report.txt",
            },
        }
        manifest["package_id"], manifest["content_digest"] = _identity(manifest)
        _write(temp / "HANDOFF.md", render_handoff(manifest))
        json_report, text_report = validation_report_bytes(
            manifest["package_id"], manifest["content_digest"], [], warnings
        )
        _write(temp / "evidence/validation-report.json", json_report)
        _write(temp / "evidence/validation-report.txt", text_report)
        manifest["files"].extend(
            [
                _file_entry(temp, "HANDOFF.md", "human-handoff", maximum, identity=False),
                _file_entry(temp, "evidence/validation-report.json", "validation-evidence", maximum, identity=False),
                _file_entry(temp, "evidence/validation-report.txt", "validation-evidence", maximum, identity=False),
            ]
        )
        manifest["files"] = sorted(manifest["files"], key=lambda entry: entry["path"])
        _write(temp / "handoff-manifest.json", canonical_json_bytes(manifest))
        result = validate_package(temp, registry_path, mode="build")
        if result["status"] != "pass":
            raise HandoffError([Diagnostic(**item) for item in result["errors"]])
        final = output / manifest["package_id"]
        if final.exists():
            existing = validate_package(final, registry_path, mode="build")
            if existing["status"] == "pass" and _tree_bytes(final) == _tree_bytes(temp):
                shutil.rmtree(temp)
                return {"status": "pass", "package": str(final), "package_id": manifest["package_id"], "content_digest": manifest["content_digest"], "reused": True}
            raise HandoffError([diagnostic("HND011", "package ID already exists with non-identical bytes", final.name)])
        temp.rename(final)
        return {"status": "pass", "package": str(final), "package_id": manifest["package_id"], "content_digest": manifest["content_digest"], "reused": False}
    except Exception:
        if temp.exists():
            shutil.rmtree(temp)
        raise


def _collect_actual_files(package: Path) -> tuple[set[str], list[Diagnostic], int]:
    files: set[str] = set()
    errors: list[Diagnostic] = []
    total = 0
    for root, directories, names in os.walk(package, followlinks=False):
        root_path = Path(root)
        for name in list(directories):
            path = root_path / name
            if stat.S_ISLNK(path.lstat().st_mode):
                errors.append(diagnostic("HND002", "package directory contains a symlink", path.relative_to(package).as_posix()))
                directories.remove(name)
        for name in names:
            path = root_path / name
            relative = path.relative_to(package).as_posix()
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                errors.append(diagnostic("HND002", "package entry is not a regular file", relative))
                continue
            files.add(relative)
            total += metadata.st_size
    return files, errors, total


def validate_package(
    package: Path,
    registry_path: Path,
    *,
    mode: str,
    expected_digest: str | None = None,
) -> dict[str, Any]:
    errors: list[Diagnostic] = []
    warnings: list[Diagnostic] = []
    try:
        if mode not in {"build", "received"}:
            raise HandoffError([diagnostic("HND001", "validation mode must be build or received")])
        if mode == "received" and not expected_digest:
            raise HandoffError([diagnostic("HND003", "received mode requires the original expected digest")])
        metadata = package.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise HandoffError([diagnostic("HND002", "package must be a non-symlink directory", package.name)])
        registry = load_json(registry_path)
        errors.extend(validate_schema(registry, "template-profile.schema.json", "registry"))
        profiles = profile_map(registry)
        policy = registry["policy"]
        actual, path_errors, total = _collect_actual_files(package)
        errors.extend(path_errors)
        if len(actual) > policy["max_file_count"]:
            errors.append(diagnostic("HND004", "package exceeds file-count limit"))
        if total > policy["max_total_package_bytes"]:
            errors.append(diagnostic("HND004", "package exceeds total-size limit"))
        if any(PurePosixPath(path).parts[0] not in ALLOWED_TOP_LEVEL for path in actual):
            errors.append(diagnostic("HND004", "package contains an unexpected top-level path"))
        manifest_path = package / "handoff-manifest.json"
        if "handoff-manifest.json" not in actual:
            raise HandoffError([diagnostic("HND006", "handoff manifest is missing")])
        manifest = load_json(manifest_path, maximum_bytes=policy["max_individual_file_bytes"])
        errors.extend(validate_schema(manifest, "handoff-manifest.schema.json", "manifest"))
        if errors:
            raise HandoffError(errors)
        entries = manifest["files"]
        paths = [entry["path"] for entry in entries]
        if len(entries) > policy["max_file_count"]:
            errors.append(diagnostic("HND004", "inventory exceeds the configured file-count limit"))
        if len(paths) != len(set(path.casefold() for path in paths)):
            errors.append(diagnostic("HND002", "inventory contains duplicate case-insensitive paths"))
        expected = set(paths) | {"handoff-manifest.json"}
        if actual != expected:
            errors.append(diagnostic("HND006", "inventory and physical package file sets differ"))
        if errors:
            raise HandoffError(errors)
        for entry in entries:
            relative = entry["path"]
            try:
                safe_relative_path(relative, context=relative)
            except HandoffError as exc:
                errors.extend(exc.diagnostics)
                continue
            path = package / relative
            if not path.exists():
                continue
            try:
                digest, length = sha256_file(path, policy["max_individual_file_bytes"])
            except ValueError:
                errors.append(diagnostic("HND004", "inventoried file exceeds individual-size limit", relative))
                continue
            if digest != entry["sha256"] or length != entry["bytes"]:
                errors.append(diagnostic("HND003", "inventoried file digest or size mismatch", relative))
            try:
                if _media_type(relative) != entry["media_type"]:
                    errors.append(diagnostic("HND004", "inventoried media type does not match extension", relative))
            except HandoffError as exc:
                errors.extend(exc.diagnostics)
            if (entry["purpose"] in GENERATED_PURPOSES) == entry["identity_included"]:
                errors.append(diagnostic("HND011", "generated/content identity classification is inconsistent", relative))
        package_id, content_digest = _identity(manifest)
        if manifest["package_id"] != package_id or manifest["content_digest"] != content_digest:
            errors.append(diagnostic("HND003", "canonical package identity does not recompute"))
        if expected_digest and manifest["content_digest"] != expected_digest:
            errors.append(diagnostic("HND003", "received package does not match the original digest"))
        source_register = load_json(package / "evidence/source-register.json", maximum_bytes=policy["max_individual_file_bytes"])
        errors.extend(validate_schema(source_register, "source-register.schema.json", "source_register"))
        source_errors, source_warnings = scan_content(source_register, context="source_register")
        errors.extend(source_errors)
        warnings.extend(source_warnings)
        source_ids = {item["source_id"] for item in source_register.get("sources", [])}
        if len(source_ids) != len(source_register.get("sources", [])):
            errors.append(diagnostic("HND006", "source IDs must be unique", "source_register"))
        for source in source_register.get("sources", []):
            location = source.get("original_location", "")
            if location.startswith("/") or (len(location) > 2 and location[0].isalpha() and location[1:3] in {":/", ":\\"}):
                errors.append(diagnostic("HND005", "source location must not expose an absolute local path", source.get("source_id")))
        if normalise(manifest["sources"]) != normalise(source_register.get("sources")):
            errors.append(diagnostic("HND003", "manifest sources do not match the source register"))
        manifest_errors, manifest_warnings = scan_content(
            {
                "request_summary": manifest["request_summary"],
                "destination": manifest["destination"],
                "trusted_instructions": manifest["trusted_instructions"],
            },
            context="manifest",
        )
        errors.extend(manifest_errors)
        warnings.extend(manifest_warnings)
        for artifact in manifest["artifacts"]:
            artifact_id = artifact["artifact_id"]
            expected_payload = f"payloads/{artifact_id}.word.json"
            expected_preview = f"previews/{artifact_id}.md"
            for field, expected_path in (("payload", expected_payload), ("preview", expected_preview)):
                try:
                    safe_relative_path(artifact[field], context=artifact_id)
                except HandoffError as exc:
                    errors.extend(exc.diagnostics)
                if artifact[field] != expected_path or artifact[field] not in actual:
                    errors.append(
                        diagnostic(
                            "HND002",
                            f"artifact {field} must use its canonical inventoried package path",
                            artifact_id,
                        )
                    )
            if errors:
                continue
            try:
                output_name = safe_relative_path(artifact["output_filename"], context=artifact_id)
                if len(output_name.parts) != 1:
                    errors.append(diagnostic("HND002", "output filename must not contain directories", artifact_id))
            except HandoffError as exc:
                errors.extend(exc.diagnostics)
            profile_stub = {
                "template_profile_id": artifact["template"]["profile_id"],
                "kind": artifact["kind"],
                "template_version": artifact["template"]["version"],
                "template_sha256": artifact["template"]["sha256"],
                "artifact_id": artifact_id,
            }
            profile = _profile_for_artifact(profile_stub, profiles, manifest["environment"])
            payload = load_json(package / artifact["payload"], maximum_bytes=policy["max_individual_file_bytes"])
            errors.extend(validate_schema(payload, "word-content.schema.json", artifact_id))
            semantic_errors, semantic_warnings = validate_payload_semantics(payload, profile, source_ids, context=artifact_id)
            errors.extend(semantic_errors)
            warnings.extend(semantic_warnings)
            if payload.get("artifact_id") != artifact_id:
                errors.append(diagnostic("HND006", "payload artifact ID does not match manifest", artifact_id))
            if (package / artifact["preview"]).exists() and render_preview(payload) != (package / artifact["preview"]).read_bytes():
                errors.append(diagnostic("HND003", "preview is not the deterministic payload projection", artifact["preview"]))
        if (package / "HANDOFF.md").exists() and render_handoff(manifest) != (package / "HANDOFF.md").read_bytes():
            errors.append(diagnostic("HND003", "HANDOFF.md is not the deterministic manifest projection", "HANDOFF.md"))
        errors = _sorted_diagnostics(errors)
        warnings = _sorted_diagnostics(warnings)
        if not errors:
            expected_json, expected_text = validation_report_bytes(package_id, content_digest, [], warnings)
            if expected_json != (package / "evidence/validation-report.json").read_bytes():
                errors.append(diagnostic("HND003", "packaged JSON validation evidence is not reproducible"))
            if expected_text != (package / "evidence/validation-report.txt").read_bytes():
                errors.append(diagnostic("HND003", "packaged text validation evidence is not reproducible"))
    except HandoffError as exc:
        errors.extend(exc.diagnostics)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        errors.append(diagnostic("HND013", "package validation could not complete safely"))
    errors = _sorted_diagnostics(errors)
    warnings = _sorted_diagnostics(warnings)
    return {
        "schema_version": "1.0",
        "status": "pass" if not errors else "fail",
        "mode": mode,
        "package_id": locals().get("manifest", {}).get("package_id"),
        "content_digest": locals().get("manifest", {}).get("content_digest"),
        "errors": [item.to_dict() for item in errors],
        "warnings": [item.to_dict() for item in warnings],
    }
