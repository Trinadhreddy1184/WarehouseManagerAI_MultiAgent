#!/usr/bin/env bash
# Convenience script to build and run the multi-agent app along with its database.

set -euo pipefail

if [ -f .env ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs)
fi

# Default S3 location for the sample dataset (override via env vars if needed)
: "${S3_BUCKET:=scotch-sampledata}"
: "${S3_KEY:=vip_tables_20250623.sql}"

# If S3 bucket/key are provided, download the SQL dump once and reuse it
if [[ -n "${S3_BUCKET:-}" && -n "${S3_KEY:-}" ]]; then
  mkdir -p data
  SQL_LOCAL="data/${S3_KEY##*/}"
  if [ ! -f "$SQL_LOCAL" ]; then
    echo "Downloading SQL dump from s3://${S3_BUCKET}/${S3_KEY}…"
    aws s3 cp "s3://${S3_BUCKET}/${S3_KEY}" "$SQL_LOCAL"
  else
    echo "Using cached SQL dump at $SQL_LOCAL"
  fi
  export SQL_FILE="$SQL_LOCAL"
  unset S3_BUCKET S3_KEY S3_PRESIGNED_URL
fi

echo "Building Docker images…"
docker-compose build

echo "Starting database…"
docker-compose up -d db

if [ -n "${SQL_FILE:-}" ]; then
  echo "Waiting for database to become ready…"
  until docker-compose exec -T db pg_isready -U "${DB_USER:-app}" -d "${DB_NAME:-warehouse}" >/dev/null 2>&1; do
    sleep 1
  done

  echo "Importing SQL dump into database…"
  if grep -qi "transaction_timeout" "$SQL_FILE"; then
    echo "Filtering unsupported transaction_timeout setting…"
    docker-compose exec -T db psql -v ON_ERROR_STOP=1 -U "${DB_USER:-app}" -d "${DB_NAME:-warehouse}" < <(sed '/transaction_timeout/d' "$SQL_FILE")
  else
    docker-compose exec -T db psql -v ON_ERROR_STOP=1 -U "${DB_USER:-app}" -d "${DB_NAME:-warehouse}" < "$SQL_FILE"
  fi

  echo "Waiting for database to restart after import…"
  until docker-compose exec -T db pg_isready -U "${DB_USER:-app}" -d "${DB_NAME:-warehouse}" >/dev/null 2>&1; do
    sleep 1
  done

  echo "Waiting for database to restart after import…"
  until docker-compose exec -T db pg_isready -U "${DB_USER:-app}" -d "${DB_NAME:-warehouse}" >/dev/null 2>&1; do
    sleep 1
  done

  echo "Verifying imported tables…"
  docker-compose exec -T db psql -U "${DB_USER:-app}" -d "${DB_NAME:-warehouse}" -c "SELECT COUNT(*) FROM vip_products LIMIT 1" >/dev/null
fi

echo "Starting application…"
docker-compose up -d app

echo "Services are up.  Database initialisation and embedding indexing run inside the container."
