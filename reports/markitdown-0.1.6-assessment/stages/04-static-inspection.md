# Stage 04 - Static package and source inspection

- Target/version: Microsoft MarkItDown 0.1.6.
- Generated: 2026-07-25T16:08:34Z.
- Inputs: Stage 03 artifacts.
- Method/tools: Archive, manifest, source, dependency, binary, script, and source-package comparison.
- Evidence state: Verified.
- Confidence: High for published Python code.
- Limitations: No discovered code will be executed.
- Analyst validation: Validated 2026-07-25.

The MCP wheel contains eight files and exposes one console entry point and one tool, `convert_to_markdown(uri)`. The tool accepts `http:`, `https:`, `file:`, and `data:` URIs and passes them directly to `MarkItDown().convert_uri`. No path root, host allowlist, address-class filter, maximum input/output size, request timeout, concurrency limit, or tool-layer authorization check is present.

HTTP mode creates unauthenticated SSE and stateless Streamable HTTP endpoints, binds to loopback by default, and enables Starlette debug mode. STDIO is the default. The core library performs network fetches without an explicit timeout and buffers response bodies into memory. Data URIs are decoded into memory. ZIP members are read recursively into memory without explicit aggregate depth/size/member limits. Plugins are disabled in the published MCP wheel because it constructs `MarkItDown()` without `enable_plugins=True`.
