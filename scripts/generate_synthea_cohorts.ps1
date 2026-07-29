param(
    [string]$Root = "data/synthea",
    [string]$Checkout = "",
    [switch]$Replace
)

$ErrorActionPreference = "Stop"

$cohorts = @(
    @{ Label = "cohort_a"; Profile = "synthea-us-small-v1" },
    @{ Label = "cohort_b"; Profile = "synthea-us-small-cohort-b-v1" }
)

foreach ($cohort in $cohorts) {
    $workspace = Join-Path $Root $cohort.Profile
    $generateArgs = @(
        "generate",
        $cohort.Profile,
        "--workspace", $workspace
    )
    if ($Checkout) {
        $generateArgs += @("--checkout", $Checkout)
    }
    if ($Replace) {
        $generateArgs += "--replace"
    }
    & clinical-data-cohort @generateArgs

    $csvDirectory = Join-Path $workspace "generated/csv"
    $normalizedDirectory = Join-Path $workspace "normalized"
    $generationManifest = Join-Path $workspace "synthea-generation-manifest.json"
    $adaptArgs = @(
        "adapt",
        $cohort.Profile,
        $csvDirectory,
        "--output-dir", $normalizedDirectory,
        "--generation-manifest", $generationManifest
    )
    if ($Replace) {
        $adaptArgs += "--replace"
    }
    & clinical-data-cohort @adaptArgs
    clinical-data-cohort verify $cohort.Profile $normalizedDirectory
}

$cohortADirectory = Join-Path $Root "synthea-us-small-v1/normalized"
$cohortBDirectory = Join-Path $Root "synthea-us-small-cohort-b-v1/normalized"
$comparisonDirectory = Join-Path $Root "cohort-comparison"
$compareArgs = @(
    "compare",
    $cohortADirectory,
    $cohortBDirectory,
    "--output-dir", $comparisonDirectory
)
if ($Replace) {
    $compareArgs += "--replace"
}
& clinical-data-cohort @compareArgs

Write-Host "Two verified disjoint Synthea cohorts are ready under $Root"
