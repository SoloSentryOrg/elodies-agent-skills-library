#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise adapter ownership boundaries without native Office acceptance."""

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell"), "PowerShell is unavailable")
class PowerPointWindowsOwnershipTests(unittest.TestCase):
    def test_adapter_never_quits_shared_application_and_preserves_uncertain_input(self):
        driver = r'''
param($Adapter, $Root, $Python, $Stager, $Mode, $Digest, $AppKind)
$global:closeCount = 0; $global:quitCount = 0; $global:mode = $Mode
$global:appKind = $AppKind
$qaName = if ($AppKind -eq 'word') { 'Word-QA' } else { 'PowerPoint-QA' }
$extension = if ($AppKind -eq 'word') { '.docx' } else { '.pptx' }
$doc = [PSCustomObject]@{ FullName = ''; Slides = [PSCustomObject]@{ Count = 1 }; TablesOfContents = [PSCustomObject]@{ Count = 0 } }
$doc | Add-Member ScriptMethod Close { $global:closeCount++; if ($global:mode -eq 'close-failure') { throw 'fixture close failure' } }
$doc | Add-Member ScriptMethod ComputeStatistics { param($Kind); return 1 }
$doc | Add-Member ScriptMethod ExportAsFixedFormat { param($Path, $Format, $Intent, $Frame, $Order, $Output, $Hidden, $Range); if ($Format -ne $(if ($global:appKind -eq 'word') { 17 } else { 2 })) { throw 'unexpected export format' }; if ($global:mode -eq 'export-failure') { throw 'fixture export failure' }; [IO.File]::WriteAllBytes($Path, [Text.Encoding]::ASCII.GetBytes('%PDF-fixture-not-native-acceptance')) }
$global:doc = $doc
$collection = [PSCustomObject]@{}
$collection | Add-Member ScriptMethod Open { param($Path, $ReadOnly, $Untitled, $WithWindow); $global:doc.FullName = $Path; if ($global:mode -eq 'wrong-identity') { $global:doc.FullName = Join-Path (Split-Path (Split-Path $Path -Parent) -Parent) ('other/' + [IO.Path]::GetFileName($Path)) }; return $global:doc }
$global:app = [PSCustomObject]@{ AutomationSecurity = 2; Presentations = $collection; Documents = $collection; Visible = $true; DisplayAlerts = -1 }
$global:app | Add-Member ScriptMethod Quit { $global:quitCount++; throw 'unrelated user application must not quit' }
function New-Object { param([string]$ComObject); if ($ComObject -notin @('PowerPoint.Application', 'Word.Application')) { throw 'unexpected COM activation' }; return $global:app }
$failed = $false
try { & $Adapter -OutputDirectory (Join-Path $Root ($qaName + '/rendered')) -Python $Python -Stager $Stager -InputPath (Join-Path $Root ($qaName + '/input/fixture' + $extension)) -ExpectedSha256 $Digest | Out-Null }
catch { $failed = $true; [Console]::Error.WriteLine($_.Exception.Message) }
$stages = @(Get-ChildItem -LiteralPath (Join-Path $Root $qaName) -Directory -Force | Where-Object { $_.Name.StartsWith('.' + $(if ($AppKind -eq 'word') { 'word' } else { 'powerpoint' }) + '-render-') })
$outputName = if ($AppKind -eq 'word') { 'fixture-word-full.pdf' } else { 'fixture-powerpoint-full.pdf' }
[PSCustomObject]@{ failed = $failed; closeCount = $global:closeCount; quitCount = $global:quitCount; security = $global:app.AutomationSecurity; visible = $global:app.Visible; alerts = $global:app.DisplayAlerts; stageCount = $stages.Count; published = (Test-Path -LiteralPath (Join-Path $Root ($qaName + '/rendered/' + $outputName))) } | ConvertTo-Json -Compress
'''
        stager = """import argparse, pathlib, hashlib
p=argparse.ArgumentParser()
for key in ['input','output','expected-sha256','kind']: p.add_argument('--'+key, required=True)
a=p.parse_args(); data=pathlib.Path(a.input).read_bytes()
assert hashlib.sha256(data).hexdigest()==a.expected_sha256
pathlib.Path(a.output).write_bytes(data)
"""
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory).resolve(); probe = root / "probe.ps1"; probe.write_text(driver)
            helper = root / "fixture-stager.py"; helper.write_text(stager)
            data = b"synthetic ownership fixture; not a native presentation"
            expected = {"success": (False, 1, 0, True), "wrong-identity": (True, 0, 1, False),
                        "close-failure": (True, 1, 1, False), "export-failure": (True, 1, 0, False)}
            cases = [(app, mode, values) for app in ["powerpoint", "word"] for mode, values in expected.items()]
            for app, mode, (failed, close_count, stage_count, published) in cases:
                with self.subTest(app=app, mode=mode):
                    adapter = pathlib.Path(__file__).with_name("render_reports_with_word.ps1" if app == "word" else "render_presentations_with_powerpoint.ps1")
                    qa = "Word-QA" if app == "word" else "PowerPoint-QA"; extension = ".docx" if app == "word" else ".pptx"
                    task = root / app / mode; inputs = task / qa / "input"; inputs.mkdir(parents=True)
                    (task / qa / "rendered").mkdir(); (inputs / ("fixture" + extension)).write_bytes(data)
                    result = subprocess.run([shutil.which("pwsh") or shutil.which("powershell"), "-NoProfile", "-NonInteractive", "-File", str(probe),
                                             str(adapter), str(task), sys.executable, str(helper), mode, hashlib.sha256(data).hexdigest(), app],
                                            capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    observed = json.loads(result.stdout.strip().splitlines()[-1])
                    self.assertEqual(observed, {"failed": failed, "closeCount": close_count, "quitCount": 0,
                                                "security": 2, "visible": True, "alerts": -1,
                                                "stageCount": stage_count, "published": published}, result.stderr)


@unittest.skipUnless(sys.platform == "darwin", "Mac AppleScript path semantics")
class PowerPointPathIdentityTests(unittest.TestCase):
    def test_full_path_identity_and_fail_closed_lookup(self):
        self._check_adapter("render_presentations_with_powerpoint.applescript")

    def test_word_full_path_identity_and_fail_closed_lookup(self):
        self._check_adapter("render_reports_with_word.applescript")

    def _check_adapter(self, filename):
        source = (pathlib.Path(__file__).parent / filename).read_text()
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
