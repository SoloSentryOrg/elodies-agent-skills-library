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
python3 -B ms-ai-ide-extension-security-assessment/scripts/validate_skill_package.py --write-manifest --expected-version 1.4.8
python3 -B ms-ai-ide-extension-security-assessment/scripts/validate_skill_package.py --expected-version 1.4.8
python3 -B -m unittest discover -s ms-ai-ide-extension-security-assessment/scripts -p 'test_*.py'
python3 -B ms-ai-ide-extension-security-assessment/scripts/validate_skill_package.py --expected-version 1.4.8
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

### Python dependency evidence

The existing Repository Security workflow scans all three complete Python hash locks (portable assessment, M365 handoff
and native PDF parser) before installation using the official OSV API. It runs on pull requests,
protected-main pushes, manual dispatch and Mondays at 05:31 UTC. Findings block;
network failures, incomplete/paginated or malformed responses, unsupported lock
records and missing evidence fail closed. No dependency exception or ignored
advisory is configured. Query, raw response, lock hashes and result are retained
for fourteen days. Advisory records can include aliases and are not a distinct
CVE count. No public report or package is published.

Run locally from a clean tracked-source checkout with a new evidence directory:

```sh
python3 scripts/check-python-dependencies.py --output /absolute/new/evidence-dir
```

Exit 0 establishes a complete empty OSV result for those exact versions at scan
time; exit 1 reports findings, and exit 2 means complete clean evidence was not
established. This gate complements install, source, descriptor, native Office,
resource-limit and runtime-acceptance checks. The first real scheduled observation
after deployment remains separate from manual/PR validation in security issue
[#34](https://github.com/SoloSentryOrg/elodies-agent-skills-library/issues/34).
