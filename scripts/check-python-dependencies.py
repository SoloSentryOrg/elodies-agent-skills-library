#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Scan all three complete Python hash locks with OSV; findings and incomplete evidence block."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ms-ai-ide-extension-security-assessment" / "scripts"))
from portable_fs import bounded_read, open_exclusive_write, require_real_directory

LOCK_FILES = (
    "ms-ai-ide-extension-security-assessment/scripts/requirements.lock",
    "prepare-m365-copilot-handoff/scripts/requirements.lock",
    "ms-ai-ide-extension-security-assessment/scripts/native-pdfium-tests.lock",
)
ENDPOINT = "https://api.osv.dev/v1/querybatch"
MAX_LOCK_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_QUERIES = 128
PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][A-Za-z0-9.!+_-]*)(\s+--hash=sha256:[0-9a-f]{64})+")
NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
# Accept normalised PEP440 pins; unusual spelling fails closed for review.
NUMBER = r"(?:0|[1-9][0-9]*)"
VERSION = re.compile(
    rf"(?:{NUMBER}!)?{NUMBER}(?:\.{NUMBER})*"
    rf"(?:(?:a|b|rc){NUMBER})?(?:\.post{NUMBER})?(?:\.dev{NUMBER})?"
    r"(?:\+[a-z0-9]+(?:[._-][a-z0-9]+)*)?"
)
ADVISORY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")

class GateError(ValueError):
    """The complete dependency scan cannot establish a passing result."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def parse_lock(data: bytes) -> dict:
    if not data or len(data) > MAX_LOCK_BYTES:
        raise GateError("lock is empty or exceeds bounds")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise GateError("lock is not UTF-8") from exc
    packages = []
    seen = set()
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        continued = line.endswith("\\")
        pending += " " + (line[:-1].rstrip() if continued else line)
        if continued:
            continue
        match = PIN.fullmatch(pending.strip())
        if not match or not NAME.fullmatch(match.group(1)) or not VERSION.fullmatch(match.group(2)):
            raise GateError("lock contains an unsupported or incomplete pinned record")
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        if name in seen:
            raise GateError("lock contains a duplicate package")
        hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})", pending)
        if len(set(hashes)) != len(hashes):
            raise GateError("lock contains duplicate hashes")
        seen.add(name)
        packages.append((name, match.group(2)))
        if len(packages) > MAX_QUERIES:
            raise GateError("lock contains too many packages")
        pending = ""
    if pending or not packages:
        raise GateError("lock is incomplete or contains no package records")
    return {"sha256": _digest(data), "packages": packages}


def load_locks(root: Path) -> dict:
    root = require_real_directory(root)
    return {relative: parse_lock(bounded_read(root / relative, MAX_LOCK_BYTES)[0])
            for relative in LOCK_FILES}


def make_query(locks: dict) -> dict:
    pairs = sorted({tuple(pair) for lock in locks.values() for pair in lock["packages"]})
    if not pairs or len(pairs) > MAX_QUERIES:
        raise GateError("query count is outside the complete-scan bound")
    return {"queries": [{"package": {"name": name, "ecosystem": "PyPI"}, "version": version}
                        for name, version in pairs]}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GateError("OSV redirects are not accepted")


def fetch(query: dict) -> bytes:
    request = urllib.request.Request(ENDPOINT, data=_encoded(query),
        headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    opener = urllib.request.build_opener(_NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=25) as response:
            if response.status != 200 or response.geturl() != ENDPOINT:
                raise GateError("OSV response identity is invalid")
            data = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise GateError("OSV transport failed; no clean result established") from exc
    if len(data) > MAX_RESPONSE_BYTES:
        raise GateError("OSV response exceeds bounds")
    return data


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GateError("OSV response contains duplicate keys")
        result[key] = value
    return result


def findings(data: bytes, expected: int) -> list[dict]:
    if not data or len(data) > MAX_RESPONSE_BYTES:
        raise GateError("OSV response is empty or exceeds bounds")
    try:
        payload = json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise GateError("OSV response is not bounded valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"results"}:
        raise GateError("OSV response does not contain the complete result set")
    results = payload["results"]
    if not isinstance(results, list) or len(results) != expected:
        raise GateError("OSV response cardinality differs from query")
    found = []
    for index, entry in enumerate(results):
        if not isinstance(entry, dict) or set(entry) - {"vulns"}:
            raise GateError("OSV query result is malformed or incomplete")
        vulns = entry.get("vulns", [])
        if not isinstance(vulns, list):
            raise GateError("OSV vulnerability collection is not an array")
        for vuln in vulns:
            if (not isinstance(vuln, dict) or not isinstance(vuln.get("id"), str)
                    or not ADVISORY_ID.fullmatch(vuln["id"])):
                raise GateError("OSV vulnerability record lacks a valid identifier")
            found.append({"query_index": index, "id": vuln["id"]})
    return found


def _write(path: Path, data: bytes) -> None:
    with open_exclusive_write(path) as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def scan(locks: dict, output: Path) -> int:
    query = make_query(locks)
    # Exclusive evidence root: no overwrite, symlink or partial old run reuse.
    parent = require_real_directory(output.absolute().parent)
    output = parent / output.name
    output.mkdir(mode=0o700)
    output = require_real_directory(output)
    request_bytes = _encoded(query)
    _write(output / "query.json", request_bytes)
    raw = fetch(query)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise GateError("OSV response exceeds bounds")
    _write(output / "response.json", raw)
    found = findings(raw, len(query["queries"]))
    receipt = {"schema_version": 1, "endpoint": ENDPOINT,
        "locks": {name: {"sha256": lock["sha256"], "package_count": len(lock["packages"])}
                  for name, lock in locks.items()},
        "query_count": len(query["queries"]), "query_sha256": _digest(request_bytes),
        "response_sha256": _digest(raw), "findings": found,
        "result": "findings" if found else "clear"}
    _write(output / "receipt.json", _encoded(receipt))
    print(f"OSV: {len(query['queries'])} package/version queries, {len(found)} advisory records")
    return 1 if found else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        return scan(load_locks(args.repository_root), args.output)
    except (GateError, OSError, ValueError) as exc:
        # No response bodies, credentials, environment or unaudited errors logged.
        print(f"Dependency gate blocked: {type(exc).__name__}; no complete clean result", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
