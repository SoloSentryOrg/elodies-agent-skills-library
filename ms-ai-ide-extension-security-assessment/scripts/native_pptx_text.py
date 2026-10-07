#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Internal native text measurements; not a runtime acceptance authority.

The caller must bind immutable authoring geometry, the staged presentation and
its native PDF by digest. This module never publishes a deck or acceptance.
PDFium calls are serial and all owned handles are explicitly closed.
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib.machinery
import itertools
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time

MAX_PDF_BYTES = 256 * 1024 * 1024
MAX_PAGES = 100
MAX_CHARACTERS = 100_000
MAX_BOXES = 4096
MAX_TEXT_BYTES = 64 * 1024
MAX_AUTHORED_BYTES = 8 * 1024 * 1024
MAX_ASSIGNMENT_WORK = 2_000_000
FRAME_TOLERANCE_PT = 0.5
FONT_FLOAT_TOLERANCE_PT = 0.00001
MAX_REQUEST_JSON = 12 * 1024 * 1024
MAX_RESULT_BYTES = 2 * 1024 * 1024
MAX_PARSER_FILES = 128
MAX_PARSER_FILE_BYTES = 32 * 1024 * 1024
MAX_PARSER_TOTAL_BYTES = 64 * 1024 * 1024
MAX_WORKER_MEMORY_BYTES = 1024 * 1024 * 1024
MAX_WORKER_CPU_SECONDS = 60


class _WindowsBasicLimits(ctypes.Structure):
    # Fixed-width Win32 types; SIZE_T/ULONG_PTR follow the process architecture.
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32), ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32)]


class _WindowsIoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                 "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _WindowsExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _WindowsBasicLimits), ("IoInfo", _WindowsIoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class NativeTextError(ValueError):
    """Native output cannot establish the required text properties."""


def _require_memory_contained_worker_platform() -> None:
    # Resource readback alone cannot prove enforcement on other POSIX hosts.
    # An approved isolated runner is still needed for the macOS measurement path.
    if os.name != "nt" and not (os.name == "posix" and sys.platform.startswith("linux")):
        raise NativeTextError("native worker requires an approved memory-contained runner on this platform")


def _windows_job_api():
    if os.name != "nt":
        raise NativeTextError("Windows worker limits require native Windows")
    # Explicit system DLL resolution, without a caller-supplied search path.
    api = ctypes.WinDLL("kernel32", use_last_error=True, winmode=0x800)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, ctypes.c_wchar_p], ctypes.c_void_p),
        "SetInformationJobObject": ([ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint32], ctypes.c_int32),
        "QueryInformationJobObject": ([ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p], ctypes.c_int32),
        "AssignProcessToJobObject": ([ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int32),
        "IsProcessInJob": ([ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int32),
        "GetCurrentProcess": ([], ctypes.c_void_p),
        "CloseHandle": ([ctypes.c_void_p], ctypes.c_int32),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes = arguments
        function.restype = result
    return api


def _enter_windows_parser_job():
    """Constrain only this disposable worker; retain its job until process exit.

    Nested-job refusal is a failure, never permission to parse without limits.
    No breakaway flag is granted. This does not restrict filesystem or network
    access and must not be described as a security sandbox.
    """
    if ctypes.sizeof(ctypes.c_void_p) != 8 or ctypes.sizeof(_WindowsBasicLimits) != 64 or ctypes.sizeof(_WindowsExtendedLimits) != 144:
        raise NativeTextError("Windows worker limit structure is unsupported")
    api = _windows_job_api()
    job = api.CreateJobObjectW(None, None)  # Unnamed, non-inheritable handle.
    if not job:
        raise NativeTextError("Windows worker job creation failed")
    try:
        limits = _WindowsExtendedLimits()
        # PROCESS_TIME | ACTIVE_PROCESS | PROCESS_MEMORY |
        # DIE_ON_UNHANDLED_EXCEPTION | KILL_ON_JOB_CLOSE; no breakaway flags.
        flags = 0x00000002 | 0x00000008 | 0x00000100 | 0x00000400 | 0x00002000
        limits.BasicLimitInformation.LimitFlags = flags
        limits.BasicLimitInformation.PerProcessUserTimeLimit = MAX_WORKER_CPU_SECONDS * 10_000_000
        limits.BasicLimitInformation.ActiveProcessLimit = 1
        limits.ProcessMemoryLimit = MAX_WORKER_MEMORY_BYTES
        if not api.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise NativeTextError("Windows worker limit setup failed")
        observed = _WindowsExtendedLimits()
        if not api.QueryInformationJobObject(job, 9, ctypes.byref(observed), ctypes.sizeof(observed), None):
            raise NativeTextError("Windows worker limit readback failed")
        if (observed.BasicLimitInformation.LimitFlags != flags or
                observed.BasicLimitInformation.PerProcessUserTimeLimit != limits.BasicLimitInformation.PerProcessUserTimeLimit or
                observed.BasicLimitInformation.ActiveProcessLimit != 1 or
                observed.ProcessMemoryLimit != MAX_WORKER_MEMORY_BYTES):
            raise NativeTextError("Windows worker limits differ from requested bounds")
        process = api.GetCurrentProcess()
        if not api.AssignProcessToJobObject(job, process):
            raise NativeTextError("Windows worker job assignment failed")
        member = ctypes.c_int32()
        if not api.IsProcessInJob(process, job, ctypes.byref(member)) or member.value != 1:
            raise NativeTextError("Windows worker job membership is unverified")
    except BaseException:
        # Before assignment this releases the unowned job. After assignment,
        # KILL_ON_JOB_CLOSE intentionally terminates this failed worker.
        api.CloseHandle(job)
        raise
    # Closing a successful self-owned job here would kill the worker. The OS
    # releases this sole handle at process exit; never assign the parent.
    return api, job


def _parser_policy(policy: object) -> bytes:
    keys = {"schema_version", "platform", "distribution_version", "pdfium_version", "native_flags", "files"}
    if not isinstance(policy, dict) or set(policy) != keys or type(policy["schema_version"]) is not int or policy["schema_version"] != 1:
        raise NativeTextError("approved parser identity is missing or malformed")
    if policy["platform"] != f"{sys.platform}-{platform.machine().lower()}":
        raise NativeTextError("approved parser platform does not match")
    for key, pattern in [("distribution_version", r"[0-9]+\.[0-9]+\.[0-9]+"),
                         ("pdfium_version", r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+")]:
        if not isinstance(policy[key], str) or not re.fullmatch(pattern, policy[key]) or len(policy[key]) > 64:
            raise NativeTextError("approved parser version is invalid")
    if policy["native_flags"] != []:
        raise NativeTextError("native parser feature flags are unsupported")
    files = policy["files"]
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_PARSER_FILES:
        raise NativeTextError("approved parser file collection exceeds bounds")
    required = {"pypdfium2/__init__.py", "pypdfium2/version.json", "pypdfium2_raw/__init__.py",
                "pypdfium2_raw/version.json", "pypdfium2_raw/bindings.py"}
    for name, digest in files.items():
        if not isinstance(name, str) or len(name) > 512 or not re.fullmatch(r"[A-Za-z0-9_./-]+", name):
            raise NativeTextError("approved parser path is invalid")
        parts = PurePosixPath(name).parts
        if not parts or parts[0] not in {"pypdfium2", "pypdfium2_raw"} or ".." in parts or str(PurePosixPath(name)) != name or not name.endswith((".py", ".json", ".dylib", ".dll", ".so", ".pyd")):
            raise NativeTextError("approved parser path escapes its package")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise NativeTextError("approved parser digest is invalid")
    if not required <= files.keys() or not any(name.endswith((".dylib", ".dll", ".so")) for name in files):
        raise NativeTextError("approved parser identity is incomplete")
    return json.dumps(policy, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def _parser_bytes(path: Path) -> bytes:
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0) |
             getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    if os.name == "posix" and (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK")):
        raise NativeTextError("native parser file safeguards are unavailable")
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= MAX_PARSER_FILE_BYTES:
            raise NativeTextError("native parser file is not bounded regular data")
        chunks = []; remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise NativeTextError("native parser file changed during snapshot")
            chunks.append(chunk); remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise NativeTextError("native parser file grew during snapshot")
        after = os.fstat(descriptor); leaf = path.lstat()
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        def path_identity(value):
            # Windows Python 3.12 fstat exposes change time in ctime, while
            # path stat preserves creation time there. Compare birthtime
            # across the two APIs; retain full change-time checks above/below.
            timestamp = (getattr(value, "st_birthtime_ns", value.st_ctime_ns)
                         if os.name == "nt" else value.st_ctime_ns)
            return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, timestamp)
        if identity(before) != identity(after) or path_identity(after) != path_identity(leaf) or stat.S_ISLNK(leaf.st_mode) or getattr(leaf, "st_file_attributes", 0) & 0x400:
            raise NativeTextError("native parser file identity changed during snapshot")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _stage_parser(policy: dict[str, object], stage: Path) -> str:
    """Copy only hash-approved bytes before importing any parser Python/native code.

    The private snapshot excludes installed bytecode caches, so a stale or
    substituted .pyc cannot override the reviewed Python source files.
    """
    encoded = _parser_policy(policy)
    if any(name == "pypdfium2" or name.startswith(("pypdfium2.", "pypdfium2_raw")) for name in sys.modules):
        raise NativeTextError("native parser was imported before identity verification")
    roots = {}
    observed = set()
    for name in ("pypdfium2", "pypdfium2_raw"):
        spec = importlib.machinery.PathFinder.find_spec(name, sys.path)
        if spec is None or not spec.origin or not spec.submodule_search_locations:
            raise NativeTextError("approved native parser is unavailable")
        root = Path(spec.origin).parent
        roots[name] = root
        for count, path in enumerate(itertools.chain([root], root.rglob("*")), 1):
            if count > 512:
                raise NativeTextError("native parser directory inventory exceeds bounds")
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                raise NativeTextError("native parser package contains a link or reparse point")
            if path.is_file() and path.name.endswith((".py", ".json", ".dylib", ".dll", ".so", ".pyd")):
                observed.add(name + "/" + path.relative_to(root).as_posix())
                if len(observed) > MAX_PARSER_FILES:
                    raise NativeTextError("native parser installation exceeds file bounds")
    if observed != set(policy["files"]):
        raise NativeTextError("native parser installation has missing or unexpected files")
    snapshots = {}; total = 0
    for name, digest in policy["files"].items():
        parts = PurePosixPath(name).parts
        data = _parser_bytes(roots[parts[0]].joinpath(*parts[1:]))
        if not data and not name.endswith(".py"):
            raise NativeTextError("native parser data or binary file is empty")
        total += len(data)
        if total > MAX_PARSER_TOTAL_BYTES:
            raise NativeTextError("native parser snapshot exceeds aggregate bounds")
        if hashlib.sha256(data).hexdigest() != digest:
            raise NativeTextError("native parser file differs from approved identity")
        snapshots[name] = data
    helper = json.loads(snapshots["pypdfium2/version.json"])
    native = json.loads(snapshots["pypdfium2_raw/version.json"])
    if ".".join(str(helper.get(k)) for k in ("major", "minor", "patch")) != policy["distribution_version"] or ".".join(str(native.get(k)) for k in ("major", "minor", "build", "patch")) != policy["pdfium_version"]:
        raise NativeTextError("native parser versions differ from approved identity")
    if native.get("origin") != "pdfium-binaries" or native.get("flags") != [] or helper.get("is_editable") is not False or helper.get("dirty") is not False:
        raise NativeTextError("native parser build origin or features are unsupported")
    for name, data in snapshots.items():
        destination = stage.joinpath(*PurePosixPath(name).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(data)
    sys.path.insert(0, str(stage))
    return hashlib.sha256(encoded).hexdigest()


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NativeTextError("native measurement must be finite numeric data")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise NativeTextError("native measurement exceeds numeric bounds") from exc
    if not math.isfinite(result):
        raise NativeTextError("native measurement must be finite numeric data")
    return result


def effective_font_size(nominal: object, matrix: object) -> float:
    """Measure horizontal, uniformly scaled text; reject unsupported transforms."""
    if not isinstance(matrix, (list, tuple)) or len(matrix) != 6:
        raise NativeTextError("native text matrix is incomplete")
    a, b, c, d, _, _ = [_number(v) for v in matrix]
    font = _number(nominal)
    if font <= 0 or a <= 0 or d <= 0 or abs(b) > 0.000001 or abs(c) > 0.000001:
        raise NativeTextError("native text has an unsupported orientation or scale")
    if not math.isclose(a, d, rel_tol=0.000001, abs_tol=0.000001):
        raise NativeTextError("native text has a nonuniform scale")
    size = font * min(a, d)
    if not math.isfinite(size) or size <= 0 or size > 1024:
        raise NativeTextError("native effective font size is invalid")
    return size


def extract_native_pdf(data: bytes) -> list[dict[str, object]]:
    """Extract inside an established worker boundary or from known test fixtures.

    This helper neither contains native allocations nor verifies parser identity.
    Untrusted PDF measurement must use ``validate_native_pdf_bounded``.
    """
    if not isinstance(data, bytes) or not data or len(data) > MAX_PDF_BYTES:
        raise NativeTextError("native PDF must be bounded immutable bytes")
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise NativeTextError("reviewed native PDF parser is unavailable") from exc
    result = []
    try:
        opened = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise NativeTextError("native PDF cannot be opened reliably") from exc
    with opened as document:
        if document.get_formtype() != pdfium.raw.FORMTYPE_NONE:
            raise NativeTextError("native PDF contains an unsupported form")
        if not 1 <= len(document) <= MAX_PAGES:
            raise NativeTextError("native PDF page count exceeds bounds")
        for index in range(len(document)):
            page = document[index]
            try:
                width, height = map(_number, page.get_size())
                if abs(width - 960) > 0.01 or abs(height - 540) > 0.01 or page.get_rotation() != 0:
                    raise NativeTextError("native PDF canvas or rotation is unsupported")
                text = page.get_textpage()
                try:
                    count = text.count_chars()
                    if not 0 <= count <= MAX_CHARACTERS:
                        raise NativeTextError("native PDF character count exceeds bounds")
                    characters = []
                    for i in range(count):
                        code = pdfium.raw.FPDFText_GetUnicode(text, i)
                        if not 0 < code <= 0x10FFFF or 0xD800 <= code <= 0xDFFF:
                            raise NativeTextError("native glyph has no valid Unicode mapping")
                        value = chr(code)
                        if value in "\r\n\t":
                            continue  # Native reading-order separators, not visible glyphs.
                        if pdfium.raw.FPDFText_HasUnicodeMapError(text, i) != 0:
                            raise NativeTextError("native glyph Unicode mapping is unreliable")
                        left, bottom, right, top = map(_number, text.get_charbox(i))
                        origin_x, origin_y = ctypes.c_double(), ctypes.c_double()
                        if not pdfium.raw.FPDFText_GetCharOrigin(text, i, origin_x, origin_y):
                            raise NativeTextError("native glyph origin is missing")
                        if value == " ":
                            size = None
                        else:
                            matrix = pdfium.raw.FS_MATRIX()
                            if not pdfium.raw.FPDFText_GetMatrix(text, i, ctypes.byref(matrix)):
                                raise NativeTextError("native glyph matrix is missing")
                            size = effective_font_size(pdfium.raw.FPDFText_GetFontSize(text, i),
                                                       [getattr(matrix, k) for k in ("a", "b", "c", "d", "e", "f")])
                        if right < left or top < bottom:
                            raise NativeTextError("native glyph bounds are inverted")
                        characters.append({"text": value, "bbox": [left, height - top, right, height - bottom],
                                           "baseline": height - _number(origin_y.value), "font_pt": size})
                    result.append({"width": width, "height": height, "characters": characters})
                finally:
                    text.close()
            finally:
                page.close()
    return result


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NativeTextError("authored/native text is missing or exceeds bounds")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise NativeTextError("authored/native text encoding is invalid") from exc
    if length > MAX_TEXT_BYTES or any(ord(c) < 32 and c not in "\t\r\n" for c in value):
        raise NativeTextError("authored/native text is invalid or exceeds bounds")
    # Explicit ASCII whitespace rule for native wrapping. Preserve other Unicode.
    return re.sub(r"[ \t\r\n]+", " ", value).strip(" \t\r\n")


def validate_native_page(page: dict[str, object], authored: list[dict[str, object]]) -> list[dict[str, object]]:
    """Validate measured glyphs against caller-bound immutable authored frames."""
    if not isinstance(page, dict) or _number(page.get("width")) != 960 or _number(page.get("height")) != 540:
        raise NativeTextError("native canvas is invalid")
    chars = page.get("characters")
    if not isinstance(chars, list) or len(chars) > MAX_CHARACTERS:
        raise NativeTextError("native character collection is unbounded")
    if not isinstance(authored, list) or not 1 <= len(authored) <= MAX_BOXES:
        raise NativeTextError("authored text collection is unbounded")
    if len(chars) * len(authored) > MAX_ASSIGNMENT_WORK:
        raise NativeTextError("native frame assignment exceeds work bounds")
    frames = []
    names = set()
    text_bytes = 0
    for item in authored:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"] or len(item["name"]) > 256 or item["name"] in names:
            raise NativeTextError("authored text name is invalid or duplicated")
        names.add(item["name"])
        expected = _text(item.get("text"))
        text_bytes += len(item["text"].encode("utf-8"))
        if text_bytes > MAX_AUTHORED_BYTES:
            raise NativeTextError("aggregate authored text exceeds byte bounds")
        if not isinstance(item.get("singleLine"), bool):
            raise NativeTextError("authored title line requirement is missing")
        bbox = item.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise NativeTextError("authored text frame is missing")
        left, top, width, height = map(_number, bbox)
        if left < 0 or top < 0 or width <= 0 or height <= 0 or left + width > 1280 or top + height > 720:
            raise NativeTextError("authored frame exceeds canvas bounds")
        frames.append({"name": item["name"], "expected": expected, "singleLine": item["singleLine"],
                       "rect": [left * .75, top * .75, (left + width) * .75, (top + height) * .75], "chars": []})
    for char in chars:
        if not isinstance(char, dict) or not isinstance(char.get("text"), str) or not char["text"]:
            raise NativeTextError("native character is invalid")
        if len(char["text"]) != 1 or ord(char["text"]) < 32:
            raise NativeTextError("native character identity is unsupported")
        bbox = char.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise NativeTextError("native glyph frame is missing")
        x0, y0, x1, y1 = map(_number, bbox)
        baseline = _number(char.get("baseline"))
        if x1 < x0 or y1 < y0:
            raise NativeTextError("native glyph bounds are inverted")
        owners = []
        for frame in frames:
            l, t, r, b = frame["rect"]
            if l - FRAME_TOLERANCE_PT <= (x0 + x1) / 2 <= r + FRAME_TOLERANCE_PT and t - FRAME_TOLERANCE_PT <= (y0 + y1) / 2 <= b + FRAME_TOLERANCE_PT:
                owners.append(frame)
        if char["text"] != " ":
            if len(owners) != 1:
                raise NativeTextError("visible native glyph is unassigned or ambiguous")
            frame = owners[0]
            l, t, r, b = frame["rect"]
            if x0 < l - FRAME_TOLERANCE_PT or y0 < t - FRAME_TOLERANCE_PT or x1 > r + FRAME_TOLERANCE_PT or y1 > b + FRAME_TOLERANCE_PT:
                raise NativeTextError("visible native glyph exceeds its authored frame")
            if _number(char.get("font_pt")) < 16 - FONT_FLOAT_TOLERANCE_PT:
                raise NativeTextError("native text renders below 16pt")
        elif len(owners) != 1:
            continue  # A reading-order gap between independent authored frames.
        owners[0]["chars"].append((baseline, char))
    results = []
    for frame in frames:
        lines = {}
        fonts = []
        for baseline, char in frame["chars"]:
            lines.setdefault(round(baseline, 2), []).append(char["text"])
            if char["text"] != " ":
                fonts.append(_number(char["font_pt"]))
        if not fonts:
            raise NativeTextError("authored text has no measured visible glyphs")
        observed = "\n".join("".join(row) for _, row in sorted(lines.items()))
        if _text(observed) != frame["expected"]:
            raise NativeTextError("native text differs from immutable authoring")
        visible_lines = {round(baseline, 2) for baseline, c in frame["chars"] if c["text"] != " "}
        if frame["singleLine"] and len(visible_lines) != 1:
            raise NativeTextError("native title wraps unexpectedly")
        results.append({"name": frame["name"], "minimum_font_pt": min(fonts), "line_count": len(visible_lines)})
    return results


def validate_native_pdf_bounded(data: bytes, authored: list[list[dict[str, object]]],
                                *, parser_identity: dict[str, object] | None = None,
                                python_executable: str = sys.executable,
                                timeout: float = 60) -> dict[str, object]:
    """Run measurements in an owned, deadline-bound process; never publish.

    This is process separation and resource bounding, not an OS security
    sandbox. Production callers must separately approve and bind the installed
    parser. Linux adds CPU/output/address-space limits.
    Windows requires a verified self-owned Job Object before reading the PDF,
    with CPU, committed-memory and active-process limits.
    Other hosts reject this worker until an approved memory-contained runner
    exists; macOS native Office rendering is a separate operation.
    """
    if not isinstance(data, bytes) or not data or len(data) > MAX_PDF_BYTES:
        raise NativeTextError("native PDF must be bounded immutable bytes")
    if not isinstance(authored, list) or not 1 <= len(authored) <= MAX_PAGES:
        raise NativeTextError("authored page collection exceeds bounds")
    boxes = total_text = 0
    for page in authored:
        if not isinstance(page, list) or not 1 <= len(page) <= MAX_BOXES:
            raise NativeTextError("authored frame collection exceeds bounds")
        boxes += len(page)
        if boxes > MAX_BOXES:
            raise NativeTextError("aggregate authored frames exceed bounds")
        for frame in page:
            if not isinstance(frame, dict) or set(frame) != {"name", "text", "singleLine", "bbox"}:
                raise NativeTextError("authored frame schema is invalid")
            if not isinstance(frame["name"], str) or not 0 < len(frame["name"]) <= 256:
                raise NativeTextError("authored frame name exceeds bounds")
            _text(frame["text"])
            total_text += len(frame["text"].encode("utf-8"))
            if total_text > MAX_AUTHORED_BYTES:
                raise NativeTextError("aggregate authored text exceeds byte bounds")
            if not isinstance(frame["singleLine"], bool) or not isinstance(frame["bbox"], (list, tuple)) or len(frame["bbox"]) != 4:
                raise NativeTextError("authored frame geometry is incomplete")
            for coordinate in frame["bbox"]:
                _number(coordinate)
    if not .001 <= _number(timeout) <= 120:
        raise NativeTextError("native parser deadline exceeds bounds")
    executable = Path(python_executable)
    if not executable.is_absolute() or not executable.is_file():
        raise NativeTextError("native parser requires an explicit trusted Python executable")
    parser_policy = _parser_policy(parser_identity)
    try:
        header = json.dumps({"authored": authored, "pdf_sha256": hashlib.sha256(data).hexdigest(),
                             "parser_identity": parser_identity},
                            ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise NativeTextError("native authoring request is invalid") from exc
    if len(header) > MAX_REQUEST_JSON:
        raise NativeTextError("native authoring request exceeds byte bounds")
    _require_memory_contained_worker_platform()
    # Only this reviewed script is executed. -I ignores user imports/PYTHONPATH.
    script = Path(__file__).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="native-pptx-worker-") as directory:
        request = Path(directory) / "request.bin"
        result = Path(directory) / "result.json"
        with request.open("xb") as stream:
            stream.write(struct.pack("!I", len(header))); stream.write(header); stream.write(data)
        with request.open("rb") as incoming, result.open("x+b") as outgoing:
            environment = {"PATH": str(executable.parent)}
            if os.name == "nt":
                # Windows needs its system directory to resolve native DLLs.
                for key in ("SystemRoot", "WINDIR"):
                    if key in os.environ:
                        environment[key] = os.environ[key]
            process = subprocess.Popen([str(executable), "-I", "-B", str(script), "--worker"],
                                       stdin=incoming, stdout=outgoing, stderr=subprocess.DEVNULL,
                                       cwd=directory, env=environment,
                                       start_new_session=os.name == "posix")
            deadline = time.monotonic() + timeout
            try:
                while process.poll() is None:
                    if os.fstat(outgoing.fileno()).st_size > MAX_RESULT_BYTES:
                        raise NativeTextError("native parser output exceeds byte bounds")
                    if time.monotonic() >= deadline:
                        raise NativeTextError("native parser deadline expired")
                    time.sleep(min(.02, max(0, deadline - time.monotonic())))
                if process.returncode != 0:
                    raise NativeTextError("native parser rejected the request")
                if not 0 < os.fstat(outgoing.fileno()).st_size <= MAX_RESULT_BYTES:
                    raise NativeTextError("native parser output is missing or exceeds bounds")
                outgoing.seek(0); raw = outgoing.read(MAX_RESULT_BYTES + 1)
            finally:
                if process.poll() is None:
                    if os.name == "posix":
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass  # The owned worker exited between poll and kill.
                    else:
                        process.kill()
                process.wait()  # Reap the exact owned process before stage cleanup.
    try:
        measured = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise NativeTextError("native parser output is malformed") from exc
    if not isinstance(measured, dict) or set(measured) != {"pdf_sha256", "request_sha256", "parser_identity_sha256", "pages"}:
        raise NativeTextError("native parser output schema is invalid")
    if measured["pdf_sha256"] != hashlib.sha256(data).hexdigest() or measured["request_sha256"] != hashlib.sha256(header).hexdigest():
        raise NativeTextError("native parser output is not bound to the request")
    if measured["parser_identity_sha256"] != hashlib.sha256(parser_policy).hexdigest():
        raise NativeTextError("native parser output is not bound to approved parser identity")
    pages = measured["pages"]
    if not isinstance(pages, list) or len(pages) != len(authored):
        raise NativeTextError("native parser page evidence is incomplete")
    for observed, expected in zip(pages, authored):
        if not isinstance(observed, list) or not isinstance(expected, list) or len(observed) != len(expected):
            raise NativeTextError("native parser frame evidence is incomplete")
        for item, frame in zip(observed, expected):
            if not isinstance(item, dict) or set(item) != {"name", "minimum_font_pt", "line_count"} or item["name"] != frame.get("name"):
                raise NativeTextError("native parser frame binding is invalid")
            if _number(item["minimum_font_pt"]) < 16 - FONT_FLOAT_TOLERANCE_PT or type(item["line_count"]) is not int or not 1 <= item["line_count"] <= MAX_CHARACTERS:
                raise NativeTextError("native parser frame measurement is invalid")
            if frame.get("singleLine") and item["line_count"] != 1:
                raise NativeTextError("native title wraps unexpectedly")
    return measured


def _worker() -> None:
    _require_memory_contained_worker_platform()
    windows_job = None
    if os.name == "nt":
        windows_job = _enter_windows_parser_job()
    if os.name == "posix":
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (MAX_WORKER_CPU_SECONDS, MAX_WORKER_CPU_SECONDS))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_PARSER_FILE_BYTES, MAX_PARSER_FILE_BYTES))
        if sys.platform.startswith("linux"):
            resource.setrlimit(resource.RLIMIT_AS, (MAX_WORKER_MEMORY_BYTES, MAX_WORKER_MEMORY_BYTES))
            if resource.getrlimit(resource.RLIMIT_AS) != (MAX_WORKER_MEMORY_BYTES, MAX_WORKER_MEMORY_BYTES):
                raise NativeTextError("native worker memory-limit readback differs from requested bounds")
    prefix = sys.stdin.buffer.read(4)
    if len(prefix) != 4:
        raise NativeTextError("native request header is missing")
    size = struct.unpack("!I", prefix)[0]
    if not 0 < size <= MAX_REQUEST_JSON:
        raise NativeTextError("native request header exceeds bounds")
    header = sys.stdin.buffer.read(size)
    if len(header) != size:
        raise NativeTextError("native request header is incomplete")
    request = json.loads(header)
    if not isinstance(request, dict) or set(request) != {"authored", "pdf_sha256", "parser_identity"}:
        raise NativeTextError("native request schema is invalid")
    data = sys.stdin.buffer.read(MAX_PDF_BYTES + 1)
    if hashlib.sha256(data).hexdigest() != request["pdf_sha256"]:
        raise NativeTextError("native PDF digest does not match the request")
    authored = request["authored"]
    if not isinstance(authored, list) or not 1 <= len(authored) <= MAX_PAGES:
        raise NativeTextError("authored page collection exceeds bounds")
    stage = Path.cwd() / "verified-parser"
    stage.mkdir()
    parser_digest = _stage_parser(request["parser_identity"], stage)
    if os.name == "posix":
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_RESULT_BYTES, MAX_RESULT_BYTES))
    pages = extract_native_pdf(data)
    if len(pages) != len(authored):
        raise NativeTextError("native PDF page count differs from authoring")
    measured = [validate_native_page(page, frames) for page, frames in zip(pages, authored)]
    raw = json.dumps({"pdf_sha256": request["pdf_sha256"], "request_sha256": hashlib.sha256(header).hexdigest(),
                      "parser_identity_sha256": parser_digest,
                      "pages": measured}, allow_nan=False, separators=(",", ":")).encode("ascii")
    if len(raw) > MAX_RESULT_BYTES:
        raise NativeTextError("native parser output exceeds byte bounds")
    sys.stdout.buffer.write(raw)


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("This internal worker is not an acceptance publisher.")
    try:
        _worker()
    except Exception:
        # No PDF content, paths or native diagnostic text is echoed to callers.
        raise SystemExit(1)
