#!/usr/bin/env bash
# Convenience script to build and run the multi-agent app along with its database.

set -euo pipefail

if [ -f .env ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs)
fi

echo "Building Docker images and starting services…"
docker-compose build
docker-compose up -d

echo "Initialising database…"
docker-compose exec -T app python scripts/init_db.py

echo "Services are up.  Visit http://localhost:8501 in your browser."
