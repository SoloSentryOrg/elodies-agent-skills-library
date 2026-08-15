#!/usr/bin/env python3
"""Validate a built or received handoff package and write explicit reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from handoff_core.package import validate_package


def _write_new(path: Path, data: bytes) -> None:
    if not path.parent.exists() or not path.parent.is_dir():
        raise ValueError(f"report parent must already exist: {path.parent}")
    with path.open("xb") as stream:
        stream.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--mode", choices=("build", "received"), required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--expected-digest")
    parser.add_argument("--json-report", type=Path, required=True)
    parser.add_argument("--text-report", type=Path, required=True)
    args = parser.parse_args()
    result = validate_package(args.package, args.registry, mode=args.mode, expected_digest=args.expected_digest)
    text_lines = [
        "Microsoft 365 Copilot handoff independent validation",
        f"Status: {result['status'].upper()}",
        f"Mode: {result['mode']}",
        f"Package ID: {result.get('package_id') or 'unavailable'}",
        f"Content digest: {result.get('content_digest') or 'unavailable'}",
        f"Errors: {len(result['errors'])}",
        f"Warnings: {len(result['warnings'])}",
    ]
    for item in [*result["errors"], *result["warnings"]]:
        suffix = f" [{item['context']}]" if item.get("context") else ""
        text_lines.append(f"- {item['severity'].upper()} {item['code']}: {item['message']}{suffix}")
    try:
        _write_new(args.json_report, json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        _write_new(args.text_report, ("\n".join(text_lines) + "\n").encode("utf-8"))
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": result["status"], "package_id": result.get("package_id"), "content_digest": result.get("content_digest")}, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
