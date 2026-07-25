# Stage 01 - Intake, identity, scope, and readiness

- Target: Microsoft `microsoft/markitdown`, latest stable version 0.1.6.
- Generated: 2026-07-25T16:08:34Z.
- Scope: VS Code on Windows 11 and macOS; Visual Studio on Windows 11.
- Context: UK financial services; Internal Confidential.
- Analysis selections: static analysis Yes; static malware review Yes; runtime analysis Yes; privacy review Yes.
- Authorization boundary: non-destructive work only; synthetic data; no production credentials or repositories; no detonation.
- Identity: Verified from GitHub and PyPI. The Microsoft product is a Python package/CLI and repository, not the third-party `bioinfo.markitdown-vscode` VSIX.
- Readiness: Partially ready. Baseline research, acquisition, hashing, static inspection, malware triage, SBOM, DOCX authoring, and Microsoft Word QA are available. Windows runtime analysis is Blocked because no disposable Windows environment is available. macOS runtime is not assumed authorized or safe without an explicit disposable host.
- Inputs: User intake; REF-001; REF-002; EVD-001.
- Method/tools: GitHub API, PyPI JSON API, web search, local prerequisite inventory.
- Evidence state: Verified with stated runtime Unknowns.
- Confidence: High for identity and static readiness; High for the Windows runtime gap.
- Limitations: No Windows runtime installation, activation, network, persistence, update, or uninstall observation.
- Analyst validation: Pending final evidence reconciliation.
