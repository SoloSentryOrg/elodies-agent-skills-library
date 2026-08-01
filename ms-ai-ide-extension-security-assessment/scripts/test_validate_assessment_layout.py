import tempfile
import unittest
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from validate_assessment_layout import _validate_citation_correction, validate_root


class AssessmentLayoutTests(unittest.TestCase):
    def make_target(self, root: Path, run_key: str = "2026-07-17-v1.0") -> Path:
        target = root / "assessments" / "Example MCP"
        (target / "source-snapshot" / run_key).mkdir(parents=True)
        (target / "evidence" / run_key).mkdir(parents=True)
        (target / "stage-output" / run_key).mkdir(parents=True)
        (target / "reports").mkdir()
        (target / "source-snapshot" / run_key / "snapshot-manifest.json").write_text(
            "{}", encoding="utf-8"
        )
        (target / "evidence" / run_key / "evidence.json").write_text("{}", encoding="utf-8")
        (target / "stage-output" / run_key / "01-intake.md").write_text("ready", encoding="utf-8")
        (target / "reports" / f"Example-MCP-{run_key}.docx").write_bytes(b"document")
        return target

    def test_accepts_matched_versioned_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_target(root)
            self.assertEqual(validate_root(root), [])

    def test_rejects_loose_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            (target / "evidence" / "loose.json").write_text("{}", encoding="utf-8")
            errors = validate_root(root)
            self.assertTrue(any("files or symlinks" in error for error in errors))

    def test_rejects_unpaired_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            (target / "stage-output" / "2026-07-17-v1.0" / "01-intake.md").unlink()
            (target / "stage-output" / "2026-07-17-v1.0").rmdir()
            errors = validate_root(root)
            self.assertTrue(any("missing stage-output/2026-07-17-v1.0/" in error for error in errors))

    def test_rejects_missing_snapshot_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            (target / "source-snapshot" / "2026-07-17-v1.0" / "snapshot-manifest.json").unlink()
            errors = validate_root(root)
            self.assertTrue(any("missing snapshot-manifest.json" in error for error in errors))

    def test_rejects_nested_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            (target / "evidence" / "2026-07-17-v1.0" / "linked.json").symlink_to("evidence.json")
            errors = validate_root(root)
            self.assertTrue(any("symlinks are prohibited" in error for error in errors))

    def test_rejects_run_without_matching_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            (target / "reports" / "Example-MCP-2026-07-17-v1.0.docx").rename(
                target / "reports" / "Example-MCP.docx"
            )
            errors = validate_root(root)
            self.assertTrue(any("no DOCX report filename contains run key" in error for error in errors))

    def test_rejects_non_docx_report_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            report = target / "reports" / "Example-MCP-2026-07-17-v1.0.docx"
            report.rename(report.with_suffix(".txt"))
            errors = validate_root(root)
            self.assertTrue(any("no DOCX report filename contains run key" in error for error in errors))

    def test_rejects_report_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            report = target / "reports" / "Example-MCP-2026-07-17-v1.0.docx"
            report.unlink()
            report.symlink_to("../source-snapshot/2026-07-17-v1.0/snapshot-manifest.json")
            errors = validate_root(root)
            self.assertTrue(any("regular non-symlink" in error for error in errors))

    def test_rejects_run_directory_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            run = target / "evidence" / "2026-07-17-v1.0"
            external = root / "external-evidence"
            run.rename(external)
            run.symlink_to(external, target_is_directory=True)
            errors = validate_root(root)
            self.assertTrue(any("files or symlinks" in error for error in errors))
            self.assertTrue(
                any("missing evidence/2026-07-17-v1.0/" in error for error in errors)
            )

    def test_rejects_required_directory_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            evidence = target / "evidence"
            external = root / "external-evidence"
            evidence.rename(external)
            evidence.symlink_to(external, target_is_directory=True)
            errors = validate_root(root)
            self.assertTrue(any("non-regular required directory evidence/" in error for error in errors))

    def test_validates_hash_bound_citation_only_correction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self.make_target(root)
            previous_run = "2026-07-17-v1.0"
            current_run = "2026-07-17-v1.1"
            (target / "source-snapshot" / current_run).mkdir()
            (target / "evidence" / current_run).mkdir()
            (target / "stage-output" / current_run).mkdir()
            (target / "source-snapshot" / current_run / "snapshot-manifest.json").write_text(
                "{}", encoding="utf-8"
            )
            (target / "evidence" / current_run / "evidence.json").write_text(
                "{}", encoding="utf-8"
            )
            (target / "stage-output" / current_run / "01-intake.md").write_text(
                "ready", encoding="utf-8"
            )
            (target / "reports" / f"Example-MCP-{current_run}.docx").write_bytes(
                b"corrected document"
            )
            previous_model = {
                "run_key": previous_run,
                "document_version": "1.0",
                "decision": "Defer pending evidence",
                "findings": [{"id": "F-001", "severity": "High"}],
                "evidence": [{"id": "EVD-BASE", "state": "Verified"}],
                "references": [{"id": "REF-001", "url": "https://example.com/old", "title": "Guide"}],
            }
            current_model = {
                **previous_model,
                "run_key": current_run,
                "document_version": "1.1",
                "revision_history": [
                    {"version": "1.0", "date": "2026-07-17"},
                    {"version": "1.1", "date": "2026-07-17"},
                ],
                "evidence": [
                    *previous_model["evidence"],
                    {"id": "EVD-CITATION-CORRECTION", "state": "Verified"},
                ],
                "references": [{"id": "REF-001", "url": "https://example.com/new", "title": "Guide"}],
            }
            previous_model_path = target / "stage-output" / previous_run / "report-model.json"
            current_stage = target / "stage-output" / current_run
            current_model_path = current_stage / "report-model.json"
            previous_model_path.write_text(json.dumps(previous_model), encoding="utf-8")
            current_model_path.write_text(json.dumps(current_model), encoding="utf-8")
            previous_report = target / "reports" / f"Example-MCP-{previous_run}.docx"
            current_report = target / "reports" / f"Example-MCP-{current_run}.docx"
            sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            provenance = {
                "schema_version": 1,
                "assessment_id": "Example MCP",
                "run_key": current_run,
                "correction_type": "citation_only",
                "supersedes_run_key": previous_run,
                "supersedes_report": previous_report.name,
                "superseded_report_sha256": sha(previous_report),
                "previous_report_model_sha256": sha(previous_model_path),
                "current_report_model_sha256": sha(current_model_path),
                "reused_from_run": previous_run,
                "reused_evidence_scope": ["source snapshot"],
                "changed_claims": [],
                "changed_findings": [],
                "changed_scores": [],
                "changed_decision": False,
                "changed_runtime_status": False,
                "citation_corrections": [{
                    "reference": "REF-001",
                    "old_url": "https://example.com/old",
                    "old_url_disposition": "redirect rejected",
                    "new_url": "https://example.com/new",
                }],
                "added_evidence": "EVD-CITATION-CORRECTION",
                "verification": {
                    "official_host": "example.com",
                    "replacement_url_http_status": 200,
                    "redirect_limit": 0,
                    "verified_at": "2026-07-17T12:00:00Z",
                    "tracking_issue": "41",
                },
            }
            provenance_path = current_stage / "correction-provenance.json"
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            manifest = {
                "correction_provenance": {
                    "file": provenance_path.name,
                    "status": "Validated",
                    "sha256": sha(provenance_path),
                }
            }
            (current_stage / "stage-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(validate_root(root), [])

            previous_report_bytes = previous_report.read_bytes()
            previous_report.unlink()
            previous_report.symlink_to(current_report)
            errors = validate_root(root)
            self.assertTrue(
                any(
                    "superseded report must be a regular non-symlink file" in error
                    for error in errors
                )
            )
            previous_report.unlink()
            previous_report.write_bytes(previous_report_bytes)

            provenance_path.unlink()
            errors = validate_root(root)
            self.assertTrue(any("lacks manifest-bound provenance" in error for error in errors))
            current_model_path.write_text("{", encoding="utf-8")
            errors = validate_root(root)
            self.assertTrue(any("lacks manifest-bound provenance" in error for error in errors))
            current_model_path.write_text(json.dumps(current_model), encoding="utf-8")
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

            current_model["findings"][0]["severity"] = "Critical"
            current_model_path.write_text(json.dumps(current_model), encoding="utf-8")
            provenance["current_report_model_sha256"] = sha(current_model_path)
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            manifest["correction_provenance"]["sha256"] = sha(provenance_path)
            (current_stage / "stage-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            errors = validate_root(root)
            self.assertTrue(any("exceed the citation-only allowlist" in error for error in errors))

    def test_correction_signal_probe_reports_io_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assessment = Path(directory) / "Example MCP"
            run_key = "2026-07-17-v1.1"
            stage_root = assessment / "stage-output" / run_key
            stage_root.mkdir(parents=True)
            with patch(
                "validate_assessment_layout._load_json",
                side_effect=[OSError("read denied"), {}],
            ):
                errors = _validate_citation_correction(assessment, run_key)
            self.assertTrue(
                any("cannot inspect correction signal" in error for error in errors)
            )


if __name__ == "__main__":
    unittest.main()
