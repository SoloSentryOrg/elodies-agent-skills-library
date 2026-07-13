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

- Runtime/dynamic analysis: **No (default) / Yes**
- Malware-focused review: No/Yes
- Privacy/data-protection assessment: Yes by default unless excluded
- Need binary reverse engineering or only package/static inspection
- Required framework or internal-policy additions
- Required derivatives: PowerPoint, Excel risk register, diagrams, Markdown, SBOM inventory, concise report
- Required template, branding, classification, approvers, and output location

## Safe defaults

- Use the latest stable version when no version is supplied, state the retrieval date, and preserve the package hash.
- Assess both IDEs only when requested or when the listing claims support for both.
- Assume no authorization for execution, installation, authentication, production access, or submission of sensitive information.
- Mark unanswered material fields as assumptions or limitations.
