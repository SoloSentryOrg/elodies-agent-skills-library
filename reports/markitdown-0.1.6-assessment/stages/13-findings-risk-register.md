# Stage 13 - Findings and risk register

- Target/version: Microsoft MarkItDown 0.1.6.
- Generated: 2026-07-25T16:08:34Z.
- Inputs: Validated Stages 03-12.
- Method/tools: Likelihood and impact scoring on 1-5 scales; inherent and residual scores calculated separately.
- Evidence state: Validated.
- Confidence: High for static findings; Medium where runtime evidence is absent.
- Limitations: Runtime evidence gaps do not lower severity.
- Analyst validation: Validated 2026-07-25.

- F-001 Unrestricted URI authority enables local-file disclosure and SSRF through agent tool use. Inherent 20 Critical; residual 16 High without enforced sandbox allowlists.
- F-002 Published HTTP/SSE modes are unauthenticated and affected by applicable MCP SDK vulnerabilities. Inherent 20 Critical; residual 20 Critical in the published configuration.
- F-003 Unbounded network/data/archive processing enables memory, time, and availability exhaustion. Inherent 16 High; residual 16 High.
- F-004 Broad and incompletely pinned transitive supply chain, including a pre-release MCP package and constrained vulnerable SDK. Inherent 16 High; residual 12 High.
- F-005 Runtime, install, update, and uninstall behavior is unverified on all requested hosts. Inherent 12 High; residual 12 High.
- F-006 Converted output may disclose personal, confidential, or regulated data to the IDE/LLM context without organizational data controls. Inherent 20 Critical; residual 15 High with proposed controls.
- F-007 Source-to-package provenance for MCP 0.0.1a4 is not reproducibly linked to an MCP-specific source tag or signed attestation. Inherent 9 Moderate; residual 9 Moderate.
