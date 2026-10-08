#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise native measurement policy independently of renderer metadata."""
import copy
import ctypes
import hashlib
import contextlib
import importlib.util
import json
import math
import os
import platform
import py_compile
import signal
import subprocess
from pathlib import Path
import tempfile
import time
import sys
import unittest
from unittest import mock

import native_pptx_text as native_module
from native_pptx_text import NativeTextError, effective_font_size, extract_native_pdf, validate_native_page, validate_native_pdf_bounded


def test_parser_identity():
    """Describe this test installation only; never select production dependencies."""
    files = {}; versions = {}
    for name in ("pypdfium2", "pypdfium2_raw"):
        root = Path(importlib.util.find_spec(name).origin).parent
        versions[name] = json.loads((root / "version.json").read_text())
        for path in root.rglob("*"):
            if path.is_file() and path.name.endswith((".py", ".json", ".dylib", ".dll", ".so", ".pyd")):
                files[name + "/" + path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    helper = versions["pypdfium2"]; native = versions["pypdfium2_raw"]
    return {"schema_version": 1, "platform": f"{sys.platform}-{platform.machine().lower()}",
            "distribution_version": ".".join(str(helper[k]) for k in ("major", "minor", "patch")),
            "pdfium_version": ".".join(str(native[k]) for k in ("major", "minor", "build", "patch")),
            "native_flags": [], "files": files}


def native_pdf(font=20, scale=1, rotation=0, canvas="960 540", form=False):
    """A real, deterministic one-page PDF, without a renderer or parser mock."""
    stream = f"BT /F1 {font} Tf {scale} 0 0 {scale} 40 480 Tm (Title) Tj ET".encode("ascii")
    objects = [b"<< /Type /Catalog /Pages 2 0 R" + (b" /AcroForm 6 0 R" if form else b"") + b" >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {canvas}] /Rotate {rotation} /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>".encode("ascii"),
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream"]
    if form:
        objects.append(b"<< /Fields [] >>")
    data = bytearray(b"%PDF-1.7\n"); offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(data)


@unittest.skipUnless(importlib.util.find_spec("pypdfium2"), "native parser is not installed in this environment")
class NativeExtractionTests(unittest.TestCase):
    def test_real_pdf_font_transform_and_authoring_match(self):
        authored = [{"name": "title", "text": "Title", "singleLine": True, "bbox": [40, 40, 300, 80]}]
        for font, scale in [(20, 1), (1, 20)]:
            with self.subTest(font=font, scale=scale):
                pages = extract_native_pdf(native_pdf(font=font, scale=scale))
                self.assertEqual(len(pages), 1)
                result = validate_native_page(pages[0], authored)
                self.assertAlmostEqual(result[0]["minimum_font_pt"], 20)
                self.assertEqual(result[0]["line_count"], 1)

    def test_real_pdf_scaled_nominal_font_cannot_bypass_minimum(self):
        authored = [{"name": "title", "text": "Title", "singleLine": True, "bbox": [40, 40, 300, 80]}]
        page = extract_native_pdf(native_pdf(font=20, scale=.5))[0]
        with self.assertRaisesRegex(NativeTextError, "below 16pt"):
            validate_native_page(page, authored)

    def test_real_pdf_unsupported_canvas_and_rotation_reject(self):
        for options in [{"rotation": 90}, {"canvas": "1280 720"}]:
            with self.subTest(options=options), self.assertRaisesRegex(NativeTextError, "canvas or rotation"):
                extract_native_pdf(native_pdf(**options))

    def test_real_extraction_never_activates_form_callbacks(self):
        # Actual supported parser and ordinary/form-bearing PDFs. These guards
        # observe the specific interface named by CVE-2026-95338, not a mock
        # substitute for PDF text extraction or a blanket vulnerability claim.
        import pypdfium2 as pdfium
        import pypdfium2.raw as raw
        names = ("FPDFDOC_InitFormFillEnvironment", "FORM_OnAfterLoadPage",
                 "FORM_OnBeforeClosePage", "FORM_DoDocumentJSAction",
                 "FORM_DoDocumentOpenAction", "FORM_DoPageAAction")
        with contextlib.ExitStack() as stack:
            guarded = [stack.enter_context(mock.patch.object(
                raw, name, side_effect=AssertionError("unexpected form activation")))
                for name in names]
            pages = extract_native_pdf(native_pdf())
            self.assertEqual(len(pages), 1)
            with self.assertRaisesRegex(NativeTextError, "unsupported form"):
                extract_native_pdf(native_pdf(form=True))
            for call in guarded:
                call.assert_not_called()
            # Positive control: the observed namespace is the actual helper
            # interface, so explicit activation must reach the rejection guard.
            with pdfium.PdfDocument(native_pdf(form=True)) as document:
                with self.assertRaisesRegex(AssertionError, "unexpected form activation"):
                    document.init_forms()
            self.assertEqual(guarded[0].call_count, 1)

    def test_real_pdf_forms_reject_before_measurement(self):
        with self.assertRaisesRegex(NativeTextError, "unsupported form"):
            extract_native_pdf(native_pdf(form=True))

    def test_malformed_pdf_never_produces_measurement(self):
        with self.assertRaisesRegex(NativeTextError, "cannot be opened reliably"):
            extract_native_pdf(b"%PDF-1.7\nnot a document\n%%EOF")

    @unittest.skipUnless(os.name == "nt" or sys.platform.startswith("linux"), "native worker requires approved memory-contained runner")
    def test_owned_worker_returns_only_digest_bound_measurements(self):
        authored = [{"name": "title", "text": "Title", "singleLine": True, "bbox": [40, 40, 300, 80]}]
        result = validate_native_pdf_bounded(native_pdf(), [authored], parser_identity=test_parser_identity())
        self.assertEqual(result["pages"], [[{"name": "title", "minimum_font_pt": 20, "line_count": 1}]])
        self.assertEqual(len(result["pdf_sha256"]), 64)
        self.assertEqual(len(result["request_sha256"]), 64)

    @unittest.skipUnless(os.name == "nt" or sys.platform.startswith("linux"), "native worker requires approved memory-contained runner")
    def test_owned_worker_rejects_bad_pdf_or_wrong_page_binding(self):
        authored = [{"name": "title", "text": "Title", "singleLine": True, "bbox": [40, 40, 300, 80]}]
        for data, pages in [(b"bad pdf", [authored]), (native_pdf(), [authored, authored])]:
            with self.subTest(pages=len(pages)), self.assertRaisesRegex(NativeTextError, "rejected"):
                validate_native_pdf_bounded(data, pages, parser_identity=test_parser_identity())

    @unittest.skipUnless(os.name == "nt" or sys.platform.startswith("linux"), "native worker requires approved memory-contained runner")
    def test_owned_worker_deadline_reaps_before_private_stage_cleanup(self):
        authored = [{"name": "title", "text": "Title", "singleLine": True, "bbox": [40, 40, 300, 80]}]
        with tempfile.TemporaryDirectory() as directory:
            # Control only the parent-owned temporary location; no child imports.
            previous = tempfile.tempdir
            try:
                tempfile.tempdir = directory
                with self.assertRaisesRegex(NativeTextError, "deadline expired"):
                    validate_native_pdf_bounded(native_pdf(), [authored], parser_identity=test_parser_identity(), timeout=.001)
                self.assertEqual(list(Path(directory).iterdir()), [])
            finally:
                tempfile.tempdir = previous

    @unittest.skipUnless(os.name == "nt" or sys.platform.startswith("linux"), "native worker requires approved memory-contained runner")
    def test_owned_worker_ignores_pythonpath_injection(self):
        authored = [{"name": "title", "text": "Title", "singleLine": True, "bbox": [40, 40, 300, 80]}]
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "injected"
            (Path(directory) / "sitecustomize.py").write_text(f"open({str(marker)!r}, 'w').write('executed')")
            previous = os.environ.get("PYTHONPATH")
            try:
                os.environ["PYTHONPATH"] = directory
                validate_native_pdf_bounded(native_pdf(), [authored], parser_identity=test_parser_identity())
                self.assertFalse(marker.exists())
            finally:
                if previous is None:
                    os.environ.pop("PYTHONPATH", None)
                else:
                    os.environ["PYTHONPATH"] = previous

    @unittest.skipUnless(os.name == "nt" or sys.platform.startswith("linux"), "native worker requires approved memory-contained runner")
    def test_worker_rejects_changed_missing_or_unexpected_parser_files(self):
        _, authored = fixture()
        for mode in ["changed", "missing", "unexpected"]:
            policy = test_parser_identity()
            if mode == "changed":
                policy["files"]["pypdfium2_raw/bindings.py"] = "0" * 64
            elif mode == "missing":
                policy["files"].pop("pypdfium2/_helpers/textpage.py")
            else:
                policy["files"]["pypdfium2/unreviewed.py"] = "0" * 64
            with self.subTest(mode=mode), self.assertRaisesRegex(NativeTextError, "rejected"):
                validate_native_pdf_bounded(native_pdf(), [authored], parser_identity=policy)

    def test_worker_rejects_unapproved_native_features_or_platform(self):
        _, authored = fixture()
        for key, value in [("native_flags", ["V8"]), ("platform", "unreviewed-platform")]:
            policy = test_parser_identity(); policy[key] = value
            with self.subTest(key=key), self.assertRaises(NativeTextError):
                validate_native_pdf_bounded(native_pdf(), [authored], parser_identity=policy)


def fixture():
    authored = [{"name": "slide-title-1", "text": "Title", "singleLine": True, "bbox": [40, 40, 300, 80]}]
    chars = [{"text": c, "bbox": [35 + i * 12, 40, 45 + i * 12, 60], "baseline": 55, "font_pt": 20}
             for i, c in enumerate("Title")]
    return {"width": 960, "height": 540, "characters": chars}, authored


class WindowsWorkerLimitTests(unittest.TestCase):
    def _api(self, failure=None):
        class Api:
            def __init__(self):
                self.closed = []; self.assigned = []; self.limits = None

            def CreateJobObjectW(self, attributes, name):
                assert attributes is None and name is None
                return None if failure == "create" else 101

            def SetInformationJobObject(self, job, kind, pointer, size):
                assert job == 101 and kind == 9 and size == 144
                self.limits = ctypes.string_at(pointer, size)
                return failure != "set"

            def QueryInformationJobObject(self, job, kind, pointer, size, returned):
                assert job == 101 and kind == 9 and size == 144 and returned is None
                ctypes.memmove(pointer, self.limits, size)
                observed = ctypes.cast(pointer, ctypes.POINTER(native_module._WindowsExtendedLimits)).contents
                if failure == "memory-mismatch":
                    observed.ProcessMemoryLimit = 0
                elif failure == "cpu-mismatch":
                    observed.BasicLimitInformation.PerProcessUserTimeLimit = 0
                elif failure == "process-mismatch":
                    observed.BasicLimitInformation.ActiveProcessLimit = 2
                elif failure == "flags-mismatch":
                    observed.BasicLimitInformation.LimitFlags |= 0x800  # Breakaway must not be granted.
                return failure != "query"

            def GetCurrentProcess(self):
                return 202

            def AssignProcessToJobObject(self, job, process):
                self.assigned.append((job, process))
                return failure != "assign"

            def IsProcessInJob(self, process, job, member):
                assert process == 202 and job == 101
                ctypes.cast(member, ctypes.POINTER(ctypes.c_int32)).contents.value = 0 if failure == "membership-value" else 1
                return failure != "membership-call"

            def CloseHandle(self, handle):
                self.closed.append(handle)
                return 1
        return Api()

    def test_job_setup_requires_verified_limits_and_current_worker_membership(self):
        api = self._api()
        with mock.patch.object(native_module, "_windows_job_api", return_value=api):
            self.assertEqual(native_module._enter_windows_parser_job(), (api, 101))
        limits = native_module._WindowsExtendedLimits.from_buffer_copy(api.limits)
        self.assertEqual(limits.BasicLimitInformation.LimitFlags, 0x250a)
        self.assertEqual(limits.BasicLimitInformation.PerProcessUserTimeLimit, 600_000_000)
        self.assertEqual(limits.BasicLimitInformation.ActiveProcessLimit, 1)
        self.assertEqual(limits.ProcessMemoryLimit, 1024 ** 3)
        self.assertEqual(api.assigned, [(101, 202)])
        self.assertEqual(api.closed, [])  # Closing a successful self-owned job kills its worker.

    def test_job_setup_failures_reject_and_release_only_the_owned_handle(self):
        for failure in ("create", "set", "query", "memory-mismatch", "cpu-mismatch", "process-mismatch",
                        "flags-mismatch", "assign", "membership-call", "membership-value"):
            api = self._api(failure)
            with self.subTest(failure=failure), mock.patch.object(native_module, "_windows_job_api", return_value=api):
                with self.assertRaises(NativeTextError):
                    native_module._enter_windows_parser_job()
            self.assertEqual(api.closed, [] if failure == "create" else [101])

    def test_unsupported_windows_abi_rejects_before_job_creation(self):
        sizeof = ctypes.sizeof
        with mock.patch.object(native_module.ctypes, "sizeof", side_effect=lambda kind: 4 if kind is ctypes.c_void_p else sizeof(kind)), \
                mock.patch.object(native_module, "_windows_job_api") as api:
            with self.assertRaisesRegex(NativeTextError, "structure is unsupported"):
                native_module._enter_windows_parser_job()
        api.assert_not_called()

    def test_worker_does_not_read_request_when_windows_limits_fail(self):
        incoming = mock.Mock()
        with mock.patch.object(native_module.os, "name", "nt"), mock.patch.object(native_module.sys, "stdin", incoming), \
                mock.patch.object(native_module, "_enter_windows_parser_job", side_effect=NativeTextError("fixture limit refusal")):
            with self.assertRaisesRegex(NativeTextError, "limit refusal"):
                native_module._worker()
        incoming.buffer.read.assert_not_called()

    def test_native_windows_limits_prevent_large_commit_and_child_process(self):
        if sys.platform != "win32":
            self.skipTest("requires actual Windows Job Object enforcement")
        script = Path(__file__).with_name("native_pptx_text.py").resolve()
        probe = r'''
import ctypes, json, runpy, subprocess, sys
m = runpy.run_path(sys.argv[1])
api, job = m['_enter_windows_parser_job']()
limits = m['_WindowsExtendedLimits']()
assert api.QueryInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits), None)
api.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
api.VirtualAlloc.restype = ctypes.c_void_p
api.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
api.VirtualFree.restype = ctypes.c_int32
allocation = api.VirtualAlloc(None, 2 * m['MAX_WORKER_MEMORY_BYTES'], 0x3000, 0x04)
memory_blocked = not allocation
if allocation:
    assert api.VirtualFree(allocation, 0, 0x8000)
try:
    child = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'raise SystemExit(0)'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except OSError:
    child_blocked = True
else:
    try:
        child_blocked = child.wait(timeout=5) != 0
    finally:
        if child.poll() is None:
            child.kill(); child.wait()
print(json.dumps({'flags': limits.BasicLimitInformation.LimitFlags,
                  'cpu_ticks': limits.BasicLimitInformation.PerProcessUserTimeLimit,
                  'memory_bytes': limits.ProcessMemoryLimit,
                  'active_processes': limits.BasicLimitInformation.ActiveProcessLimit,
                  'memory_blocked': memory_blocked, 'child_blocked': child_blocked}))
'''
        environment = {"PATH": str(Path(sys.executable).parent)}
        for name in ("SystemRoot", "WINDIR"):
            if name in os.environ:
                environment[name] = os.environ[name]
        result = subprocess.run([sys.executable, "-I", "-B", "-c", probe, str(script)],
                                capture_output=True, text=True, env=environment, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"flags": 0x250a, "cpu_ticks": 600_000_000,
                                                   "memory_bytes": 1024 ** 3, "active_processes": 1,
                                                   "memory_blocked": True, "child_blocked": True})


class LinuxWorkerPrivilegeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX resource API")
    def test_root_capabilities_and_unverifiable_limits_reject(self):
        import resource
        clean = b"CapInh:\t0000000000000000\nCapPrm:\t0000000000000000\nCapEff:\t0000000000000000\nCapAmb:\t0000000000000000\n"
        cases = [
            ((0, 1001, 1001), clean, [0, 1], (0, 0), "unprivileged"),
            ((1001, 1001, 1001), clean.replace(b"CapPrm:\t0000000000000000", b"CapPrm:\t0000000001000000"), [0, 1], (0, 0), "capabilities"),
            ((1001, 1001, 1001), clean.replace(b"CapAmb:", b"Missing:"), [0, 1], (0, 0), "capabilities"),
            ((1001, 1001, 1001), clean, [-1], (0, 0), "no-new-privileges"),
            ((1001, 1001, 1001), clean, [0, 0], (0, 0), "no-new-privileges"),
            ((1001, 1001, 1001), clean, [0, 1], (1, 1), "child-limit"),
        ]
        for uids, data, calls, observed, error in cases:
            with self.subTest(error=error), \
                 mock.patch.object(native_module.os, "getresuid", return_value=uids, create=True), \
                 mock.patch("builtins.open", mock.mock_open(read_data=data)), \
                 mock.patch.object(native_module.ctypes, "CDLL") as load, \
                 mock.patch.object(resource, "setrlimit"), \
                 mock.patch.object(resource, "getrlimit", return_value=observed):
                load.return_value.prctl.side_effect = calls
                with self.assertRaisesRegex(NativeTextError, error):
                    native_module._deny_linux_worker_children()


class BoundedDiagnosticPipeTests(unittest.TestCase):
    def capture_fast_exit(self, payload):
        # Below anonymous-pipe capacity: exit before any parent read.
        code = "import os,sys; os.write(2, bytes.fromhex(sys.argv[1])); raise SystemExit(1)"
        child = subprocess.Popen([sys.executable, "-I", "-B", "-c", code, payload.hex()],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                 start_new_session=os.name == "posix")
        reader = native_module._BoundedWorkerDiagnostics(child.stderr)
        try:
            deadline = time.monotonic() + 5
            while not native_module._owned_worker_exited(child):
                if time.monotonic() >= deadline:
                    self.fail("diagnostic fixture did not exit")
                time.sleep(.01)
            native_module._reap_owned_worker(child)
            reader.finish()
            self.assertTrue(reader.eof)
            self.assertEqual(child.returncode, 1)
            return reader
        finally:
            if child.returncode is None:
                native_module._reap_owned_worker(child)
            child.stderr.close()

    def test_fast_exit_preserves_only_allowed_failure_context(self):
        payload = b'{"failureStage":"parser-snapshot","failureType":"ImportError"}'
        reader = self.capture_fast_exit(payload)
        self.assertFalse(reader.overflow)
        self.assertEqual(bytes(reader.data), payload)
        self.assertEqual(native_module._safe_worker_failure(bytes(reader.data)),
                         "; stage parser-snapshot; type ImportError")

    def test_fast_exit_oversized_stderr_is_capped_and_marked(self):
        reader = self.capture_fast_exit(b"private PDF text " * 128)
        self.assertTrue(reader.overflow)
        self.assertEqual(len(reader.data), native_module.MAX_FAILURE_BYTES)
        self.assertEqual(native_module._safe_worker_failure(bytes(reader.data)), "")

    def test_active_oversized_writer_is_drained_capped_and_reaped(self):
        child = subprocess.Popen([sys.executable, "-I", "-B", "-c",
                                  "import os; os.write(2, b'x' * (1024 * 1024))"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                 start_new_session=os.name == "posix")
        reader = native_module._BoundedWorkerDiagnostics(child.stderr)
        try:
            deadline = time.monotonic() + 5
            while not reader.overflow:
                reader.drain()
                if time.monotonic() >= deadline:
                    self.fail("oversized fixture did not produce overflow")
                time.sleep(.01)
            native_module._reap_owned_worker(child)
            reader.finish()
            self.assertTrue(reader.eof)
            self.assertEqual(len(reader.data), native_module.MAX_FAILURE_BYTES)
            self.assertIsNotNone(child.returncode)
        finally:
            if child.returncode is None:
                native_module._reap_owned_worker(child)
            child.stderr.close()

    def test_retained_writer_cannot_extend_reader_lifecycle(self):
        incoming, outgoing = os.pipe()
        with os.fdopen(incoming, "rb", buffering=0) as stream:
            try:
                reader = native_module._BoundedWorkerDiagnostics(stream)
                started = time.monotonic()
                with self.assertRaisesRegex(NativeTextError, "did not close after cleanup"):
                    reader.finish()
                self.assertLess(time.monotonic() - started, 1)
                self.assertEqual(reader.data, b"")
            finally:
                os.close(outgoing)


class NativeMeasurementTests(unittest.TestCase):
    def test_failed_worker_context_is_bounded_and_never_reflects_messages(self):
        safe = b'{"failureStage":"parser-extraction","failureType":"MemoryError"}'
        self.assertEqual(native_module._safe_worker_failure(safe),
                         "; stage parser-extraction; type MemoryError")
        for raw in (b"private native stderr", b"x" * 1025,
                    b'{"failureStage":"/private/report","failureType":"MemoryError"}',
                    b'{"failureStage":"request","failureType":"secret"}',
                    b'{"failureStage":[],"failureType":"MemoryError"}',
                    b'{"failureStage":"request","failureType":"MemoryError","message":"private PDF"}'):
            with self.subTest(raw=raw[:64]):
                self.assertEqual(native_module._safe_worker_failure(raw), "")

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires actual Linux address-space enforcement")
    def test_native_linux_worker_denies_mapping_before_request_read(self):
        script = Path(__file__).with_name("native_pptx_text.py").resolve()
        # Probe only an owned child. PROT_NONE reserves address space without
        # touching physical memory if a regressed worker permits the mapping.
        probe = r'''
import errno, json, mmap, resource, runpy, subprocess, sys
m = runpy.run_path(sys.argv[1])
class BeforeRequest:
    def read(self, size):
        assert size == 4
        limit = m['MAX_WORKER_MEMORY_BYTES']
        assert resource.getrlimit(resource.RLIMIT_AS) == (limit, limit)
        assert resource.getrlimit(resource.RLIMIT_NPROC) == (0, 0)
        try:
            child = subprocess.Popen([sys.executable, "-I", "-B", "-c", "raise SystemExit(0)"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            child_denied = exc.errno == errno.EAGAIN
        else:
            child.wait(timeout=5)
            child_denied = False
        try:
            mapping = mmap.mmap(-1, 2 * limit, prot=0)
        except OSError as exc:
            denied = exc.errno == errno.ENOMEM
        else:
            mapping.close()
            denied = False
        print(json.dumps({'address_space_bytes': limit,
                          'mapping_denied': denied,
                          'child_creation_denied': child_denied,
                          'before_request_consumption': True}))
        raise SystemExit(0)
class Incoming:
    buffer = BeforeRequest()
sys.stdin = Incoming()
m['_worker']()
'''
        result = subprocess.run([sys.executable, "-I", "-B", "-c", probe, str(script)],
                                capture_output=True, text=True,
                                env={"PATH": str(Path(sys.executable).parent)}, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"address_space_bytes": 1024 ** 3,
                                                   "mapping_denied": True,
                                                   "child_creation_denied": True,
                                                   "before_request_consumption": True})

    @unittest.skipUnless(sys.platform.startswith("linux") or sys.platform == "win32", "requires native worker CPU enforcement")
    def test_native_cpu_limit_terminates_owned_busy_worker(self):
        script = Path(__file__).with_name("native_pptx_text.py").resolve()
        probe = r'''
import runpy, sys
m = runpy.run_path(sys.argv[1])
m['_worker'].__globals__['MAX_WORKER_CPU_SECONDS'] = 1
class Busy:
    def read(self, size):
        print('owned CPU limit active', flush=True)
        while True:
            pass
class Incoming:
    buffer = Busy()
sys.stdin = Incoming()
m['_worker']()
'''
        environment = {"PATH": str(Path(sys.executable).parent)}
        for key in ("SystemRoot", "WINDIR"):
            if key in os.environ:
                environment[key] = os.environ[key]
        result = subprocess.run([sys.executable, "-I", "-B", "-c", probe, str(script)],
                                capture_output=True, text=True, env=environment, timeout=10)
        self.assertEqual(result.stdout.strip(), "owned CPU limit active", result.stderr)
        if sys.platform == "win32":
            # Job quota termination, not an arbitrary crash or Python failure.
            self.assertEqual(result.returncode & 0xFFFFFFFF, 0xC0000044, result.stderr)  # STATUS_QUOTA_EXCEEDED
        else:
            self.assertIn(result.returncode, (-signal.SIGKILL, -signal.SIGXCPU), result.stderr)

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux non-reaping wait and session cleanup")
    def test_early_exit_worker_cleanup_spares_separate_sentinel(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "owned-child.pid"
            code = "import os,sys,time; pid=os.fork(); " + \
                   "(time.sleep(30) if pid==0 else (open(sys.argv[1],'w').write(str(pid)),os._exit(0)))"
            sentinel = subprocess.Popen([sys.executable, "-I", "-B", "-c", "import time; time.sleep(30)"],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            leader = subprocess.Popen([sys.executable, "-I", "-B", "-c", code, str(marker)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      start_new_session=True)
            reaped = False
            try:
                deadline = time.monotonic() + 5
                while not native_module._owned_worker_exited(leader):
                    self.assertLess(time.monotonic(), deadline, "owned leader did not exit")
                    time.sleep(.01)
                self.assertIsNone(leader.returncode, "leader was prematurely reaped")
                child_pid = int(marker.read_text())
                native_module._reap_owned_worker(leader)
                reaped = True
                self.assertEqual(leader.returncode, 0)
                deadline = time.monotonic() + 5
                while True:
                    try:
                        state = Path(f"/proc/{child_pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
                    except FileNotFoundError:
                        break
                    if state == "Z":
                        break  # Terminated; its OS reaper owns the orphan zombie.
                    self.assertLess(time.monotonic(), deadline, "owned descendant survived group cleanup")
                    time.sleep(.01)
                self.assertIsNone(sentinel.poll(), "unrelated sentinel was signalled")
                with self.assertRaises(ChildProcessError):
                    native_module._reap_owned_worker(leader)  # Refuse a reaped/reusable PID.
            finally:
                if not reaped:
                    native_module._reap_owned_worker(leader)
                if sentinel.poll() is None:
                    sentinel.kill()
                sentinel.wait()

    def test_unsupported_host_rejects_before_worker_launch(self):
        _, authored = fixture()
        for host in ("darwin", "freebsd14", "unknown"):
            with self.subTest(host=host), mock.patch.object(native_module.os, "name", "posix"), \
                    mock.patch.object(native_module.sys, "platform", host), \
                    mock.patch.object(native_module, "_parser_policy", return_value=b"test-only-policy"), \
                    mock.patch.object(native_module, "Path") as executable_path, \
                    mock.patch.object(native_module.subprocess, "Popen") as launch:
                executable_path.return_value.is_absolute.return_value = True
                executable_path.return_value.is_file.return_value = True
                with self.assertRaisesRegex(NativeTextError, "memory-contained runner"):
                    validate_native_pdf_bounded(native_pdf(), [authored], parser_identity={})
                launch.assert_not_called()

    def test_unsupported_worker_rejects_before_request_read(self):
        with mock.patch.object(native_module.os, "name", "posix"), \
                mock.patch.object(native_module.sys, "platform", "darwin"), \
                mock.patch.object(native_module.sys, "stdin") as incoming:
            with self.assertRaisesRegex(NativeTextError, "memory-contained runner"):
                native_module._worker()
            incoming.buffer.read.assert_not_called()

    def test_supported_worker_platforms_pass_platform_gate_only(self):
        for family, host in [("nt", "win32"), ("posix", "linux")]:
            with self.subTest(host=host), mock.patch.object(native_module.os, "name", family), \
                    mock.patch.object(native_module.sys, "platform", host):
                native_module._require_memory_contained_worker_platform()

    @unittest.skipUnless(os.name == "posix", "POSIX resource API")
    def test_linux_memory_readback_failure_precedes_request_read(self):
        import resource
        with mock.patch.object(native_module.sys, "platform", "linux"), \
                mock.patch.object(resource, "setrlimit") as set_limit, \
                mock.patch.object(resource, "getrlimit", return_value=(0, 0)), \
                mock.patch.object(native_module.sys, "stdin") as incoming:
            with self.assertRaisesRegex(NativeTextError, "memory-limit readback"):
                native_module._worker()
            set_limit.assert_any_call(resource.RLIMIT_AS, (native_module.MAX_WORKER_MEMORY_BYTES,) * 2)
            incoming.buffer.read.assert_not_called()

    def test_parser_snapshot_preserves_crlf_and_control_bytes(self):
        payload = b"source\r\n\x1a\x00binary\r\nend"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parser.bin"
            path.write_bytes(payload)
            self.assertEqual(native_module._parser_bytes(path), payload)

    def test_windows_snapshot_compares_equivalent_timestamps_and_rejects_changes(self):
        from types import SimpleNamespace
        payload = b"known fixture\r\n\x1a"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parser.bin"
            path.write_bytes(payload)
            observed = path.stat()
            fields = {name: getattr(observed, name) for name in
                      ("st_dev", "st_ino", "st_size", "st_mode", "st_mtime_ns", "st_ctime_ns")}
            for case in ("stable", "changed-during-read", "replaced-path", "changed-path-mtime", "changed-path-birth", "legacy"):
                before = dict(fields, st_ctime_ns=200, st_birthtime_ns=100)
                after = dict(before)
                leaf = dict(fields, st_ctime_ns=100, st_birthtime_ns=100)
                if case == "changed-during-read":
                    after["st_ctime_ns"] = 300
                elif case == "replaced-path":
                    leaf["st_ino"] += 1
                elif case == "changed-path-mtime":
                    leaf["st_mtime_ns"] += 1
                elif case == "changed-path-birth":
                    leaf["st_birthtime_ns"] += 1
                elif case == "legacy":
                    for metadata in (before, after, leaf):
                        metadata.pop("st_birthtime_ns")
                        metadata["st_ctime_ns"] = 100
                with self.subTest(case=case), mock.patch.object(native_module.os, "name", "nt"), \
                        mock.patch.object(native_module.os, "fstat", side_effect=[SimpleNamespace(**before), SimpleNamespace(**after)]), \
                        mock.patch.object(type(path), "lstat", return_value=SimpleNamespace(**leaf)):
                    if case in ("stable", "legacy"):
                        self.assertEqual(native_module._parser_bytes(path), payload)
                    else:
                        with self.assertRaisesRegex(NativeTextError, "identity changed"):
                            native_module._parser_bytes(path)

    def test_verified_snapshot_excludes_substituted_installed_bytecode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); installed = root / "installed"; stage = root / "snapshot"; stage.mkdir()
            helper = installed / "pypdfium2"; native = installed / "pypdfium2_raw"
            helper.mkdir(parents=True); native.mkdir()
            source = helper / "__init__.py"
            source.write_text("MARKER = 'untrusted'\n")
            stamp = source.stat().st_mtime
            py_compile.compile(str(source), doraise=True)
            source.write_text("MARKER = 'reviewed!'\n")  # Same length and timestamp as cached code.
            os.utime(source, (stamp, stamp))
            (helper / "version.json").write_text(json.dumps({"major": 1, "minor": 0, "patch": 0, "dirty": False, "is_editable": False}))
            (helper / "_helpers").mkdir()
            (helper / "_helpers" / "__init__.py").write_bytes(b"")  # Legitimate hash-approved package marker.
            (native / "__init__.py").write_text("# test-only package\n")
            (native / "bindings.py").write_text("# test-only bindings\n")
            (native / "libpdfium.dylib").write_bytes(b"test-only identity; never loaded")
            (native / "version.json").write_text(json.dumps({"major": 1, "minor": 0, "build": 1, "patch": 0, "origin": "pdfium-binaries", "flags": []}))
            files = {p.relative_to(installed).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in installed.rglob("*") if p.is_file() and p.suffix != ".pyc"}
            policy = {"schema_version": 1, "platform": f"{sys.platform}-{platform.machine().lower()}",
                      "distribution_version": "1.0.0", "pdfium_version": "1.0.1.0", "native_flags": [], "files": files}
            path = root / "identity.json"; path.write_text(json.dumps(policy))
            script = Path(__file__).with_name("native_pptx_text.py")
            probe = r'''
import json, pathlib, runpy, sys
m = runpy.run_path(sys.argv[1])
sys.path.insert(0, sys.argv[2])
def trace(frame, event, argument):
    # Only metadata of this owned fixture, at the original rejection site.
    # Never alter the reader, exception, file bytes or acceptance result.
    if event == 'exception' and frame.f_code.co_name == '_parser_bytes':
        names = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        observed = {key: {name: getattr(frame.f_locals[key], name) for name in names}
                    for key in ('before', 'after', 'leaf') if key in frame.f_locals}
        print(json.dumps({'fixture_snapshot_metadata': observed}), file=sys.stderr)
    return trace
sys.settrace(trace)
try:
    m['_stage_parser'](json.loads(pathlib.Path(sys.argv[3]).read_text()), pathlib.Path(sys.argv[4]))
finally:
    sys.settrace(None)
import pypdfium2
print(pypdfium2.MARKER)
'''
            result = subprocess.run([sys.executable, "-I", "-B", "-c", probe, str(script), str(installed), str(path), str(stage)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "reviewed!")
            self.assertFalse(list(stage.rglob("*.pyc")))

    def test_worker_requires_explicit_approved_identity(self):
        _, authored = fixture()
        with self.assertRaisesRegex(NativeTextError, "approved parser identity"):
            validate_native_pdf_bounded(native_pdf(), [authored])

    def test_worker_rejects_aggregate_authoring_before_serialization(self):
        _, authored = fixture()
        pages = [[dict(authored[0], name=f"box-{i}", text="x" * (64 * 1024)) for i in range(129)]]
        with self.assertRaisesRegex(NativeTextError, "aggregate authored text"):
            validate_native_pdf_bounded(native_pdf(), pages)

    def test_worker_rejects_bad_deadline_or_relative_interpreter(self):
        _, authored = fixture()
        for options in [{"timeout": 0}, {"timeout": math.inf}, {"timeout": True},
                        {"timeout": 121}, {"python_executable": "python"}]:
            with self.subTest(options=options), self.assertRaises(NativeTextError):
                validate_native_pdf_bounded(native_pdf(), [authored], **options)

    def test_worker_rejects_extra_unbounded_authoring_fields(self):
        _, authored = fixture(); authored[0]["untrusted_extra"] = "not allowed"
        with self.assertRaisesRegex(NativeTextError, "frame schema"):
            validate_native_pdf_bounded(native_pdf(), [authored])

    def test_nominal_font_requires_effective_transform(self):
        self.assertEqual(effective_font_size(1, [20, 0, 0, 20, 30, 40]), 20)
        self.assertEqual(effective_font_size(20, [1, 0, 0, 1, 30, 40]), 20)
        self.assertEqual(effective_font_size(20, [.5, 0, 0, .5, 30, 40]), 10)

    def test_invalid_or_unsupported_transforms_reject(self):
        cases = [(0, [1, 0, 0, 1, 0, 0]), (True, [1, 0, 0, 1, 0, 0]),
                 (10 ** 400, [1, 0, 0, 1, 0, 0]), (20, None),
                 (20, [1, 0, 0, 1]), (20, [1, 0, 0, math.nan, 0, 0]),
                 (20, [0, 1, -1, 0, 0, 0]), (20, [1, .1, 0, 1, 0, 0]),
                 (20, [-1, 0, 0, 1, 0, 0]), (20, [1, 0, 0, .5, 0, 0])]
        for font, matrix in cases:
            with self.subTest(font=font, matrix=matrix), self.assertRaises(NativeTextError):
                effective_font_size(font, matrix)

    def test_valid_measurement_and_float_precision(self):
        page, authored = fixture()
        result = validate_native_page(page, authored)
        self.assertEqual(result, [{"name": "slide-title-1", "minimum_font_pt": 20, "line_count": 1}])
        for char in page["characters"]:
            char["font_pt"] = 15.999998092651367  # PDFium float32 transform at 16pt.
        validate_native_page(page, authored)

    def test_small_or_scaled_text_rejects(self):
        for size in [15, 15.999, effective_font_size(20, [.5, 0, 0, .5, 0, 0])]:
            page, authored = fixture()
            page["characters"][0]["font_pt"] = size
            with self.subTest(size=size), self.assertRaisesRegex(NativeTextError, "below 16pt"):
                validate_native_page(page, authored)

    def test_missing_changed_or_additional_text_rejects(self):
        for mode in ["missing", "changed", "additional"]:
            page, authored = fixture()
            if mode == "missing":
                page["characters"].pop()
            elif mode == "changed":
                page["characters"][0]["text"] = "X"
            else:
                extra = copy.deepcopy(page["characters"][0]); extra["bbox"] = [700, 40, 710, 60]
                page["characters"].append(extra)
            with self.subTest(mode=mode), self.assertRaises(NativeTextError):
                validate_native_page(page, authored)

    def test_duplicate_names_and_overlapping_frames_reject(self):
        for duplicate_name in [True, False]:
            page, authored = fixture(); other = copy.deepcopy(authored[0])
            if not duplicate_name:
                other["name"] = "another-box"
            authored.append(other)
            with self.subTest(duplicate_name=duplicate_name), self.assertRaises(NativeTextError):
                validate_native_page(page, authored)

    def test_glyph_center_inside_does_not_hide_frame_overflow(self):
        page, authored = fixture(); page["characters"][0]["bbox"] = [29, 40, 39, 60]
        with self.assertRaisesRegex(NativeTextError, "exceeds its authored frame"):
            validate_native_page(page, authored)

    def test_wrapped_title_rejects(self):
        page, authored = fixture(); authored[0]["text"] = "Tit le"
        for char in page["characters"][3:]:
            char["baseline"] = 75; char["bbox"][1] = 60; char["bbox"][3] = 80
        with self.assertRaisesRegex(NativeTextError, "wraps unexpectedly"):
            validate_native_page(page, authored)

    def test_missing_invalid_and_nonfinite_measurements_reject(self):
        for key, value in [("bbox", None), ("bbox", [35, math.inf, 45, 60]),
                           ("baseline", None), ("font_pt", True), ("text", "\x00")]:
            page, authored = fixture(); page["characters"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(NativeTextError):
                validate_native_page(page, authored)

    def test_canvas_and_authoring_evidence_reject(self):
        for key, value in [("bbox", None), ("bbox", [40, 40, 2000, 80]),
                           ("singleLine", None), ("text", "Title\ud800")]:
            page, authored = fixture(); authored[0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(NativeTextError):
                validate_native_page(page, authored)
        page, authored = fixture(); page["width"] = 1280
        with self.assertRaises(NativeTextError):
            validate_native_page(page, authored)

    def test_unicode_whitespace_is_not_silently_normalized(self):
        page, authored = fixture(); authored[0]["text"] += "\u00a0"
        with self.assertRaisesRegex(NativeTextError, "differs"):
            validate_native_page(page, authored)

    def test_assignment_work_is_bounded(self):
        page, authored = fixture(); page["characters"] *= 10_000
        authored *= 100
        with self.assertRaisesRegex(NativeTextError, "work bounds"):
            validate_native_page(page, authored)

    def test_empty_native_page_cannot_bypass_aggregate_authoring_bound(self):
        page, authored = fixture(); page["characters"] = []
        frames = [dict(authored[0], name=f"box-{i}", text="x" * (64 * 1024)) for i in range(129)]
        with self.assertRaisesRegex(NativeTextError, "aggregate authored text"):
            validate_native_page(page, frames)


if __name__ == "__main__":
    unittest.main()
