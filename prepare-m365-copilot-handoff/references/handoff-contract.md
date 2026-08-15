# Handoff contract

## Contract files

- `schemas/job.schema.json`: trusted build request, create-only operation and logical destination.
- `schemas/word-content.schema.json`: semantic Word sections and blocks with explicit `en-GB`.
- `schemas/source-register.schema.json`: traceable, classified source metadata without credentials.
- `schemas/template-profile.schema.json`: bounded registry and template integrity contract.
- `schemas/handoff-manifest.schema.json`: immutable package manifest and complete non-manifest file inventory.
- `schemas/processing-receipt.schema.json`: reserved Phase 2 receipt input; this release does not verify returned Office output.

All schemas use JSON Schema Draft 2020-12 and fail closed on unknown trusted fields. The runtime rejects floating-point values so its canonical JSON is an RFC 8785-compatible integer/string subset.

## Physical package

```text
m365h-<20-hex>/
├── handoff-manifest.json
├── HANDOFF.md
├── payloads/<artifact-id>.word.json
├── previews/<artifact-id>.md
└── evidence/
    ├── source-register.json
    ├── validation-report.json
    └── validation-report.txt
```

The manifest inventories every other file. Content files participate in identity; deterministic human/evidence projections are inventoried but excluded to avoid digest cycles and are regenerated during validation.

## Identity algorithm

1. Normalise strings to UTF-8, Unicode NFC and LF.
2. Reject floats and unsupported JSON values.
3. Sort inventory paths by Unicode code point.
4. Canonicalise schema version, producer, environment, classification, locale, summary, destination, trusted instructions, artifact records and identity-bearing file entries.
5. Calculate SHA-256 over those canonical bytes.
6. Set `content_digest` to `sha256:<hex>` and `package_id` to `m365h-` plus the first 20 hex characters.

`created_at`, local paths, filesystem timestamps and generated report bytes do not affect identity. `created_at` is supplied by the job so identical job bytes also produce byte-identical packages.

## Phase 1 limits

- Word only; one to eight artifacts.
- `create` only; no update, replacement or version mutation.
- JSON and generated Markdown only; no assets, archives or source binaries.
- `internal` classification only.
- 64 files, 10 MiB per file and 50 MiB total by the bundled registry policy.
- SharePoint/OneDrive destinations are logical labels only; no upload occurs.
