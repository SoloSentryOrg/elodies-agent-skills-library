# Installed Agent Skill assessment

Assess every installed or bundled skill as an independent governed artefact. Include its full transitive content: `SKILL.md`, metadata, references, assets, scripts, templates, executables, generated configuration, external links, and installer/update path.

## Establish provenance and installation

- Identify which IDE/package installs it, exact path/scope, publisher, version/commit, licence, signature/hash, update and uninstall behavior.
- Distinguish bundled, downloaded-on-demand, repository-local, user-global, extension-contributed, and remotely supplied instructions.
- Determine whether the same bytes and behavior are available to both IDEs. Do not assume format portability means identical installation or tool access.

## Analyze instruction behavior

- Trigger breadth, ambiguity, priority conflicts, instruction override attempts, and social-engineering language
- Prompt/context injection and untrusted-content handling
- Hidden instructions in Unicode, comments, metadata, images, encoded content, linked files, or generated artefacts
- Tool invocation, approval bypass, privilege, destructive actions, and cross-tool escalation
- External references, remote content, redirects, mutable branches/tags, and dynamic retrieval
- Script execution, interpreters, arguments, shell injection, filesystem/network access, persistence, and cleanup
- Supply chain: provenance, dependencies, update channel, pinning, integrity, maintainer compromise, and typosquatting
- Data access, collection, retention, telemetry, secrets handling, and exfiltration paths
- Unsafe output handling, misinformation, excessive agency, denial/cost loops, and auditability

## Framework and disposition

Apply OWASP LLM and OWASP Agentic AI at minimum; apply OWASP MCP when the skill configures or invokes MCP; map relevant MITRE ATLAS, NIST AI RMF, secure-development, privacy, and sector controls. Score each finding using the main risk method. State whether the skill is required, optional, separately installable, and safe to approve independently.
