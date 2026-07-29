$ErrorActionPreference = "Stop"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

docker compose up -d postgres
docker compose --profile demo run --rm app

Write-Host "Demo outputs are available under data/processed and data/analytics."
