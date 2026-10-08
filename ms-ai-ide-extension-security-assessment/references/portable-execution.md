# Portable execution and installation

Use the bundled scripts when the host document or presentation skill does not
provide a required deterministic surface. Host authoring skills remain the
preferred route; portable helpers do not waive native Microsoft Office QA.

## Capability order

1. Resolve host document, presentation, and workspace dependency capabilities.
2. Use the host artifact skill for authoring and editing when available.
3. Use the bundled schema-driven helpers for deterministic staging, compilation,
   validation, VSIX inspection, or derivative generation.
4. If a required host capability is unavailable, record `Blocked` or `Defer
   pending evidence`; do not silently relabel a candidate as authoritative.

## Portable core

- `scripts/safe_stage_inputs.py` validates complete hash-bound stage inputs.
- `scripts/initialize_stage_bundle.py` creates a non-authoritative, incomplete
  fifteen-stage skeleton governed by the JSON Schemas in `schemas/`.
- `scripts/build_assessment_docx.py` compiles a schema-driven report beneath an
  explicit `--workspace-root`.
- `scripts/validate_assessment_layout.py --root <workspace>` validates the
  assessment workspace contract.
- `scripts/validate_assessment_report.py <report.docx>` validates authoritative
  report structure and publication safety.
- `scripts/validate_skill_package.py` validates the distributed skill tree and
  its package manifest.

Install the pinned Python dependencies from `scripts/requirements.lock` in an
isolated environment. Do not use unpinned global packages.

For a new installation, create a dedicated virtual environment outside the
skill package and install the locked wheels explicitly:

```sh
python3 -m venv /trusted/path/ms-ai-assessment-runtime
/trusted/path/ms-ai-assessment-runtime/bin/python -m pip install \
  --disable-pip-version-check --no-input --only-binary=:all: --require-hashes \
  -r scripts/requirements.lock
/trusted/path/ms-ai-assessment-runtime/bin/python scripts/validate_skill_package.py
```

On Windows PowerShell, use the equivalent isolated installation:

```powershell
py -3.11 -m venv C:\TrustedTools\ms-ai-assessment-runtime
C:\TrustedTools\ms-ai-assessment-runtime\Scripts\python.exe -m pip install `
  --disable-pip-version-check --no-input --only-binary=:all: --require-hashes `
  -r scripts\requirements.lock
C:\TrustedTools\ms-ai-assessment-runtime\Scripts\python.exe scripts\validate_skill_package.py
```

Record the Python and installed-package versions as assessment tool evidence.
If a compatible wheel is unavailable for the host platform, stop and record the
helper as `Blocked`; do not remove hash checking or build an unreviewed source
distribution to force installation.

## Optional helpers

- `scripts/inspect_vsix.py` performs bounded, non-executing VSIX inspection.
- `scripts/create_word_qa_contact_sheets.py` creates Word-render QA sheets.
- `scripts/create_pptx_montage.py` creates the retained slide montage using the
  pinned Pillow dependency; bind it into the artifact runtime receipt and pass
  its absolute path with `--montage-helper` plus the isolated Python executable
  with `--python` to both receipt creation and deck generation. A normal POSIX
  virtual-environment `bin/python` symlink is supported only when the receipt
  binds the launcher, resolved executable, and `pyvenv.cfg`; Windows virtual
  environments bind the corresponding `Scripts\\python.exe` and configuration.
- `scripts/secure_pptx_stage_bundle.py` stages bounded report data for slides.
- `scripts/build_assessment_pptx.mjs` uses the host-provided
  `@oai/artifact-tool` runtime only after
  `scripts/create_artifact_runtime_receipt.mjs` binds its package identity,
  version, entrypoint, and digests. Keep the prepared runtime workspace and its
  receipt outside the untrusted assessment workspace.
The JavaScript receipt and builder share `scripts/stable_regular_file.mjs`.
The receipt retains its 64 MiB per-file and 512 MiB total package bounds;
the builder caps each file read at 512 MiB. Reads use a verified regular-file
descriptor, reject growth or identity/metadata changes, and close the handle on
failure. POSIX hosts require no-follow and nonblocking open flags so a replaced
FIFO cannot wait for a writer. Windows checks the opened handle and leaf identity
before reading; it does not claim POSIX no-follow flags or descriptor-relative
ancestor protection. Keep runtime and output directories trusted on every host.

The presentation builder binds every authored text box, including footers, to
its exact name and text before asking the renderer for layout evidence. The
layout gate rejects missing, renamed, altered, duplicate or additional text,
requires positive text bounds and line counts, and applies the 16-point minimum
to all authored text. Single-line title requirements come from the authoring
path. The retained v4-only gate remains fail-closed; the current v5 renderer
lacks the former resolved font and line-count evidence. These source checks do
not establish native rendering acceptance or update historical acceptance.

- `scripts/validate_assessment_pptx.py` rejects macros, ActiveX, embedded
  objects, review content, unsafe external relationships, and non-neutral
  author metadata before a generated deck is published.
- `scripts/stage_office_artifact.py` digest-binds passive DOCX/PPTX inputs
  before native Office rendering; pass each expected digest to the AppleScript
  renderer.
- `scripts/finalize_office_qa.py` creates an immutable QA record and a new
  closeout manifest after every-page or every-slide visual inspection,
  accessibility checks, privacy checks, and the Word contents-page rule pass.
- `scripts/render_reports_with_word.applescript` and
  `scripts/render_presentations_with_powerpoint.applescript` automate native
  Office rendering on an authorized macOS host. The PowerPoint adapter resolves
  the complete Office-reported path before matching its unique staged input;
  basename matching is never sufficient. Its error handler closes only an
  identified presentation. If Office has not exposed that identity (for example,
  while awaiting file-access approval), the private stage is retained for
  explicit operator cleanup. Per-event automation timeouts remain distinct from
  the caller's overall process deadline and from native rendering acceptance.
- `scripts/render_reports_with_word.ps1` and
  `scripts/render_presentations_with_powerpoint.ps1` provide the equivalent
  macro-disabled, read-only native Office QA adapters on an authorized Windows
  host. They require the digest-bound Python stager and never activate the
  assessed extension.

Optional helpers must fail clearly when their host prerequisite is absent. Never
install or activate an assessed extension merely to satisfy an artifact helper.
For retained PPTX QA, create a new empty `--qa-dir` beneath the assessment
workspace before each attempt. A failed attempt deliberately leaves partial QA
evidence for diagnosis; do not reuse that directory. Quarantine or remove it
only after verifying it is task-owned, then use a fresh directory.

## Personal installation

Use `scripts/sync_skill_installations.py` with the verified released skill as
`--source` and repeat `--destination` for each supported client. The helper
validates and stages the whole package, retains recoverable backups, and replaces
destinations atomically. Create and verify destination parent directories before
running it; do not pass a symlinked destination or parent.

Create release inputs with `scripts/build_release_archive.py` followed by
`scripts/build_release_manifest.py`. The synchronizer independently verifies
that the ZIP contains exactly the package-manifest tree and that the release
manifest binds the expected tag and full source commit.

After synchronization, validate the complete tree and invoke the skill from a
fresh client session. GitHub Copilot does not discover a Codex-only installation;
install the whole package in a Copilot-supported skill directory.

The default personal destinations are:

- Codex: `~/.codex/skills/ms-ai-ide-extension-security-assessment`
- Claude Code: `~/.claude/skills/ms-ai-ide-extension-security-assessment`
- GitHub Copilot: `~/.copilot/skills/ms-ai-ide-extension-security-assessment`

On Windows these resolve beneath `%USERPROFILE%` (for example,
`%USERPROFILE%\.codex\skills\ms-ai-ide-extension-security-assessment`). The
same complete package is installed for each client; do not copy only
`SKILL.md` or omit the `scripts`, `schemas`, and `references` trees.

The core helpers support Windows, macOS, and Linux. POSIX hosts use
descriptor-relative no-follow operations. Windows hosts reject symlinks,
junctions, and reparse-point ancestors, bind reads to the opened file identity,
and use exclusive creation in trusted NTFS workspaces. A filesystem that cannot
provide these semantics is unsupported and must be recorded as `Blocked` rather
than silently weakened.

## Native parser test evidence

The hosted Linux and Windows regression jobs install the separate hash-locked
`scripts/native-pdfium-tests.lock` with binary-only/no-dependency installation.
This selects supported pypdfium2 5.14.0 wheels for those runners and macOS ARM64
acceptance testing; it does not add a production parser dependency or establish
production acceptance. Verbose tests distinguish actual parser executions from
platform/prerequisite skips. The form-interface probe checks genuine ordinary
and form-bearing PDFs and rejects unexpected form initialization/actions.

CVE-2026-95338 maps through Chromium issue 556535630 to PDFium fix
`4a36628222bb647c23b4ef3b8f3fc64e93e1dd3b` (8 September 2026), with stable
backport `2358b16c1947eff67f0732754af6b3c4e1715ff9`. Fixed Chrome
154.0.8037.57 pins that backport. Public PDFium chromium/8076 history includes
the original fix; upstream 28 September builds and signed 29 September archives
match all three selected wheel native binaries. The upstream attestation binds
the binary-builder source, not an immutable resolved PDFium checkout SHA; keep
that qualification. Source and runtime form-interface evidence concern this
extractor's usage, not absence of all PDFium vulnerabilities. Production pipeline,
source-bound runtime acceptance and licensed native Windows Office remain gates.

Primary sources: [PDFium fix](https://pdfium.googlesource.com/pdfium/+/4a36628222bb647c23b4ef3b8f3fc64e93e1dd3b),
[fixed Chrome dependency pin](https://chromium.googlesource.com/chromium/src/+/refs/tags/154.0.8037.57/DEPS),
[upstream native build](https://github.com/bblanchon/pdfium-binaries/actions/runs/36410865276/attempts/2),
[pypdfium2 release](https://github.com/pypdfium2-team/pypdfium2/releases/tag/5.14.0).
