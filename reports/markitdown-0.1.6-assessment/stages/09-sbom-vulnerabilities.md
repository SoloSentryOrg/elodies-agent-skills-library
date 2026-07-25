# Stage 09 - SBOM and vulnerability analysis

- Target/version: Microsoft MarkItDown 0.1.6.
- Generated: 2026-07-25T16:08:34Z.
- Inputs: Stage 03 artifacts and package metadata.
- Method/tools: Syft, OSV-Scanner, Grype, Trivy, and manual advisory triage where applicable.
- Evidence state: Verified resolution snapshot and advisory triage.
- Confidence: High.
- Limitations: Optional dependency sets and uninstalled transitive resolution will be distinguished.
- Analyst validation: Validated 2026-07-25.

Syft 1.49.0 generated CycloneDX inventories for both wheels. A reproducible `uv` resolution for Python 3.12 produced 71 Windows packages and 68 macOS packages. The MCP package requires `mcp~=1.8.0`, resolving to 1.8.1 and excluding fixed later releases.

Applicable SDK advisories:

- CVE-2025-66416 / GHSA-9h52-p55h-vw2f: DNS rebinding protection absent by default for unauthenticated localhost HTTP MCP servers; fixed in 1.23.0.
- CVE-2025-53366 / GHSA-3qhf-m339-9g5v: malformed requests can cause service unavailability; fixed in 1.9.4.
- CVE-2025-53365 / GHSA-j975-95f5-7wqh: streamable HTTP exception can crash the server; fixed in 1.10.0.

Detected but not applicable: CVE-2026-52869 requires authenticated stateful HTTP sessions; published MarkItDown is unauthenticated and stateless for Streamable HTTP. CVE-2026-59950 affects a deprecated WebSocket transport that MarkItDown does not expose.
