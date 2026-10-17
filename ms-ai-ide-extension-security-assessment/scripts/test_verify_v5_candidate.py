# SPDX-License-Identifier: MIT
"""Fail-closed transport tests for private, pending v5 candidates."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from capture_v5_powerpoint_render import MAX_ADAPTER_OUTPUT, _run_adapter, capture
from capture_v5_powerpoint_render import main as capture_main
from measure_v5_candidate import main as measure_main
from measure_v5_candidate import measure
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

    def test_native_adapter_output_has_live_byte_bound(self) -> None:
        command = [sys.executable, "-c", f"import sys; sys.stdout.write('x'*{MAX_ADAPTER_OUTPUT + 1})"]
        with self.assertRaisesRegex(ValueError, "exceeds bounds"):
            _run_adapter(command)
        small = _run_adapter([sys.executable, "-c", "import sys; print('ok'); print('note', file=sys.stderr)"])
        self.assertEqual((small.returncode, small.stdout, small.stderr), (0, "ok\n", "note\n"))

    def _native_render_inputs(self) -> tuple[Path, Path, Path, dict[str, object]]:
        request = prepare(self.source, self.candidate)
        request_path = self.request_dir / "native-request.json"
        request_path.write_bytes(encoded(request))
        qa_root = self.root / "PowerPoint-QA"
        (qa_root / "input").mkdir(parents=True)
        (qa_root / "rendered").mkdir()
        qa_root = qa_root.resolve(strict=True)
        staged = qa_root / "input" / "candidate.pptx"
        staged.write_bytes(self.files["candidate.pptx"])
        (self.source / "scripts/capture_v5_powerpoint_render.py").write_bytes(b"reviewed synthetic coordinator\n")
        return request_path, staged, qa_root / "rendered" / "candidate-powerpoint-full.pdf", request

    def test_native_adapter_provenance_binds_exact_candidate_without_acceptance(self) -> None:
        request_path, staged, pdf, request = self._native_render_inputs()
        def render(command, **_kwargs):
            self.assertEqual(command[0], "/usr/bin/osascript")
            self.assertEqual(command[-2:], [str(staged), request["candidate_pptx_sha256"]])
            pdf.write_bytes(b"%PDF-1.7\n" + b"synthetic native output" * 4)
            return subprocess.CompletedProcess(command, 0, f"candidate\t1\t{pdf}\n", "")
        with mock.patch("capture_v5_powerpoint_render._run_adapter", side_effect=render) as runner:
            proof = capture(self.source, self.candidate, request_path, staged,
                            Path(sys.executable).resolve(),
                            request_sha256=digest(encoded(request)), host_platform="darwin")
        runner.assert_called_once()
        self.assertEqual(proof["schema"], "solosentry.pptx.v5-native-render/v1")
        self.assertEqual(proof["candidate_pptx_sha256"], digest(self.files["candidate.pptx"]))
        self.assertEqual(proof["native_pdf_sha256"], digest(pdf.read_bytes()))
        self.assertRegex(proof["native_python_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(proof["human_acceptance"], "Pending")
        self.assertNotIn("Passed", json.dumps(proof))

    def test_native_adapter_provenance_rejects_stale_or_unowned_output(self) -> None:
        request_path, staged, pdf, request = self._native_render_inputs()
        python = Path(sys.executable).resolve()
        with mock.patch("capture_v5_powerpoint_render._run_adapter") as runner:
            with self.assertRaisesRegex(ValueError, "request differs"):
                capture(self.source, self.candidate, request_path, staged, python,
                        request_sha256="0" * 64, host_platform="darwin")
            runner.assert_not_called()
        staged.unlink()
        staged.symlink_to(self.candidate / "candidate.pptx")
        with mock.patch("capture_v5_powerpoint_render._run_adapter") as runner:
            with self.assertRaises((OSError, ValueError)):
                capture(self.source, self.candidate, request_path, staged, python,
                        request_sha256=digest(encoded(request)), host_platform="darwin")
            runner.assert_not_called()
        staged.unlink()
        staged.write_bytes(self.files["candidate.pptx"])
        def wrong_document(command, **_kwargs):
            pdf.write_bytes(b"%PDF-1.7\n" + b"synthetic native output" * 4)
            return subprocess.CompletedProcess(command, 0, f"unrelated\t1\t{pdf}\n", "")
        with (mock.patch("capture_v5_powerpoint_render._run_adapter", side_effect=wrong_document),
              self.assertRaisesRegex(ValueError, "unexpected export")):
            capture(self.source, self.candidate, request_path, staged, python,
                    request_sha256=digest(encoded(request)), host_platform="darwin")

    def test_native_adapter_provenance_rejects_retained_stage_without_receipt(self) -> None:
        request_path, staged, pdf, request = self._native_render_inputs()
        def retained_stage(command, **_kwargs):
            pdf.write_bytes(b"%PDF-1.7\n" + b"synthetic native output" * 4)
            (staged.parent.parent / ".powerpoint-render.retained").mkdir()
            return subprocess.CompletedProcess(command, 0, f"candidate\t1\t{pdf}\n", "")
        output = self.request_dir.resolve(strict=True) / "native-proof.json"
        with mock.patch("capture_v5_powerpoint_render._run_adapter", side_effect=retained_stage) as runner, \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(capture_main(["--root", str(self.source), "--candidate-dir", str(self.candidate),
                                           "--request", str(request_path),
                                           "--request-sha256", digest(encoded(request)),
                                           "--qa-input", str(staged), "--python", str(Path(sys.executable).resolve()),
                                           "--output", str(output)]), 1)
        runner.assert_called_once()
        self.assertFalse(output.exists())

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

    def _measurement_inputs(self):
        request = prepare(self.source, self.candidate)
        request_bytes = encoded(request)
        request_path = self.request_dir / "native-request.json"
        request_path.write_bytes(request_bytes)
        pdf_dir = self.root / "rendered"
        pdf_dir.mkdir(mode=0o700)
        pdf_path = pdf_dir / "candidate-powerpoint-full.pdf"
        pdf_bytes = b"%PDF-1.7\nsynthetic coordinator test; worker is mocked\n"
        pdf_path.write_bytes(pdf_bytes)
        policy_path = self.source / "reviewed-parser-identity.json"
        policy_bytes = encoded({"synthetic": "reviewed in coordinator test"})
        policy_path.write_bytes(policy_bytes)
        digests = {"request_sha256": digest(request_bytes), "pdf_sha256": digest(pdf_bytes),
                   "parser_sha256": digest(policy_bytes)}
        return request_path, pdf_path, policy_path, digests

    def test_measurement_handoff_binds_current_inputs_without_acceptance(self) -> None:
        request_path, pdf_path, policy_path, digests = self._measurement_inputs()
        observed = {"parser_identity_sha256": "f" * 64,
                    "pages": [[{"name": "title", "minimum_font_pt": 20, "line_count": 1}]]}
        with mock.patch("measure_v5_candidate.validate_native_pdf_bounded", return_value=observed) as worker:
            record = measure(self.source, self.candidate, request_path, pdf_path,
                             policy_path, Path("/trusted/python"), **digests)
        worker.assert_called_once()
        self.assertEqual(worker.call_args.args[1], [[self.frame]])
        self.assertEqual(worker.call_args.kwargs["parser_identity"],
                         {"synthetic": "reviewed in coordinator test"})
        self.assertEqual(record["status"], "Pending native provenance and acceptance")
        self.assertEqual(record["native_pdf_sha256"], digests["pdf_sha256"])
        self.assertEqual(record["pages"], observed["pages"])
        self.assertNotIn("Passed", json.dumps(record))

    def test_measurement_handoff_rejects_stale_inputs_and_parser_failure(self) -> None:
        request_path, pdf_path, policy_path, digests = self._measurement_inputs()
        with mock.patch("measure_v5_candidate.validate_native_pdf_bounded") as worker:
            for field in ("request_sha256", "pdf_sha256", "parser_sha256"):
                changed = dict(digests, **{field: "0" * 64})
                with self.subTest(field=field), self.assertRaises(ValueError):
                    measure(self.source, self.candidate, request_path, pdf_path,
                            policy_path, Path("/trusted/python"), **changed)
            worker.assert_not_called()
        with mock.patch("measure_v5_candidate.validate_native_pdf_bounded",
                        side_effect=ValueError("private PDF content must not be logged")):
            output = self.request_dir / "measurements.json"
            error = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(error):
                code = measure_main(["--root", str(self.source), "--candidate-dir", str(self.candidate),
                                     "--request", str(request_path), "--request-sha256", digests["request_sha256"],
                                     "--native-pdf", str(pdf_path), "--native-pdf-sha256", digests["pdf_sha256"],
                                     "--parser-identity", str(policy_path),
                                     "--parser-identity-sha256", digests["parser_sha256"],
                                     "--python", "/trusted/python", "--output", str(output)])
            self.assertEqual(code, 1)
            self.assertNotIn("private PDF content", error.getvalue())
            self.assertFalse(output.exists())

    def test_measurement_handoff_detects_mutation_and_writes_private_pending_record(self) -> None:
        request_path, pdf_path, policy_path, digests = self._measurement_inputs()
        observed = {"parser_identity_sha256": "f" * 64,
                    "pages": [[{"name": "title", "minimum_font_pt": 20, "line_count": 1}]]}
        with (mock.patch("measure_v5_candidate.validate_native_pdf_bounded",
                         side_effect=lambda *_args, **_kwargs: (pdf_path.write_bytes(b"changed"), observed)[1]),
              self.assertRaisesRegex(ValueError, "changed during native parsing")):
            measure(self.source, self.candidate, request_path, pdf_path,
                    policy_path, Path("/trusted/python"), **digests)
        pdf_path.write_bytes(b"%PDF-1.7\nsynthetic coordinator test; worker is mocked\n")
        output = self.request_dir / "measurements.json"
        with mock.patch("measure_v5_candidate.validate_native_pdf_bounded", return_value=observed), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = measure_main(["--root", str(self.source), "--candidate-dir", str(self.candidate),
                                 "--request", str(request_path), "--request-sha256", digests["request_sha256"],
                                 "--native-pdf", str(pdf_path), "--native-pdf-sha256", digests["pdf_sha256"],
                                 "--parser-identity", str(policy_path),
                                 "--parser-identity-sha256", digests["parser_sha256"],
                                 "--python", "/trusted/python", "--output", str(output)])
        self.assertEqual(code, 0)
        self.assertEqual(output.stat().st_mode & 0o777, 0o400)
        self.assertEqual(json.loads(output.read_bytes())["status"],
                         "Pending native provenance and acceptance")
        with mock.patch("measure_v5_candidate.validate_native_pdf_bounded", return_value=observed), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(measure_main(["--root", str(self.source), "--candidate-dir", str(self.candidate),
                                           "--request", str(request_path), "--request-sha256", digests["request_sha256"],
                                           "--native-pdf", str(pdf_path), "--native-pdf-sha256", digests["pdf_sha256"],
                                           "--parser-identity", str(policy_path),
                                           "--parser-identity-sha256", digests["parser_sha256"],
                                           "--python", "/trusted/python", "--output", str(output)]), 1)


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
