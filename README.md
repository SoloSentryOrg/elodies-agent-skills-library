# Elodie's Agent Skills Library

A collection of reusable Agent Skills maintained by SoloSentry for public review and reuse.

## Skills

| Skill | Purpose |
|---|---|
| [`ms-ai-ide-extension-security-assessment`](ms-ai-ide-extension-security-assessment/) | Produces repeatable, evidence-led security assessments for AI-related Visual Studio and VS Code extensions, MCP integrations, and installed Agent Skills. |
| [`prepare-m365-copilot-handoff`](prepare-m365-copilot-handoff/) | Builds and validates immutable Word handoff packages for manual Microsoft 365 Copilot processing. |

## Repository model

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

For changes to the portable assessment skill, use the approved Python 3.12
environment and finish all previous test processes before refreshing its
manifest. Run these steps sequentially after the source edits:

```bash
python3 -B ms-ai-ide-extension-security-assessment/scripts/validate_skill_package.py --write-manifest --expected-version 1.4.7
python3 -B ms-ai-ide-extension-security-assessment/scripts/validate_skill_package.py --expected-version 1.4.7
python3 -B -m unittest discover -s ms-ai-ide-extension-security-assessment/scripts -p 'test_*.py'
python3 -B ms-ai-ide-extension-security-assessment/scripts/validate_skill_package.py --expected-version 1.4.7
```

On Windows, use `python` in place of `python3`. The final validation must pass
without rewriting the manifest. Do not refresh while tests hold temporary
package fixtures, or regenerate a manifest to hide unexpected post-test
changes. Preserve a failed run, investigate the cause, and repeat the sequence
only after a reviewed correction. These checks establish package integrity;
native runtime and human acceptance remain separate gates.

The candidate native PDF measurement worker currently requires Linux address-space
limits or a verified Windows Job Object. It rejects other hosts before launching
or reading a request. The macOS measurement path still needs an approved runner
with enforced memory containment; existing macOS Word/PowerPoint rendering and
the production v4 layout gate remain separate. Direct extractor tests use small,
known fixtures and do not establish containment or acceptance for untrusted PDFs.
Native text metrics alone do not establish visible rendering or human inspection.

## Security

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md). Do not open a public issue containing exploit details, credentials, sensitive prompts, or private repository content.

## Licence

This repository is licensed under the [MIT License](LICENSE).
