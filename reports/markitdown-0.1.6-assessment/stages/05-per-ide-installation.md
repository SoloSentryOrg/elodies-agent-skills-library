# Stage 05 - Per-IDE installation and lifecycle

- Target/version: Microsoft MarkItDown 0.1.6.
- Generated: 2026-07-25T16:08:34Z.
- Inputs: Stages 01, 03, and 04.
- Method/tools: Expected-state manifest from official package evidence; runtime observations kept separate.
- Evidence state: Verified expected state; runtime state Unknown.
- Confidence: Medium.
- Limitations: Windows runtime evidence Blocked; no Microsoft MarkItDown VSIX assumed.
- Analyst validation: Validated 2026-07-25.

VS Code can register local MCP servers in user or workspace `mcp.json`; current documentation supports sandbox configuration and trust prompts. Visual Studio 2022 17.14+ and Visual Studio 2026 support MCP servers and organizational allow lists. MarkItDown is an MCP server/package, not a VSIX extension, so expected installation consists of the Python environment, package/dependencies, IDE MCP configuration, process, and caches/logs created by the client or package manager. Exact paths, process trees, update behavior, and uninstall residue are Unknown until host verification.
