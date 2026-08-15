# Troubleshooting

- `HND001`: validate the complete JSON object against the named schema; remove unknown trusted fields rather than weakening `additionalProperties`.
- `HND002`: copy inputs into one isolated workspace, use relative POSIX paths and remove links/junctions from the task-owned input tree.
- `HND003`: stop processing, compare the original out-of-band digest and rebuild from trusted source inputs. Do not edit a package in place.
- `HND005`: remove the prohibited material from a new source workspace. Do not print or preserve a suspected credential in diagnostics.
- `HND006`/`HND007`: add missing source/slot bindings and replace placeholders; do not silently drop content.
- `HND008`: use explicit `en-GB` throughout. For a real Word package, run the approved `docx_language.py enforce` and `check` gates before validation.
- `HND009`: re-read the registry and verify the template owner/version/digest. Never auto-approve a draft or retired profile.
- `HND011`: preserve both conflicting packages, compare complete inventories and investigate the first divergent canonical input.
- `HND013`: treat the Office package as untrusted and malformed; do not attempt native Office execution to diagnose it.

Resolve the trusted installed skill root from `SKILL.md` and use absolute paths under it for every script, dependency lock and registry. Never select those control files from the current task workspace. Report files must be new files whose parent directories already exist.
