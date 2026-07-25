# Stage 10 - MCP and Agent Skills

- Target/version: Microsoft MarkItDown 0.1.6.
- Generated: 2026-07-25T16:08:34Z.
- Inputs: Stages 03-04 and official documentation.
- Method/tools: Package/repository search for MCP tools/resources/prompts, Agent Skills, installers, and transitive instruction content.
- Evidence state: Verified.
- Confidence: High.
- Limitations: Documented integrations will not be treated as installed state.
- Analyst validation: Validated 2026-07-25.

MCP is Applicable. The server exposes one tool and no resources or prompts in the published wheel. Tool input is a single unrestricted URI string; tool output is Markdown. No Agent Skills, SKILL.md files, skill installer, skill manifest, or installed-skill behavior were observed in the assessed package contents. Agent Skills are therefore Not applicable, not absent from every possible deployment. Third-party MarkItDown plugins are a separate executable extension mechanism; they are disabled by default in the published MCP wheel and must remain prohibited unless independently assessed.
