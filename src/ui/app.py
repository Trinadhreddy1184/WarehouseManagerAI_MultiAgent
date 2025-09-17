import os, sys, logging
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

# Initialize logging
setup_logging()
logger = logging.getLogger(__name__)

# Load environment variables (e.g. AWS credentials, DB, etc.)
load_dotenv()

# Configure Streamlit page
st.set_page_config(page_title="Warehouse Inventory Assistant", layout="wide")
st.title("Warehouse Inventory Assistant")

# Optional sidebar instructions
st.sidebar.title("Instructions")
st.sidebar.info(
    "Enter your query about the warehouse inventory. "
    "The assistant will use the inventory database to answer your questions."
)

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

