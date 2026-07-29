param(
    [string]$Root = "data/synthea",
    [string]$OutputDirectory = "data/synthea/cohort-quality",
    [switch]$Replace
)

$ErrorActionPreference = "Stop"

$cohortADirectory = Join-Path $Root "synthea-us-small-v1/normalized"
$cohortBDirectory = Join-Path $Root "synthea-us-small-cohort-b-v1/normalized"

$arguments = @(
    "quality-report",
    $cohortADirectory,
    $cohortBDirectory,
    "--output-dir", $OutputDirectory
)
if ($Replace) {
    $arguments += "--replace"
}

& clinical-data-cohort @arguments
