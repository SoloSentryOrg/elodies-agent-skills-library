#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline tests for the schema-driven PowerPoint assessment builder."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import platform
import tempfile
import textwrap
import unittest
import venv
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_assessment_pptx.mjs"
RECEIPT = ROOT / "scripts" / "create_artifact_runtime_receipt.mjs"
MONTAGE = ROOT / "scripts" / "create_pptx_montage.py"


def _presentation_skill_dir() -> Path:
    override = os.environ.get("CODEX_PRESENTATIONS_SKILL_DIR")
    if override:
        return Path(override).expanduser().resolve()
    root = Path.home() / ".codex" / "plugins" / "cache" / "openai-primary-runtime" / "presentations"
    candidates = sorted(root.glob("*/skills/presentations"))
    return candidates[-1] if candidates else root / "unavailable" / "skills" / "presentations"


SKILL_DIR = _presentation_skill_dir()
SETUP = SKILL_DIR / "container_tools" / "setup_artifact_tool_workspace.mjs"
ARTIFACT_NODE_MODULES = Path(os.environ["CODEX_ARTIFACT_NODE_MODULES"]).expanduser().resolve() if os.environ.get("CODEX_ARTIFACT_NODE_MODULES") else None
BUNDLED_ARTIFACT_AVAILABLE = ARTIFACT_NODE_MODULES is not None and (ARTIFACT_NODE_MODULES / "@oai" / "artifact-tool" / "package.json").is_file()
def valid_model() -> dict[str, object]:
    references = [
        {
            "id": f"REF-{index:03d}",
            "title": f"Primary source {index}",
            "publisher": "Example Publisher",
            "url": f"https://example.com/source/{index}",
            "accessed": "2026-08-01",
            "applicability": "Supports the synthetic assessment claim.",
        }
        for index in range(1, 13)
    ]
    findings = []
    for index in range(1, 3):
        findings.append({
            "id": f"F-{index:03d}",
            "title": f"Synthetic risk {index}",
            "scope": "VS Code",
            "scenario": f"A synthetic attacker scenario is assessed. REF-{index:03d}",
            "evidence_ids": f"EVD-TEST-{index:03d}",
            "likelihood": "2",
            "impact": "3",
            "inherent": "6 Moderate",
            "controls": "Workspace trust and explicit approval.",
            "control_strength": "Moderate",
            "residual_likelihood": "1",
            "residual_impact": "3",
            "residual": "3 Low",
            "recommendation": f"Verify least privilege before deployment. REF-{index:03d}",
            "owner": "Extension service owner",
            "priority": "P2",
            "target_date": "Before deployment",
            "verification": "Confirm the permission boundary with synthetic data.",
            "mappings": "OWASP Agentic Security",
            "confidence": "Moderate",
        })
    sections = [
        {"id": f"section.{index:02d}", "heading": f"Section {index}", "level": 1, "paragraphs": [], "bullets": [], "tables": []}
        for index in range(1, 21)
    ]
    evidence = [
        {"id": f"EVD-TEST-{index:03d}", "title": f"Evidence {index}", "source": "Synthetic fixture", "method": "Static inspection", "state": "Verified", "limitation": "Synthetic only"}
        for index in range(1, 6)
    ]
    return {
        "schema_version": 2,
        "assessment": "Synthetic MCP Extension",
        "target": "Synthetic MCP Extension",
        "publisher": "Example Publisher",
        "extension_id": "example.synthetic-mcp",
        "version": "1.2.3",
        "run_key": "2026-08-01-v1.0",
        "assessment_date": "2026-08-01",
        "document_version": "1.0",
        "classification": "PUBLIC",
        "decision": "Approve with conditions",
        "overall_residual_risk": "Moderate",
        "review_trigger": "New permissions, runtime evidence, or a material version change. REF-001",
        "ide_scope": ["VS Code"],
        "executive_outcomes": [f"Outcome {index} is supported by synthetic evidence. REF-{index:03d}" for index in range(1, 6)],
        "approval_conditions": [f"Condition {index} must be verified before deployment. REF-{index:03d}" for index in range(1, 5)],
        "sections": sections,
        "findings": findings,
        "evidence": evidence,
        "references": references,
        "glossary": [{"term": f"Term {index}", "definition": "Synthetic definition"} for index in range(1, 6)],
        "figure": {
            "title": "Synthetic trust boundaries",
            "alt_text": "A synthetic IDE host connects to an MCP client and service. REF-001",
            "nodes": ["IDE host", "MCP client", "MCP service"],
            "edges": [["IDE host", "MCP client", "invokes"], ["MCP client", "MCP service", "HTTPS"]],
        },
        "derivative_sources": {
            "cover": ["EVD-TEST-001", "REF-001"],
            "executive_outcomes": [[f"EVD-TEST-{index:03d}", f"REF-{index:03d}"] for index in range(1, 6)],
            "approval_conditions": [[f"EVD-TEST-{index:03d}", f"REF-{index:03d}"] for index in range(1, 5)],
            "figure": ["EVD-TEST-001", "REF-001"],
            "findings": {f"F-{index:03d}": [f"EVD-TEST-{index:03d}", f"REF-{index:03d}"] for index in range(1, 3)},
            "decision": ["EVD-TEST-001", "REF-001"],
            "review_trigger": ["EVD-TEST-001", "REF-001"],
        },
    }


class AssessmentPptxTests(unittest.TestCase):
    def test_v5_structure_preserves_authoring_and_requires_native_measurements(self) -> None:
        probe = r'''
          const fs = require("node:fs");
          const vm = require("node:vm");
          const assert = require("node:assert/strict");
          const source = fs.readFileSync(process.argv[1], "utf8");
          const start = source.indexOf("function validateV5Structure(");
          const end = source.indexOf("\nfunction validateLayout(", start);
          assert.ok(start >= 0 && end > start);
          const check = vm.runInNewContext(`(${source.slice(start, end)})`, { ModelError: Error, Buffer }, { timeout: 1000 });
          const expected = [{ name: "title", text: "Readable title", singleLine: true, bbox: [40, 40, 1200, 60] }];
          const title = { name: "title", text: "Readable title", kind: "textbox", scope: "slide", editable: true,
            position: { left: 40, top: 40, width: 1200, height: 60 }, style: { fontSize: 1 } };
          const manifest = () => ({ schema: "openai.presentation.layout/v5", unit: "px",
            slide: { position: { left: 0, top: 0, width: 1280, height: 720 } }, inheritedLayers: [], elements: [title] });
          const invoke = (value, authoring = expected) => check(JSON.stringify(value), "test-slide", authoring);
          const result = invoke(manifest());
          assert.equal(result.nativeMeasurementsRequired, true);
          assert.ok(Object.isFrozen(result));
          // A nominal renderer font or missing line count cannot establish acceptance.
          assert.equal(result.schema, "openai.presentation.layout/v5");
          for (const change of [
            { text: "Changed" }, { name: "renamed" }, { editable: false }, { kind: "shape" },
            { position: { ...title.position, left: 41 } }, { children: [] },
            { position: { left: 0, top: 0, width: 1281, height: 60 } },
          ]) {
            const value = manifest(); value.elements = [{ ...title, ...change }];
            assert.throws(() => invoke(value));
          }
          const duplicate = manifest(); duplicate.elements.push({ ...title });
          assert.throws(() => invoke(duplicate), /differs/);
          const extra = manifest(); extra.elements.push({ ...title, name: "unreviewed", text: "Extra" });
          assert.throws(() => invoke(extra), /unbound/);
          const inherited = manifest(); inherited.inheritedLayers = [{ scope: "master", elements: [{ ...title, scope: "master", name: "hidden" }] }];
          assert.throws(() => invoke(inherited), /unbound/);
          const missing = manifest(); missing.elements = [{ kind: "shape", scope: "slide", position: title.position }];
          assert.throws(() => invoke(missing), /missing authored/);
          for (const value of [{ ...manifest(), unit: "pt" }, { ...manifest(), schema: "openai.presentation.layout/v4" },
            { ...manifest(), slide: { position: { left: 0, top: 0, width: 960, height: 540 } } },
            { ...manifest(), inheritedLayers: null },
            { ...manifest(), inheritedLayers: [{ scope: "slide", elements: [] }] }]) assert.throws(() => invoke(value), /unsupported/);
          const bounds = manifest(); bounds.elements = Array(4097).fill(title);
          assert.throws(() => invoke(bounds), /exceeds bounds/);
          assert.throws(() => check(" ".repeat(8 * 1024 * 1024 + 1), "oversized", expected), /oversized/);
          assert.throws(() => invoke(manifest(), [{ ...expected[0], bbox: null }]), /invalid authored/);
        '''
        result = subprocess.run(["node", "-e", probe, str(SCRIPT)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_private_candidate_hash_and_mode_boundaries(self) -> None:
        evidence = self.root / "bound.layout.json"
        evidence.write_text('{"schema":"openai.presentation.layout/v5"}', encoding="utf-8")
        probe = r'''
          const fs = require("node:fs");
          const fsp = require("node:fs/promises");
          const vm = require("node:vm");
          const path = require("node:path");
          const crypto = require("node:crypto");
          const assert = require("node:assert/strict");
          const source = fs.readFileSync(process.argv[1], "utf8");
          const begin = source.indexOf("async function verifyCandidateFiles(");
          const end = source.indexOf("\nasync function buildPrivateV5Candidate(", begin);
          const sha256 = data => crypto.createHash("sha256").update(data).digest("hex");
          const check = vm.runInNewContext(`(${source.slice(begin, end)})`, {
            ModelError: Error, path, sha256,
            readStableRegularFile: async file => ({data: await fsp.readFile(file)}),
          }, {timeout: 1000});
          const argStart = source.indexOf("function parseArgs(");
          const argEnd = source.indexOf("\nfunction text(", argStart);
          const parse = vm.runInNewContext(`(${source.slice(argStart, argEnd)})`, {
            ModelError: Error, process: {env: {}},
          }, {timeout: 1000});
          const directory = process.argv[2];
          const file = path.join(directory, "bound.layout.json");
          const data = fs.readFileSync(file);
          const binding = {file: "bound.layout.json", size: data.length, sha256: sha256(data)};
          (async () => {
            await check(directory, [binding]);
            await assert.rejects(check(directory, [{...binding, sha256: "0".repeat(64)}]), /immutable binding/);
            await assert.rejects(check(directory, [{...binding, file: "../escape.json"}]), /invalid/);
            await assert.rejects(check(directory, [binding, binding]), /invalid/);
            await fsp.writeFile(file, Buffer.concat([data, Buffer.from("changed")]));
            await assert.rejects(check(directory, [binding]), /immutable binding/);
            for (const incompatible of [["--output", "normal.pptx"], ["--build-manifest", "normal.json"],
                ["--qa-dir", "normal-qa"], ["--validate-only"]]) {
              assert.throws(() => parse(["--v5-candidate-dir", "private", ...incompatible]), /cannot use normal/);
            }
          })().catch(error => { console.error(error); process.exitCode = 1; });
        '''
        result = subprocess.run(["node", "-e", probe, str(SCRIPT), str(self.root)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_layout_gate_rejects_incomplete_rendering_evidence(self) -> None:
        """Exercise the actual guard with malformed evidence, not authored models."""
        probe = r'''
          const fs = require("node:fs");
          const vm = require("node:vm");
          const assert = require("node:assert/strict");
          const source = fs.readFileSync(process.argv[1], "utf8");
          const start = source.indexOf("function validateLayout(");
          const end = source.indexOf("\nasync function createMontage(", start);
          assert.ok(start >= 0 && end > start);
          const validate = vm.runInNewContext(`(${source.slice(start, end)})`, {
            ModelError: Error, Buffer,
          }, { timeout: 1000 });
          const title = { name: "slide-title-1", bbox: [40, 40, 1200, 60],
            text: "Readable title", resolvedFontSize: 32, textLayout: { lineCount: 1 } };
          const expectations = [{ name: title.name, text: title.text, singleLine: true }];
          const validateGuard = validate;
          // Geometry-only controls explicitly author no text; every text control
          // is bound to the trusted title, irrespective of renderer omissions.
          const check = (value, stem, expected = expectations) => validateGuard(value, stem, expected);
          const manifest = (elements) => JSON.stringify({
            schema: "openai.presentation.layout/v4", elements,
          });
          check(manifest([title]), "valid");
          // A line's zero-height geometry remains permitted.
          check(manifest([{ bbox: [40, 140, 800, 0] }]), "line", []);
          for (const bbox of [undefined, [], [0, 0, 100], "0,0,100,100"]) {
            const unsafe = { ...title, bbox, resolvedFontSize: 1,
              textLayout: { lineCount: 3 } };
            assert.throws(() => check(manifest([unsafe]), "incomplete"),
              /incomplete layout bounds/);
          }
          for (const element of [null, false, 42, [], "text"]) {
            assert.throws(() => check(manifest([element]), "invalid"),
              /incomplete layout bounds/);
          }
          assert.throws(() => check(manifest([]), "empty"), /unsupported/);
          check(manifest(Array(4096).fill({ bbox: [40, 140, 800, 0] })), "count-boundary", []);
          assert.throws(() => check(manifest(Array(4097).fill(title)), "count"), /unsupported/);
          assert.throws(() => check(" ".repeat(8 * 1024 * 1024 + 1), "size"), /oversized/);
          assert.throws(() => check(null, "non-string"), /invalid layout manifest/);
          assert.throws(() => check("{", "invalid-json"));
          for (const bbox of [[null, 0, 100, 100], ["0", 0, 100, 100],
            [0, 0, -1, 100], [0, 0, 100, -1]]) {
            assert.throws(() => check(manifest([{ ...title, bbox }]), "coordinates"), /overflows/);
          }
          assert.throws(() => check(manifest([{ ...title, bbox: [0, 0, 1281, 100] }]),
            "overflow"), /overflows/);
          assert.throws(() => check(manifest([{ ...title, resolvedFontSize: 15 }]),
            "tiny"), /below 16pt/);
          assert.throws(() => check(manifest([{ ...title, textLayout: { lineCount: 2 } }]),
            "wrapped"), /wraps/);
          assert.throws(() => check(JSON.stringify({
            schema: "openai.presentation.layout/v5", elements: [title],
          }), "unsupported-runtime"), /unsupported/);
          assert.throws(() => validateGuard(manifest([title]), "missing-authoring"), /authored text expectations/);
          for (const text of [undefined, null, "", "Other text", 42]) {
            assert.throws(() => check(manifest([{ ...title, text }]), "omitted-text"), /authored text evidence/);
          }
          assert.throws(() => check(manifest([{ ...title, name: "footer-forged" }]), "renamed"), /unbound/);
          assert.throws(() => check(manifest([{ bbox: [40, 140, 800, 0] }]), "missing-text"), /missing authored/);
          assert.throws(() => check(manifest([title, title]), "duplicate"), /duplicate authored/);
          for (const textLayout of [undefined, {}, { lineCount: 0 }, { lineCount: 1.5 }, { lineCount: "1" }]) {
            assert.throws(() => check(manifest([{ ...title, textLayout }]), "lines"), /line-layout/);
          }
          const footer = { ...title, name: "footer-number-1", resolvedFontSize: 15 };
          assert.throws(() => check(manifest([footer]), "tiny-footer", [
            { name: footer.name, text: footer.text, singleLine: false },
          ]), /below 16pt/);
          for (const expected of [null, {}, [{ ...expectations[0], text: "" }],
            [expectations[0], expectations[0]], [{ ...expectations[0], singleLine: "false" }]]) {
            assert.throws(() => check(manifest([title]), "invalid-authoring", expected), /authored text expectations/);
          }
        '''
        result = subprocess.run(
            ["node", "-e", probe, str(SCRIPT)], capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_authored_text_is_independent_of_renderer_metadata(self) -> None:
        probe = r'''
          const fs = require("node:fs");
          const vm = require("node:vm");
          const assert = require("node:assert/strict");
          const source = fs.readFileSync(process.argv[1], "utf8");
          const start = source.indexOf("function addText(");
          const end = source.indexOf("\nfunction addFooter(", start);
          const authored = new WeakMap();
          const add = vm.runInNewContext(`(${source.slice(start, end)})`, {
            ModelError: Error, AUTHORED_TEXT: authored,
          }, { timeout: 1000 });
          const shapes = [];
          const slide = { shapes: { add(config) {
            const shape = { config };
            Object.defineProperty(shape, "text", {
              get() { return this.frame; }, set(value) { this.frame = { value }; },
            });
            shapes.push(shape); return shape;
          } } };
          add(slide, "slide-title-2", "Exact title", { left: 40, top: 40, width: 1200, height: 60 }, 40);
          add(slide, "body-2", "Two lines\nExact body", { left: 40, top: 140, width: 1200, height: 100 }, 18);
          add(slide, "footer-number-2", "2", { left: 1100, top: 660, width: 100, height: 28 }, 16);
          const expected = authored.get(slide);
          assert.equal(expected.length, 3);
          assert.equal(expected[0].singleLine, true);
          assert.equal(expected[1].singleLine, false);
          assert.equal(expected[2].singleLine, false);
          assert.equal(expected[1].text, "Two lines\nExact body");
          assert.ok(expected.every(Object.isFrozen));
          assert.ok(expected.every((item) => Object.isFrozen(item.bbox)));
          assert.equal(JSON.stringify(expected[0].bbox), JSON.stringify([40, 40, 1200, 60]));
          shapes[0].config.position.left = 0;
          assert.equal(expected[0].bbox[0], 40);
          shapes[0].frame.value = "Renderer altered title";
          shapes[0].config.name = "footer-forged";
          assert.equal(expected[0].text, "Exact title");
          assert.equal(expected[0].name, "slide-title-2");
          assert.equal(shapes[2].frame.style.fontSize, 16 * 96 / 72);
          assert.throws(() => add(slide, "slide-title-2", "Duplicate", {}, 40), /duplicate/);
          assert.equal(authored.get(slide).length, 3);
          assert.equal(shapes.length, 3);
        '''
        result = subprocess.run(
            ["node", "-e", probe, str(SCRIPT)], capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.stage_root = self.root / "stage-output"
        self.input = self.stage_root / "report-model.json"

    def write_word_closeout(self, model: dict[str, object]) -> list[str]:
        docx = self.root / "authoritative.docx"
        with zipfile.ZipFile(docx, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document/>")
        docx_sha256 = hashlib.sha256(docx.read_bytes()).hexdigest()
        qa = self.root / "office-native-qa.json"
        qa_payload = {
            "schema_version": 1,
            "assessment": model["assessment"],
            "run_key": model["run_key"],
            "status": "Passed",
            "word": {
                "input_file": docx.name,
                "input_sha256": docx_sha256,
                "page_count": 3,
                "contents_starts_on_fresh_page": True,
                "every_page_inspected": True,
                "result": "Passed",
            },
        }
        qa.write_text(json.dumps(qa_payload), encoding="utf-8")
        qa_sha256 = hashlib.sha256(qa.read_bytes()).hexdigest()
        word_subrecord_sha256 = hashlib.sha256(
            json.dumps(
                qa_payload["word"],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        build = self.root / "authoritative.build.json"
        build_payload = {
            "assessment": model["assessment"],
            "run_key": model["run_key"],
            "report_model_sha256": hashlib.sha256(self.input.read_bytes()).hexdigest(),
            "output": docx.relative_to(self.root).as_posix(),
            "output_sha256": docx_sha256,
            "native_word_closeout": {
                "status": "Passed",
                "qa_record": qa.relative_to(self.root).as_posix(),
                "qa_record_sha256": qa_sha256,
                "word_subrecord_sha256": word_subrecord_sha256,
            },
        }
        build.write_text(json.dumps(build_payload), encoding="utf-8")
        return [
            "--authoritative-docx", str(docx),
            "--authoritative-build-manifest", str(build),
            "--word-qa-record", str(qa),
        ]

    def test_word_qa_binding_allows_later_powerpoint_update(self) -> None:
        model = valid_model()
        self.write_model(model)
        word_args = self.write_word_closeout(model)
        qa = self.root / "office-native-qa.json"
        payload = json.loads(qa.read_text(encoding="utf-8"))
        payload["powerpoint"] = {
            "input_file": "later.pptx",
            "input_sha256": "0" * 64,
            "slide_count": 9,
            "every_slide_inspected": True,
            "result": "Passed",
        }
        qa.write_text(json.dumps(payload), encoding="utf-8")

        result = self.run_builder(
            "--stage-root", str(self.stage_root), "--validate-only", *word_args
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["authoritative_word"])

    def test_word_qa_binding_uses_authoritative_assessment_identity(self) -> None:
        model = valid_model()
        model["target"] = "Synthetic MCP Extension (example.synthetic-mcp)"
        self.write_model(model)
        word_args = self.write_word_closeout(model)

        result = self.run_builder(
            "--stage-root", str(self.stage_root), "--validate-only", *word_args
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["authoritative_word"])

    def test_word_qa_binding_rejects_word_subrecord_change(self) -> None:
        model = valid_model()
        self.write_model(model)
        word_args = self.write_word_closeout(model)
        qa = self.root / "office-native-qa.json"
        payload = json.loads(qa.read_text(encoding="utf-8"))
        payload["word"]["page_count"] = 4
        qa.write_text(json.dumps(payload), encoding="utf-8")

        result = self.run_builder(
            "--stage-root", str(self.stage_root), "--validate-only", *word_args
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("QA subrecord digest mismatch", result.stderr)

    def test_build_requires_authoritative_word_inputs(self) -> None:
        self.write_model(valid_model())
        result = self.run_builder(
            "--stage-root", str(self.stage_root),
            "--output", str(self.root / "assessment.pptx"),
            "--build-manifest", str(self.root / "assessment.build.json"),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("are required for a build", result.stderr)

    def test_rejects_failed_top_level_word_qa_status(self) -> None:
        model = valid_model()
        self.write_model(model)
        word_args = self.write_word_closeout(model)
        qa = self.root / "office-native-qa.json"
        payload = json.loads(qa.read_text(encoding="utf-8"))
        payload["status"] = "Failed"
        qa.write_text(json.dumps(payload), encoding="utf-8")

        result = self.run_builder(
            "--stage-root", str(self.stage_root), "--validate-only", *word_args
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("QA record is incomplete", result.stderr)

    def write_model(self, model: dict[str, object]) -> None:
        self.stage_root.mkdir(parents=True, exist_ok=True)
        model_bytes = json.dumps(model, sort_keys=True).encode("utf-8")
        self.input.write_bytes(model_bytes)
        stage_entries = []
        for index in range(1, 16):
            filename = f"stage-{index:02d}.md"
            data = f"# Stage {index}\n\nAnalyst validation status: Validated\n".encode()
            (self.stage_root / filename).write_bytes(data)
            stage_entries.append({
                "stage": index,
                "file": filename,
                "status": "Validated",
                "sha256": hashlib.sha256(data).hexdigest(),
            })
        claims = {
            "schema_version": 1,
            "assessment": model["assessment"],
            "target": model["target"],
            "version": model["version"],
            "analyst_validation": "Validated",
            "claims": [{"id": "synthetic.claim", "value": "Synthetic validated claim", "evidence_ids": ["EVD-TEST-001"]}],
        }
        claim_bytes = json.dumps(claims, sort_keys=True).encode("utf-8")
        (self.stage_root / "validated-claims.json").write_bytes(claim_bytes)
        manifest = {
            "schema_version": 1,
            "assessment": model["assessment"],
            "target": model["target"],
            "version": model["version"],
            "stages": stage_entries,
            "claims": {
                "file": "validated-claims.json",
                "status": "Validated",
                "sha256": hashlib.sha256(claim_bytes).hexdigest(),
            },
            "report_model": {
                "file": "report-model.json",
                "status": "Validated",
                "sha256": hashlib.sha256(model_bytes).hexdigest(),
            },
        }
        (self.stage_root / "stage-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def write_montage_helper(self) -> Path:
        helper = self.root / "portable_montage.py"
        helper.write_text(
            textwrap.dedent(
                """\
                import argparse
                import struct
                import zlib
                from pathlib import Path

                parser = argparse.ArgumentParser()
                parser.add_argument("--input_files", nargs="+")
                parser.add_argument("--output_file", required=True)
                parser.add_argument("--num_col")
                parser.add_argument("--label_mode")
                parser.add_argument("--fail_on_image_error", action="store_true")
                args = parser.parse_args()
                width = 2000
                height = ((len(args.input_files) + 4) // 5) * 225

                def chunk(kind, data):
                    return (
                        struct.pack(">I", len(data)) + kind + data
                        + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
                    )

                rows = b"".join(b"\\x00" + (b"\\xff\\xff\\xff" * width) for _ in range(height))
                png = (
                    b"\\x89PNG\\r\\n\\x1a\\n"
                    + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(rows, 9))
                    + chunk(b"IEND", b"")
                )
                Path(args.output_file).write_bytes(png)
                """
            ),
            encoding="utf-8",
        )
        return helper

    def run_builder(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["node", str(SCRIPT), "--workspace-root", str(self.root), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
            env={**os.environ, "NO_COLOR": "1"},
        )

    def test_validate_only_accepts_word_report_model_schema(self) -> None:
        self.write_model(valid_model())
        result = self.run_builder("--stage-root", str(self.stage_root), "--validate-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(summary["status"], "validated")
        self.assertEqual(summary["findings"], 2)
        self.assertEqual(summary["references"], 12)

    def test_validate_only_accepts_detailed_ide_scope_label(self) -> None:
        model = valid_model()
        model["ide_scope"] = [
            "Static platform scope: the platform-neutral package and all bundled native prebuilds; behavioural platform scope remains Blocked."
        ]
        self.write_model(model)

        result = self.run_builder(
            "--stage-root", str(self.stage_root), "--validate-only"
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_validate_only_rejects_ide_scope_over_160_bytes(self) -> None:
        model = valid_model()
        model["ide_scope"] = ["x" * 161]
        self.write_model(model)

        result = self.run_builder(
            "--stage-root", str(self.stage_root), "--validate-only"
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("ide_scope is oversized", result.stderr)

    def test_validate_only_rejects_stage_root_outside_workspace(self) -> None:
        self.write_model(valid_model())
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / "stage-output"
            shutil.copytree(self.stage_root, outside)
            result = self.run_builder("--stage-root", str(outside), "--validate-only")
        self.assertEqual(result.returncode, 2)
        self.assertIn("workspace root", result.stderr)

    def test_validate_only_accepts_correction_revision_history(self) -> None:
        model = valid_model()
        model["document_version"] = "1.1"
        model["revision_history"] = [
            {
                "version": "1.0",
                "date": "2026-08-01",
                "status": "Assessment complete; deferred",
                "change": "Initial evidence-led assessment.",
            },
            {
                "version": "1.1",
                "date": "2026-08-01",
                "status": "Citation correction; deferred",
                "change": "Corrected one external reference; findings unchanged.",
            },
        ]
        self.write_model(model)
        result = self.run_builder(
            "--stage-root", str(self.stage_root), "--validate-only"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        model["revision_history"][-1]["version"] = "1.2"
        self.write_model(model)
        result = self.run_builder(
            "--stage-root", str(self.stage_root), "--validate-only"
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("must match", result.stderr)

    def test_rejects_duplicate_invalid_and_out_of_order_revisions(self) -> None:
        model = valid_model()
        model["document_version"] = "1.1"
        model["revision_history"] = [
            {"version": "1.0", "date": "2026-08-02", "status": "Complete", "change": "Initial."},
            {"version": "1.1", "date": "2026-08-01", "status": "Corrected", "change": "Citation."},
        ]
        for expected in (
            "nondecreasing", "valid ISO date", "invalid or duplicate",
            "in increasing order",
        ):
            self.write_model(model)
            result = self.run_builder(
                "--stage-root", str(self.stage_root), "--validate-only"
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn(expected, result.stderr)
            if expected == "nondecreasing":
                model["revision_history"][0]["date"] = "2026-02-30"
            elif expected == "valid ISO date":
                model["revision_history"][0]["date"] = "2026-08-01"
                model["revision_history"][1]["version"] = "1.0"
            elif expected == "invalid or duplicate":
                model["revision_history"][0]["version"] = "9007199254740993.0"
                model["revision_history"][1]["version"] = "9007199254740992.1"

    def test_rejects_private_reference_url(self) -> None:
        model = valid_model()
        model["references"][0]["url"] = "https://127.0.0.1/private"
        self.write_model(model)
        result = self.run_builder("--stage-root", str(self.stage_root), "--validate-only")
        self.assertEqual(result.returncode, 2)
        self.assertIn("non-public address", result.stderr)

    def test_rejects_private_ipv6_and_alternate_ipv4_urls(self) -> None:
        for index, unsafe_url in enumerate(("https://[::1]/private", "https://[fd00::1]/private", "https://[::ffff:127.0.0.1]/private", "https://2130706433/private", "https://0x7f000001/private")):
            with self.subTest(url=unsafe_url):
                child = self.root / f"case-{index}"
                child.mkdir()
                original_root = self.stage_root
                original_input = self.input
                try:
                    self.stage_root = child / "stage-output"
                    self.input = self.stage_root / "report-model.json"
                    model = valid_model()
                    model["references"][0]["url"] = unsafe_url
                    self.write_model(model)
                    result = self.run_builder("--stage-root", str(self.stage_root), "--validate-only")
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("non-public address", result.stderr)
                finally:
                    self.stage_root = original_root
                    self.input = original_input

    def test_rejects_duplicate_finding_identifier(self) -> None:
        model = valid_model()
        model["findings"][1]["id"] = "F-001"
        self.write_model(model)
        result = self.run_builder("--stage-root", str(self.stage_root), "--validate-only")
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate finding id", result.stderr)

    def test_rejects_prohibited_internal_material(self) -> None:
        model = valid_model()
        model["executive_outcomes"][0] = "Central lessons register LL-0001"
        self.write_model(model)
        result = self.run_builder("--stage-root", str(self.stage_root), "--validate-only")
        self.assertEqual(result.returncode, 2)
        self.assertIn("prohibited internal", result.stderr)

    def test_rejects_symlink_input(self) -> None:
        self.write_model(valid_model())
        real = self.root / "real.json"
        real.write_bytes(self.input.read_bytes())
        self.input.unlink()
        self.input.symlink_to(real)
        result = self.run_builder("--stage-root", str(self.stage_root), "--validate-only")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unsafe stage input", result.stderr)

    def test_rejects_report_model_digest_mismatch(self) -> None:
        self.write_model(valid_model())
        self.input.write_text("{}", encoding="utf-8")
        result = self.run_builder("--stage-root", str(self.stage_root), "--validate-only")
        self.assertEqual(result.returncode, 2)
        self.assertIn("report model digest mismatch", result.stderr)

    def test_refuses_to_overwrite_existing_output(self) -> None:
        model = valid_model()
        self.write_model(model)
        word_args = self.write_word_closeout(model)
        output = self.root / "existing.pptx"
        output.write_bytes(b"preserve me")
        manifest = self.root / "build.json"
        result = self.run_builder(
            "--stage-root", str(self.stage_root),
            "--output", str(output),
            "--build-manifest", str(manifest),
            "--workspace", str(self.root),
            "--artifact-runtime-receipt", str(self.root / "unused-receipt.json"),
            *word_args,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("output already exists", result.stderr)
        self.assertEqual(output.read_bytes(), b"preserve me")

    def test_refuses_to_overwrite_existing_build_manifest(self) -> None:
        model = valid_model()
        self.write_model(model)
        word_args = self.write_word_closeout(model)
        output = self.root / "assessment.pptx"
        manifest = self.root / "existing.json"
        manifest.write_bytes(b"preserve me")
        result = self.run_builder(
            "--stage-root", str(self.stage_root),
            "--output", str(output),
            "--build-manifest", str(manifest),
            "--workspace", str(self.root),
            "--artifact-runtime-receipt", str(self.root / "unused-receipt.json"),
            *word_args,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("output already exists", result.stderr)
        self.assertEqual(manifest.read_bytes(), b"preserve me")
        self.assertFalse(output.exists())

    @unittest.skipUnless(shutil.which("node") and (SETUP.is_file() or BUNDLED_ARTIFACT_AVAILABLE), "bundled artifact runtime unavailable")
    def test_builds_editable_pptx_with_sources_and_renders(self) -> None:
        self._exercise_build()

    @unittest.skipUnless(shutil.which("node") and BUNDLED_ARTIFACT_AVAILABLE and os.name == "posix", "bundled v5 candidate runtime unavailable")
    def test_builds_private_v5_candidate_without_normal_publication(self) -> None:
        self._exercise_build(candidate=True)

    def _exercise_build(self, candidate=False) -> None:
        model = valid_model()
        model["target"] = (
            "Synthetic MCP Extension (example.synthetic-mcp) with a deliberately "
            "long descriptive deployment target"
        )
        long_outcome = (
            "Preserve the complete executive outcome even when it exceeds the former "
            "presentation shortening threshold, because a derivative must not silently "
            "remove a material condition, limitation, scope statement, or control requirement."
        )
        model["executive_outcomes"][0] = long_outcome
        long_recommendation = (
            "Preserve the complete remediation text across slide pagination, including "
            "least privilege, credential rotation, audit evidence, incident response, "
            "rollback verification and residual-risk acceptance before deployment. REF-001"
        )
        model["findings"][0]["recommendation"] = long_recommendation
        model["references"].extend([
            {
                "id": f"REF-{index:03d}",
                "title": f"Primary source {index}",
                "publisher": "Example Publisher",
                "url": f"https://example.com/source/{index}",
                "accessed": "2026-08-01",
                "applicability": "Supports the synthetic assessment claim.",
            }
            for index in range(13, 26)
        ])
        model["derivative_sources"]["executive_outcomes"] = [
            [f"REF-{index:03d}" for index in range(start, start + 5)]
            for start in range(1, 26, 5)
        ]
        model["approval_conditions"].append("Condition 5 must be verified before deployment. REF-005")
        model["derivative_sources"]["approval_conditions"].append(["EVD-TEST-005", "REF-005"])
        model["figure"] = {
            "title": "Synthetic trust boundaries",
            "alt_text": "A six-node synthetic architecture exercises long same-row routing. REF-001",
            "nodes": ["IDE host", "MCP client", "MCP service", "Local tools", "Remote service", "Third party"],
            "edges": [
                ["IDE host", "MCP client", "invokes"],
                ["MCP client", "MCP service", "HTTPS"],
                ["Local tools", "Third party", "bounded integration"],
            ],
        }
        self.write_model(model)
        word_args = self.write_word_closeout(model)
        runtime_temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(runtime_temp.cleanup)
        runtime_root = Path(runtime_temp.name)
        python_runtime = runtime_root / "python-runtime"
        venv.EnvBuilder(with_pip=False, system_site_packages=True, symlinks=True).create(python_runtime)
        python_launcher = python_runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.assertTrue(python_launcher.exists())
        fixture_site = (
            python_runtime / "Lib" / "site-packages"
            if os.name == "nt"
            else python_runtime / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
        )
        fixture_site.mkdir(parents=True, exist_ok=True)
        import PIL
        pillow_package = Path(PIL.__file__).parent
        shutil.copytree(pillow_package, fixture_site / "PIL")
        pillow_metadata = next(pillow_package.parent.glob("pillow-*.dist-info"), None)
        if pillow_metadata is None:
            pillow_metadata = next(pillow_package.parent.glob("Pillow-*.dist-info"))
        shutil.copytree(pillow_metadata, fixture_site / pillow_metadata.name)
        workspace = runtime_root / "artifact-workspace"
        workspace.mkdir()
        if BUNDLED_ARTIFACT_AVAILABLE:
            (workspace / "package.json").write_text(json.dumps({"private": True, "type": "module"}), encoding="utf-8")
            (workspace / "node_modules").symlink_to(ARTIFACT_NODE_MODULES, target_is_directory=True)
        else:
            setup = subprocess.run(
                ["node", str(SETUP), "--workspace", str(workspace)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
            self.assertEqual(setup.returncode, 0, setup.stderr)
        output = self.root / "assessment.pptx"
        manifest = self.root / "assessment-build.json"
        qa = self.root / "qa"
        trusted_montage = MONTAGE
        receipt = runtime_root / "artifact-runtime-receipt.json"
        receipt_result = subprocess.run(
            ["node", str(RECEIPT), "--workspace", str(workspace), "--trusted-runtime-root", str((workspace / "node_modules" / "@oai" / "artifact-tool").resolve().parents[1]), "--output", str(receipt), "--montage-helper", str(trusted_montage), "--python", str(python_launcher)],
            cwd=ROOT, text=True, capture_output=True, check=False, timeout=120,
        )
        self.assertEqual(receipt_result.returncode, 0, receipt_result.stderr)
        qa.mkdir()
        if candidate:
            candidate_dir = self.root / "private-v5-candidate"
            result = self.run_builder("--stage-root", str(self.stage_root),
                "--v5-candidate-dir", str(candidate_dir), "--workspace", str(workspace),
                "--artifact-runtime-receipt", str(receipt), "--montage-helper", str(trusted_montage),
                "--python", str(python_launcher), *word_args)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(summary["status"], "Pending native measurement")
            self.assertNotIn("output", summary)
            self.assertFalse(output.exists())
            self.assertFalse(manifest.exists())
            self.assertEqual(candidate_dir.stat().st_mode & 0o777, 0o700)
            payload = json.loads((candidate_dir / "candidate.json").read_text())
            self.assertEqual(payload["status"], "Pending native measurement")
            self.assertTrue(payload["nativeMeasurementsRequired"])
            self.assertEqual(payload["native_powerpoint_closeout"], "Pending")
            self.assertEqual(payload["human_acceptance"], "Pending")
            self.assertEqual(payload["layout_schema"], "openai.presentation.layout/v5")
            for item in payload["files"]:
                data = (candidate_dir / item["file"]).read_bytes()
                self.assertEqual(len(data), item["size"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])
                self.assertEqual((candidate_dir / item["file"]).stat().st_mode & 0o777, 0o400)
            self.assertEqual(payload["candidate_pptx_sha256"], hashlib.sha256((candidate_dir / "candidate.pptx").read_bytes()).hexdigest())
            authoring = json.loads((candidate_dir / "authoring.json").read_text())
            self.assertEqual([x["slide"] for x in authoring["slides"]], list(range(1, payload["slide_count"] + 1)))
            for slide in authoring["slides"]:
                self.assertTrue(slide["authored"])
                layout = json.loads((candidate_dir / slide["layout"]).read_text())
                self.assertEqual(layout["schema"], "openai.presentation.layout/v5")
            for relative, digest in payload["source_bindings"].items():
                self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), digest)
            # The same actual runtime remains refused by the normal measured path.
            refused = self.run_builder("--stage-root", str(self.stage_root), "--output", str(output),
                "--build-manifest", str(manifest), "--workspace", str(workspace),
                "--artifact-runtime-receipt", str(receipt), "--qa-dir", str(qa),
                "--montage-helper", str(trusted_montage), "--python", str(python_launcher), *word_args)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("unsupported layout manifest", refused.stderr)
            self.assertFalse(output.exists())
            self.assertFalse(manifest.exists())
            return  # Never enter the production acceptance-receipt writer below.
        result = self.run_builder(
            "--stage-root", str(self.stage_root),
            "--output", str(output),
            "--build-manifest", str(manifest),
            "--workspace", str(workspace),
            "--artifact-runtime-receipt", str(receipt),
            "--qa-dir", str(qa),
            "--montage-helper", str(trusted_montage),
            "--python", str(python_launcher),
            *word_args,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertGreaterEqual(summary["slide_count"], 7)
        self.assertTrue(output.is_file())
        self.assertTrue(manifest.is_file())
        self.assertGreater(output.stat().st_size, 20_000)
        self.assertEqual(len(list(qa.glob("slide-*.png"))), summary["slide_count"])
        self.assertEqual(len(list(qa.glob("slide-*.layout.json"))), summary["slide_count"])
        self.assertTrue((qa / "deck-montage.png").is_file())
        montage = json.loads((qa / "deck-montage.json").read_text(encoding="utf-8"))
        self.assertEqual(montage["slide_count"], summary["slide_count"])
        self.assertEqual(montage["rows"], (summary["slide_count"] + 4) // 5)
        self.assertGreaterEqual(montage["width"], 2000)
        self.assertTrue((qa / "deck.inspect.ndjson").is_file())
        self.assertFalse(Path(f"{output}.inspect.ndjson").exists())
        with zipfile.ZipFile(output) as archive:
            names = set(archive.namelist())
            self.assertIn("ppt/presentation.xml", names)
            note_names = sorted(
                name for name in names
                if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml")
            )
            self.assertEqual(len(note_names), summary["slide_count"])
            note_documents = [archive.read(name).decode("utf-8", errors="replace") for name in note_names]
            self.assertTrue(all("[Sources]" in document for document in note_documents))
            self.assertIn("https://example.com/source/1", "\n".join(note_documents))
            self.assertTrue(all("EVD-TEST-" in document or "https://example.com/source/" in document for document in note_documents))
            self.assertNotIn("Synthetic fixture", "\n".join(note_documents))
            self.assertNotIn("Synthetic only", "\n".join(note_documents))
            self.assertGreater(len(set(note_documents)), 4)
            self.assertIn("https://example.com/source/5", "\n".join(note_documents))
            self.assertIn("https://example.com/source/25", "\n".join(note_documents))
            self.assertFalse(any(name.endswith("vbaProject.bin") for name in names))
            slide_text = {}
            for name in sorted(item for item in names if item.startswith("ppt/slides/slide") and item.endswith(".xml")):
                document = ElementTree.fromstring(archive.read(name))
                slide_text[name] = [element.text or "" for element in document.iter() if element.tag.endswith("}t")]
            all_slide_text = [text for values in slide_text.values() for text in values]
            condition_four = next(values for values in slide_text.values() if any("Condition 4" in value for value in values))
            condition_five = next(values for values in slide_text.values() if any("Condition 5" in value for value in values))
            self.assertIn("04", condition_four)
            self.assertIn("05", condition_five)
            self.assertIn(long_outcome, all_slide_text)
            self.assertIn(long_recommendation, all_slide_text)
            self.assertIn(model["assessment"], slide_text["ppt/slides/slide1.xml"])
            self.assertFalse(any("…" in value for value in all_slide_text))
            architecture_name = next(
                name for name, values in slide_text.items()
                if "Synthetic trust boundaries" in values
            )
            architecture_document = ElementTree.fromstring(archive.read(architecture_name))
            architecture_shape_names = [
                element.attrib.get("name", "")
                for element in architecture_document.iter()
                if element.tag.endswith("}cNvPr")
            ]
            self.assertEqual(
                {
                    "architecture-spanning-edge-2-source",
                    "architecture-spanning-edge-2-route",
                    "architecture-spanning-edge-2-target",
                    "architecture-spanning-edge-2-arrow",
                },
                {
                    name for name in architecture_shape_names
                    if name.startswith("architecture-spanning-edge-2-")
                },
            )
        build_manifest = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(build_manifest["native_powerpoint_closeout"], "Pending")
        self.assertEqual(build_manifest["output"]["slide_count"], summary["slide_count"])
        self.assertEqual(build_manifest["output"]["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
        acceptance_output = os.environ.get("PORTABLE_PPTX_ACCEPTANCE_OUTPUT")
        if acceptance_output:
            bound_files = (
                "scripts/build_assessment_pptx.mjs",
                "scripts/create_artifact_runtime_receipt.mjs",
                "scripts/stable_regular_file.mjs",
                "scripts/native_pptx_text.py",
                "scripts/test_native_pptx_text.py",
                "scripts/render_presentations_with_powerpoint.applescript",
                "scripts/render_presentations_with_powerpoint.ps1",
                "scripts/stage_office_artifact.py",
                "scripts/test_powerpoint_path_identity.py",
                "scripts/create_pptx_montage.py",
                "scripts/portable_fs.py",
                "scripts/requirements.lock",
                "scripts/secure_pptx_stage_bundle.py",
                "scripts/validate_assessment_pptx.py",
                "scripts/test_build_assessment_pptx.py",
            )
            receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
            acceptance = {
                "schema_version": 1,
                "status": "Passed",
                "test": "test_builds_editable_pptx_with_sources_and_renders",
                "platform": platform.system().casefold(),
                "python": platform.python_version(),
                "node": subprocess.run(["node", "--version"], text=True, capture_output=True, check=True).stdout.strip(),
                "artifact_tool_version": receipt_payload["version"],
                "artifact_runtime_receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
                "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "slide_count": summary["slide_count"],
                "source_bindings": {relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() for relative in bound_files},
            }
            Path(acceptance_output).write_text(json.dumps(acceptance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.assertEqual(build_manifest["inputs"]["report_model"]["sha256"], hashlib.sha256(self.input.read_bytes()).hexdigest())
        self.assertEqual(build_manifest["inputs"]["authoritative_word"]["docx"]["sha256"], hashlib.sha256((self.root / "authoritative.docx").read_bytes()).hexdigest())
        native_word_qa = build_manifest["inputs"]["authoritative_word"]["native_word_qa"]
        self.assertEqual(native_word_qa["status"], "Passed")
        self.assertRegex(native_word_qa["word_subrecord_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("sha256", native_word_qa)
        self.assertEqual(build_manifest["inputs"]["stage_manifest_sha256"], hashlib.sha256((self.stage_root / "stage-manifest.json").read_bytes()).hexdigest())
        self.assertEqual(len(build_manifest["inputs"]["stages"]), 15)
        self.assertTrue(build_manifest["runtime_versions"]["node"].startswith("v"))
        self.assertTrue(build_manifest["runtime_versions"]["artifact_tool"])
        qa_hashes = {item["file"]: item["sha256"] for item in build_manifest["qa_files"]}
        self.assertEqual(set(qa_hashes), {item.name for item in qa.iterdir()})
        for item in qa.iterdir():
            self.assertEqual(qa_hashes[item.name], hashlib.sha256(item.read_bytes()).hexdigest())
        self.assertEqual(list(self.root.glob(".assessment.pptx.*.tmp.pptx")), [])


if __name__ == "__main__":
    unittest.main()
