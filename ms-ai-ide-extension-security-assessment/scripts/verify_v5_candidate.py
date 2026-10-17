# SPDX-License-Identifier: MIT
"""Prepare an immutable, source-bound request for native PPTX measurement.

This is a transport verifier, not a renderer, parser or acceptance publisher.
The output remains Pending and contains the authored text, so keep it private.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
from pathlib import Path

from portable_fs import is_link_or_reparse, open_exclusive_write, require_real_directory
from validate_pptx_runtime_acceptance import BOUND_FILES

SHA256 = re.compile(r"^[0-9a-f]{64}$")
LEAF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,255}$")
MAX_MANIFEST = 8 * 1024 * 1024
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
MAX_REQUEST = 12 * 1024 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _json(data: bytes) -> object:
    def reject_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON value: {value}")

    def finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("non-finite JSON number")
        return parsed

    try:
        return json.loads(data.decode("utf-8", errors="strict"),
                          object_pairs_hook=_unique, parse_constant=reject_constant,
                          parse_float=finite_float)
    except RecursionError as exc:
        raise ValueError("JSON nesting exceeds bounds") from exc


def _read(path: Path, maximum: int) -> bytes:
    parent = require_real_directory(path.parent)
    leaf_path = parent / path.name
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
        raise ValueError("secure candidate descriptor flags are unavailable")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(leaf_path, flags)
    try:
        before = os.fstat(descriptor)
        leaf_before = leaf_path.lstat()
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                                  value.st_mtime_ns, value.st_ctime_ns)
        if (not stat.S_ISREG(before.st_mode) or not stat.S_ISREG(leaf_before.st_mode)
            or is_link_or_reparse(leaf_before) or identity(before) != identity(leaf_before)
            or not 0 <= before.st_size <= maximum):
            raise ValueError("candidate file is not stable bounded regular data")
        parts: list[bytes] = []
        remaining = before.st_size
        while remaining:
            block = os.read(descriptor, min(remaining, 1024 * 1024))
            if not block:
                raise ValueError("candidate file changed while being read")
            parts.append(block)
            remaining -= len(block)
        if os.read(descriptor, 1):
            raise ValueError("candidate file grew while being read")
        after = os.fstat(descriptor)
        leaf_after = leaf_path.lstat()
        if (identity(before) != identity(after) or identity(after) != identity(leaf_after)
            or not stat.S_ISREG(leaf_after.st_mode) or is_link_or_reparse(leaf_after)):
            raise ValueError("candidate file changed while being read")
        return b"".join(parts)
    finally:
        os.close(descriptor)


def _number(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("authored geometry must be finite numeric data")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError("authored geometry exceeds numeric bounds") from exc
    if not math.isfinite(number) or abs(number) > 1_000_000_000:
        raise ValueError("authored geometry must be finite bounded data")
    return number


def _authored(authoring: object, count: int, files: set[str]) -> list[list[dict[str, object]]]:
    if (not isinstance(authoring, dict) or set(authoring) != {"schema", "unit", "canvas", "slides"}
        or authoring["schema"] != "solosentry.pptx.authoring/v1" or authoring["unit"] != "px"
        or authoring["canvas"] != [1280, 720]):
        raise ValueError("candidate authoring identity is invalid")
    slides = authoring["slides"]
    if not isinstance(slides, list) or len(slides) != count:
        raise ValueError("candidate authoring slide count differs")
    result: list[list[dict[str, object]]] = []
    total_text = total_frames = 0
    for index, slide in enumerate(slides, 1):
        if (not isinstance(slide, dict) or set(slide) != {"slide", "layout", "authored"}
            or type(slide["slide"]) is not int or slide["slide"] != index
            or slide["layout"] != f"slide-{index:02d}.layout.json"
            or slide["layout"] not in files):
            raise ValueError("candidate authoring slide identity is invalid")
        frames = slide["authored"]
        if not isinstance(frames, list) or not 1 <= len(frames) <= 4096:
            raise ValueError("candidate authored frames are missing or unbounded")
        names: set[str] = set()
        for frame in frames:
            if (not isinstance(frame, dict) or set(frame) != {"name", "text", "singleLine", "bbox"}
                or not isinstance(frame["name"], str) or not 0 < len(frame["name"]) <= 256
                or frame["name"] in names or not isinstance(frame["text"], str)
                or not frame["text"].strip() or type(frame["singleLine"]) is not bool):
                raise ValueError("candidate authored frame is invalid")
            names.add(frame["name"])
            text_bytes = len(frame["text"].encode("utf-8"))
            total_text += text_bytes
            if text_bytes > 65536 or total_text > 8 * 1024 * 1024:
                raise ValueError("candidate authored text exceeds bounds")
            box = frame["bbox"]
            if not isinstance(box, list) or len(box) != 4:
                raise ValueError("candidate authored frame lacks geometry")
            left, top, width, height = map(_number, box)
            if left < 0 or top < 0 or width <= 0 or height <= 0 or left + width > 1280 or top + height > 720:
                raise ValueError("candidate authored frame exceeds canvas")
        total_frames += len(frames)
        if total_frames > 4096:
            raise ValueError("candidate authored frame collection exceeds bounds")
        result.append(frames)
    return result


def _layout(layout: object, frames: list[dict[str, object]]) -> None:
    if (not isinstance(layout, dict) or layout.get("schema") != "openai.presentation.layout/v5"
        or layout.get("unit") != "px" or not isinstance(layout.get("slide"), dict)
        or not isinstance(layout["slide"].get("position"), dict)
        or not isinstance(layout.get("elements"), list) or not layout["elements"]
        or not isinstance(layout.get("inheritedLayers"), list)
        or len(layout["inheritedLayers"]) > 8):
        raise ValueError("candidate structural layout identity is invalid")
    canvas = layout["slide"]["position"]
    if [_number(canvas.get(key)) for key in ("left", "top", "width", "height")] != [0, 0, 1280, 720]:
        raise ValueError("candidate structural canvas is invalid")
    expected = {frame["name"]: frame for frame in frames}
    seen: set[str] = set()
    layers = [{"scope": "slide", "elements": layout["elements"]}, *layout["inheritedLayers"]]
    count = 0
    for layer in layers:
        if (not isinstance(layer, dict) or layer.get("scope") not in {"slide", "layout", "master"}
            or (layer is not layers[0] and layer["scope"] == "slide")
            or not isinstance(layer.get("elements"), list)):
            raise ValueError("candidate inherited structural layer is invalid")
        count += len(layer["elements"])
        if count > 4096:
            raise ValueError("candidate structural elements exceed bounds")
        for element in layer["elements"]:
            if (not isinstance(element, dict) or not isinstance(element.get("position"), dict)
                or element.get("scope") != layer["scope"] or not isinstance(element.get("kind"), str)
                or not element["kind"] or "elements" in element or "children" in element):
                raise ValueError("candidate structural element is incomplete")
            box = [_number(element["position"].get(key)) for key in ("left", "top", "width", "height")]
            left, top, width, height = box
            if (width < 0 or height < 0 or left < -0.5 or top < -0.5
                or left + width > 1280.5 or top + height > 720.5):
                raise ValueError("candidate structural element exceeds canvas")
            name = element.get("name")
            frame = expected.get(name) if isinstance(name, str) else None
            if frame is not None:
                if (layer["scope"] != "slide" or element["kind"] != "textbox"
                    or element.get("editable") is not True or name in seen
                    or element.get("text") != frame["text"]
                    or any(abs(a - _number(b)) > 0.000001 for a, b in zip(box, frame["bbox"]))):
                    raise ValueError("candidate layout differs from authored text")
                seen.add(name)
            elif element["kind"] == "textbox" or ("text" in element
                and (not isinstance(element["text"], str) or element["text"].strip())):
                raise ValueError("candidate layout contains unbound text")
    if seen != set(expected):
        raise ValueError("candidate layout is missing authored text")


def prepare(root: Path, candidate_dir: Path) -> dict[str, object]:
    root = require_real_directory(root)
    directory = require_real_directory(candidate_dir)
    before = directory.lstat()
    if os.name != "posix" or (before.st_mode & 0o777) != 0o700:
        raise ValueError("private candidate requires a POSIX 0700 directory")
    manifest_bytes = _read(directory / "candidate.json", MAX_MANIFEST)
    candidate = _json(manifest_bytes)
    expected = {"schema", "status", "nativeMeasurementsRequired", "native_powerpoint_closeout",
                "human_acceptance", "slide_count", "layout_schema", "inputs", "runtime",
                "candidate_pptx_sha256", "source_bindings", "files"}
    if (not isinstance(candidate, dict) or set(candidate) != expected
        or candidate["schema"] != "solosentry.pptx.v5-candidate/v1"
        or candidate["status"] != "Pending native measurement"
        or candidate["nativeMeasurementsRequired"] is not True
        or candidate["native_powerpoint_closeout"] != "Pending"
        or candidate["human_acceptance"] != "Pending"
        or candidate["layout_schema"] != "openai.presentation.layout/v5"
        or type(candidate["slide_count"]) is not int or not 1 <= candidate["slide_count"] <= 100
        or not isinstance(candidate["inputs"], dict)):
        raise ValueError("candidate manifest identity or pending state is invalid")
    runtime = candidate["runtime"]
    if (not isinstance(runtime, dict) or set(runtime) != {"node", "artifact_tool", "artifact_runtime_receipt_sha256"}
        or not isinstance(runtime["node"], str) or not isinstance(runtime["artifact_tool"], str)
        or not SHA256.fullmatch(str(runtime["artifact_runtime_receipt_sha256"]))):
        raise ValueError("candidate runtime identity is invalid")
    bindings = candidate["source_bindings"]
    if not isinstance(bindings, dict) or set(bindings) != set(BOUND_FILES):
        raise ValueError("candidate source bindings are incomplete")
    for relative in BOUND_FILES:
        digest = bindings[relative]
        if (not isinstance(digest, str) or not SHA256.fullmatch(digest)
            or _sha(_read(root / relative, MAX_FILE)) != digest):
            raise ValueError(f"candidate source binding is stale: {relative}")
    declared = candidate["files"]
    if not isinstance(declared, list) or not 1 <= len(declared) <= 256:
        raise ValueError("candidate file inventory is invalid")
    files: dict[str, bytes] = {}
    total = 0
    for item in declared:
        if (not isinstance(item, dict) or set(item) != {"file", "size", "sha256"}
            or not isinstance(item["file"], str) or not LEAF.fullmatch(item["file"])
            or item["file"] in files or type(item["size"]) is not int
            or not 1 <= item["size"] <= MAX_FILE
            or not isinstance(item["sha256"], str) or not SHA256.fullmatch(item["sha256"])):
            raise ValueError("candidate file binding is invalid")
        data = _read(directory / item["file"], MAX_FILE)
        if len(data) != item["size"] or _sha(data) != item["sha256"]:
            raise ValueError("candidate file differs from its binding")
        files[item["file"]] = data
        total += len(data)
        if total > MAX_TOTAL:
            raise ValueError("candidate file collection exceeds aggregate bounds")
    required = {"candidate.pptx", "authoring.json", "artifact-runtime-receipt.json"}
    required.update(f"slide-{index:02d}.layout.json" for index in range(1, candidate["slide_count"] + 1))
    if (not required <= set(files)
        or list(files) != sorted(files)
        or set(directory.iterdir()) != {directory / name for name in files} | {directory / "candidate.json"}):
        raise ValueError("candidate directory inventory is incomplete or unexpected")
    if (candidate["candidate_pptx_sha256"] != _sha(files["candidate.pptx"])
        or runtime["artifact_runtime_receipt_sha256"] != _sha(files["artifact-runtime-receipt.json"])):
        raise ValueError("candidate output or runtime receipt digest differs")
    authored = _authored(_json(files["authoring.json"]), candidate["slide_count"], set(files))
    for index, frames in enumerate(authored, 1):
        layout = _json(files[f"slide-{index:02d}.layout.json"])
        _layout(layout, frames)
    after = directory.lstat()
    if (before.st_dev, before.st_ino, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_mtime_ns):
        raise ValueError("candidate directory changed during verification")
    return {"schema": "solosentry.pptx.native-measurement-request/v1",
            "status": "Pending native rendering",
            "candidate_manifest_sha256": _sha(manifest_bytes),
            "candidate_pptx_sha256": _sha(files["candidate.pptx"]),
            "authoring_sha256": _sha(files["authoring.json"]),
            "artifact_runtime_receipt_sha256": runtime["artifact_runtime_receipt_sha256"],
            "source_bindings": bindings, "slide_count": candidate["slide_count"], "authored": authored}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request = prepare(args.root, args.candidate_dir)
        raw = (json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")
        if len(raw) > MAX_REQUEST:
            raise ValueError("native measurement request exceeds byte bounds")
        output = args.output.absolute()
        output_parent = require_real_directory(output.parent)
        if (output_parent.stat().st_mode & 0o777) != 0o700:
            raise ValueError("native measurement request requires a private POSIX 0700 output directory")
        if output_parent == args.candidate_dir.resolve(strict=True):
            raise ValueError("measurement request must remain outside immutable candidate directory")
        with open_exclusive_write(output, mode=0o400) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        print(f"PENDING: native measurement request {output}; sha256={_sha(raw)}")
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
