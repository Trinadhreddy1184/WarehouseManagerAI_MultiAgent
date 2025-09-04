"""Streamlit front‑end for the multi‑agent retail application."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Tuple

import logging

import streamlit as st
from dotenv import load_dotenv

# Ensure the project root is on the path so ``import src`` works
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.load_config import load_llm_config, load_database_config

from src.config.logging_config import setup_logging

from src.llm.manager import LLMManager
from src.agents.agent_manager import AgentManager


logger = logging.getLogger(__name__)


def main() -> None:
    """Run the Streamlit application."""
    setup_logging()

    # Load environment variables from a .env file if present
    load_dotenv()

    st.set_page_config(page_title="Retail Inventory Chatbot", layout="wide")
    st.header("Retail Inventory Chatbot")

    logger.info("Streamlit app started")

    # Resolve config paths from environment or use defaults
    llm_config_path = os.getenv("LLM_CONFIG_PATH", "src/config/llm_config.yaml")
    db_config_path = os.getenv("DATABASE_CONFIG_PATH", "src/config/database_config.yaml")

    # Load configurations
    logger.debug("Loading LLM config from %s", llm_config_path)
    llm_config = load_llm_config(llm_config_path)
    logger.debug("Loading DB config from %s", db_config_path)
    _ = load_database_config(db_config_path)  # currently unused; ensures env vars are loaded

    # Create LLM and agent manager
    llm_manager = LLMManager.from_config(llm_config)
    agent_manager = AgentManager(llm_manager)

    logger.info("AgentManager and LLMManager initialised")


    # Initialise chat history
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"]: List[Tuple[str, str]] = []

    # Prompt input
    user_input = st.text_input("Ask a question", placeholder="E.g. What whiskies are in stock?", key="prompt")

    if user_input:

        logger.info("User input received: %s", user_input)

        with st.spinner("Generating response…"):
            response = agent_manager.handle_request(user_input, st.session_state["chat_history"])
        # Append to history
        st.session_state["chat_history"].append(("user", user_input))
        st.session_state["chat_history"].append(("assistant", response))

        logger.debug("Assistant response: %s", response)


    # Display chat history
    for role, text in st.session_state.get("chat_history", []):
        if role == "user":
            st.markdown(f"**You:** {text}")
        else:
            st.markdown(f"**Assistant:** {text}")


if __name__ == "__main__":
    main()
