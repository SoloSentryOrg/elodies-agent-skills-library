# VS Code and Visual Studio MCP Security Assessments

Evidence-led security assessments of MCP extensions and integrations for
Microsoft Visual Studio Code and Visual Studio, maintained by SoloSentry.

The assessed installation is the unit of review. That includes the extension or
MCP server, its dependencies, configuration, tools, prompts, resources,
permissions, data flows, update and removal behavior, and any Agent Skills
packaged or installed with it.

## Assessments

Authoritative reports and retained, non-sensitive evidence are published under
[`reports/`](reports/). Each assessment distinguishes VS Code and Visual Studio
support and evidence, records static, malware and authorized runtime-analysis
coverage, and gives an explicit approval recommendation.

The repository is the central assessment library. Every assessment is stored in
its own directory with the authoritative DOCX report and any available retained
evidence, stage outputs and reproducible build material.

Agent Skills are reviewed when they are bundled with, installed by, or required
for the assessed extension or MCP integration. They are treated as
security-sensitive behavioral code and assessed alongside the rest of the
installation rather than as the repository's primary product.

## Assessment methodology

| Resource | Purpose |
|---|---|
| [`ms-ai-ide-extension-security-assessment`](ms-ai-ide-extension-security-assessment/) | Reusable methodology for assessing AI-related Visual Studio and VS Code extensions, MCP integrations, and any installed Agent Skills. |

## Repository model

- All substantive changes use a branch and pull request.
- `main` is protected by repository rules and required validation.
- Assessment reports must pass fail-closed document, evidence, privacy, and
  secure-review gates before publication.
- Skill instructions and supporting files are treated as security-sensitive behavioral code.
- Third-party packages, scripts, links, and instructions are untrusted until reviewed.

## Using the assessment skill

The reusable assessment skill is stored directly under the repository root.
Copy it into an approved Agent Skills location without modifying its internal
structure. Review the skill, its references, scripts, assets, provenance, and
requested tool access before use.

## Adding assessments or changing the methodology

Follow [CONTRIBUTING.md](CONTRIBUTING.md), the root [AGENTS.md](AGENTS.md), and the pull-request template. Run:

```bash
ruby scripts/validate_repository.rb
python3 scripts/check-lessons-evidence.py --changed-file example-skill/SKILL.md --body-file /path/to/pr-body.md
```

## Security

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md). Do not open a public issue containing exploit details, credentials, sensitive prompts, or private repository content.

## Licence

This repository is licensed under the [MIT License](LICENSE).
