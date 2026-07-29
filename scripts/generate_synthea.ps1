param(
    [string]$Workspace = "data/synthea/synthea-us-small-v1",
    [string]$Checkout = "",
    [switch]$Replace
)

$ErrorActionPreference = "Stop"

$generateArgs = @(
    "synthea-generate",
    "--workspace", $Workspace
)
if ($Checkout) {
    $generateArgs += @("--checkout", $Checkout)
}
if ($Replace) {
    $generateArgs += "--replace"
}

clinical-data synthea-profile
& clinical-data @generateArgs

$csvDirectory = Join-Path $Workspace "generated/csv"
$normalizedDirectory = Join-Path $Workspace "normalized"
$generationManifest = Join-Path $Workspace "synthea-generation-manifest.json"

$adaptArgs = @(
    "synthea-adapt",
    $csvDirectory,
    "--output-dir", $normalizedDirectory,
    "--generation-manifest", $generationManifest
)
if ($Replace) {
    $adaptArgs += "--replace"
}

& clinical-data @adaptArgs
clinical-data synthea-verify $normalizedDirectory

Write-Host "Reproducible Synthea dataset ready at $normalizedDirectory"
