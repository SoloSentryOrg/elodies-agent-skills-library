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
function Test-OwnedPresentation {
    param($Presentation, [string]$StagedPath)
    try {
        $fullName = [string]$Presentation.FullName
        if ([string]::IsNullOrWhiteSpace($fullName) -or -not [IO.Path]::IsPathRooted($fullName)) { return $false }
        return [string]::Equals([IO.Path]::GetFullPath($fullName), [IO.Path]::GetFullPath($StagedPath), [StringComparison]::OrdinalIgnoreCase)
    }
    catch { return $false }
}

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
$openAttempted = $false
$identified = $false
$closeAttempted = $false
$closed = $false
$previousAutomationSecurity = $null
try {
    & $pythonPath $stagerPath --input $input --output $staged --expected-sha256 $ExpectedSha256 --kind pptx
    if ($LASTEXITCODE -ne 0) { throw 'Digest-bound PowerPoint staging failed.' }
    if (Test-Path -LiteralPath $publishedPdf) { throw 'PowerPoint QA output already exists.' }
    $powerpoint = New-Object -ComObject PowerPoint.Application
    $previousAutomationSecurity = $powerpoint.AutomationSecurity
    if ($previousAutomationSecurity -notin @(1, 2, 3)) { throw 'PowerPoint automation security state is unavailable.' }
    $powerpoint.AutomationSecurity = 3
    $openAttempted = $true
    $presentation = $powerpoint.Presentations.Open($staged, $true, $false, $false)
    if (-not (Test-OwnedPresentation $presentation $staged)) { throw 'PowerPoint did not expose the exact staged presentation identity.' }
    $identified = $true
    $slideCount = $presentation.Slides.Count
    # Export a fixed-format copy rather than saving the presentation under a
    # different name. Pass an explicit null PrintRange for the complete deck.
    $presentation.ExportAsFixedFormat($temporaryPdf, 2, 1, 0, 1, 1, 0, $null)
    if (-not (Test-OwnedPresentation $presentation $staged)) { throw 'PowerPoint presentation identity changed before close.' }
    $closeAttempted = $true
    $presentation.Close()
    $closed = $true
    [IO.File]::Move($temporaryPdf, $publishedPdf)
    [PSCustomObject]@{ Input = $input; Sha256 = $ExpectedSha256; SlideCount = $slideCount; Pdf = $publishedPdf }
}
finally {
    if ($identified -and -not $closeAttempted -and $null -ne $presentation -and (Test-OwnedPresentation $presentation $staged)) {
        $closeAttempted = $true
        try { $presentation.Close(); $closed = $true } catch { Write-Warning 'The staged presentation could not close; its private input is retained.' }
    }
    if ($null -ne $powerpoint -and $null -ne $previousAutomationSecurity) {
        try {
            if ($powerpoint.AutomationSecurity -eq 3) { $powerpoint.AutomationSecurity = $previousAutomationSecurity }
        } catch { Write-Warning 'PowerPoint automation security state could not be restored.' }
    }
    # A COM activation does not establish ownership of an application-wide
    # instance. Never quit PowerPoint or close unrelated presentations.
    foreach ($ownedReference in @($presentation, $powerpoint)) {
        if ($null -ne $ownedReference -and [Runtime.InteropServices.Marshal]::IsComObject($ownedReference)) {
            try { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($ownedReference) | Out-Null } catch {}
        }
    }
    if ($openAttempted -and -not $closed) {
        Write-Warning ('PowerPoint private staging retained for unresolved presentation ownership/close: ' + $task)
    }
    elseif ((Split-Path $task -Parent) -eq (Split-Path $output -Parent) -and (Split-Path $task -Leaf).StartsWith('.powerpoint-render-')) {
        Remove-Item -LiteralPath $task -Recurse -Force -ErrorAction SilentlyContinue
    }
}
