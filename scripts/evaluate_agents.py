import os
import sys
from pathlib import Path
import textwrap

# Ensure the project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

# Masked display of database URL (for verification)
db_url = os.getenv("DATABASE_URL", "")
masked_url = (db_url[: db_url.find("@")] + "@***") if "@" in db_url else (db_url or "(not set)")
print("[py] DATABASE_URL:", masked_url)

# Verify database connectivity
from src.database.db_manager import get_db
try:
    df = get_db().query_df("SELECT 1 AS ok", None)
    assert not df.empty and int(df.iloc[0]["ok"]) == 1
    print("[py] DB connection OK.")
except Exception as e:
    print("[py][x] DB connection failed:", repr(e))
    sys.exit(3)

# Initialize LLMManager and AgentManager
from src.config.load_config import load_llm_config
from src.llm.manager import LLMManager
from src.agents.agent_manager import AgentManager

llm_config_path = os.getenv("LLM_CONFIG_PATH", "src/config/llm_config.yaml")
try:
    llm_config = load_llm_config(llm_config_path)
except Exception as e:
    print("[py][x] Failed to load LLM config:", repr(e))
    sys.exit(1)

try:
    llm_manager = LLMManager.from_config(llm_config)
except Exception as e:
    print("[py][x] Failed to initialize LLMManager:", repr(e))
    sys.exit(1)

agent_manager = AgentManager(llm_manager)
print("[py] Agents:", [type(a).__name__ for a in agent_manager.agents])

# Define test queries for each agent scenario
tests = [
    "List the inventory items available in store 1.",
    "Do we have gin?",
    "Do we have product XYZ in store 1 inventory?"
]

# Run each test query through the AgentManager
for q in tests:
    print(f"\n[py] Q: {q}")
    try:
        ans = agent_manager.handle_request(q, [])
        print(textwrap.shorten("[py] A: " + (ans or ""), width=500))
    except Exception as e:
        print("[py][x] Error:", repr(e))

print("\n[py] Agent evaluation test complete.")

