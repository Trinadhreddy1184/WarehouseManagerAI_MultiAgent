#!/usr/bin/env bash
# Sanity check for live database contents and LLM response.
# Connects to the configured database and prints sample rows from the
# ``app_inventory`` table, then generates a response using the configured LLM.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT_DIR/src"

QUESTION=${1:-"How many widgets are in stock?"}
LLM_CONFIG=${LLM_CONFIG_PATH:-"$ROOT_DIR/src/config/llm_config.yaml"}

# Show some data from the live database
python - <<PYTHON
from database.db_manager import get_db

print("Current inventory sample:")
db = get_db()
print(db.query_df("SELECT * FROM app_inventory LIMIT 5"))
PYTHON

echo
# Query the real LLM defined in configuration
python - <<PYTHON
from config.load_config import load_llm_config
from llm.manager import LLMManager

config = load_llm_config("$LLM_CONFIG")
manager = LLMManager.from_config(config)
print("LLM response:")
print(manager.generate("$QUESTION"))
PYTHON

