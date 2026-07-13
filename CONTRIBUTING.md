# Contributing

## Change process

1. Create a branch from current `origin/main`.
2. Add or update one bounded skill or governance change.
3. Review all instructions, references, scripts, assets, external URLs, and dependencies as untrusted code.
4. Run the local repository validation and any skill-specific tests.
5. Perform and document a secure review. Resolve findings before push.
6. Commit with a clear message, signature, and DCO sign-off where available.
7. Open a pull request using the repository template and wait for required checks.
8. Merge only when checks are green, conversations are resolved, and residual risk is acceptable.

## Skill requirements

- Use a lowercase hyphenated directory directly under the repository root.
- Include a valid `SKILL.md` with only `name` and `description` in YAML frontmatter.
- Make the frontmatter name match the directory name.
- Keep the entry point concise and use one-level references for detailed guidance.
- Include `agents/openai.yaml` when UI metadata improves discoverability.
- Do not add opaque binaries, credentials, local state, or unreviewed generated output.
- Pin mutable external dependencies or document why pinning is impossible and how integrity is verified.

## Pull-request evidence

Document changed files, validation commands/results, secure-review findings and fixes, residual risk, source/provenance, and applicable central lessons. A clean automated check does not replace review.
