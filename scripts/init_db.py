"""Initialise the application database.

This script creates the core tables required by the app and loads seed data
from the SQL dump supplied with the liquor and wine inventory.  The dump must
be sourced from S3 – either streamed directly using ``S3_BUCKET`` and
``S3_KEY`` or by providing the path to a local copy via ``SQL_FILE``.  If no
SQL source is provided the script will fail rather than creating placeholder
tables.
"""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

import logging

# Ensure the src package is on the Python path when executed as a script
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.logging_config import setup_logging  # noqa: E402
from database.db_manager import get_db  # noqa: E402  (import after path tweak)

from sqlalchemy import create_engine  # noqa: E402
try:  # Optional dependency for pgvector
    from pgvector.sqlalchemy import register_vector  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover - optional dependency
    register_vector = None  # type: ignore


logger = logging.getLogger(__name__)

def _load_sql() -> str:
    """Load SQL statements from S3 or a local file copied from S3."""
    bucket = os.getenv("S3_BUCKET")
    key = os.getenv("S3_KEY")
    local_path = os.getenv("SQL_FILE")

    if bucket and key:
        logger.info("Loading SQL from S3 bucket=%s key=%s", bucket, key)
        try:
            s3_uri = f"s3://{bucket}/{key}"
            result = subprocess.run(
                ["aws", "s3", "cp", s3_uri, "-"],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout
        except Exception as exc:
            logger.exception("Failed to load SQL from S3: %s", exc)
            raise

    if local_path and os.path.exists(local_path):
        logger.info("Loading SQL from local file %s", local_path)
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as exc:
            logger.exception("Failed to read SQL file %s: %s", local_path, exc)
            raise

    raise FileNotFoundError(
        "No SQL source provided; set S3_BUCKET/S3_KEY or SQL_FILE to the dump from S3"
    )


def _execute_sql(sql: str, db_url: str) -> None:
    """Execute a SQL script against ``db_url``.

    The function prefers the ``psql`` command line client for maximum
    compatibility with dumps produced by ``pg_dump``.  If ``psql`` is not
    available (for example when running in a minimal test environment) it
    falls back to using SQLAlchemy directly so that at least basic
    statements can be executed.  Any errors from ``psql`` are surfaced to the
    caller so that the initialisation can fail fast.
    """
    try:
        subprocess.run(
            ["psql", db_url, "-v", "ON_ERROR_STOP=1"],
            input=sql,
            text=True,
            check=True,
            capture_output=True,
        )
        return
    except FileNotFoundError:
        logger.warning("psql not found – falling back to SQLAlchemy execution")
    except subprocess.CalledProcessError as exc:
        logger.error("psql failed: %s", exc.stderr.strip())
        raise

    # Fallback using SQLAlchemy; this is a best-effort approach and will not
    # handle every ``pg_dump`` feature but allows unit tests or simple setups
    # without ``psql`` to execute standard SQL statements.
    engine = create_engine(db_url, future=True)
    if register_vector:
        register_vector(engine)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(sql)
    finally:
        engine.dispose()

def main() -> None:
    setup_logging()
    logger.info("Starting database initialisation")
    try:
        db = get_db()
        sql = _load_sql()
        _execute_sql(sql, db.url)
        db.execute("CREATE EXTENSION IF NOT EXISTS vector")
        # Verify that core tables from the dump are present
        db.query_df("SELECT 1 FROM vip_products LIMIT 1")
    except Exception:
        logger.exception("Database initialisation failed")
        sys.exit(1)
    logger.info("Database initialisation complete")



if __name__ == "__main__":
    main()
