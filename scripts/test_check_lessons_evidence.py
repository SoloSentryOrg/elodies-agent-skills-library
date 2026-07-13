#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

"""Regression tests for the central lessons evidence guard."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("check-lessons-evidence.py")
SPEC = importlib.util.spec_from_file_location("check_lessons_evidence", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT_PATH}")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class ValidateBodyTests(unittest.TestCase):
    def test_rejects_empty_rationale(self) -> None:
        body = """## Lessons Learned

No applicable central lessons.
Rationale:
"""

        with self.assertRaises(guard.LessonsEvidenceError):
            guard.validate_body(body)

    def test_accepts_non_empty_rationale(self) -> None:
        body = """## Lessons Learned

No applicable central lessons.
Rationale: This first-time public-release change has no matching active lesson.
"""

        guard.validate_body(body)

    def test_accepts_pull_request_template_rationale(self) -> None:
        body = """## Lessons Learned

- Central register reviewed: yes
- No applicable central lesson. Rationale: Existing lessons target other repositories.
"""

        guard.validate_body(body)


if __name__ == "__main__":
    unittest.main()
