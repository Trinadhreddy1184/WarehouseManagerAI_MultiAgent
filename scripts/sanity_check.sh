#!/usr/bin/env bash
# Run the Python sanity check against the imported inventory tables.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT_DIR/src"

python "$ROOT_DIR/scripts/sanity_check.py" "$@"

