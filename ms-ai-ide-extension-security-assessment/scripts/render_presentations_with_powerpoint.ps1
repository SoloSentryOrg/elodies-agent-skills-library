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
if ((Split-Path $output -Leaf) -ne 'rendered' -or (Split-Path (Split-Path $output -Parent) -Leaf) -ne 'PowerPoint-QA') { throw 'Output must be the stable PowerPoint-QA\rendered directory.' }
$inputDirectory = Join-Path (Split-Path $output -Parent) 'input'
if ((Split-Path $input -Parent) -ne $inputDirectory -or [IO.Path]::GetExtension($input) -cne '.pptx') { throw 'Input must be a PPTX directly beneath PowerPoint-QA\input.' }
$task = Join-Path (Split-Path $output -Parent) ('.powerpoint-render-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($task) | Out-Null
$staged = Join-Path $task 'input.pptx'
$temporaryPdf = Join-Path $task 'output.pdf'
$stem = [IO.Path]::GetFileNameWithoutExtension($input) -replace '[^A-Za-z0-9._-]', '_'
$publishedPdf = Join-Path $output ($stem + '-powerpoint-full.pdf')
$powerpoint = $null
$presentation = $null
try {
    & $pythonPath $stagerPath --input $input --output $staged --expected-sha256 $ExpectedSha256 --kind pptx
    if ($LASTEXITCODE -ne 0) { throw 'Digest-bound PowerPoint staging failed.' }
    if (Test-Path -LiteralPath $publishedPdf) { throw 'PowerPoint QA output already exists.' }
    $powerpoint = New-Object -ComObject PowerPoint.Application
    $powerpoint.AutomationSecurity = 3
    $presentation = $powerpoint.Presentations.Open($staged, $true, $false, $false)
    $slideCount = $presentation.Slides.Count
    $presentation.SaveAs($temporaryPdf, 32)
    $presentation.Close()
    $presentation = $null
    [IO.File]::Move($temporaryPdf, $publishedPdf)
    [PSCustomObject]@{ Input = $input; Sha256 = $ExpectedSha256; SlideCount = $slideCount; Pdf = $publishedPdf }
}
finally {
    if ($null -ne $presentation) { try { $presentation.Close() } catch {} }
    if ($null -ne $powerpoint) { try { $powerpoint.Quit() } catch {}; [Runtime.InteropServices.Marshal]::FinalReleaseComObject($powerpoint) | Out-Null }
    if ((Split-Path $task -Parent) -eq (Split-Path $output -Parent) -and (Split-Path $task -Leaf).StartsWith('.powerpoint-render-')) { Remove-Item -LiteralPath $task -Recurse -Force -ErrorAction SilentlyContinue }
}
