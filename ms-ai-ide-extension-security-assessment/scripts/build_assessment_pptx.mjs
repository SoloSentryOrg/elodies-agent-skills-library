#!/usr/bin/env node
// SPDX-License-Identifier: MIT
/** Build an editable PowerPoint derivative from a validated assessment model. */

import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import crypto from "node:crypto";
import { constants as fsConstants } from "node:fs";
import { isIP } from "node:net";
import { fileURLToPath, pathToFileURL } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const SECURE_BUNDLE_HELPER = path.join(SCRIPT_DIR, "secure_pptx_stage_bundle.py");
const PPTX_VALIDATOR = path.join(SCRIPT_DIR, "validate_assessment_pptx.py");

const MAX_TEXT_BYTES = 64 * 1024;
const MAX_FINDINGS = 100;
const MAX_REFERENCES = 250;
const DECISIONS = new Set([
  "Approve",
  "Approve with conditions",
  "Defer pending evidence",
  "Do not approve",
]);
const RATINGS = new Set(["Low", "Moderate", "High", "Critical"]);
const RUN_KEY = /^\d{4}-\d{2}-\d{2}-v\d+\.\d+$/;
const FINDING_ID = /^(?:F|RISK)-\d{3}$/;
const REFERENCE_ID = /^REF-\d{3}$/;
const EVIDENCE_ID = /^EVD-[A-Z0-9-]{3,64}$/;
const IDENTIFIER = /^[a-z][a-z0-9_.-]{2,127}$/;
const DENIED_HOST_SUFFIXES = [".internal", ".local", ".localhost"];
const PROHIBITED_TEXT = [
  /\bLL-\d{4}\b/i,
  /\bcentral lessons(?:-learned)?\b/i,
  /\bRCA[- ]\d+\b/i,
  /\/Users\/[^/\s]+\//i,
  /file:\/\//i,
];

class ModelError extends Error {}

function usage() {
  return [
    "Usage: node scripts/build_assessment_pptx.mjs --workspace-root ROOT --stage-root STAGE_DIR --output REPORT.pptx",
    "       --build-manifest BUILD.json --authoritative-docx REPORT.docx",
    "       --authoritative-build-manifest REPORT.build.json --word-qa-record QA.json",
    "       --workspace ARTIFACT_WORKSPACE --artifact-runtime-receipt RECEIPT.json",
    "       [--qa-dir QA_DIR --montage-helper HELPER.py --python /ABS/PYTHON] [--validate-only]",
    "",
    "Initialize ARTIFACT_WORKSPACE first with the Presentations skill's",
    "setup_artifact_tool_workspace.mjs helper.",
  ].join("\n");
}

function parseArgs(argv) {
  const result = { workspace: null, artifactRuntimeReceipt: null, qaDir: null, montageHelper: null, python: process.env.PYTHON || "python3", validateOnly: false };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--validate-only") {
      result.validateOnly = true;
      continue;
    }
    if (!["--workspace-root", "--stage-root", "--output", "--build-manifest", "--authoritative-docx", "--authoritative-build-manifest", "--word-qa-record", "--workspace", "--artifact-runtime-receipt", "--qa-dir", "--montage-helper", "--python"].includes(arg)) {
      throw new ModelError(`unexpected argument: ${arg}`);
    }
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      throw new ModelError(`missing value for ${arg}`);
    }
    const key = { "--workspace-root": "workspaceRoot", "--stage-root": "stageRoot", "--output": "output", "--build-manifest": "buildManifest", "--authoritative-docx": "authoritativeDocx", "--authoritative-build-manifest": "authoritativeBuildManifest", "--word-qa-record": "wordQaRecord", "--workspace": "workspace", "--artifact-runtime-receipt": "artifactRuntimeReceipt", "--qa-dir": "qaDir", "--montage-helper": "montageHelper", "--python": "python" }[arg];
    result[key] = value;
    index += 1;
  }
  if (!result.workspaceRoot) throw new ModelError("--workspace-root is required");
  if (!result.stageRoot) throw new ModelError("--stage-root is required");
  if (!result.validateOnly && !result.output) throw new ModelError("--output is required unless --validate-only is used");
  if (!result.validateOnly && !result.buildManifest) throw new ModelError("--build-manifest is required unless --validate-only is used");
  if (!result.validateOnly && (!result.authoritativeDocx || !result.authoritativeBuildManifest || !result.wordQaRecord)) {
    throw new ModelError("--authoritative-docx, --authoritative-build-manifest, and --word-qa-record are required for a build");
  }
  if (!result.validateOnly && (!result.workspace || !result.artifactRuntimeReceipt)) {
    throw new ModelError("--workspace and --artifact-runtime-receipt are required for a build");
  }
  const authoritativeCount = [result.authoritativeDocx, result.authoritativeBuildManifest, result.wordQaRecord].filter(Boolean).length;
  if (authoritativeCount > 0 && authoritativeCount < 3) {
    throw new ModelError("authoritative Word inputs must be supplied together");
  }
  if (!result.validateOnly && result.qaDir && !result.montageHelper) throw new ModelError("--montage-helper is required with --qa-dir");
  return result;
}

function text(value, field, { allowEmpty = false, maxBytes = MAX_TEXT_BYTES } = {}) {
  if (typeof value !== "string" || (!allowEmpty && !value.trim())) {
    throw new ModelError(`${field} must be a non-empty string`);
  }
  if (value.includes("\0") || Buffer.byteLength(value, "utf8") > maxBytes) {
    throw new ModelError(`${field} is oversized or contains NUL`);
  }
  for (const pattern of PROHIBITED_TEXT) {
    if (pattern.test(value)) throw new ModelError(`${field} contains prohibited internal or unsafe text`);
  }
  return value.trim();
}

function array(value, field, minimum, maximum) {
  if (!Array.isArray(value) || value.length < minimum || value.length > maximum) {
    throw new ModelError(`${field} must contain between ${minimum} and ${maximum} items`);
  }
  return value;
}

function record(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ModelError(`${field} must be an object`);
  }
  return value;
}

function publicHttps(value, field) {
  const raw = text(value, field, { maxBytes: 4096 });
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    throw new ModelError(`${field} must be a valid URL`);
  }
  if (parsed.protocol !== "https:" || parsed.username || parsed.password || !parsed.hostname) {
    throw new ModelError(`${field} must be a public HTTPS URL without credentials`);
  }
  const host = parsed.hostname.toLowerCase().replace(/\.$/, "").replace(/^\[|\]$/g, "");
  if (host === "localhost" || DENIED_HOST_SUFFIXES.some((suffix) => host.endsWith(suffix))) {
    throw new ModelError(`${field} targets a private hostname`);
  }
  if (isIP(host) && !isPublicIp(host)) {
    throw new ModelError(`${field} targets a non-public address`);
  }
  return raw;
}

function isPublicIp(host) {
  if (isIP(host) === 4) {
    const octets = host.split(".").map(Number);
    const [a, b] = octets;
    if (a === 0 || a === 10 || a === 127 || a >= 224) return false;
    if (a === 100 && b >= 64 && b <= 127) return false;
    if (a === 169 && b === 254) return false;
    if (a === 172 && b >= 16 && b <= 31) return false;
    if (a === 192 && [0, 2, 168].includes(b)) return false;
    if (a === 198 && (b === 18 || b === 19 || b === 51)) return false;
    if (a === 203 && b === 0 && octets[2] === 113) return false;
    return true;
  }
  if (isIP(host) === 6) {
    const lower = host.toLowerCase();
    if (lower === "::" || lower === "::1" || lower.startsWith("fc") || lower.startsWith("fd")) return false;
    if (/^fe[89ab]/.test(lower) || lower.startsWith("ff") || lower.startsWith("2001:db8")) return false;
    if (lower.startsWith("::ffff:")) return false;
    return true;
  }
  return false;
}

function validateTable(raw, field) {
  const table = record(raw, field);
  if (Object.keys(table).length !== 3 || Object.keys(table).some((key) => !["title", "columns", "rows"].includes(key))) {
    throw new ModelError(`${field} has missing or unexpected fields`);
  }
  table.title = text(table.title, `${field}.title`);
  table.columns = array(table.columns, `${field}.columns`, 1, 12).map((item) => text(item, `${field}.columns`));
  table.rows = array(table.rows, `${field}.rows`, 1, 250).map((row, index) =>
    array(row, `${field}.rows[${index}]`, table.columns.length, table.columns.length).map((item) => text(item, `${field}.rows[${index}]`)),
  );
  return table;
}

function validateModel(raw) {
  const model = record(raw, "report model");
  const essential = [
    "schema_version", "assessment", "target", "publisher", "extension_id", "version",
    "run_key", "assessment_date", "document_version", "classification", "decision",
    "overall_residual_risk", "review_trigger", "ide_scope", "executive_outcomes",
    "approval_conditions", "sections", "findings", "evidence", "references", "glossary", "figure",
    "derivative_sources",
  ];
  const optional = new Set(["revision_history"]);
  const modelFields = new Set(Object.keys(model));
  if (
    essential.some((field) => !modelFields.has(field))
    || [...modelFields].some(
      (field) => !essential.includes(field) && !optional.has(field),
    )
  ) {
    const missing = essential.filter((field) => !modelFields.has(field));
    const unexpected = [...modelFields].filter(
      (field) => !essential.includes(field) && !optional.has(field),
    );
    throw new ModelError(`report model fields differ; missing=${JSON.stringify(missing)}, unexpected=${JSON.stringify(unexpected)}`);
  }
  for (const field of essential) {
    if (!Object.hasOwn(model, field)) throw new ModelError(`report model is missing ${field}`);
  }
  if (model.schema_version !== 2) throw new ModelError("unsupported report model schema");
  for (const field of ["assessment", "target", "publisher", "extension_id", "version", "assessment_date", "document_version", "review_trigger"]) {
    model[field] = text(model[field], field, { maxBytes: 2048 });
  }
  if (!RUN_KEY.test(text(model.run_key, "run_key", { maxBytes: 64 }))) throw new ModelError("run_key is invalid");
  if (model.classification !== "PUBLIC") throw new ModelError("PowerPoint derivatives require PUBLIC classification");
  if (!DECISIONS.has(model.decision)) throw new ModelError("decision is invalid");
  if (!RATINGS.has(model.overall_residual_risk)) throw new ModelError("overall_residual_risk is invalid");
  model.ide_scope = array(model.ide_scope, "ide_scope", 1, 4).map((item) => text(item, "ide_scope", { maxBytes: 160 }));
  model.executive_outcomes = array(model.executive_outcomes, "executive_outcomes", 5, 10).map((item) => text(item, "executive_outcomes", { maxBytes: 4096 }));
  model.approval_conditions = array(model.approval_conditions, "approval_conditions", 1, 20).map((item) => text(item, "approval_conditions", { maxBytes: 4096 }));
  const rawRevisions = Object.hasOwn(model, "revision_history")
    ? model.revision_history
    : [{
      version: model.document_version,
      date: model.assessment_date,
      status: "Candidate pending native Word closeout",
      change: "Initial schema-driven assessment",
    }];
  const seenRevisionVersions = new Set();
  let previousRevisionDate = null;
  let previousRevisionVersion = null;
  model.revision_history = array(rawRevisions, "revision_history", 1, 20).map(
    (rawRevision, index) => {
      const revision = record(rawRevision, `revision_history[${index}]`);
      const required = ["version", "date", "status", "change"];
      if (
        Object.keys(revision).length !== required.length
        || Object.keys(revision).some((field) => !required.includes(field))
      ) {
        throw new ModelError(
          `revision_history[${index}] has missing or unexpected fields`,
        );
      }
      for (const field of required) {
        revision[field] = text(
          revision[field],
          `revision_history[${index}].${field}`,
          { maxBytes: 4096 },
        );
      }
      if (!/^\d+\.\d+$/.test(revision.version) || seenRevisionVersions.has(revision.version)) {
        throw new ModelError(
          `revision_history[${index}].version is invalid or duplicate`,
        );
      }
      seenRevisionVersions.add(revision.version);
      const revisionVersion = revision.version.split(".").map(BigInt);
      if (
        previousRevisionVersion !== null
        && (
          revisionVersion[0] < previousRevisionVersion[0]
          || (
            revisionVersion[0] === previousRevisionVersion[0]
            && revisionVersion[1] <= previousRevisionVersion[1]
          )
        )
      ) {
        throw new ModelError(
          "revision_history versions must be in increasing order",
        );
      }
      previousRevisionVersion = revisionVersion;
      if (!/^\d{4}-\d{2}-\d{2}$/.test(revision.date)) {
        throw new ModelError(
          `revision_history[${index}].date must be a valid ISO date`,
        );
      }
      const revisionDate = new Date(`${revision.date}T00:00:00Z`);
      if (
        Number.isNaN(revisionDate.getTime())
        || revisionDate.toISOString().slice(0, 10) !== revision.date
      ) {
        throw new ModelError(
          `revision_history[${index}].date must be a valid ISO date`,
        );
      }
      if (previousRevisionDate !== null && revision.date < previousRevisionDate) {
        throw new ModelError(
          "revision_history dates must be in nondecreasing order",
        );
      }
      previousRevisionDate = revision.date;
      return revision;
    },
  );
  if (model.revision_history.at(-1).version !== model.document_version) {
    throw new ModelError(
      "latest revision history version must match document_version",
    );
  }
  const seenSections = new Set();
  model.sections = array(model.sections, "sections", 20, 100).map((rawSection, index) => {
    const section = record(rawSection, `sections[${index}]`);
    const required = ["id", "heading", "level", "paragraphs", "bullets", "tables"];
    if (Object.keys(section).length !== required.length || Object.keys(section).some((field) => !required.includes(field))) throw new ModelError(`sections[${index}] has missing or unexpected fields`);
    section.id = text(section.id, `sections[${index}].id`);
    if (!IDENTIFIER.test(section.id) || seenSections.has(section.id)) throw new ModelError(`invalid or duplicate section id: ${section.id}`);
    seenSections.add(section.id);
    section.heading = text(section.heading, `sections[${index}].heading`);
    if (!Number.isInteger(section.level) || ![1, 2, 3].includes(section.level)) throw new ModelError(`sections[${index}].level is invalid`);
    section.paragraphs = array(section.paragraphs, `sections[${index}].paragraphs`, 0, 30).map((item) => text(item, `sections[${index}].paragraphs`));
    section.bullets = array(section.bullets, `sections[${index}].bullets`, 0, 30).map((item) => text(item, `sections[${index}].bullets`));
    section.tables = array(section.tables, `sections[${index}].tables`, 0, 12).map((item, tableIndex) => validateTable(item, `sections[${index}].tables[${tableIndex}]`));
    return section;
  });

  const seenEvidence = new Set();
  model.evidence = array(model.evidence, "evidence", 5, 250).map((rawEvidence, index) => {
    const evidence = record(rawEvidence, `evidence[${index}]`);
    const required = ["id", "title", "source", "method", "state", "limitation"];
    if (Object.keys(evidence).length !== required.length || Object.keys(evidence).some((field) => !required.includes(field))) throw new ModelError(`evidence[${index}] has missing or unexpected fields`);
    for (const field of required) evidence[field] = text(evidence[field], `evidence[${index}].${field}`);
    if (!EVIDENCE_ID.test(evidence.id) || seenEvidence.has(evidence.id)) throw new ModelError(`invalid or duplicate evidence id: ${evidence.id}`);
    seenEvidence.add(evidence.id);
    return evidence;
  });

  model.glossary = array(model.glossary, "glossary", 5, 100).map((rawGlossary, index) => {
    const item = record(rawGlossary, `glossary[${index}]`);
    if (Object.keys(item).length !== 2 || Object.keys(item).some((field) => !["term", "definition"].includes(field))) throw new ModelError(`glossary[${index}] has missing or unexpected fields`);
    item.term = text(item.term, `glossary[${index}].term`);
    item.definition = text(item.definition, `glossary[${index}].definition`);
    return item;
  });

  const findings = array(model.findings, "findings", 1, MAX_FINDINGS);
  const seenFindings = new Set();
  model.findings = findings.map((rawFinding, index) => {
    const finding = record(rawFinding, `findings[${index}]`);
    const required = ["id", "title", "scope", "scenario", "evidence_ids", "likelihood", "impact", "inherent", "controls", "control_strength", "residual_likelihood", "residual_impact", "residual", "recommendation", "owner", "priority", "target_date", "verification", "mappings", "confidence"];
    if (Object.keys(finding).length !== required.length || Object.keys(finding).some((field) => !required.includes(field))) {
      throw new ModelError(`findings[${index}] has missing or unexpected fields`);
    }
    for (const field of required) {
      if (!Object.hasOwn(finding, field)) throw new ModelError(`findings[${index}] is missing ${field}`);
      finding[field] = text(finding[field], `findings[${index}].${field}`, { maxBytes: 8192 });
    }
    if (!FINDING_ID.test(finding.id) || seenFindings.has(finding.id)) throw new ModelError(`invalid or duplicate finding id: ${finding.id}`);
    seenFindings.add(finding.id);
    return finding;
  });

  const references = array(model.references, "references", 12, MAX_REFERENCES);
  const seenReferences = new Set();
  model.references = references.map((rawReference, index) => {
    const reference = record(rawReference, `references[${index}]`);
    const required = ["id", "title", "publisher", "url", "accessed", "applicability"];
    if (Object.keys(reference).length !== required.length || Object.keys(reference).some((field) => !required.includes(field))) {
      throw new ModelError(`references[${index}] has missing or unexpected fields`);
    }
    for (const field of required) {
      if (!Object.hasOwn(reference, field)) throw new ModelError(`references[${index}] is missing ${field}`);
    }
    reference.id = text(reference.id, `references[${index}].id`, { maxBytes: 32 });
    if (!REFERENCE_ID.test(reference.id) || seenReferences.has(reference.id)) throw new ModelError(`invalid or duplicate reference id: ${reference.id}`);
    seenReferences.add(reference.id);
    reference.title = text(reference.title, `references[${index}].title`, { maxBytes: 4096 });
    reference.publisher = text(reference.publisher, `references[${index}].publisher`, { maxBytes: 1024 });
    reference.url = publicHttps(reference.url, `references[${index}].url`);
    reference.accessed = text(reference.accessed, `references[${index}].accessed`, { maxBytes: 128 });
    reference.applicability = text(reference.applicability, `references[${index}].applicability`, { maxBytes: 4096 });
    return reference;
  });

  const figure = record(model.figure, "figure");
  if (Object.keys(figure).length !== 4 || Object.keys(figure).some((field) => !["title", "alt_text", "nodes", "edges"].includes(field))) {
    throw new ModelError("figure has missing or unexpected fields");
  }
  figure.title = text(figure.title, "figure.title", { maxBytes: 1024 });
  figure.alt_text = text(figure.alt_text, "figure.alt_text", { maxBytes: 4096 });
  figure.nodes = array(figure.nodes, "figure.nodes", 3, 7).map((node) => text(node, "figure.nodes", { maxBytes: 256 }));
  if (new Set(figure.nodes).size !== figure.nodes.length) throw new ModelError("figure.nodes contains duplicates");
  figure.edges = array(figure.edges, "figure.edges", 2, 12).map((edge, index) => {
    const values = array(edge, `figure.edges[${index}]`, 3, 3).map((item) => text(item, `figure.edges[${index}]`, { maxBytes: 256 }));
    if (!figure.nodes.includes(values[0]) || !figure.nodes.includes(values[1])) throw new ModelError(`figure.edges[${index}] references an unknown node`);
    return values;
  });

  const derivative = record(model.derivative_sources, "derivative_sources");
  const derivativeFields = ["cover", "executive_outcomes", "approval_conditions", "figure", "findings", "decision", "review_trigger"];
  if (Object.keys(derivative).length !== derivativeFields.length || Object.keys(derivative).some((field) => !derivativeFields.includes(field))) {
    throw new ModelError("derivative_sources has missing or unexpected fields");
  }
  const knownSources = new Set([...seenEvidence, ...seenReferences]);
  const sourceIds = (value, field) => {
    const ids = array(value, field, 1, 20).map((item) => text(item, field, { maxBytes: 80 }));
    if (new Set(ids).size !== ids.length || ids.some((id) => !knownSources.has(id))) throw new ModelError(`${field} contains duplicate or unknown source ids`);
    return ids;
  };
  derivative.cover = sourceIds(derivative.cover, "derivative_sources.cover");
  derivative.figure = sourceIds(derivative.figure, "derivative_sources.figure");
  derivative.decision = sourceIds(derivative.decision, "derivative_sources.decision");
  derivative.review_trigger = sourceIds(derivative.review_trigger, "derivative_sources.review_trigger");
  derivative.executive_outcomes = array(derivative.executive_outcomes, "derivative_sources.executive_outcomes", model.executive_outcomes.length, model.executive_outcomes.length)
    .map((item, index) => sourceIds(item, `derivative_sources.executive_outcomes[${index}]`));
  derivative.approval_conditions = array(derivative.approval_conditions, "derivative_sources.approval_conditions", model.approval_conditions.length, model.approval_conditions.length)
    .map((item, index) => sourceIds(item, `derivative_sources.approval_conditions[${index}]`));
  derivative.findings = record(derivative.findings, "derivative_sources.findings");
  if (Object.keys(derivative.findings).length !== seenFindings.size || Object.keys(derivative.findings).some((id) => !seenFindings.has(id))) {
    throw new ModelError("derivative_sources.findings must cover every finding exactly");
  }
  for (const findingId of [...seenFindings].sort()) derivative.findings[findingId] = sourceIds(derivative.findings[findingId], `derivative_sources.findings.${findingId}`);
  return model;
}

function decodeBase64(value, field) {
  if (typeof value !== "string" || !/^[A-Za-z0-9+/]*={0,2}$/.test(value)) throw new ModelError(`${field} is not valid base64`);
  return Buffer.from(value, "base64");
}

async function loadSecureBundle(args) {
  const helperInfo = await fs.lstat(SECURE_BUNDLE_HELPER);
  if (!helperInfo.isFile() || helperInfo.isSymbolicLink()) throw new ModelError("secure stage bundle helper is missing or unsafe");
  const helperArgs = [SECURE_BUNDLE_HELPER, "--workspace-root", path.resolve(args.workspaceRoot), "--stage-root", path.resolve(args.stageRoot)];
  if (args.authoritativeDocx && args.authoritativeBuildManifest && args.wordQaRecord) {
    helperArgs.push(
      "--authoritative-docx", path.resolve(args.authoritativeDocx),
      "--authoritative-build-manifest", path.resolve(args.authoritativeBuildManifest),
      "--word-qa-record", path.resolve(args.wordQaRecord),
    );
  }
  let stdout;
  try {
    ({ stdout } = await execFileAsync(args.python, helperArgs, { timeout: 30000, maxBuffer: 32 * 1024 * 1024 }));
  } catch (error) {
    throw new ModelError(`secure stage input read failed: ${String(error.stderr || error.message).trim()}`);
  }
  const bundle = record(parseJson(Buffer.from(stdout, "utf8"), "secure stage bundle"), "secure stage bundle");
  if (bundle.schema_version !== 1 || typeof bundle.stage_root !== "string") throw new ModelError("secure stage bundle schema is invalid");
  return bundle;
}

function parseJson(data, field) {
  let source;
  try {
    source = new TextDecoder("utf-8", { fatal: true }).decode(data);
    return JSON.parse(source);
  } catch {
    throw new ModelError(`${field} is invalid UTF-8 JSON`);
  }
}

function sha256(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}

function validateDigestEntry(entry, field) {
  const item = record(entry, field);
  if (item.status !== "Validated" || typeof item.file !== "string" || !/^[0-9a-f]{64}$/.test(item.sha256 || "")) {
    throw new ModelError(`${field} is not a validated digest entry`);
  }
  return item;
}

async function loadBoundModel(args) {
  const secureBundle = await loadSecureBundle(args);
  const stageRoot = secureBundle.stage_root;
  const manifestData = decodeBase64(secureBundle.manifest, "secure stage bundle manifest");
  const manifest = record(parseJson(manifestData, "stage manifest"), "stage manifest");
  const stages = array(manifest.stages, "stage manifest stages", 15, 15);
  if (stages.map((item) => item?.stage).some((stage, index) => stage !== index + 1)) throw new ModelError("stage manifest is incomplete or unordered");
  const secureStages = array(secureBundle.stages, "secure stage bundle stages", 15, 15);
  const stageBindings = [];
  for (const [index, rawStage] of stages.entries()) {
    const stage = validateDigestEntry(rawStage, `stage manifest stages[${index}]`);
    const observed = record(secureStages[index], `secure stage bundle stages[${index}]`);
    if (observed.file !== stage.file || observed.sha256 !== stage.sha256) throw new ModelError(`stage ${index + 1} digest mismatch`);
    if (observed.analyst_validated !== true) throw new ModelError(`stage ${index + 1} lacks analyst validation`);
    stageBindings.push({ stage: index + 1, file: stage.file, sha256: stage.sha256 });
  }

  const claimEntry = validateDigestEntry(manifest.claims, "stage manifest claims");
  const claimData = decodeBase64(secureBundle.claims, "secure stage bundle claims");
  if (sha256(claimData) !== claimEntry.sha256) throw new ModelError("validated claims digest mismatch");
  const claims = record(parseJson(claimData, "validated claims"), "validated claims");
  if (claims.analyst_validation !== "Validated") throw new ModelError("claims are not analyst validated");

  const modelEntry = validateDigestEntry(manifest.report_model, "stage manifest report_model");
  const modelData = decodeBase64(secureBundle.report_model, "secure stage bundle report model");
  if (sha256(modelData) !== modelEntry.sha256) throw new ModelError("report model digest mismatch");
  const model = validateModel(parseJson(modelData, "report model"));
  for (const field of ["assessment", "target", "version"]) {
    if (model[field] !== manifest[field] || model[field] !== claims[field]) throw new ModelError(`report model ${field} does not match validated stage identity`);
  }
  const knownEvidence = new Set(model.evidence.map((item) => item.id));
  for (const claim of array(claims.claims, "validated claims claims", 1, 500)) {
    const item = record(claim, "validated claim");
    const claimId = text(item.id, "validated claim id", { maxBytes: 128 });
    const evidenceIds = array(item.evidence_ids, `validated claim ${claimId} evidence_ids`, 1, 50);
    const missing = evidenceIds.filter((id) => typeof id !== "string" || !knownEvidence.has(id));
    if (missing.length) throw new ModelError(`validated claim ${claimId} references unknown evidence ids: ${JSON.stringify(missing)}`);
  }
  for (const finding of model.findings) {
    const evidenceIds = finding.evidence_ids.split(/[,;]/).map((item) => item.trim()).filter(Boolean);
    if (!evidenceIds.length || evidenceIds.some((id) => !EVIDENCE_ID.test(id))) throw new ModelError(`finding ${finding.id} has invalid evidence ids`);
    const missing = evidenceIds.filter((id) => !knownEvidence.has(id));
    if (missing.length) throw new ModelError(`finding ${finding.id} references unknown evidence ids: ${JSON.stringify(missing)}`);
  }
  return {
    stageRoot,
    input: path.join(stageRoot, modelEntry.file),
    model,
    bindings: {
      stage_manifest_sha256: sha256(manifestData),
      stages: stageBindings,
      claims: { file: claimEntry.file, sha256: claimEntry.sha256 },
      report_model: { file: modelEntry.file, sha256: modelEntry.sha256 },
    },
    authoritativeWord: secureBundle.authoritative_word || null,
  };
}

function workspaceRelative(workspaceRoot, filename, field) {
  const resolved = path.resolve(filename);
  const relative = path.relative(workspaceRoot, resolved);
  if (!relative || relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
    throw new ModelError(`${field} must remain inside the workspace root`);
  }
  return relative.split(path.sep).join("/");
}

function manifestWorkspacePath(workspaceRoot, value, field) {
  if (typeof value !== "string" || !value || path.isAbsolute(value)) throw new ModelError(`${field} must be a workspace-relative path`);
  const resolved = path.resolve(workspaceRoot, value);
  workspaceRelative(workspaceRoot, resolved, field);
  return resolved;
}

function internalPath(value, field) {
  if (typeof value !== "string" || !value || value.includes("\0") || Buffer.byteLength(value, "utf8") > 4096) {
    throw new ModelError(`${field} must be a non-empty bounded path`);
  }
  return path.resolve(value);
}

function validateAuthoritativeWord(workspaceRoot, model, modelBinding, raw) {
  const authoritative = record(raw, "authoritative Word inputs");
  for (const field of ["docx_path", "docx_sha256", "build_manifest_path", "build_manifest_sha256", "build_manifest", "qa_record_path", "word_subrecord_sha256", "qa_record"]) {
    if (!Object.hasOwn(authoritative, field)) throw new ModelError(`authoritative Word inputs are missing ${field}`);
  }
  const docxPath = internalPath(authoritative.docx_path, "authoritative Word DOCX path");
  const buildPath = internalPath(authoritative.build_manifest_path, "authoritative Word build manifest path");
  const qaPath = internalPath(authoritative.qa_record_path, "authoritative Word QA record path");
  if (path.extname(docxPath).toLowerCase() !== ".docx" || path.extname(buildPath).toLowerCase() !== ".json" || path.extname(qaPath).toLowerCase() !== ".json") {
    throw new ModelError("authoritative Word inputs use unexpected extensions");
  }
  const docxRelative = workspaceRelative(workspaceRoot, docxPath, "authoritative Word DOCX");
  const buildRelative = workspaceRelative(workspaceRoot, buildPath, "authoritative Word build manifest");
  const qaRelative = workspaceRelative(workspaceRoot, qaPath, "authoritative Word QA record");
  for (const [value, field] of [[authoritative.docx_sha256, "authoritative Word DOCX digest"], [authoritative.build_manifest_sha256, "authoritative Word build manifest digest"], [authoritative.word_subrecord_sha256, "authoritative Word QA subrecord digest"]]) {
    if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) throw new ModelError(`${field} is invalid`);
  }

  const buildData = decodeBase64(authoritative.build_manifest, "authoritative Word build manifest");
  const qaData = decodeBase64(authoritative.qa_record, "authoritative Word QA record");
  if (sha256(buildData) !== authoritative.build_manifest_sha256) {
    throw new ModelError("authoritative Word build manifest digest mismatch");
  }
  const build = record(parseJson(buildData, "authoritative Word build manifest"), "authoritative Word build manifest");
  const qa = record(parseJson(qaData, "authoritative Word QA record"), "authoritative Word QA record");
  if (build.assessment !== model.assessment || build.run_key !== model.run_key || build.report_model_sha256 !== modelBinding.sha256) {
    throw new ModelError("authoritative Word build identity or report-model binding does not match the PowerPoint model");
  }
  if (build.output_sha256 !== authoritative.docx_sha256 || manifestWorkspacePath(workspaceRoot, build.output, "authoritative Word build output") !== docxPath) {
    throw new ModelError("authoritative Word DOCX does not match its build manifest");
  }
  const closeout = record(build.native_word_closeout, "authoritative Word native closeout");
  if (closeout.status !== "Passed"
    || manifestWorkspacePath(workspaceRoot, closeout.qa_record, "authoritative Word closeout QA record") !== qaPath) {
    throw new ModelError("authoritative Word native closeout is not Passed or is not bound to the supplied QA record");
  }
  if (typeof closeout.word_subrecord_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(closeout.word_subrecord_sha256)
    || closeout.word_subrecord_sha256 !== authoritative.word_subrecord_sha256) {
    throw new ModelError("authoritative Word QA subrecord digest mismatch");
  }
  const word = record(qa.word, "authoritative Word QA word result");
  if (qa.status !== "Passed" || qa.assessment !== model.assessment || qa.run_key !== model.run_key
    || word.result !== "Passed" || word.every_page_inspected !== true || word.contents_starts_on_fresh_page !== true
    || word.input_sha256 !== authoritative.docx_sha256 || word.input_file !== path.basename(docxPath)
    || !Number.isInteger(word.page_count) || word.page_count < 1) {
    throw new ModelError("authoritative Word QA record is incomplete or does not match the supplied DOCX");
  }
  return {
    docx: { file: docxRelative, sha256: authoritative.docx_sha256 },
    build_manifest: { file: buildRelative, sha256: authoritative.build_manifest_sha256 },
    native_word_qa: { file: qaRelative, word_subrecord_sha256: authoritative.word_subrecord_sha256, page_count: word.page_count, status: "Passed" },
  };
}

async function resolveWorkspaceRoot(value) {
  const absolute = path.resolve(value);
  const info = await fs.lstat(absolute);
  if (!info.isDirectory() || info.isSymbolicLink()) throw new ModelError("--workspace-root must be a real directory");
  return await fs.realpath(absolute);
}

async function resolveExistingWithinWorkspace(workspaceRoot, value, field) {
  const absolute = path.resolve(value);
  const info = await fs.lstat(absolute);
  if (info.isSymbolicLink()) throw new ModelError(`${field} must not be a symlink`);
  const resolved = await fs.realpath(absolute);
  workspaceRelative(workspaceRoot, resolved, field);
  return resolved;
}

async function safeOutput(workspaceRoot, filename, expectedExtension) {
  const requested = path.resolve(filename);
  const realParent = await fs.realpath(path.dirname(requested)).catch((error) => {
    if (error.code === "ENOENT") throw new ModelError("output parent must already exist");
    throw error;
  });
  const resolved = path.join(realParent, path.basename(requested));
  workspaceRelative(workspaceRoot, resolved, "output");
  if (path.extname(resolved).toLowerCase() !== expectedExtension) throw new ModelError(`output must use ${expectedExtension}`);
  const parent = path.dirname(resolved);
  let parentInfo;
  try {
    parentInfo = await fs.lstat(parent);
  } catch (error) {
    if (error.code === "ENOENT") throw new ModelError("output parent must already exist");
    throw error;
  }
  if (!parentInfo.isDirectory() || parentInfo.isSymbolicLink()) throw new ModelError("output parent must be a real directory");
  try {
    const outputInfo = await fs.lstat(resolved);
    if (outputInfo.isSymbolicLink() || !outputInfo.isFile()) throw new ModelError("existing output must be a regular non-symlink file");
    throw new ModelError("output already exists; choose a new versioned path");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  return resolved;
}

function shorten(value, maximum) {
  const clean = String(value).replace(/\s+/g, " ").trim();
  if (clean.length <= maximum) return clean;
  const candidate = clean.slice(0, maximum - 1).replace(/\s+\S*$/, "").trim();
  return `${candidate || clean.slice(0, maximum - 1)}…`;
}

function notesFor(model, ids) {
  const byId = new Map([
    ...model.references.map((item) => [item.id, { ...item, detail: item.url }]),
    ...model.evidence.map((item) => [item.id, { ...item, detail: "Evidence identifier retained in the authoritative report" }]),
  ]);
  if (!Array.isArray(ids) || ids.length === 0 || ids.some((id) => !byId.has(id))) throw new ModelError("slide source binding is missing or unknown");
  const lines = ["[Sources]"];
  for (const id of [...new Set(ids)]) {
    const item = byId.get(id);
    lines.push(`${item.id} — ${item.title} — ${item.detail}`);
  }
  return lines.join("\n");
}

function addText(slide, name, value, position, fontSize, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name,
    position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = value;
  shape.text.style = {
    fontSize,
    typeface: "Helvetica Neue",
    color: options.color || "#000000",
    bold: options.bold || false,
    alignment: options.alignment || "left",
    verticalAlignment: options.verticalAlignment || "top",
    autoFit: "shrinkText",
    insets: { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return shape;
}

function addFooter(slide, number, model) {
  addText(slide, `footer-classification-${number}`, "PUBLIC", { left: 41, top: 658, width: 130, height: 28 }, 16, { color: "#58616B" });
  addText(slide, `footer-number-${number}`, String(number), { left: 1175, top: 658, width: 64, height: 28 }, 16, { alignment: "right", color: "#58616B" });
  addText(slide, `footer-run-${number}`, model.run_key, { left: 490, top: 658, width: 300, height: 28 }, 16, { alignment: "center", color: "#7A838C" });
}

function addTitle(slide, title, number, model) {
  addText(slide, `slide-title-${number}`, shorten(title, 58), { left: 41, top: 34, width: 1198, height: 100 }, 40, { bold: true });
  addFooter(slide, number, model);
}

function setNotes(slide, model, sourceIds) {
  slide.speakerNotes.textFrame.setText(notesFor(model, sourceIds));
  slide.speakerNotes.setVisible(true);
}

function addCover(presentation, model) {
  const slide = presentation.slides.add();
  slide.background.fill = "#FFFFFF";
  addText(slide, "cover-kicker", "MICROSOFT IDE AI EXTENSION SECURITY ASSESSMENT", { left: 41, top: 42, width: 760, height: 52 }, 24, { color: "#3D8DFF", bold: true });
  addText(slide, "cover-title", shorten(model.target, 56), { left: 41, top: 174, width: 1050, height: 260 }, 72, { bold: true, verticalAlignment: "bottom" });
  addText(slide, "cover-subtitle", `${model.publisher} · ${model.version} · ${model.ide_scope.join(" / ")}`, { left: 41, top: 490, width: 940, height: 105 }, 24, { color: "#303842" });
  addText(slide, "cover-control", `${model.assessment_date} · Document ${model.document_version} · PUBLIC`, { left: 41, top: 620, width: 800, height: 34 }, 18, { color: "#58616B" });
  setNotes(slide, model, model.derivative_sources.cover);
}

function addOutcomeSlides(presentation, model, startNumber) {
  const chunks = [];
  for (let index = 0; index < model.executive_outcomes.length; index += 5) chunks.push(model.executive_outcomes.slice(index, index + 5));
  chunks.forEach((outcomes, chunkIndex) => {
    const number = startNumber + chunkIndex;
    const slide = presentation.slides.add();
    slide.background.fill = "#FFFFFF";
    addTitle(slide, chunkIndex === 0 ? `Decision: ${model.decision}` : "The assessment's remaining executive outcomes", number, model);
    addText(slide, `outcome-risk-${number}`, `Overall residual risk: ${model.overall_residual_risk}`, { left: 41, top: 132, width: 680, height: 48 }, 24, { bold: true, color: "#3D8DFF" });
    outcomes.forEach((outcome, index) => {
      const top = 205 + index * 86;
      addText(slide, `outcome-index-${number}-${index}`, String(chunkIndex * 5 + index + 1).padStart(2, "0"), { left: 41, top, width: 70, height: 46 }, 24, { bold: true, color: "#3D8DFF" });
      addText(slide, `outcome-copy-${number}-${index}`, outcome, { left: 130, top, width: 1075, height: 74 }, 18);
    });
    setNotes(slide, model, model.derivative_sources.executive_outcomes.slice(chunkIndex * 5, chunkIndex * 5 + outcomes.length).flat());
  });
  return chunks.length;
}

function addArchitectureSlides(presentation, model, number) {
  const slide = presentation.slides.add();
  slide.background.fill = "#FFFFFF";
  addTitle(slide, model.figure.title, number, model);
  const nodes = model.figure.nodes;
  const columns = nodes.length <= 4 ? nodes.length : Math.ceil(nodes.length / 2);
  const nodeWidth = 210;
  const horizontalGap = columns > 1 ? (1170 - columns * nodeWidth) / (columns - 1) : 0;
  const positions = new Map();
  nodes.forEach((node, index) => {
    const row = Math.floor(index / columns);
    const column = index % columns;
    positions.set(node, { left: 55 + column * (nodeWidth + horizontalGap), top: 210 + row * 260, width: nodeWidth, height: 105, row, column });
  });
  const nodeShapes = new Map();
  nodes.forEach((node, index) => {
    const position = positions.get(node);
    const shape = slide.shapes.add({
      geometry: "rect",
      name: `architecture-node-${index}`,
      position: { left: position.left, top: position.top, width: position.width, height: position.height },
      fill: index === 0 ? "#D0EDFA" : "#EDEDED",
      line: { style: "solid", fill: index === 0 ? "#3D8DFF" : "#B8BCC4", width: 1 },
    });
    nodeShapes.set(node, shape);
  });
  // PowerPoint-native connectors preserve the actual source and target even for
  // diagonals whose source is to the right of the target.
  model.figure.edges.forEach(([source, target, label], index) => {
    const a = positions.get(source);
    const b = positions.get(target);
    slide.shapes.connect(nodeShapes.get(source), nodeShapes.get(target), {
      kind: "straight",
      line: { style: "solid", fill: "#8A929A", width: 2 },
      tail: { type: "arrow", width: "sm", length: "sm" },
    });
    const ax = a.left + a.width / 2;
    const ay = a.top + a.height / 2;
    const bx = b.left + b.width / 2;
    const by = b.top + b.height / 2;
    addText(slide, `architecture-edge-label-${index}`, String(index + 1).padStart(2, "0"), { left: (ax + bx) / 2 - 30, top: (ay + by) / 2 - 28, width: 60, height: 38 }, 16, { alignment: "center", color: "#58616B", bold: true });
  });
  nodes.forEach((node, index) => {
    const position = positions.get(node);
    addText(slide, `architecture-node-label-${index}`, shorten(node, 52), { left: position.left + 12, top: position.top + 12, width: position.width - 24, height: position.height - 24 }, 20, { bold: true, alignment: "center", verticalAlignment: "middle" });
  });
  setNotes(slide, model, model.derivative_sources.figure);
  const chunks = [];
  for (let index = 0; index < model.figure.edges.length; index += 6) chunks.push(model.figure.edges.slice(index, index + 6));
  chunks.forEach((edges, chunkIndex) => {
    const detailNumber = number + chunkIndex + 1;
    const detail = presentation.slides.add();
    detail.background.fill = "#FFFFFF";
    addTitle(detail, chunkIndex === 0 ? "Trust-boundary flows and interfaces" : "Additional trust-boundary flows", detailNumber, model);
    edges.forEach(([source, target, label], index) => {
      const absoluteIndex = chunkIndex * 6 + index;
      const top = 155 + index * 80;
      addText(detail, `flow-index-${absoluteIndex}`, String(absoluteIndex + 1).padStart(2, "0"), { left: 41, top, width: 65, height: 42 }, 22, { bold: true, color: "#3D8DFF" });
      addText(detail, `flow-route-${absoluteIndex}`, shorten(`${source} → ${target}`, 62), { left: 125, top, width: 470, height: 50 }, 20, { bold: true });
      addText(detail, `flow-label-${absoluteIndex}`, shorten(label, 150), { left: 620, top, width: 580, height: 50 }, 20, { color: "#303842" });
      if (index < edges.length - 1) detail.shapes.add({ geometry: "rect", name: `flow-rule-${absoluteIndex}`, position: { left: 41, top: top + 62, width: 1198, height: 1 }, fill: "#D5D8DC", line: { style: "solid", fill: "none", width: 0 } });
    });
    setNotes(detail, model, model.derivative_sources.figure);
  });
  return 1 + chunks.length;
}

function ratingScore(value) {
  const number = Number.parseInt(String(value), 10);
  if (Number.isFinite(number)) return number;
  const lower = String(value).toLowerCase();
  if (lower.includes("critical")) return 25;
  if (lower.includes("high")) return 16;
  if (lower.includes("moderate")) return 9;
  if (lower.includes("low")) return 4;
  return 0;
}

function addFindingSlides(presentation, model, startNumber) {
  const sorted = [...model.findings].sort((a, b) => ratingScore(b.residual) - ratingScore(a.residual) || a.id.localeCompare(b.id));
  const chunks = [];
  for (let index = 0; index < sorted.length; index += 4) chunks.push(sorted.slice(index, index + 4));
  chunks.forEach((findings, chunkIndex) => {
    const number = startNumber + chunkIndex;
    const slide = presentation.slides.add();
    slide.background.fill = "#FFFFFF";
    addTitle(slide, chunkIndex === 0 ? "Residual risk concentrates in these findings" : "Additional findings remain within the treatment plan", number, model);
    findings.forEach((finding, index) => {
      const top = 160 + index * 118;
      addText(slide, `finding-id-${number}-${index}`, finding.id, { left: 41, top, width: 125, height: 36 }, 22, { bold: true, color: "#3D8DFF" });
      addText(slide, `finding-title-${number}-${index}`, shorten(finding.title, 88), { left: 180, top, width: 680, height: 56 }, 22, { bold: true });
      addText(slide, `finding-rating-${number}-${index}`, `Residual ${shorten(finding.residual, 22)}`, { left: 920, top, width: 280, height: 38 }, 20, { bold: true, alignment: "right" });
      addText(slide, `finding-action-${number}-${index}`, shorten(finding.recommendation, 155), { left: 180, top: top + 58, width: 1020, height: 45 }, 16, { color: "#303842" });
      slide.shapes.add({ geometry: "rect", name: `finding-rule-${number}-${index}`, position: { left: 41, top: top + 108, width: 1198, height: 1 }, fill: "#D5D8DC", line: { style: "solid", fill: "none", width: 0 } });
    });
    setNotes(slide, model, findings.flatMap((finding) => model.derivative_sources.findings[finding.id]));
  });
  return chunks.length;
}

function addControlSlides(presentation, model, startNumber) {
  const chunks = [];
  const chunkCount = Math.ceil(model.approval_conditions.length / 4);
  const chunkSize = Math.ceil(model.approval_conditions.length / chunkCount);
  for (let index = 0; index < model.approval_conditions.length; index += chunkSize) chunks.push(model.approval_conditions.slice(index, index + chunkSize));
  chunks.forEach((conditions, chunkIndex) => {
    const number = startNumber + chunkIndex;
    const slide = presentation.slides.add();
    slide.background.fill = "#FFFFFF";
    addTitle(slide, chunkIndex === 0 ? "Approval depends on verified controls" : "Further conditions complete the control plan", number, model);
    conditions.forEach((condition, index) => {
      const column = index % 2;
      const row = Math.floor(index / 2);
      const left = 41 + column * 615;
      const top = 185 + row * 215;
      addText(slide, `control-number-${number}-${index}`, String(chunkIndex * chunkSize + index + 1).padStart(2, "0"), { left, top, width: 70, height: 40 }, 24, { bold: true, color: "#3D8DFF" });
      addText(slide, `control-copy-${number}-${index}`, shorten(condition, 205), { left: left + 85, top, width: 485, height: 150 }, 20);
    });
    setNotes(slide, model, model.derivative_sources.approval_conditions.slice(chunkIndex * chunkSize, chunkIndex * chunkSize + conditions.length).flat());
  });
  return chunks.length;
}

function addClose(presentation, model, number) {
  const slide = presentation.slides.add();
  slide.background.fill = "#FFFFFF";
  addText(slide, "close-kicker", "DECISION", { left: 41, top: 42, width: 300, height: 52 }, 24, { color: "#3D8DFF", bold: true });
  addText(slide, "close-decision", model.decision, { left: 41, top: 170, width: 1060, height: 220 }, 68, { bold: true, verticalAlignment: "bottom" });
  addText(slide, "close-risk", `Residual risk: ${model.overall_residual_risk}`, { left: 41, top: 455, width: 760, height: 56 }, 30, { bold: true });
  addText(slide, "close-trigger", `Review trigger: ${model.review_trigger}`, { left: 41, top: 525, width: 1130, height: 112 }, 18, { color: "#303842" });
  addFooter(slide, number, model);
  setNotes(slide, model, [...model.derivative_sources.decision, ...model.derivative_sources.review_trigger]);
}

async function validatePythonRuntime(receipt, pythonValue) {
  const runtime = record(receipt.python_runtime, "artifact runtime Python receipt");
  const requestedLauncher = path.resolve(pythonValue);
  const launcherParent = await fs.realpath(path.dirname(requestedLauncher));
  const launcher = path.join(launcherParent, path.basename(requestedLauncher));
  const launcherInfo = await fs.lstat(launcher);
  if ((!launcherInfo.isFile() && !launcherInfo.isSymbolicLink()) || runtime.launcher !== launcher
    || !["file", "symlink"].includes(runtime.launcher_kind)
    || runtime.launcher_kind !== (launcherInfo.isSymbolicLink() ? "symlink" : "file")) {
    throw new ModelError("Python launcher identity does not match its runtime receipt");
  }
  const target = await fs.realpath(launcher);
  if (runtime.target !== target || !/^[0-9a-f]{64}$/.test(runtime.target_sha256 || "")
    || await hashRegularFile(target, "Python launcher target") !== runtime.target_sha256) {
    throw new ModelError("Python launcher target does not match its runtime receipt");
  }
  if (launcherInfo.isSymbolicLink()) {
    if (runtime.launcher_target !== await fs.readlink(launcher)) throw new ModelError("Python venv launcher link changed after receipt creation");
  } else if (runtime.launcher_target !== null) throw new ModelError("regular Python launcher has an invalid link receipt");
  const pyvenv = record(runtime.pyvenv_cfg, "Python virtual-environment configuration receipt");
  const expectedPyvenv = path.join(path.dirname(path.dirname(launcher)), "pyvenv.cfg");
  if (pyvenv.path !== expectedPyvenv || !/^[0-9a-f]{64}$/.test(pyvenv.sha256 || "")
    || await hashRegularFile(expectedPyvenv, "Python virtual-environment configuration") !== pyvenv.sha256) {
    throw new ModelError("Python virtual-environment configuration does not match its runtime receipt");
  }
  return launcher;
}

async function loadArtifactTool(workspace, receiptFile, workspaceRoot, montageHelper, pythonValue) {
  const workspacePath = await fs.realpath(path.resolve(workspace));
  const info = await fs.lstat(workspacePath);
  if (!info.isDirectory() || info.isSymbolicLink()) throw new ModelError("--workspace must be a real directory");
  if (!path.relative(workspaceRoot, workspacePath).startsWith("..")) throw new ModelError("artifact workspace must remain outside the untrusted assessment workspace");
  const receiptPath = await fs.realpath(path.resolve(receiptFile));
  if (!path.relative(workspaceRoot, receiptPath).startsWith("..")) throw new ModelError("artifact runtime receipt must remain outside the assessment workspace");
  const { data: receiptData } = await readStableRegularFile(receiptPath, "artifact runtime receipt");
  const receipt = record(parseJson(receiptData, "artifact runtime receipt"), "artifact runtime receipt");
  for (const field of ["workspace_package_sha256", "package_json_sha256", "entrypoint_sha256"]) {
    if (!/^[0-9a-f]{64}$/.test(receipt[field] || "")) throw new ModelError(`artifact runtime receipt ${field} is invalid`);
  }
  if (receipt.schema_version !== 1 || receipt.package !== "@oai/artifact-tool" || receipt.workspace !== workspacePath
    || typeof receipt.version !== "string" || !/^\d+\.\d+\.\d+/.test(receipt.version)) {
    throw new ModelError("artifact runtime receipt identity is invalid");
  }
  const packageRoot = await fs.realpath(receipt.package_root);
  const trustedRuntimeRoot = await fs.realpath(receipt.trusted_runtime_root);
  const entrypoint = await fs.realpath(receipt.entrypoint);
  const expectedPackageLink = path.join(workspacePath, "node_modules", "@oai", "artifact-tool");
  const linkedPackageRoot = await fs.realpath(expectedPackageLink).catch(() => null);
  if (entrypoint !== receipt.entrypoint || packageRoot !== receipt.package_root
    || receipt.package_link !== expectedPackageLink || linkedPackageRoot !== packageRoot
    || path.relative(trustedRuntimeRoot, packageRoot).startsWith("..") || packageRoot === trustedRuntimeRoot
    || path.relative(packageRoot, entrypoint).startsWith("..")) {
    throw new ModelError("artifact runtime receipt paths are not canonical and contained");
  }
  const files = [
    [path.join(workspacePath, "package.json"), receipt.workspace_package_sha256, "workspace package.json"],
    [path.join(packageRoot, "package.json"), receipt.package_json_sha256, "artifact-tool package.json"],
    [entrypoint, receipt.entrypoint_sha256, "artifact-tool entrypoint"],
  ];
  for (const [filename, expected, field] of files) {
    if (await hashRegularFile(filename, field) !== expected) throw new ModelError(`${field} does not match its runtime receipt`);
  }
  const expectedTree = array(receipt.package_tree, "artifact runtime package tree", 1, 10000);
  const observedTree = [];
  let totalTreeBytes = 0;
  async function walkRuntime(directory, relative = "") {
    const entries = await fs.readdir(directory, { withFileTypes: true });
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
      const childRelative = relative ? `${relative}/${entry.name}` : entry.name;
      const child = path.join(directory, entry.name);
      if (entry.isSymbolicLink() || (!entry.isFile() && !entry.isDirectory())) throw new ModelError(`artifact runtime contains a symlink or special entry: ${childRelative}`);
      if (entry.isDirectory()) await walkRuntime(child, childRelative);
      else {
        const { data } = await readStableRegularFile(child, `artifact runtime file ${childRelative}`);
        totalTreeBytes += data.length;
        if (observedTree.length >= 10000 || totalTreeBytes > 512 * 1024 * 1024) throw new ModelError("artifact runtime package tree exceeds receipt bounds");
        observedTree.push({ path: childRelative, size: data.length, sha256: sha256(data) });
      }
    }
  }
  await walkRuntime(packageRoot);
  if (JSON.stringify(observedTree) !== JSON.stringify(expectedTree)) throw new ModelError("artifact runtime package tree does not match its receipt");
  if (montageHelper) {
    const helper = record(receipt.montage_helper, "artifact runtime montage-helper receipt");
    const canonicalHelper = await fs.realpath(path.resolve(montageHelper));
    if (helper.path !== canonicalHelper || !/^[0-9a-f]{64}$/.test(helper.sha256 || "")
      || await hashRegularFile(canonicalHelper, "montage helper") !== helper.sha256) {
      throw new ModelError("montage helper does not match its runtime receipt");
    }
  }
  const pythonLauncher = montageHelper ? await validatePythonRuntime(receipt, pythonValue) : null;
  return { module: await import(`${pathToFileURL(entrypoint).href}?receipt=${receipt.entrypoint_sha256}`), version: receipt.version, receiptSha256: sha256(receiptData), pythonLauncher };
}

async function writeBlob(filename, blob) {
  await fs.writeFile(filename, new Uint8Array(await blob.arrayBuffer()), { flag: "wx", mode: 0o600 });
}

function validateLayout(layoutText, stem) {
  const layout = JSON.parse(layoutText);
  if (layout?.schema !== "openai.presentation.layout/v4" || !Array.isArray(layout.elements)) {
    throw new ModelError(`${stem} produced an unsupported layout manifest`);
  }
  for (const element of layout.elements) {
    if (!Array.isArray(element.bbox) || element.bbox.length !== 4) continue;
    const [left, top, width, height] = element.bbox;
    if (![left, top, width, height].every(Number.isFinite) || width < 0 || height < 0 || left < -0.5 || top < -0.5 || left + width > 1280.5 || top + height > 720.5) {
      throw new ModelError(`${stem} element ${element.name || element.id} overflows the slide canvas`);
    }
    if (typeof element.text === "string" && element.text.trim() && !String(element.name || "").startsWith("footer-")) {
      if (!Number.isFinite(element.resolvedFontSize) || element.resolvedFontSize < 16) {
        throw new ModelError(`${stem} element ${element.name || element.id} renders below 16pt`);
      }
    }
    if (String(element.name || "").startsWith("slide-title-") && element.textLayout?.lineCount !== 1) {
      throw new ModelError(`${stem} title wraps unexpectedly`);
    }
  }
}

async function createMontage(helperValue, pythonValue, qaPath, slideCount) {
  const helper = path.resolve(helperValue);
  const info = await fs.lstat(helper);
  if (!info.isFile() || info.isSymbolicLink() || path.extname(helper).toLowerCase() !== ".py") throw new ModelError("--montage-helper must be a regular non-symlink Python file");
  const python = path.resolve(pythonValue);
  const pythonInfo = await fs.lstat(python);
  if (!pythonInfo.isFile() && !pythonInfo.isSymbolicLink()) throw new ModelError("--python must be a regular file or a bound virtual-environment symlink");
  const pythonTarget = await fs.realpath(python);
  const pythonTargetInfo = await fs.lstat(pythonTarget);
  if (!pythonTargetInfo.isFile() || pythonTargetInfo.isSymbolicLink()) throw new ModelError("--python must resolve to a regular executable");
  const slides = Array.from({ length: slideCount }, (_, index) => path.join(qaPath, `slide-${String(index + 1).padStart(2, "0")}.png`));
  const output = path.join(qaPath, "deck-montage.png");
  try {
    await execFileAsync(python, [helper, "--input_files", ...slides, "--output_file", output, "--num_col", "5", "--label_mode", "number", "--fail_on_image_error"], {
      timeout: 120000,
      maxBuffer: 1024 * 1024,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONNOUSERSITE: "1" },
    });
  } catch (error) {
    throw new ModelError(`presentation montage helper failed: ${error.message}`);
  }
  const { data } = await readStableRegularFile(output, "presentation montage");
  if (data.length < 24 || data.subarray(1, 4).toString("ascii") !== "PNG") throw new ModelError("presentation montage helper did not produce PNG output");
  const width = data.readUInt32BE(16);
  const height = data.readUInt32BE(20);
  const expectedRows = Math.ceil(slideCount / 5);
  if (width < 2000 || height < expectedRows * 225) throw new ModelError("presentation montage dimensions do not cover every slide");
  await fs.writeFile(path.join(qaPath, "deck-montage.json"), `${JSON.stringify({ slide_count: slideCount, columns: 5, rows: expectedRows, width, height }, null, 2)}\n`, { flag: "wx" });
}

async function buildDeck(model, output, qaDir, workspace, artifactRuntimeReceipt, workspaceRoot, montageHelper, python) {
  const artifactTool = await loadArtifactTool(workspace, artifactRuntimeReceipt, workspaceRoot, montageHelper, python);
  const { Presentation, PresentationFile } = artifactTool.module;
  const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });
  addCover(presentation, model);
  let number = 2;
  number += addOutcomeSlides(presentation, model, number);
  number += addArchitectureSlides(presentation, model, number);
  number += addFindingSlides(presentation, model, number);
  number += addControlSlides(presentation, model, number);
  addClose(presentation, model, number);

  let qaPath = null;
  if (qaDir) {
    qaPath = await fs.realpath(path.resolve(qaDir));
    workspaceRelative(workspaceRoot, qaPath, "QA directory");
    const qaInfo = await fs.lstat(qaPath);
    if (!qaInfo.isDirectory() || qaInfo.isSymbolicLink()) throw new ModelError("--qa-dir must be a real directory");
    if ((await fs.readdir(qaPath)).length !== 0) throw new ModelError("--qa-dir must be empty");
  }
  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    const rendered = await presentation.export({ slide, format: "png", scale: 1 });
    const layout = await slide.export({ format: "layout" });
    const layoutText = await layout.text();
    validateLayout(layoutText, stem);
    if (qaPath) {
      await writeBlob(path.join(qaPath, `${stem}.png`), rendered);
      await fs.writeFile(path.join(qaPath, `${stem}.layout.json`), layoutText, { flag: "wx" });
    }
  }
  if (qaPath) {
    await createMontage(montageHelper, artifactTool.pythonLauncher, qaPath, presentation.slides.items.length);
  }
  const pptx = await PresentationFile.exportPptx(presentation);
  const temporaryOutput = path.join(path.dirname(output), `.${path.basename(output)}.${process.pid}.${crypto.randomBytes(8).toString("hex")}.tmp.pptx`);
  const inspectSidecar = `${temporaryOutput}.inspect.ndjson`;
  let temporarySha256;
  let published = false;
  try {
    await pptx.save(temporaryOutput);
    await fs.chmod(temporaryOutput, 0o400);
    temporarySha256 = await hashRegularFile(temporaryOutput, "temporary PowerPoint output");
    try {
      await execFileAsync(python, [PPTX_VALIDATOR, temporaryOutput], { timeout: 30000, maxBuffer: 1024 * 1024 });
    } catch (error) {
      throw new ModelError(`PowerPoint output validation failed: ${String(error.stderr || error.message).trim()}`);
    }
    try {
      await fs.link(temporaryOutput, output);
      published = true;
    } catch (error) {
      if (error.code === "EEXIST") throw new ModelError("output already exists; refusing to overwrite it");
      throw error;
    }
    const [temporaryInfo, outputInfo] = await Promise.all([fs.lstat(temporaryOutput), fs.lstat(output)]);
    if (!outputInfo.isFile() || outputInfo.isSymbolicLink()
      || temporaryInfo.dev !== outputInfo.dev || temporaryInfo.ino !== outputInfo.ino) {
      throw new ModelError("PowerPoint output publication identity changed");
    }
    const publishedSha256 = await hashRegularFile(output, "published PowerPoint output");
    if (publishedSha256 !== temporarySha256) throw new ModelError("published PowerPoint output digest changed");
    try {
      await execFileAsync(python, [PPTX_VALIDATOR, output], { timeout: 30000, maxBuffer: 1024 * 1024 });
    } catch (error) {
      throw new ModelError(`published PowerPoint validation failed: ${String(error.stderr || error.message).trim()}`);
    }
    try {
      const sidecarInfo = await fs.lstat(inspectSidecar);
      if (sidecarInfo.isFile() && !sidecarInfo.isSymbolicLink()) {
        if (qaPath) {
          await fs.copyFile(inspectSidecar, path.join(qaPath, "deck.inspect.ndjson"), fsConstants.COPYFILE_EXCL);
          await fs.unlink(inspectSidecar);
        }
        else await fs.unlink(inspectSidecar);
      }
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  } catch (error) {
    if (published) {
      await fs.unlink(output).catch(() => {});
    }
    throw error;
  } finally {
    await fs.unlink(temporaryOutput).catch((error) => {
      if (error.code !== "ENOENT") throw error;
    });
    await fs.unlink(inspectSidecar).catch((error) => {
      if (error.code !== "ENOENT") throw error;
    });
  }
  return { slideCount: presentation.slides.items.length, qaPath, artifactToolVersion: artifactTool.version, artifactRuntimeReceiptSha256: artifactTool.receiptSha256, outputSha256: temporarySha256 };
}

async function readStableRegularFile(filename, field) {
  let handle;
  try {
    const pathInfo = await fs.lstat(filename);
    if (!pathInfo.isFile() || pathInfo.isSymbolicLink()) throw new ModelError(`${field} must be a regular non-symlink file`);
    handle = await fs.open(filename, fsConstants.O_RDONLY | (fsConstants.O_NOFOLLOW ?? 0));
    const before = await handle.stat();
    if (!before.isFile()) throw new ModelError(`${field} must be a regular non-symlink file`);
    const data = await handle.readFile();
    const after = await handle.stat();
    if (pathInfo.dev !== before.dev || pathInfo.ino !== before.ino || data.length !== before.size || before.dev !== after.dev || before.ino !== after.ino
      || before.size !== after.size || before.mtimeMs !== after.mtimeMs) {
      throw new ModelError(`${field} changed while being read`);
    }
    return { data, stat: after };
  } catch (error) {
    if (error instanceof ModelError) throw error;
    throw new ModelError(`${field} must be a stable regular non-symlink file`);
  } finally {
    if (handle) await handle.close();
  }
}

async function hashRegularFile(filename, field) {
  const { data } = await readStableRegularFile(filename, field);
  return sha256(data);
}

async function qaBindings(qaPath) {
  if (!qaPath) return [];
  const directoryBefore = await fs.lstat(qaPath);
  if (!directoryBefore.isDirectory() || directoryBefore.isSymbolicLink()) throw new ModelError("QA output directory is unsafe");
  const names = (await fs.readdir(qaPath)).sort();
  const bindings = [];
  for (const name of names) {
    if (name.includes("/") || name.includes("\\") || name === "." || name === "..") throw new ModelError("QA output contains an unsafe filename");
    const filename = path.join(qaPath, name);
    const { data, stat } = await readStableRegularFile(filename, `QA file ${name}`);
    const pathInfo = await fs.lstat(filename);
    if (pathInfo.dev !== stat.dev || pathInfo.ino !== stat.ino) throw new ModelError(`QA file ${name} changed identity while being bound`);
    bindings.push({ file: name, sha256: sha256(data) });
  }
  const directoryAfter = await fs.lstat(qaPath);
  if (directoryBefore.dev !== directoryAfter.dev || directoryBefore.ino !== directoryAfter.ino
    || directoryBefore.mtimeMs !== directoryAfter.mtimeMs) {
    throw new ModelError("QA output directory changed while being bound");
  }
  return bindings;
}

async function writeBuildManifest(filename, model, bindings, output, build) {
  const payload = {
    schema_version: 1,
    assessment: model.assessment,
    target: model.target,
    extension_id: model.extension_id,
    version: model.version,
    run_key: model.run_key,
    classification: model.classification,
    generated_at: new Date().toISOString(),
    generator: "scripts/build_assessment_pptx.mjs",
    runtime_versions: {
      node: process.version,
      artifact_tool: build.artifactToolVersion,
    },
    artifact_runtime_receipt_sha256: build.artifactRuntimeReceiptSha256,
    inputs: bindings,
    output: {
      file: path.basename(output),
      sha256: build.outputSha256,
      slide_count: build.slideCount,
    },
    qa_files: await qaBindings(build.qaPath),
    native_powerpoint_closeout: "Pending",
  };
  await fs.writeFile(filename, `${JSON.stringify(payload, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const workspaceRoot = await resolveWorkspaceRoot(args.workspaceRoot);
  args.workspaceRoot = workspaceRoot;
  args.stageRoot = await resolveExistingWithinWorkspace(workspaceRoot, args.stageRoot, "stage root");
  for (const [key, field] of [["authoritativeDocx", "authoritative Word DOCX"], ["authoritativeBuildManifest", "authoritative Word build manifest"], ["wordQaRecord", "Word QA record"]]) {
    if (args[key]) args[key] = await resolveExistingWithinWorkspace(workspaceRoot, args[key], field);
  }
  const { stageRoot, input, model, bindings, authoritativeWord } = await loadBoundModel(args);
  workspaceRelative(workspaceRoot, stageRoot, "stage root");
  if (authoritativeWord) {
    bindings.authoritative_word = validateAuthoritativeWord(workspaceRoot, model, bindings.report_model, authoritativeWord);
  }
  if (args.validateOnly) {
    process.stdout.write(`${JSON.stringify({ status: "validated", stage_root: stageRoot, input, target: model.target, findings: model.findings.length, references: model.references.length, authoritative_word: Boolean(bindings.authoritative_word) })}\n`);
    return;
  }
  const output = await safeOutput(workspaceRoot, args.output, ".pptx");
  const buildManifest = await safeOutput(workspaceRoot, args.buildManifest, ".json");
  if (input === output) throw new ModelError("input and output paths must differ");
  if (buildManifest === output || buildManifest === input) throw new ModelError("build manifest path must differ from input and output paths");
  const build = await buildDeck(model, output, args.qaDir, args.workspace, args.artifactRuntimeReceipt, workspaceRoot, args.montageHelper, args.python);
  await writeBuildManifest(buildManifest, model, bindings, output, build);
  process.stdout.write(`${JSON.stringify({ status: "built", output, build_manifest: buildManifest, slide_count: build.slideCount, qa_dir: build.qaPath })}\n`);
}

try {
  await main();
} catch (error) {
  const message = error instanceof ModelError ? error.message : `unexpected failure: ${error.message}`;
  process.stderr.write(`build_assessment_pptx: ${message}\n`);
  if (process.env.DEBUG_ASSESSMENT_PPTX === "1" && error.stack) process.stderr.write(`${error.stack}\n`);
  process.exitCode = 2;
}
