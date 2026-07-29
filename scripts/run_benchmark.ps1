param(
    [int[]]$Patients = @(250, 1000, 2500),
    [int]$Repetitions = 5,
    [int]$Warmups = 1,
    [int]$Seed = 20260729,
    [string]$OutputDirectory = "data/benchmarks/loading"
)

$ErrorActionPreference = "Stop"

if (-not $env:DATABASE_URL) {
    $env:DATABASE_URL = "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"
}

python -m pip install -e ".[dev]"
docker compose up -d postgres

$patientArguments = $Patients | ForEach-Object { $_.ToString() }

& clinical-data-benchmark `
    --patients @patientArguments `
    --repetitions $Repetitions `
    --warmups $Warmups `
    --seed $Seed `
    --output-dir $OutputDirectory

if ($LASTEXITCODE -ne 0) {
    throw "The governed loading benchmark failed with exit code $LASTEXITCODE."
}

Write-Host "Benchmark evidence written to $OutputDirectory"
