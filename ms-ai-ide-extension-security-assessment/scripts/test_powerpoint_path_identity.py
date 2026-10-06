#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the Mac adapter's filesystem-only identity handler, without Office."""

import pathlib
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == "darwin", "Mac AppleScript path semantics")
class PowerPointPathIdentityTests(unittest.TestCase):
    def test_full_path_identity_and_fail_closed_lookup(self):
        source = (pathlib.Path(__file__).parent / "render_presentations_with_powerpoint.applescript").read_text()
        start = source.index("on canonicalOfficePath(")
        end = source.index("end canonicalOfficePath", start) + len("end canonicalOfficePath")
        with tempfile.TemporaryDirectory(prefix="office-identity-") as directory:
            root = pathlib.Path(directory).resolve()
            script = root / "identity.applescript"
            script.write_text(source[start:end] + "\non run argv\n"
                              "set suppliedPath to item 1 of argv\n"
                              "if item 2 of argv is \"hfs\" then set suppliedPath to (POSIX file suppliedPath) as text\n"
                              "return canonicalOfficePath(suppliedPath)\nend run\n")
            original = root / "input.pptx"
            original.write_bytes(b"synthetic identity fixture")
            other = root / "other" / "input.pptx"
            other.parent.mkdir()
            other.write_bytes(b"different file with the same basename")
            suspicious = root / "quote' $(touch UNEXPECTED) `touch UNEXPECTED` .pptx"
            suspicious.write_bytes(b"literal filename")
            cases = [(str(original), "posix", str(original)),
                     (str(original).replace("/private/tmp/", "/tmp/"), "posix", str(original)),
                     (str(original), "hfs", str(original)),
                     (str(other), "posix", str(other)),
                     (str(root / "absent.pptx"), "posix", ""),
                     (str(suspicious), "posix", str(suspicious))]
            for value, mode, expected in cases:
                with self.subTest(path=value, mode=mode):
                    result = subprocess.run(["osascript", str(script), value, mode],
                                            cwd=root, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.rstrip("\n"), expected)
            self.assertNotEqual(str(other), str(original))
            self.assertFalse((root / "UNEXPECTED").exists())


if __name__ == "__main__":
    unittest.main()
