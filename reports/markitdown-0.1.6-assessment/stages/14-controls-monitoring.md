# Stage 14 - Controls roadmap and monitoring

- Target/version: Microsoft MarkItDown 0.1.6.
- Generated: 2026-07-25T16:08:34Z.
- Inputs: Validated findings and enterprise context.
- Method/tools: Preventive, detective, responsive, recovery, ownership, milestone, and verification-test design.
- Evidence state: Validated roadmap.
- Confidence: High.
- Limitations: Named organizational owners and implementation dates are not supplied.
- Analyst validation: Validated 2026-07-25.

Immediate controls: prohibit HTTP/SSE and remote binding; use STDIO only; block published package pending remediation; require IDE MCP allowlisting and per-tool confirmation; sandbox filesystem reads to an approved staging folder; deny network by default; prohibit data URIs and plugins; run as a dedicated low-privilege identity; pin package hashes and a remediated dependency set.

Within 30 days: obtain a vendor/remediated build that supports a fixed MCP SDK; implement URI scheme/host/path allowlists, private-address rejection, redirect validation, size/time/depth/concurrency limits, structured audit logs, and privacy workflow controls.

Within 31-90 days: complete disposable Windows 11 and macOS runtime testing, update/uninstall residue verification, incident exercises, DPIA, materiality assessment, business-owner acceptance, and exit testing. Detection should cover MCP configuration drift, non-STDIO transport, unexpected bind addresses, forbidden file paths/domains, large conversions, repeated failures, dependency drift, and sensitive-output handling.
