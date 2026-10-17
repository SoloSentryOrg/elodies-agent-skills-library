# SPDX-License-Identifier: MIT
"""Fail-closed transport tests for private, pending v5 candidates."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from validate_pptx_runtime_acceptance import BOUND_FILES
from verify_v5_candidate import _json, main, prepare


def encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"),
                     "private v5 candidate staging requires POSIX no-follow support")
class CandidateTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.candidate = self.root / "candidate"
        self.candidate.mkdir(mode=0o700)
        self.request_dir = self.root / "requests"
        self.request_dir.mkdir(mode=0o700)
        self.bindings = {}
        for relative in BOUND_FILES:
            target = self.source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            data = f"synthetic source: {relative}\n".encode()
            target.write_bytes(data)
            self.bindings[relative] = digest(data)
        self.frame = {"name": "title", "text": "Synthetic private text", "singleLine": True,
                      "bbox": [40, 40, 1200, 60]}
        self.layout = {"schema": "openai.presentation.layout/v5", "unit": "px",
                       "slide": {"position": {"left": 0, "top": 0, "width": 1280, "height": 720}},
                       "inheritedLayers": [], "elements": [
                           {"name": "title", "text": self.frame["text"], "kind": "textbox",
                            "scope": "slide", "editable": True,
                            "position": {"left": 40, "top": 40, "width": 1200, "height": 60}}]}
        self.files = {
            "artifact-runtime-receipt.json": encoded({"synthetic": True}),
            "authoring.json": encoded({"schema": "solosentry.pptx.authoring/v1", "unit": "px",
                                       "canvas": [1280, 720], "slides": [
                                           {"slide": 1, "layout": "slide-01.layout.json",
                                            "authored": [self.frame]}]}),
            "candidate.pptx": b"synthetic PPTX placeholder; transport test only\n",
            "slide-01.layout.json": encoded(self.layout),
        }
        self._write_candidate()

    def _write_candidate(self) -> None:
        for name, data in self.files.items():
            (self.candidate / name).write_bytes(data)
        manifest = {
            "schema": "solosentry.pptx.v5-candidate/v1",
            "status": "Pending native measurement", "nativeMeasurementsRequired": True,
            "native_powerpoint_closeout": "Pending", "human_acceptance": "Pending",
            "slide_count": 1, "layout_schema": "openai.presentation.layout/v5", "inputs": {},
            "runtime": {"node": "synthetic", "artifact_tool": "synthetic",
                        "artifact_runtime_receipt_sha256": digest(self.files["artifact-runtime-receipt.json"])},
            "candidate_pptx_sha256": digest(self.files["candidate.pptx"]),
            "source_bindings": self.bindings,
            "files": [{"file": name, "size": len(data), "sha256": digest(data)}
                      for name, data in sorted(self.files.items())],
        }
        (self.candidate / "candidate.json").write_bytes(encoded(manifest))

    def test_pending_request_binds_sources_and_never_claims_acceptance(self) -> None:
        request = prepare(self.source, self.candidate)
        self.assertEqual(request["status"], "Pending native rendering")
        self.assertEqual(request["authored"], [[self.frame]])
        self.assertNotIn("Passed", json.dumps(request))
        output = self.request_dir / "native-request.json"
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(main(["--root", str(self.source), "--candidate-dir",
                                   str(self.candidate), "--output", str(output)]), 0)
        self.assertEqual(output.stat().st_mode & 0o777, 0o400)
        self.assertEqual(json.loads(output.read_bytes()), request)

    def test_changed_source_or_candidate_is_rejected(self) -> None:
        (self.source / BOUND_FILES[0]).write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "stale"):
            prepare(self.source, self.candidate)
        (self.source / BOUND_FILES[0]).write_bytes(
            f"synthetic source: {BOUND_FILES[0]}\n".encode())
        (self.candidate / "candidate.pptx").write_bytes(b"altered")
        with self.assertRaisesRegex(ValueError, "binding"):
            prepare(self.source, self.candidate)

    def test_matching_hashes_do_not_authorise_unbound_layout_text(self) -> None:
        self.layout["elements"].append({"name": "extra", "text": "Unreviewed text",
                                        "kind": "textbox", "scope": "slide", "editable": True,
                                        "position": {"left": 40, "top": 140, "width": 400, "height": 40}})
        self.files["slide-01.layout.json"] = encoded(self.layout)
        self._write_candidate()
        with self.assertRaisesRegex(ValueError, "unbound text"):
            prepare(self.source, self.candidate)

    def test_symlink_extra_file_and_duplicate_json_fail_closed(self) -> None:
        target = self.candidate / "candidate.pptx"
        target.unlink()
        target.symlink_to(self.source / BOUND_FILES[0])
        with self.assertRaises((OSError, ValueError)):
            prepare(self.source, self.candidate)
        target.unlink()
        target.write_bytes(self.files["candidate.pptx"])
        (self.candidate / "extra.txt").write_text("unbound", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            prepare(self.source, self.candidate)
        (self.candidate / "extra.txt").unlink()
        (self.candidate / "candidate.json").write_bytes(b'{"status":"Pending", "status":"Passed"}')
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            prepare(self.source, self.candidate)

    def test_output_is_private_and_not_overwritten(self) -> None:
        output = self.request_dir / "native-request.json"
        output.write_bytes(b"preserve")
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(main(["--root", str(self.source), "--candidate-dir",
                                   str(self.candidate), "--output", str(output)]), 1)
        self.assertEqual(output.read_bytes(), b"preserve")
        public_dir = self.root / "public"
        public_dir.mkdir(mode=0o755)
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(main(["--root", str(self.source), "--candidate-dir",
                                   str(self.candidate), "--output", str(public_dir / "request.json")]), 1)
        self.assertFalse((public_dir / "request.json").exists())


class PortableBoundaryTests(unittest.TestCase):
    def test_nonfinite_json_exponents_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-finite"):
            _json(b'{"number":1e100000}')

    @unittest.skipUnless(os.name == "nt", "Windows-only fail-closed check")
    def test_windows_cannot_stage_posix_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "POSIX 0700"):
                prepare(root, root)


if __name__ == "__main__":
    unittest.main()
