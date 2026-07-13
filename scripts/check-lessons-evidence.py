#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

"""Reference CI guard for central lessons-learned evidence in pull request bodies."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path.cwd()
LESSON_ALLOWLIST_PATH = ROOT / "scripts" / "central-lessons-allowlist.json"
LESSON_ID_RE = re.compile(r"\bLL-[0-9]{4}\b")
LESSONS_HEADING_RE = re.compile(r"(?im)^##+\s+(central\s+)?lessons?(\s+learned)?\b.*$")
NOT_APPLICABLE_RE = re.compile(
    r"\b(no|none)\s+applicable\s+(central\s+)?lessons?\b|\bcentral\s+lessons?\s*:\s*(n/a|not applicable|none)\b",
    re.IGNORECASE,
)
RATIONALE_RE = re.compile(r"\b(rationale|reason|why)\s*:", re.IGNORECASE)
DEFAULT_SCOPED_PATTERNS = (
    r"^AGENTS[.]md$",
    r"^[.]github/(workflows|ISSUE_TEMPLATE)/",
    r"^[.]github/pull_request_template[.]md$",
    r"^catalog/",
    r"^factory-contracts/",
    r"^factory-lifecycle-actions/",
    r"^factory-requests/",
    r"^images/",
    r"^packages/",
    r"^policies/",
    r"^schemas/",
    r"^scripts/",
    r"^security/",
    r"^docs/",
    r"^[a-z0-9][a-z0-9-]*/",
    r"^(README|SECURITY|CONTRIBUTING)[.]md$",
)


class LessonsEvidenceError(Exception):
    """Raised when lessons evidence is missing or malformed."""


def fail(message: str) -> None:
    print(f"lessons evidence validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LessonsEvidenceError(f"{path}: JSON parse failed: {exc}") from exc
    if not isinstance(data, dict):
        raise LessonsEvidenceError(f"{path}: top-level JSON value must be an object")
    return data


def run_git_diff(base_sha: str, head_sha: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}...{head_sha}"],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise LessonsEvidenceError(result.stderr.strip() or "git diff failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def event_context(event_path: Path | None) -> tuple[str, list[str], bool]:
    if event_path is None:
        return "", [], False
    event = load_json(event_path)
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        return "", [], False
    body = pull_request.get("body") or ""
    if not isinstance(body, str):
        raise LessonsEvidenceError("pull_request.body must be a string when present")
    base = pull_request.get("base")
    head = pull_request.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        raise LessonsEvidenceError("pull_request.base and pull_request.head are required")
    base_sha = base.get("sha")
    head_sha = head.get("sha")
    if not isinstance(base_sha, str) or not isinstance(head_sha, str):
        raise LessonsEvidenceError("pull_request base/head sha values are required")
    return body, run_git_diff(base_sha, head_sha), True


def read_changed_files(args: argparse.Namespace) -> list[str]:
    changed: list[str] = []
    changed.extend(args.changed_file or [])
    if args.changed_files_file:
        changed.extend(
            line.strip()
            for line in args.changed_files_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return sorted({path for path in changed if path})


def scoped_files(changed_files: list[str], patterns: list[re.Pattern[str]]) -> list[str]:
    return sorted(
        path
        for path in changed_files
        if any(pattern.search(path) for pattern in patterns)
    )


def lessons_section(body: str) -> str | None:
    match = LESSONS_HEADING_RE.search(body)
    if not match:
        return None
    next_heading = re.search(r"(?m)^##+\s+", body[match.end() :])
    if next_heading:
        return body[match.start() : match.end() + next_heading.start()]
    return body[match.start() :]


def allowed_lesson_ids() -> set[str]:
    data = load_json(LESSON_ALLOWLIST_PATH)
    raw_ids = data.get("allowed_lesson_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise LessonsEvidenceError(
            f"{LESSON_ALLOWLIST_PATH}: allowed_lesson_ids must be a non-empty list"
        )
    ids = set(raw_ids)
    if any(not isinstance(item, str) or not LESSON_ID_RE.fullmatch(item) for item in ids):
        raise LessonsEvidenceError(
            f"{LESSON_ALLOWLIST_PATH}: allowed_lesson_ids contains an invalid ID"
        )
    return ids


def validate_body(body: str) -> None:
    section = lessons_section(body)
    if section is None:
        raise LessonsEvidenceError(
            "scoped changes require a 'Lessons Learned' PR section citing lesson IDs or a not-applicable rationale"
        )
    ids = sorted(set(LESSON_ID_RE.findall(section)))
    if ids:
        unknown = sorted(set(ids) - allowed_lesson_ids())
        if unknown:
            raise LessonsEvidenceError(
                f"unknown central lesson ID(s): {', '.join(unknown)}; refresh the pinned allowlist from the central register"
            )
        print(f"lessons evidence: cited {', '.join(ids)}")
        return
    if NOT_APPLICABLE_RE.search(section) and RATIONALE_RE.search(section):
        print("lessons evidence: no applicable central lesson recorded with rationale")
        return
    raise LessonsEvidenceError(
        "Lessons Learned section must cite at least one LL-000x ID or state no applicable central lesson with a rationale"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-path", type=Path, default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--body-file", type=Path)
    parser.add_argument("--changed-file", action="append")
    parser.add_argument("--changed-files-file", type=Path)
    parser.add_argument("--scoped-pattern", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        body = args.body_file.read_text(encoding="utf-8") if args.body_file else ""
        changed = read_changed_files(args)
        is_pr_event = False
        if args.event_path and not body and not changed:
            body, changed, is_pr_event = event_context(args.event_path)
        if args.event_path and not is_pr_event and not body and not changed:
            print("lessons evidence check skipped: event is not a pull_request")
            return 0
        raw_patterns = args.scoped_pattern or list(DEFAULT_SCOPED_PATTERNS)
        patterns = [re.compile(pattern) for pattern in raw_patterns]
        scoped = scoped_files(changed, patterns)
        if not scoped:
            print("lessons evidence check passed: no scoped files changed")
            return 0
        validate_body(body)
    except LessonsEvidenceError as exc:
        fail(str(exc))
    print(f"lessons evidence check passed for {len(scoped)} scoped file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
