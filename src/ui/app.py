import logging
import os
import sys
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
import pandas as pd

# Ensure project root is on the path for imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.load_config import load_llm_config, load_database_config
from src.config.logging_config import setup_logging
from src.llm.manager import LLMManager
from src.agents.agent_manager import AgentManager
from src.database.db_manager import ensure_database_url, get_db

# Initialize logging
setup_logging()
logger = logging.getLogger(__name__)

# Load environment variables (e.g. AWS credentials, DB, etc.)
load_dotenv()
db_url = ensure_database_url()
db_host = os.getenv("DB_HOST", "unknown")
db_port = os.getenv("DB_PORT", "5432")


def _mask_db_url(url: str) -> str:
    if not url:
        return ""
    if "@" not in url:
        return url
    scheme = ""
    remainder = url
    if "://" in url:
        scheme, remainder = url.split("://", 1)
    user_host = remainder.split("@", 1)
    if len(user_host) != 2:
        return url
    user_part, host_part = user_host
    user = user_part.split(":", 1)[0]
    prefix = f"{scheme}://" if scheme else ""
    return f"{prefix}{user}:***@{host_part}"


masked_url = _mask_db_url(db_url)
logger.info(
    "Streamlit resolved database target host=%s port=%s url=%s",
    db_host,
    db_port,
    masked_url or "(unset)",
)

previous_status = st.session_state.get("db_status")
try:
    get_db().query_df("SELECT 1", None)
    current_status = {
        "ok": True,
        "message": f"Connected to inventory DB at {db_host}:{db_port}",
    }
    if not previous_status or not previous_status.get("ok", False):
        logger.info("Database connectivity check succeeded at %s:%s", db_host, db_port)
except Exception as exc:  # pragma: no cover - best effort for UI feedback
    current_status = {
        "ok": False,
        "message": (
            "Database connection failed. Ensure the Docker database container is running "
            "(see scripts/smoke_db_via_container_ip.sh)."
        ),
    }
    if not previous_status or previous_status.get("ok", True):
        logger.exception("Database connectivity check failed: %s", exc)

st.session_state["db_status"] = current_status

# Configure Streamlit page
st.set_page_config(page_title="Warehouse Inventory Assistant", layout="wide")
st.title("Warehouse Inventory Assistant")

# Optional sidebar instructions
st.sidebar.title("Instructions")
st.sidebar.info(
    "Enter your query about the warehouse inventory. "
    "The assistant will use the inventory database to answer your questions."
)

db_status = st.session_state.get("db_status", {"ok": False, "message": "Database status unknown."})
if db_status["ok"]:
    st.sidebar.success(db_status["message"])
else:
    st.sidebar.error(db_status["message"])

# Initialize chat history
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []  # list of (role, message)

# Initialize AgentManager (load configs, build LLM and agents) once
if "agent_manager" not in st.session_state:
    llm_config_path = os.getenv("LLM_CONFIG_PATH", "src/config/llm_config.yaml")
    db_config_path = os.getenv("DATABASE_CONFIG_PATH", "src/config/database_config.yaml")
    llm_config = load_llm_config(llm_config_path)
    _ = load_database_config(db_config_path)
    llm_manager = LLMManager.from_config(llm_config)
    agent_manager = AgentManager(llm_manager)
    st.session_state["agent_manager"] = agent_manager

# Get user input
user_input = st.chat_input("Your message:")

if user_input:
    # Display existing conversation
    for role, msg in st.session_state["chat_history"]:
        st.chat_message(role).markdown(msg)

    # Append and display new user message
    st.session_state["chat_history"].append(("user", user_input))
    st.chat_message("user").markdown(user_input)

    if not st.session_state.get("db_status", {}).get("ok", False):
        response = (
            "The inventory database is unavailable right now. "
            "Please ensure the Docker services are running and try again."
        )
    else:
        # Call the multi-agent system to get a response
        with st.spinner("Assistant is typing..."):
            response = st.session_state["agent_manager"].handle_request(
                user_input, st.session_state["chat_history"]
            )

    # Append assistant response to history
    st.session_state["chat_history"].append(("assistant", response))

    # Check if response contains a Markdown table (SQL results)
    if "```" in response:
        try:
            # Extract text inside the first code block
            table_text = response.split("```")[1]
        except IndexError:
            table_text = ""
        lines = table_text.strip().splitlines()
        if lines:
            header = [h.strip() for h in lines[0].split("|")]
            data_rows = []
            for row in lines[1:]:
                if "|" not in row:
                    continue
                data_rows.append([cell.strip() for cell in row.split("|")])
            if data_rows:
                # Build DataFrame and display as table
                df = pd.DataFrame(data_rows, columns=header)
                st.chat_message("assistant").markdown("**Results:**")
                st.table(df)
            else:
                # Fallback to raw response if parsing fails
                st.chat_message("assistant").markdown(response)
        else:
            st.chat_message("assistant").markdown(response)
    else:
        # No table in response; just render Markdown
        st.chat_message("assistant").markdown(response)
else:
    # If no new input, just display the existing conversation
    for role, msg in st.session_state["chat_history"]:
        st.chat_message(role).markdown(msg)

