#!/usr/bin/env python3
"""Build one immutable Word handoff package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from handoff_core import build_package
from handoff_core.policy import HandoffError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_package(args.job, args.workspace, args.registry, args.output)
    except HandoffError as exc:
        print(json.dumps({"status": "fail", "errors": [item.to_dict() for item in exc.diagnostics]}, sort_keys=True))
        return 1
    except (OSError, KeyError, TypeError, ValueError):
        print(json.dumps({"status": "fail", "errors": [{"code": "HND013", "severity": "error", "message": "build could not complete safely"}]}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
