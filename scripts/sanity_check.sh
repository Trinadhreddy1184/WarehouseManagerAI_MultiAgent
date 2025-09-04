#!/usr/bin/env bash
# Simple sanity check for LLM response and database access.
# Creates a temporary SQLite database with sample data and queries it using
# DBManager, then generates a response via LLMManager using a dummy LLM.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT_DIR/src"

DB_FILE="$(mktemp /tmp/warehouse_sanity.XXXXXX.db)"
QUESTION=${1:-"How many widgets are in stock?"}

# Create sample database and populate it
python - <<PYTHON
from database.db_manager import DBManager

db = DBManager("sqlite:///$DB_FILE")
db.execute("CREATE TABLE inventory (id INTEGER PRIMARY KEY, name TEXT, qty INTEGER);")
db.execute("INSERT INTO inventory (name, qty) VALUES ('widget', 10), ('gadget', 5);")
print("Current inventory:")
print(db.query_df("SELECT * FROM inventory"))
PYTHON

# Query LLM using a dummy backend
python - <<PYTHON
from llm.manager import LLMManager

class DummyLLM:
    def generate(self, user_request, chat_history):
        return f"Dummy answer to: {user_request}"

config = {"llm": {}, "bedrock": {}}
manager = LLMManager(config, DummyLLM())
print("LLM response:")
print(manager.generate("$QUESTION"))
PYTHON

echo "SQLite database stored at: $DB_FILE"
