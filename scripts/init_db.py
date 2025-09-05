"""Verify the application database.

The inventory SQL dump is imported before the app starts (see ``run_all.sh``).
This script only ensures required extensions exist and expected tables are
present; it does **not** create or load any data.
"""
from __future__ import annotations

import sys
from pathlib import Path

import logging

# Ensure the src package is on the Python path when executed as a script
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.logging_config import setup_logging  # noqa: E402
from database.db_manager import get_db  # noqa: E402  (import after path tweak)


logger = logging.getLogger(__name__)

def main() -> None:
    setup_logging()
    logger.info("Starting database initialisation")
    try:
        db = get_db()
        try:
            db.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception as exc:  # pragma: no cover - depends on DB
            logger.warning("Vector extension unavailable: %s", exc)
        db.query_df("SELECT 1 FROM vip_products LIMIT 1")
    except Exception:
        logger.exception("Database initialisation failed")
        sys.exit(1)
    logger.info("Database initialisation complete")



if __name__ == "__main__":
    main()
