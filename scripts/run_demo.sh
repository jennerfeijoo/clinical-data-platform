#!/usr/bin/env sh
set -eu

if [ ! -f .env ]; then
    cp .env.example .env
fi

docker compose up -d postgres
docker compose --profile demo run --rm app

printf '%s\n' 'Demo outputs are available under data/processed and data/analytics.'
