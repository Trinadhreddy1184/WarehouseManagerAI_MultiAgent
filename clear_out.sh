#!/usr/bin/env bash
# Tear down the Docker environment and remove volumes.

set -euo pipefail

echo "Stopping services and removing volumes…"
docker-compose down -v
echo "Cleanup complete."
