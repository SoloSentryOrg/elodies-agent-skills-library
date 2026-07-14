# Framework application guide

Verify current official framework versions and control identifiers at assessment time. Do not rely on remembered numbering. Cite primary framework or regulator sources and record access dates.

## Minimum baseline

- **OWASP Top 10 for LLM Applications:** prompt injection, disclosure, supply chain, poisoning, output handling, agency, prompt leakage, retrieval/vector weaknesses, misinformation, consumption, as present in the current edition.
- **OWASP Agentic AI:** map agent-specific threats and mitigations using the current official taxonomy/project materials.
- **MITRE ATLAS:** map credible adversary techniques, not every possible technique.
- **NIST AI RMF and NIST AI 600-1:** organize governance, mapping, measurement, and management evidence; use the Generative AI Profile for generative-AI risks.
- **CIS Controls:** map prioritized safeguards for inventory, secure configuration, access, vulnerability management, logging, malware defenses, recovery, service providers, and testing.
- **ISO/IEC 27001 Annex A:** map applicable organizational, people, physical, and technological controls; identify the edition used.
- **NCSC secure-AI guidance:** apply secure design, development, deployment, operation, supply-chain, monitoring, and incident-management principles from current UK NCSC guidance.

Apply every minimum-baseline framework to each supported IDE assessment. Map precise applicable controls or techniques rather than every possible identifier.

## Conditional requirements

Record `Applicable` or `Not applicable` with a reason and evidence for every conditional requirement:

- **OWASP MCP:** apply when MCP is present, supported, configured, bundled, invoked, or reasonably expected. Label draft or beta status accurately.
- **OWASP ASVS:** apply the current OWASP Application Security Verification Standard to applicable extension services, APIs, authentication, session management, access control, validation, output handling, cryptography, communications, file handling, configuration and webview components. Select and justify the appropriate ASVS verification level. Do not force web-specific requirements onto non-web components; record `Not applicable` with evidence when no qualifying application surface exists.
- **UK GDPR and ICO guidance:** apply when personal-data processing is actual, possible, or unresolved. Include the Data Protection Act 2018 and PECR where relevant. Assess lawfulness, transparency, minimisation, privacy by design and default, security, controller/processor roles, recipients, transfers, retention, deletion, DPIA screening, and data-subject effects.
- **FCA/PRA and UK financial- or insurance-sector obligations:** apply for relevant regulated entities, services, deployments, outsourcing or third-party arrangements. Assess materiality, operational resilience, important business services, data security, auditability, concentration, incident reporting, accountability, and exit planning.
- **Other jurisdictions and sectors:** apply equivalent privacy, AI, cyber-security, resilience, records, outsourcing, consumer-protection, or regulated-accountability requirements where the deployment context requires them.

## UK financial and insurance sector application

Determine applicability before mapping. Consider current official requirements and guidance from:

- FCA Principles, SYSC and operational-resilience expectations;
- PRA Fundamental Rules, operational resilience, outsourcing/third-party risk, model risk and supervisory statements relevant to the assessed use;
- FCA/PRA policy on critical third parties and third-party dependencies where applicable;
- UK DORA-equivalent context only when legally/applicably justified; do not state EU DORA applies merely because the firm is UK-regulated;
- UK GDPR, Data Protection Act 2018, ICO AI/data-protection guidance and PECR where relevant;
- sector-specific records, auditability, change control, concentration risk, exit planning, incident reporting, consumer duty, and regulated accountability.

Identify whether each item is law, rule, supervisory statement, guidance, consultation, or good practice. Do not present guidance as a binding rule. Record jurisdiction, entity type, materiality, outsourcing relationship, data involved, deployment context, and assessment date.

## Crosswalk discipline

- Map each finding/control once to precise applicable clauses; avoid decorative many-to-many mappings.
- Explain the evidence showing the control objective is met or the gap exists.
- Include a framework-disposition table listing every minimum and conditional framework, its edition/status, applicability, evidence, mapped sections and any limitation.
- Keep framework compliance conclusions scoped: an extension assessment does not certify organizational compliance.
