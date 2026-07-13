# Quality gates

## Evidence and security

- Identity, publisher, ID, version, package hash, IDE support, and assessment date are explicit.
- All material/current claims have working citations to primary evidence.
- “None,” “no evidence,” and “not installed” claims state the inspection scope and evidence state.
- Package handling remained static unless runtime analysis was authorized.
- Secrets, personal data, tokens, proprietary code, and unsafe URLs are absent from the deliverable and logs.
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

## Final secure review

Before committing or pushing skill changes, inspect all changed files for unsafe instructions, overbroad execution authority, secret leakage, malicious links, and insecure package-handling guidance. Resolve findings before any commit to `main`; if findings remain, propose fixes and request a decision.
