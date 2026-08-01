#!/usr/bin/env python3
"""Fail closed when durable assessment runs do not follow the repository layout."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import stat
from pathlib import Path

from portable_fs import is_link_or_reparse


RUN_KEY = re.compile(r"^\d{4}-\d{2}-\d{2}-v\d+\.\d+$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
MAX_CORRECTION_BYTES = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> object:
    if not _is_regular_file(path):
        raise ValueError(f"{label} is missing or not a regular file")
    if path.stat().st_size > MAX_CORRECTION_BYTES:
        raise ValueError(f"{label} is oversized")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc


def _validated_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not HEX_64.fullmatch(value):
        raise ValueError(f"{label} is not a lowercase SHA-256 digest")
    return value


def _validate_citation_correction(assessment: Path, run_key: str) -> list[str]:
    """Validate and hash-bind an optional citation-only correction run."""

    errors: list[str] = []
    evidence_copy = assessment / "evidence" / run_key / "correction-provenance.json"
    stage_root = assessment / "stage-output" / run_key
    provenance_path = stage_root / "correction-provenance.json"
    if not provenance_path.exists():
        manifest_signals_correction = False
        model_signals_correction = False
        try:
            manifest = _load_json(stage_root / "stage-manifest.json", "stage manifest")
            manifest_signals_correction = (
                isinstance(manifest, dict)
                and "correction_provenance" in manifest
            )
        except OSError as exc:
            errors.append(
                f"{stage_root / 'stage-manifest.json'}: cannot inspect correction signal: {exc}"
            )
        except ValueError:
            pass
        try:
            model = _load_json(stage_root / "report-model.json", "report model")
            revisions = model.get("revision_history") if isinstance(model, dict) else None
            evidence = model.get("evidence") if isinstance(model, dict) else None
            model_signals_correction = (
                isinstance(revisions, list)
                and len(revisions) > 1
            ) or (
                isinstance(evidence, list)
                and any(
                    isinstance(item, dict)
                    and item.get("id") == "EVD-CITATION-CORRECTION"
                    for item in evidence
                )
            )
        except OSError as exc:
            errors.append(
                f"{stage_root / 'report-model.json'}: cannot inspect correction signal: {exc}"
            )
        except ValueError:
            pass
        if manifest_signals_correction or model_signals_correction:
            errors.append(
                f"{provenance_path}: correction-signalling run lacks manifest-bound provenance"
            )
        return errors
    if _is_regular_file(evidence_copy):
        errors.append(
            f"{evidence_copy}: correction provenance belongs in stage-output so it can be manifest-bound"
        )
    try:
        raw = _load_json(provenance_path, "correction provenance")
        expected_fields = {
            "schema_version", "assessment_id", "run_key", "correction_type",
            "supersedes_run_key", "supersedes_report",
            "superseded_report_sha256", "previous_report_model_sha256",
            "current_report_model_sha256", "reused_from_run",
            "reused_evidence_scope", "changed_claims", "changed_findings",
            "changed_scores", "changed_decision", "changed_runtime_status",
            "citation_corrections", "added_evidence", "verification",
        }
        if not isinstance(raw, dict) or set(raw) != expected_fields:
            raise ValueError("correction provenance has missing or unexpected fields")
        if raw["schema_version"] != 1 or raw["correction_type"] != "citation_only":
            raise ValueError("unsupported correction provenance schema or type")
        if raw["assessment_id"] != assessment.name or raw["run_key"] != run_key:
            raise ValueError("correction provenance identity does not match its run")
        previous_run = raw["supersedes_run_key"]
        if (
            not isinstance(previous_run, str)
            or not RUN_KEY.fullmatch(previous_run)
            or raw["reused_from_run"] != previous_run
            or previous_run == run_key
        ):
            raise ValueError("correction provenance has an invalid superseded run")
        if any(raw[field] != [] for field in ("changed_claims", "changed_findings", "changed_scores")):
            raise ValueError("citation-only correction cannot change claims, findings, or scores")
        if raw["changed_decision"] is not False or raw["changed_runtime_status"] is not False:
            raise ValueError("citation-only correction cannot change decision or runtime status")
        if (
            not isinstance(raw["reused_evidence_scope"], list)
            or not raw["reused_evidence_scope"]
            or any(not isinstance(item, str) or not item.strip() for item in raw["reused_evidence_scope"])
        ):
            raise ValueError("reused_evidence_scope must contain non-empty strings")

        report_root = assessment / "reports"
        previous_report_name = raw["supersedes_report"]
        if (
            not isinstance(previous_report_name, str)
            or Path(previous_report_name).name != previous_report_name
            or Path(previous_report_name).suffix.casefold() != ".docx"
            or previous_run not in previous_report_name
        ):
            raise ValueError("superseded report name is invalid")
        previous_report = report_root / previous_report_name
        if not _is_regular_file(previous_report):
            raise ValueError("superseded report must be a regular non-symlink file")
        if _sha256(previous_report) != _validated_digest(
            raw["superseded_report_sha256"], "superseded report digest"
        ):
            raise ValueError("superseded report digest mismatch")

        previous_model_path = assessment / "stage-output" / previous_run / "report-model.json"
        current_model_path = stage_root / "report-model.json"
        previous_model = _load_json(previous_model_path, "superseded report model")
        current_model = _load_json(current_model_path, "current report model")
        if not isinstance(previous_model, dict) or not isinstance(current_model, dict):
            raise ValueError("correction report models must be JSON objects")
        if _sha256(previous_model_path) != _validated_digest(
            raw["previous_report_model_sha256"], "superseded report model digest"
        ):
            raise ValueError("superseded report model digest mismatch")
        if _sha256(current_model_path) != _validated_digest(
            raw["current_report_model_sha256"], "current report model digest"
        ):
            raise ValueError("current report model digest mismatch")

        corrections = raw["citation_corrections"]
        correction_fields = {
            "reference", "old_url", "old_url_disposition", "new_url"
        }
        if (
            not isinstance(corrections, list)
            or len(corrections) != 1
            or not isinstance(corrections[0], dict)
            or set(corrections[0]) != correction_fields
        ):
            raise ValueError("citation-only correction must declare exactly one URL change")
        correction = corrections[0]
        if (
            not isinstance(correction["old_url"], str)
            or not correction["old_url"].startswith("https://")
            or not isinstance(correction["new_url"], str)
            or not correction["new_url"].startswith("https://")
            or correction["old_url"] == correction["new_url"]
            or not isinstance(correction["old_url_disposition"], str)
            or not correction["old_url_disposition"].strip()
        ):
            raise ValueError("citation correction URLs or disposition are invalid")
        reference_id = correction["reference"]
        previous_references = previous_model.get("references")
        current_references = current_model.get("references")
        if not isinstance(previous_references, list) or not isinstance(current_references, list):
            raise ValueError("report model references are invalid")
        previous_by_id = {
            item.get("id"): item for item in previous_references if isinstance(item, dict)
        }
        current_by_id = {
            item.get("id"): item for item in current_references if isinstance(item, dict)
        }
        if (
            len(previous_by_id) != len(previous_references)
            or len(current_by_id) != len(current_references)
            or set(previous_by_id) != set(current_by_id)
            or reference_id not in previous_by_id
        ):
            raise ValueError("reference identities changed outside the declared correction")
        changed_reference_ids = [
            item_id for item_id in previous_by_id
            if previous_by_id[item_id] != current_by_id[item_id]
        ]
        if changed_reference_ids != [reference_id]:
            raise ValueError("reference changes do not match the declared correction")
        old_reference = copy.deepcopy(previous_by_id[reference_id])
        new_reference = copy.deepcopy(current_by_id[reference_id])
        old_url = old_reference.pop("url", None)
        new_url = new_reference.pop("url", None)
        if (
            old_reference != new_reference
            or old_url != correction["old_url"]
            or new_url != correction["new_url"]
        ):
            raise ValueError("declared citation change does not match the report models")

        added_evidence = raw["added_evidence"]
        previous_evidence = previous_model.get("evidence")
        current_evidence = current_model.get("evidence")
        if (
            not isinstance(added_evidence, str)
            or not isinstance(previous_evidence, list)
            or not isinstance(current_evidence, list)
        ):
            raise ValueError("correction evidence declaration is invalid")
        previous_evidence_by_id = {
            item.get("id"): item for item in previous_evidence if isinstance(item, dict)
        }
        current_evidence_by_id = {
            item.get("id"): item for item in current_evidence if isinstance(item, dict)
        }
        if (
            len(previous_evidence_by_id) != len(previous_evidence)
            or len(current_evidence_by_id) != len(current_evidence)
            or set(current_evidence_by_id) - set(previous_evidence_by_id) != {added_evidence}
            or set(previous_evidence_by_id) - set(current_evidence_by_id)
            or any(
                previous_evidence_by_id[item_id] != current_evidence_by_id[item_id]
                for item_id in previous_evidence_by_id
            )
        ):
            raise ValueError("evidence changes exceed the declared correction record")

        normalized_previous = copy.deepcopy(previous_model)
        normalized_current = copy.deepcopy(current_model)
        for model in (normalized_previous, normalized_current):
            model.pop("revision_history", None)
        normalized_current["run_key"] = normalized_previous.get("run_key")
        normalized_current["document_version"] = normalized_previous.get("document_version")
        normalized_current["references"] = normalized_previous.get("references")
        normalized_current["evidence"] = normalized_previous.get("evidence")
        if normalized_current != normalized_previous:
            raise ValueError("report model changes exceed the citation-only allowlist")

        verification = raw["verification"]
        if (
            not isinstance(verification, dict)
            or set(verification) != {
                "official_host", "replacement_url_http_status", "redirect_limit",
                "verified_at", "tracking_issue",
            }
            or not isinstance(verification["official_host"], str)
            or not verification["official_host"].strip()
            or verification["replacement_url_http_status"] != 200
            or verification["redirect_limit"] != 0
            or not isinstance(verification["verified_at"], str)
            or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})",
                verification["verified_at"],
            )
            or not isinstance(verification["tracking_issue"], str)
            or not verification["tracking_issue"].isdigit()
        ):
            raise ValueError("correction verification record is invalid")

        manifest_path = stage_root / "stage-manifest.json"
        manifest = _load_json(manifest_path, "stage manifest")
        entry = manifest.get("correction_provenance") if isinstance(manifest, dict) else None
        if (
            not isinstance(entry, dict)
            or set(entry) != {"file", "status", "sha256"}
            or entry.get("file") != provenance_path.name
            or entry.get("status") != "Validated"
            or entry.get("sha256") != _sha256(provenance_path)
        ):
            raise ValueError("stage manifest does not hash-bind correction provenance")
    except (OSError, ValueError) as exc:
        errors.append(f"{provenance_path}: {exc}")
    return errors


def _is_real_directory(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(metadata.st_mode) and not is_link_or_reparse(metadata)


def _is_regular_file(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(metadata.st_mode) and not is_link_or_reparse(metadata)


def validate_assessment(assessment: Path) -> list[str]:
    errors: list[str] = []
    sources = assessment / "source-snapshot"
    evidence = assessment / "evidence"
    stages = assessment / "stage-output"
    reports = assessment / "reports"

    for parent in (sources, evidence, stages, reports):
        if not _is_real_directory(parent):
            errors.append(
                f"{assessment}: missing or non-regular required directory {parent.name}/"
            )

    if errors:
        return errors

    for parent in (sources, evidence, stages):
        loose = sorted(path.name for path in parent.iterdir() if path.is_file() or path.is_symlink())
        if loose:
            errors.append(f"{parent}: files or symlinks must be inside run directories: {', '.join(loose)}")

    source_runs = {path.name for path in sources.iterdir() if _is_real_directory(path)}
    evidence_runs = {path.name for path in evidence.iterdir() if _is_real_directory(path)}
    stage_runs = {path.name for path in stages.iterdir() if _is_real_directory(path)}
    all_runs = source_runs | evidence_runs | stage_runs

    for run_key in sorted(all_runs):
        if not RUN_KEY.fullmatch(run_key):
            errors.append(f"{assessment}: invalid run key {run_key!r}")
            continue
        if run_key not in source_runs:
            errors.append(f"{assessment}: missing source-snapshot/{run_key}/")
        if run_key not in evidence_runs:
            errors.append(f"{assessment}: missing evidence/{run_key}/")
        if run_key not in stage_runs:
            errors.append(f"{assessment}: missing stage-output/{run_key}/")
        for parent in (sources, evidence, stages):
            run = parent / run_key
            symlinks = (
                sorted(str(path.relative_to(run)) for path in run.rglob("*") if path.is_symlink())
                if _is_real_directory(run)
                else []
            )
            if symlinks:
                errors.append(f"{run}: symlinks are prohibited: {', '.join(symlinks)}")
            if _is_real_directory(run) and not any(
                _is_regular_file(path) for path in run.rglob("*")
            ):
                errors.append(f"{run}: run directory is empty")
        manifest = sources / run_key / "snapshot-manifest.json"
        if run_key in source_runs and not _is_regular_file(manifest):
            errors.append(f"{sources / run_key}: missing snapshot-manifest.json")
        matching_reports = sorted(
            path
            for path in reports.iterdir()
            if path.suffix.casefold() == ".docx" and run_key in path.name
        )
        regular_reports = [
            path for path in matching_reports if _is_regular_file(path)
        ]
        if not matching_reports:
            errors.append(f"{reports}: no DOCX report filename contains run key {run_key}")
        elif len(matching_reports) != 1:
            errors.append(
                f"{reports}: expected exactly one DOCX report for {run_key}, "
                f"found {len(matching_reports)}"
            )
        elif not regular_reports:
            errors.append(f"{matching_reports[0]}: report must be a regular non-symlink file")
        if run_key in source_runs and run_key in evidence_runs and run_key in stage_runs:
            errors.extend(_validate_citation_correction(assessment, run_key))

    if not all_runs:
        errors.append(f"{assessment}: no versioned evidence/stage-output runs found")
    return errors


def validate_root(root: Path) -> list[str]:
    assessments = root / "assessments"
    if not _is_real_directory(assessments):
        return [f"{root}: missing or non-regular assessments/ directory"]
    visible = sorted(path for path in assessments.iterdir() if not path.name.startswith("."))
    invalid = [path for path in visible if not _is_real_directory(path)]
    if invalid:
        return [
            f"{path}: assessment target must be a real directory"
            for path in invalid
        ]
    targets = visible
    if not targets:
        return [f"{assessments}: no assessment directories found"]
    return [error for target in targets for error in validate_assessment(target)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    errors = validate_root(args.root.resolve())
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("PASS: source, evidence, and stage-output runs use matching date-version directories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
