# Mandatory stage-output contract

Create and retain the following assessment stages before assembling the authoritative report. Use deterministic filenames or a machine-readable manifest mapping equivalent files to these stages.

1. Intake, identity, scope, analysis selections, authorization boundaries, and readiness.
2. Evidence plan and evidence-register baseline.
3. Acquisition provenance, signatures, hashes, versions, and immutable artefact inventory.
4. Static package, source, manifest, dependency, and binary inspection.
5. Per-IDE installation manifest, activation, persistence, update, uninstall, and residue analysis.
6. Architecture, trust boundaries, data flows, privileges, authentication, telemetry, privacy, and network endpoints.
7. Runtime test plan, baseline, observations, network/process/file/configuration deltas, cleanup, and blocked-platform gaps.
8. Malware, IOC/YARA, obfuscation, native-code, source-package comparison, and supply-chain review.
9. SBOM or SBOM-style inventory, vulnerability/advisory scans, and manual triage.
10. MCP tools/resources/prompts and installed Agent Skills inventory and assessment.
11. Privacy, data protection, records, sector, jurisdiction, and regulatory assessment.
12. Complete framework-disposition and requirement mappings for each applicable IDE.
13. Validated finding records and consolidated risk register.
14. Enterprise controls roadmap, detection opportunities, monitoring, owners, milestones, and verification tests.
15. Claim-to-evidence and claim-to-reference manifest plus report QA record.

Each stage output must state target/version, generation time, input evidence IDs, method/tool versions, evidence state, confidence, limitations, and analyst validation status. Resolve contradictions before report assembly.

The report generator must consume all validated stages. If a mandatory stage is unavailable, preserve a placeholder recording `Blocked`, `Not applicable`, or `Unknown` with rationale; do not omit the stage or silently replace it with prose generated from conversation history.
