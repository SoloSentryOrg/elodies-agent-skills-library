# Evidence and research method

## Source priority

1. Package/VSIX and directly observed host evidence
2. Official marketplace listing and signed publisher identity
3. Official source repository, documentation, privacy terms, licence, SBOM, release notes, and advisories
4. Standards bodies, regulators, NVD/CVE records, GitHub advisories, and vendor security advisories
5. Reputable independent analysis

Record source title, publisher, URL, publication/update date, access date, version applicability, evidence type, hash where relevant, and limitations. Archive or quote only within copyright and policy limits.

## Minimum research set

- identity, publisher verification, extension ID, version, dates, installs/ratings only if decision-relevant;
- supported IDEs/OSs, licence, privacy policy, support and security-reporting route;
- official docs, source, build/release provenance, changelog/release history;
- package/VSIX, signature, checksums, SBOM, dependencies, bundled binaries/scripts;
- CVEs, CWE patterns, vendor and ecosystem advisories, malicious-package reports;
- permissions/capabilities, activation events, commands, settings, authentication, secrets, telemetry;
- MCP registrations, transports, tools/resources/prompts, dynamic discovery, endpoint changes;
- installed Agent Skills and all transitive files/references/scripts;
- update mechanism, supply-chain controls, deprecation/support status.

## Evidence states

- **Verified:** directly supported by cited primary evidence or observation.
- **Inferred:** reasoned from verified facts; label the inference and rationale.
- **Not observed:** searched within stated scope but not found; list search method.
- **Not applicable:** explain why.
- **Unknown:** evidence unavailable or analysis not authorized.

## Installation manifest fields

For each item capture: IDE, version, path/registry key/name, artefact type, size, hash/signature, source, purpose, privilege, persistence, update/uninstall behavior, observed/expected state, confidence, and evidence ID.

Cover: VSIX/package files; directories; manifests; JavaScript/TypeScript bundles; DLL/native executables; runtimes; dependencies; scripts; services; drivers; scheduled tasks; registry; user/workspace/machine configs; caches/logs/databases; Agent Skills; MCP definitions; endpoints; certificates; tokens/secrets; permissions; environment variables; PATH changes; processes; child processes; IPC; telemetry; browser/webviews; containers; and uninstall residue.

## Static package safety

- Download without installing; preserve original bytes and compute a cryptographic hash.
- Inspect archives in a disposable directory. Prevent archive traversal and symlink escape.
- Do not execute post-install hooks, scripts, binaries, macros, or extension activation.
- Scan package contents where tools are available, but do not treat a clean scan as proof of safety.
- Record minified/obfuscated code, native components, remote code loading, unsigned artefacts, and source/package mismatches.
