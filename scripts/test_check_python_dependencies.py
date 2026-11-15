#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fail-closed tests for the complete hash-lock OSV gate."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("python_dependency_gate", Path(__file__).with_name("check-python-dependencies.py"))
M = importlib.util.module_from_spec(SPEC)
if SPEC.loader is None:
    raise RuntimeError("dependency gate loader unavailable")
SPEC.loader.exec_module(M)
H = "a" * 64

def pin(name="Pillow", version="13.0.0"):
    return f"{name}=={version} \\\n    --hash=sha256:{H}\n".encode()

class DependencyGateTests(unittest.TestCase):
    def test_complete_hash_locked_records_and_cross_lock_versions(self):
        a = M.parse_lock(pin() + b"# comment\n" + pin("rpds-py", "0.30.0"))
        b = M.parse_lock(pin("pillow") + pin("rpds-py", "0.27.0"))
        query = M.make_query({"one.lock": a, "two.lock": b})
        self.assertEqual([(x["package"]["name"], x["version"]) for x in query["queries"]], [("pillow", "13.0.0"), ("rpds-py", "0.27.0"), ("rpds-py", "0.30.0")])
        self.assertTrue(all(x["package"]["ecosystem"] == "PyPI" for x in query["queries"]))

    def test_rejects_partial_unpinned_and_hostile_lock_forms(self):
        for value in [b"", b"# only a comment\n", b"Pillow>=13\n", b"Pillow==13\n", b"-r other.lock\n", b"--index-url https://evil.invalid\n", pin()+pin("pillow"), pin()+b"dangling \\\n", pin()+b"x==1 --hash=sha256:no\n", b"Pillow @ https://evil.invalid/a.whl\n", b"Pillow==13; os_name == 'nt' --hash=sha256:"+H.encode(), b"x==1 --hash=sha256:"+H.encode()+b" --hash=sha256:"+H.encode(), b"\xff", b"x"*(M.MAX_LOCK_BYTES+1)]:
            with self.subTest(value=value[:80]), self.assertRaises(M.GateError):
                M.parse_lock(value)

    def test_invalid_normalised_versions_and_names_cannot_look_clean(self):
        for name, version in [("package.", "1.0"), ("package-", "1.0"), ("package", "1..0"), ("package", "1!2!3"), ("package", "1+"), ("package", "1___a")]:
            with self.subTest(name=name, version=version), self.assertRaises(M.GateError):
                M.parse_lock(pin(name, version))

    def test_normalised_release_prerelease_epoch_and_local_versions(self):
        for version in ["1.0", "1.2rc1", "1.2.dev0", "1!2.0.post1+local.1"]:
            with self.subTest(version=version):
                M.parse_lock(pin("a", version))

    def test_real_repository_locks_include_every_version(self):
        locks = M.load_locks(Path(__file__).resolve().parents[1])
        query = M.make_query(locks)
        pairs = {(x["package"]["name"], x["version"]) for x in query["queries"]}
        self.assertEqual(len(pairs), 13)
        self.assertIn(("pypdfium2", "5.14.0"), pairs)
        self.assertIn(("pillow", "13.0.0"), pairs)
        self.assertIn(("lxml", "6.1.3"), pairs)
        self.assertIn(("rpds-py", "2026.6.3"), pairs)
        self.assertIn(("rpds-py", "0.30.0"), pairs)

    def test_response_requires_exact_cardinality_and_typed_collections(self):
        self.assertEqual(M.findings(b'{"results":[{}, {"vulns":[]}]}', 2), [])
        for value in [b"", b"null", b"[]", b"{}", b'{"results":[]}', b'{"results":[{}]}', b'{"results":[{}, {}, {}]}', b'{"results":[{}, null]}', b'{"results":[{}, {"error":"failed"}]}', b'{"results":[{}, {"vulns":null}]}', b'{"results":[{}, {"vulns":false}]}', b'{"results":[{}, {"vulns":{}}]}', b'{"results":[{}, {"vulns":0}]}', b'{"results":[{}, {"vulns":[{}]}]}', b'{"results":[{}, {"vulns":["GHSA"]}]}', b'{"results":[],"error":"failed"}', b" "*(M.MAX_RESPONSE_BYTES+1)]:
            with self.subTest(value=value[:100]), self.assertRaises(M.GateError):
                M.findings(value, 2)

    def test_findings_are_retained_and_block_even_with_fixed_event(self):
        raw = json.dumps({"results":[{"vulns":[{"id":"GHSA-vfmq-68hx-4jfw","modified":"2026-09-03T00:00:00Z"}]}]}).encode()
        self.assertEqual(M.findings(raw, 1), [{"query_index":0,"id":"GHSA-vfmq-68hx-4jfw"}])
        with tempfile.TemporaryDirectory() as d, mock.patch.object(M, "fetch", return_value=raw):
            self.assertEqual(M.scan({"one.lock":M.parse_lock(pin())}, Path(d)/"evidence"), 1)
            self.assertEqual((Path(d)/"evidence/response.json").read_bytes(), raw)

    def test_duplicate_keys_and_paginated_results_never_establish_clearance(self):
        for raw in [b'{"results":[{}],"results":[{}]}', b'{"results":[{"vulns":[],"vulns":[]}]}', b'{"results":[{"vulns":[],"next_page_token":"unseen"}]}']:
            with self.subTest(raw=raw), self.assertRaises(M.GateError):
                M.findings(raw, 1)

    def test_transport_is_single_bounded_https_request_without_credentials(self):
        query=M.make_query({"one":M.parse_lock(pin())})
        response=mock.MagicMock()
        response.__enter__.return_value=response
        response.status=200
        response.geturl.return_value=M.ENDPOINT
        response.read.return_value=b'{"results":[{}]}'
        opener=mock.Mock()
        opener.open.return_value=response
        with mock.patch.object(M.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(M.fetch(query), b'{"results":[{}]}')
        opener.open.assert_called_once()
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.osv.dev/v1/querybatch")
        self.assertEqual(request.get_method(), "POST")
        self.assertFalse(request.has_header("Authorization"))
        self.assertEqual(json.loads(request.data), query)
        self.assertEqual(opener.open.call_args.kwargs, {"timeout":25})
        response.read.assert_called_once_with(M.MAX_RESPONSE_BYTES+1)

    def test_redirects_oversized_wrong_identity_and_http_failure_reject(self):
        with self.assertRaises(M.GateError):
            M._NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil.invalid")
        for status,url,data in [(200,M.ENDPOINT,b"x"*(M.MAX_RESPONSE_BYTES+1)),(201,M.ENDPOINT,b"{}"),(200,"https://evil.invalid",b"{}")]:
            response=mock.MagicMock();response.__enter__.return_value=response
            response.status=status;response.geturl.return_value=url;response.read.return_value=data
            opener=mock.Mock();opener.open.return_value=response
            with self.subTest(status=status,url=url), mock.patch.object(M.urllib.request, "build_opener", return_value=opener), self.assertRaises(M.GateError):
                M.fetch({"queries":[]})
            opener.open.assert_called_once()
        opener=mock.Mock();opener.open.side_effect=M.urllib.error.URLError("unavailable")
        with mock.patch.object(M.urllib.request,"build_opener",return_value=opener),self.assertRaises(M.GateError):
            M.fetch({"queries":[]})
        opener.open.assert_called_once()

    def test_transport_error_remains_distinct_and_preserves_request(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(M, "fetch", side_effect=M.GateError("timeout")):
            with self.assertRaises(M.GateError):
                M.scan({"one.lock":M.parse_lock(pin())}, Path(d)/"evidence")
            self.assertTrue((Path(d)/"evidence/query.json").is_file())
            self.assertFalse((Path(d)/"evidence/response.json").exists())

    def test_evidence_is_exclusive_and_retains_lock_query_response_hashes(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(M, "fetch", return_value=b'{"results":[{}]}'):
            output=Path(d)/"evidence"
            self.assertEqual(M.scan({"one.lock":M.parse_lock(pin())}, output), 0)
            result=json.loads((output/"receipt.json").read_text())
            self.assertEqual(result["query_count"], 1)
            self.assertEqual(result["findings"], [])
            self.assertEqual(len(result["query_sha256"]), 64)
            self.assertEqual(len(result["response_sha256"]), 64)
            with self.assertRaises((M.GateError, OSError)):
                M.scan({"one.lock":M.parse_lock(pin())}, output)

    def test_missing_and_symlink_locks_reject(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with self.assertRaises((M.GateError, OSError)):
                M.load_locks(root)
            for rel in M.LOCK_FILES:
                p=root/rel;p.parent.mkdir(parents=True, exist_ok=True);p.write_bytes(pin())
            first=root/M.LOCK_FILES[0];first.unlink();first.symlink_to(root/M.LOCK_FILES[1])
            with self.assertRaises((M.GateError, OSError, ValueError)):
                M.load_locks(root)

if __name__ == "__main__":
    unittest.main()
