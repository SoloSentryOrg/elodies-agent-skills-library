# Stage 06 - Architecture, data flows, and privacy

- Target/version: Microsoft MarkItDown 0.1.6.
- Generated: 2026-07-25T16:08:34Z.
- Inputs: Stages 03-05.
- Method/tools: Trust-boundary, privilege, authentication, endpoint, telemetry, and data-flow analysis.
- Evidence state: Verified static architecture; runtime destinations Unknown.
- Confidence: High for code paths; Medium for deployment behavior.
- Limitations: Runtime destinations cannot be directly observed on blocked hosts.
- Analyst validation: Validated 2026-07-25.

Trust boundaries are: user/agent prompt to IDE MCP client; client to local MCP server; URI to local filesystem or network; parser and optional native/transitive dependencies; returned Markdown to the LLM context. The server runs with the invoking user's privileges. A malicious or mistaken tool call can read any permitted local file or contact any reachable URL, including loopback, link-local, intranet, or cloud metadata destinations unless external controls block it. Converted content can include personal, confidential, credential, or regulated data and is returned into the agent context. No MarkItDown application telemetry was observed in the published MCP code, but optional converters can use network services and IDE/client telemetry is outside package scope.
