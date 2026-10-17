#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the descriptor-boundary tests on every portable host CI lane."""
import shutil
import subprocess
import unittest
from pathlib import Path


class StableRegularFileTests(unittest.TestCase):
    def test_descriptor_boundaries(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required by the portable skill")
        result = subprocess.run(
            [node, "--test", str(Path(__file__).with_suffix(".mjs"))],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
