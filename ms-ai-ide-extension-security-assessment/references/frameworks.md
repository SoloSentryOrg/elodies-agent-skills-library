# Framework application guide

Verify current official framework versions and control identifiers at assessment time. Do not rely on remembered numbering. Cite primary framework or regulator sources and record access dates.

## Mandatory mappings

- **OWASP Top 10 for LLM Applications:** prompt injection, disclosure, supply chain, poisoning, output handling, agency, prompt leakage, retrieval/vector weaknesses, misinformation, consumption, as present in the current edition.
- **OWASP Agentic AI:** map agent-specific threats and mitigations using the current official taxonomy/project materials.
- **OWASP MCP:** apply when MCP is present or configured; label draft/beta status accurately.
- **MITRE ATLAS:** map credible adversary techniques, not every possible technique.
- **NIST AI RMF:** organize governance, mapping, measurement, and management evidence; include the Generative AI Profile when relevant.
- **OWASP ASVS:** apply to extension services, authentication, sessions, input/output, cryptography, communications, files, configuration, and APIs where relevant; do not force web-only requirements onto non-web components.
- **CIS Controls:** map prioritized safeguards for inventory, secure configuration, access, vulnerability management, logging, malware defenses, recovery, service providers, and testing.
- **ISO/IEC 27001 Annex A:** map applicable organizational, people, physical, and technological controls; identify the edition used.
- **NCSC secure-AI guidance:** apply secure design, development, deployment, operation, supply-chain, monitoring, and incident-management principles from current UK NCSC guidance.

## UK financial and insurance sector

Determine applicability before mapping. Consider current official requirements and guidance from:

- FCA Principles, SYSC and operational-resilience expectations;
- PRA Fundamental Rules, operational resilience, outsourcing/third-party risk, model risk and supervisory statements relevant to the assessed use;
- FCA/PRA policy on critical third parties and third-party dependencies where applicable;
- UK DORA-equivalent context only when legally/applicably justified; do not state EU DORA applies merely because the firm is UK-regulated;
- UK GDPR and Data Protection Act 2018, ICO AI/data-protection guidance, PECR where relevant;
- sector-specific records, auditability, change control, concentration risk, exit planning, incident reporting, consumer duty, and regulated accountability.

Identify whether each item is law, rule, supervisory statement, guidance, consultation, or good practice. Do not present guidance as a binding rule. Record jurisdiction, entity type, materiality, outsourcing relationship, data involved, deployment context, and assessment date.

## Crosswalk discipline

- Map each finding/control once to precise applicable clauses; avoid decorative many-to-many mappings.
- Explain the evidence showing the control objective is met or the gap exists.
- Keep framework compliance conclusions scoped: an extension assessment does not certify organizational compliance.
