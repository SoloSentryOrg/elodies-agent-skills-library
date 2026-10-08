# SPDX-License-Identifier: MIT
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$Stager,
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSha256
)

$ErrorActionPreference = 'Stop'
function Test-OwnedWordDocument {
    param($Document, [string]$StagedPath)
    try {
        $fullName = [string]$Document.FullName
        if ([string]::IsNullOrWhiteSpace($fullName) -or -not [IO.Path]::IsPathRooted($fullName)) { return $false }
        return [string]::Equals([IO.Path]::GetFullPath($fullName), [IO.Path]::GetFullPath($StagedPath), [StringComparison]::OrdinalIgnoreCase)
    }
    catch { return $false }
}

$output = (Resolve-Path -LiteralPath $OutputDirectory).Path
$input = (Resolve-Path -LiteralPath $InputPath).Path
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$stagerPath = (Resolve-Path -LiteralPath $Stager).Path
if ((Split-Path $output -Leaf) -ne 'rendered' -or (Split-Path (Split-Path $output -Parent) -Leaf) -ne 'Word-QA') { throw 'Output must be the stable Word-QA\rendered directory.' }
$inputDirectory = Join-Path (Split-Path $output -Parent) 'input'
if ((Split-Path $input -Parent) -ne $inputDirectory -or [IO.Path]::GetExtension($input) -cne '.docx') { throw 'Input must be a DOCX directly beneath Word-QA\input.' }
$task = Join-Path (Split-Path $output -Parent) ('.word-render-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($task) | Out-Null
$staged = Join-Path $task 'input.docx'
$temporaryPdf = Join-Path $task 'output.pdf'
$stem = [IO.Path]::GetFileNameWithoutExtension($input) -replace '[^A-Za-z0-9._-]', '_'
$publishedPdf = Join-Path $output ($stem + '-word-full.pdf')
$word = $null
$document = $null
$openAttempted = $false
$identified = $false
$closeAttempted = $false
$closed = $false
$previousSecurity = $null
$previousVisible = $null
$previousAlerts = $null
try {
    & $pythonPath $stagerPath --input $input --output $staged --expected-sha256 $ExpectedSha256 --kind docx
    if ($LASTEXITCODE -ne 0) { throw 'Digest-bound Word staging failed.' }
    if (Test-Path -LiteralPath $publishedPdf) { throw 'Word QA output already exists.' }
    $word = New-Object -ComObject Word.Application
    $previousSecurity = $word.AutomationSecurity
    $previousVisible = $word.Visible
    $previousAlerts = $word.DisplayAlerts
    if ($previousSecurity -notin @(1, 2, 3) -or $previousAlerts -notin @(-2, -1, 0) -or $null -eq $previousVisible) { throw 'Word automation state is unavailable.' }
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3
    $openAttempted = $true
    $document = $word.Documents.Open($staged, $false, $true, $false)
    if (-not (Test-OwnedWordDocument $document $staged)) { throw 'Word did not expose the exact staged document identity.' }
    $identified = $true
    $tablesOfContents = $document.TablesOfContents
    try {
        for ($index = 1; $index -le $tablesOfContents.Count; $index++) {
            $tableOfContents = $tablesOfContents.Item($index)
            try {
                $tableOfContents.Update() | Out-Null
                $tableOfContents.UpdatePageNumbers() | Out-Null
            }
            finally {
                if ([Runtime.InteropServices.Marshal]::IsComObject($tableOfContents)) { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($tableOfContents) | Out-Null }
            }
        }
    }
    finally {
        if ([Runtime.InteropServices.Marshal]::IsComObject($tablesOfContents)) { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($tablesOfContents) | Out-Null }
    }
    $pageCount = $document.ComputeStatistics(2)
    $document.ExportAsFixedFormat($temporaryPdf, 17)
    if (-not (Test-OwnedWordDocument $document $staged)) { throw 'Word document identity changed before close.' }
    $closeAttempted = $true
    $document.Close(0)
    $closed = $true
    [IO.File]::Move($temporaryPdf, $publishedPdf)
    [PSCustomObject]@{ Input = $input; Sha256 = $ExpectedSha256; PageCount = $pageCount; Pdf = $publishedPdf }
}
finally {
    if ($identified -and -not $closeAttempted -and $null -ne $document -and (Test-OwnedWordDocument $document $staged)) {
        $closeAttempted = $true
        try { $document.Close(0); $closed = $true } catch { Write-Warning 'The staged document could not close; its private input is retained.' }
    }
    if ($null -ne $word -and $null -ne $previousSecurity) {
        try {
            if ($word.AutomationSecurity -eq 3) { $word.AutomationSecurity = $previousSecurity }
            if ($word.Visible -eq $false -and $null -ne $previousVisible) { $word.Visible = $previousVisible }
            if ($word.DisplayAlerts -eq 0 -and $null -ne $previousAlerts) { $word.DisplayAlerts = $previousAlerts }
        } catch { Write-Warning 'Word automation state could not be fully restored.' }
    }
    # COM activation does not establish exclusive ownership of a Word instance.
    foreach ($ownedReference in @($document, $word)) {
        if ($null -ne $ownedReference -and [Runtime.InteropServices.Marshal]::IsComObject($ownedReference)) {
            try { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($ownedReference) | Out-Null } catch {}
        }
    }
    if ($openAttempted -and -not $closed) { Write-Warning ('Word private staging retained for unresolved document ownership/close: ' + $task) }
    elseif ((Split-Path $task -Parent) -eq (Split-Path $output -Parent) -and (Split-Path $task -Leaf).StartsWith('.word-render-')) {
        Remove-Item -LiteralPath $task -Recurse -Force -ErrorAction SilentlyContinue
    }
}
