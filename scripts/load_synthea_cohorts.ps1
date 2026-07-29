param(
    [string]$Root = "data/synthea",
    [string]$ProcessedRoot = "data/processed/synthea-cohorts",
    [string]$RawRoot = "data/raw",
    [string]$DatabaseUrl = "",
    [switch]$BaselineExisting,
    [switch]$ReplaceComparison
)

$ErrorActionPreference = "Stop"

$cohortADirectory = Join-Path $Root "synthea-us-small-v1/normalized"
$cohortBDirectory = Join-Path $Root "synthea-us-small-cohort-b-v1/normalized"
$comparisonDirectory = Join-Path $Root "cohort-comparison"

$arguments = @(
    "load-pair",
    $cohortADirectory,
    $cohortBDirectory,
    "--processed-root", $ProcessedRoot,
    "--raw-root", $RawRoot,
    "--output-dir", $comparisonDirectory
)
if ($DatabaseUrl) {
    $arguments += @("--database-url", $DatabaseUrl)
}
if ($BaselineExisting) {
    $arguments += "--baseline-existing"
}
if ($ReplaceComparison) {
    $arguments += "--replace"
}

& clinical-data-cohort @arguments
