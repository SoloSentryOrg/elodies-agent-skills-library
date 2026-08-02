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
try {
    & $pythonPath $stagerPath --input $input --output $staged --expected-sha256 $ExpectedSha256 --kind docx
    if ($LASTEXITCODE -ne 0) { throw 'Digest-bound Word staging failed.' }
    if (Test-Path -LiteralPath $publishedPdf) { throw 'Word QA output already exists.' }
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3
    $document = $word.Documents.Open($staged, $false, $true, $false)
    $tablesOfContents = $document.TablesOfContents
    try {
        for ($index = 1; $index -le $tablesOfContents.Count; $index++) {
            $tableOfContents = $tablesOfContents.Item($index)
            try {
                $tableOfContents.Update() | Out-Null
                $tableOfContents.UpdatePageNumbers() | Out-Null
            }
            finally {
                [Runtime.InteropServices.Marshal]::FinalReleaseComObject($tableOfContents) | Out-Null
            }
        }
    }
    finally {
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($tablesOfContents) | Out-Null
    }
    $pageCount = $document.ComputeStatistics(2)
    $document.ExportAsFixedFormat($temporaryPdf, 17)
    $document.Close(0)
    $document = $null
    [IO.File]::Move($temporaryPdf, $publishedPdf)
    [PSCustomObject]@{ Input = $input; Sha256 = $ExpectedSha256; PageCount = $pageCount; Pdf = $publishedPdf }
}
finally {
    if ($null -ne $document) { try { $document.Close(0) } catch {} }
    if ($null -ne $word) { try { $word.Quit() } catch {}; [Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) | Out-Null }
    if ((Split-Path $task -Parent) -eq (Split-Path $output -Parent) -and (Split-Path $task -Leaf).StartsWith('.word-render-')) { Remove-Item -LiteralPath $task -Recurse -Force -ErrorAction SilentlyContinue }
}
