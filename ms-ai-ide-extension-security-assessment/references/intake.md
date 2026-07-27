# Intake questionnaire

Ask only fields not already answered. Clarification is permitted before assessment begins.

## Identity and scope

- Extension/product name as shown in the marketplace
- Marketplace URL or marketplace (Visual Studio Marketplace, VS Code Marketplace, private catalogue, other)
- Publisher and extension ID, if known
- Version/channel: exact version or latest current
- IDEs: VS Code, Visual Studio, both; IDE versions/channels and operating systems
- Assessment purpose, scope exclusions, target audience, decision deadline
- Enterprise environment: sector, jurisdictions, data classifications, deployment model, managed/unmanaged endpoints
- Air-gapped/restricted-egress status and proxy/inspection constraints

## AI and integration surface

- MCP expected or known; local/remote servers and authentication
- Agent Skills expected or known; installation scope and locations
- Models/providers, agent mode, tool permissions, auto-approval, terminal/file/cloud access
- Source repository/package availability and any supplied artefacts

## Analysis choices

- Static package/source/code analysis: **Yes (default) / No**
- Malware-focused review and static scanning: **Yes (default) / No**
- Runtime/dynamic analysis: **Yes (default) / No**
- Privacy/data-protection assessment: Yes by default unless excluded
- Need binary reverse engineering or only package/static inspection
- Required framework or internal-policy additions
- Required derivatives: PowerPoint, Excel risk register, diagrams, Markdown, SBOM inventory, concise report
- Required template, branding, classification, approvers, and output location

## Safe defaults

- Use the latest stable version when no version is supplied, state the retrieval date, and preserve the package hash.
- Assess both IDEs only when requested or when the listing claims support for both.
- Treat the three Yes defaults as standing authorization for non-destructive static analysis, static malware scanning, and isolated runtime observation using synthetic data. Require a disposable, revertible, least-privilege environment before installation or execution.
- Never infer authorization for production access, real credentials, customer data, destructive testing, persistence, credential access, lateral movement, detonation, or unrestricted external callbacks.
- If a safe runtime environment is unavailable, do not silently change runtime analysis to No. Record the selected Yes state, the blocked capability, the evidence not collected, and the resulting approval constraint.
- Mark unanswered material fields as assumptions or limitations.
