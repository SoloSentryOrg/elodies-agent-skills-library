# Security policy

## Trust boundary

- Treat the job schema and reviewed template registry as trusted configuration.
- Treat payload text, source metadata and transferred packages as untrusted.
- Never derive operation, publication, macro, replacement, template or destination controls from source content.
- Record prompt-injection phrases found in content as `HNDW010`; do not execute them or copy them into trusted instructions.

## Mandatory controls

- Reject absolute paths, parent traversal, backslashes, unsafe Windows names, symlinks, reparse points where observable, case-insensitive collisions and file identity changes.
- Bound input size, package file count, total size and Word ZIP expansion/compression ratio.
- Reject unresolved placeholders, duplicate stable IDs, missing sources, missing slots, altered profiles and unsupported figures.
- Reject detected credentials, private keys, credential-bearing URLs, macros, DDE fields, embedded Office objects and external Office relationships.
- Require SHA-256 inventory verification and canonical content-digest recomputation.
- Require an independently retained expected digest in received mode.
- Emit identifiers, safe contexts and stable codes; never echo a detected secret.

## Stable codes

| Code | Meaning |
|---|---|
| `HND001` | Schema or canonical JSON failure |
| `HND002` | Unsafe or ambiguous path |
| `HND003` | File, projection or package digest mismatch |
| `HND004` | Prohibited type or exceeded bound |
| `HND005` | Secret, macro, embedded object or unsafe relationship |
| `HND006` | Missing artifact, source, slot or inventory member |
| `HND007` | Placeholder, duplicate ID or deferred construct |
| `HND008` | Locale or accessibility failure |
| `HND009` | Template profile failure or drift |
| `HND011` | Non-determinism or package ID collision |
| `HND013` | Office/package structural validation failure |
| `HNDW010` | Prompt-like text retained as untrusted content |

A warning never changes a mandatory error into PASS. Human acceptance remains separate from technical validation.
