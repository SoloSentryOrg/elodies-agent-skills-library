# Authoritative report structure

Use professional tone, numbered headings, table of contents, revision history, document control/classification, glossary, numbered figures/tables, page numbers, and consistent captions. Use the detailed report as the source of truth for all derivatives.

## Front matter and shared overview

1. Executive Summary
   - Decision and overall residual risk
   - Top five important outcomes as bullets
   - Approval conditions and immediate actions
2. Purpose & Function Overview
3. Scope, Assumptions, Methodology and Assessment Criteria
4. Product Identity and Version

## Part I — VS Code assessment (self-contained)

Repeat enough product context for this part to stand alone:

1. Executive decision for VS Code
2. Purpose/function and supported version
3. Architecture
4. Trust boundaries
5. Data flows
6. Installation manifest and uninstall behavior
7. Runtime processes and activation
8. Network communications, authentication, telemetry, privacy
9. MCP surface and installed skills, including a complete per-skill decision/risk summary for every skill applicable to this IDE
10. Supply-chain and dependency assessment
11. Threat scenarios and findings
12. OWASP LLM, Agentic AI, MCP (if applicable), MITRE ATLAS, NIST AI RMF, ASVS, CIS, ISO 27001, NCSC, FCA/PRA/UK-sector mappings
13. Enterprise controls and detection opportunities
14. Residual risk, confidence, limitations, and approval recommendation
15. VS Code evidence and host-verification actions

## Part II — Visual Studio assessment (self-contained)

Use the same complete subsection sequence as Part I, using Visual Studio-specific evidence, paths, package format, processes, trust settings, permissions, policies, and tool surface.

## Part III — Shared installed Agent Skills (only if applicable)

1. Shared skill inventory and provenance
2. Per-skill purpose, installation, architecture/data flow, privileges and dependencies
3. Prompt injection, hidden instructions, external references, tool invocation, scripts, supply chain, data exfiltration, privacy and audit analysis
4. Framework mappings, findings, scoring, controls, residual risk and approval per skill

This part may hold the full common analysis, but it does not replace the complete decision/risk summary required inside each applicable IDE part.

## Consolidated sections

1. Cross-IDE comparison and systemic/composition risks
2. Consolidated Supply Chain Assessment
3. Consolidated Privacy/Data Protection Assessment
4. Enterprise Controls Roadmap
5. Detection Opportunities and Monitoring Plan
6. Consolidated Risk Register
7. Residual Risk and Approval Recommendation
8. Limitations and Confidence Levels
9. Evidence Register
10. References
11. Appendices, including exhaustive manifests, SBOM-style inventory, schemas, and verification procedures

## Citation mechanics

- Assign stable references such as `REF-001` and evidence items such as `EVD-001`.
- Create a Word bookmark at each references-table entry, for example `REF_001`.
- Make each in-text citation display `[REF-001]` and hyperlink internally to that bookmark.
- In the references table, hyperlink the source title or URL to the external source.
- Use separate citations for distinct claims; include pinpoint section/page/version where available.
- Test every internal and external hyperlink during QA.
- Inspect the final DOCX package XML to confirm every in-text `REF-nnn` hyperlink targets an existing bookmark and every reference entry has the expected external relationship. Treat broken or duplicate bookmark targets as a shipping failure.
