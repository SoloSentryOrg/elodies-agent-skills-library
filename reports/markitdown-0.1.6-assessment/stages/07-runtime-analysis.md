# Stage 07 - Runtime analysis

- Target/version: Microsoft MarkItDown 0.1.6.
- Generated: 2026-07-25T16:08:34Z.
- Inputs: User authorization boundary and Stage 01.
- Method/tools: Runtime plan only; no installation or activation on non-disposable hosts.
- Evidence state: Blocked for Windows 11; Unknown for macOS pending a disposable host.
- Confidence: High regarding the gap.
- Limitations: No observed process, network, filesystem, configuration, update, or uninstall deltas.
- Analyst validation: Validated gap and host-verification plan 2026-07-25.

Dynamic analysis is authorized but not executed because no disposable Windows environment is available and no disposable macOS host was established. Required verification includes before/after package and IDE state, process/child-process capture, filesystem/configuration deltas, DNS/TLS/HTTP destinations, malformed request handling, URI allow/deny behavior, resource limits, MCP schemas, update, uninstall, residue, and rollback. Production endpoints and credentials are prohibited.
