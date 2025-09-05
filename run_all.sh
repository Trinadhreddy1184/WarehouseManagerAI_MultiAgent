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

echo "Building Docker images and starting services…"
docker-compose build
docker-compose up -d

echo "Services are up.  Database initialisation and embedding indexing run inside the container."
