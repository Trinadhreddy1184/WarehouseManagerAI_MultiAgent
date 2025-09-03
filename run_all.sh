#!/usr/bin/env bash
# Convenience script to build and run the multi-agent app along with its database.

set -euo pipefail

echo "Building Docker images and starting services…"
docker-compose build
docker-compose up -d
echo "Services are up.  Visit http://localhost:8501 in your browser."
