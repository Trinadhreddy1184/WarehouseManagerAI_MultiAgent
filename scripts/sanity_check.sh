#!/usr/bin/env bash
# Quick sanity check for database connectivity and LLM response generation.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ROOT_DIR

# Load environment variables if an .env file exists
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  source "$ROOT_DIR/.env"
  set +a
fi

# Ensure src/ is on the Python path
export PYTHONPATH="$ROOT_DIR/src:${PYTHONPATH:-}"

python3 <<'PY'
import os
from pathlib import Path
import yaml

from llm.manager import LLMManager
from database.db_manager import get_db

root = Path(os.environ["ROOT_DIR"])
config_path = root / "src" / "config" / "llm_config.yaml"

print("Database sanity check...")
try:
    db = get_db()
    df = db.query_df("SELECT 1 AS ok")
    print(df.to_string(index=False))
except Exception as exc:
    print(f"Database check failed: {exc}")

print("\nLLM sanity check...")
try:
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    llm = LLMManager.from_config(config)
    reply = llm.generate("Hello, provide a fun fact about inventory management.")
    print("LLM response:", reply)
except Exception as exc:
    print(f"LLM check failed: {exc}")
PY
