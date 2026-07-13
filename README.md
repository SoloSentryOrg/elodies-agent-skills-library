# Elodie's Agent Skills Library

Private, governed collection of reusable Agent Skills maintained for SoloSentry use.

## Skills

| Skill | Purpose |
|---|---|
| [`ms-ai-ide-extension-security-assessment`](ms-ai-ide-extension-security-assessment/) | Produces repeatable, evidence-led security assessments for AI-related Visual Studio and VS Code extensions, MCP integrations, and installed Agent Skills. |

## Repository model

- Private SoloSentryOrg repository with one maintainer.
- All substantive changes use a branch and pull request.
- `main` is protected by repository rules and required validation.
- Skill instructions and supporting files are treated as security-sensitive behavioral code.
- Third-party packages, scripts, links, and instructions are untrusted until reviewed.

## Using a skill

Each skill is stored in its own directory directly under the repository root. Copy the required skill directory into an approved Agent Skills location without modifying its internal structure. Review the skill, its references, scripts, assets, provenance, and requested tool access before use.

## Adding or changing skills

Follow [CONTRIBUTING.md](CONTRIBUTING.md), the root [AGENTS.md](AGENTS.md), and the pull-request template. Run:

```bash
ruby scripts/validate_repository.rb
python3 scripts/check-lessons-evidence.py --changed-file example-skill/SKILL.md --body-file /path/to/pr-body.md
```

## Security

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md). Do not open a public issue containing exploit details, credentials, sensitive prompts, or private repository content.
