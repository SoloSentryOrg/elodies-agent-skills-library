# Template profiles

## Selection rules

1. Read `registry/template-profiles.json`.
2. Match the artifact kind, environment, profile ID, semantic version and SHA-256 exactly.
3. Require lifecycle state `approved` and locale `en-GB`.
4. Supply every required semantic slot exactly once. Use only declared optional slots.
5. Reject profile drift; do not update a job to match an unexplained registry change.

## Bundled synthetic pilot

`solosentry-word-handoff-pilot` is approved only for `synthetic-test`. Its digest is an explicit contract fixture, not evidence that a tenant template exists. It supports package/test verification with synthetic content and cannot satisfy a `production` job.

Before adding a production profile, record and review:

- template owner and immutable Microsoft 365 logical location;
- `.dotx` or `.docx` filename and independently calculated SHA-256;
- required and optional semantic slots plus downstream content-control bindings;
- `en-GB` defaults, styles and runs;
- accessibility expectations and desktop Word inspection evidence;
- replacement, retirement and rollback owner.

Do not change the synthetic profile to `production` or replace its fixture digest with a guessed value.
