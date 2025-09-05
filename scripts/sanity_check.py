#!/usr/bin/env python
"""Basic connectivity test for the database and LLM.

This script attempts a trivial ``SELECT 1`` against the configured database
and performs a single text generation request via :class:`LLMManager`.  It is
useful for quickly verifying that the application is correctly configured
before launching the full stack.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the project ``src`` directory is on the Python path when executed
# directly from the repository root or an installed location.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.logging_config import setup_logging  # noqa: E402
from config.load_config import load_llm_config  # noqa: E402
from database.db_manager import get_db  # noqa: E402
from llm.manager import LLMManager  # noqa: E402


def main() -> None:
    """Run the sanity checks."""
    setup_logging()

    # Database ping
    db = get_db()
    db.query_df("SELECT 1")

    # LLM ping
    llm_config_path = os.getenv("LLM_CONFIG_PATH", "src/config/llm_config.yaml")
    llm = LLMManager.from_config(load_llm_config(llm_config_path))
    response = llm.generate("Hello", [])
    print("LLM response:", response)

    print("Sanity check passed.")


if __name__ == "__main__":
    main()

