# Quality gates

## Evidence and security

- Identity, publisher, ID, version, package hash, IDE support, and assessment date are explicit.
- All material/current claims have working citations to primary evidence.
- “None,” “no evidence,” and “not installed” claims state the inspection scope and evidence state.
- Package handling remained static unless runtime analysis was authorized.
- Secrets, personal data, tokens, proprietary code, and unsafe URLs are absent from the deliverable and logs.
- Internal lessons-learned registers, lesson IDs, RCA records, governance
  evidence, and related proprietary workflow details are absent from the
  report and all derivatives, even when they informed internal work.
- Agent Skills are distinguished from MCP tools, prompts, and resources and assessed independently.
- Cross-tool and multi-MCP composition risks are assessed.
- If malware review is Yes, hashes/signatures, reputation/advisories, static scans, IOC/YARA results where available, obfuscation/native-code triage, source-package comparison, scan limitations, and detonation status are recorded.

## Completeness and consistency

- Every requested report section is present or explicitly marked not applicable with rationale.
- VS Code and Visual Studio parts each stand alone and contain their own decision, evidence, controls, limitations, confidence, and framework mapping.
- Likelihood × impact calculations and rating bands are correct; residual risk reflects verified controls.
- Every consolidated risk-register table has a complete column/scoring legend
  immediately above it, including definitions for all abbreviations and the
  rating bands; the reader does not need to search elsewhere in the report.
- Framework editions and regulatory status are current and accurately characterized.
- Every minimum-baseline framework is mapped in each applicable IDE part; every conditional framework has an evidence-backed `Applicable` or `Not applicable` disposition.
- OWASP ASVS mappings state the edition, verification level and applicable requirement identifiers; a `Not applicable` disposition identifies the inspected application surface and rationale.
- Findings link to evidence, controls, owners, priorities, and verification tests.
- Approval scope includes version, IDE, conditions, review date/trigger, and unresolved blockers.

## Word and derivative QA

- Use a professional business-report design, real heading/list styles, readable tables, captions, TOC, headers/footers, revision history, and accessibility-friendly structure.
- Ensure in-text citations hyperlink to reference-table bookmarks and reference entries link externally.
- Validate DOCX bookmark targets and external hyperlink relationships by inspecting the OOXML package; do not rely only on visual appearance.
- Check cross-references, table/figure numbering, bookmarks, URLs, metadata, classification, spelling, and terminology.
- Render the DOCX to page images, inspect every page at full size, fix clipping/overflow/orphans/table defects, and re-render.
- Run accessibility and metadata/privacy checks supported by the document workflow.
- Derivatives contain no new claims or changed scores and identify the authoritative report/version.
- Each PPTX, XLSX, diagram, or other derivative passes the applicable presentation, spreadsheet, visualization, document, or PDF workflow validation gate.

## Deterministic authoritative-report gate

- Run `python scripts/validate_assessment_report.py <report.docx>` before delivery.
- Treat every validator failure as a shipping blocker. Do not waive thresholds, remove required sections, or relabel a summary as authoritative to obtain a pass.
- Confirm the report was assembled from every mandatory stage output in [stage-output-contract.md](stage-output-contract.md), not from a conversational summary or a manually shortened findings list.
- Record the validator version, command, result, report SHA-256, Microsoft Word page count, page-inspection result, accessibility result, and metadata/privacy result as retained QA evidence.
- Use [authoritative-report-standard.md](authoritative-report-standard.md) as the minimum acceptance profile. The profile's structural floors are anti-truncation controls, not writing targets; substantive evidence and judgment remain mandatory.

## Final secure review

Before committing or pushing skill changes, inspect all changed files for unsafe instructions, overbroad execution authority, secret leakage, malicious links, and insecure package-handling guidance. Resolve findings before any commit to `main`; if findings remain, propose fixes and request a decision.

## Optional repository publication handoff

- Apply this gate only when the repository defines an approved publication
  contract and the user explicitly requests public publication.
- Require every deterministic and native Microsoft Word gate above to pass
  before creating a publication request.
- Require the human disclosure owner to clear the exact report; `PUBLIC`
  classification means shareable content, not approval to publish.
- Derive report path, digest, Word page count, run identity, and QA outcomes
  from tracked authoritative evidence instead of manual transcription.
- Include the approved request in the assessment pull request when the
  repository contract supports a combined review.
- Use the repository's bounded, resumable orchestrator for bundle correlation,
  signed promotion, exact-head checks, human merge handoff, post-merge
  verification, and approved cleanup.
- Never auto-merge, introduce a cross-repository credential, or publish source
  snapshots, evidence, stage output, private paths, issue links, or provenance.
