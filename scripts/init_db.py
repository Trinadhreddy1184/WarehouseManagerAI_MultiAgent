"""Initialise the application database.

This script creates the core tables required by the app and optionally
loads seed data from a SQL file.  The SQL can be supplied via:

- An S3 bucket/key specified by the environment variables ``S3_BUCKET`` and
  ``S3_KEY``.
- A pre‑signed URL in ``S3_PRESIGNED_URL``.
- A local path provided through ``SQL_FILE`` (defaults to ``data/init.sql``).

If none of these are supplied the script simply ensures that the
``app_inventory`` table exists.
"""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

import logging
import boto3
import requests

# Ensure the src package is on the Python path when executed as a script
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.logging_config import setup_logging  # noqa: E402
from database.db_manager import get_db  # noqa: E402  (import after path tweak)


logger = logging.getLogger(__name__)

def _load_sql() -> str:
    """Load SQL statements from S3, a URL or a local file."""
    bucket = os.getenv("S3_BUCKET")
    key = os.getenv("S3_KEY")
    presigned = os.getenv("S3_PRESIGNED_URL")
    local_path = os.getenv("SQL_FILE", str(ROOT / "data" / "init.sql"))

    if bucket and key:
        logger.info("Loading SQL from S3 bucket=%s key=%s", bucket, key)
        try:
            s3 = boto3.client("s3", region_name=os.getenv("S3_REGION"))
            obj = s3.get_object(Bucket=bucket, Key=key)
            return obj["Body"].read().decode("utf-8")
        except Exception as exc:
            logger.exception("Failed to load SQL from S3: %s", exc)
            raise

    if presigned:
        logger.info("Loading SQL from presigned URL")
        try:
            resp = requests.get(presigned, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            logger.exception("Failed to load SQL from URL: %s", exc)
            raise

    if os.path.exists(local_path):
        logger.info("Loading SQL from local file %s", local_path)
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as exc:
            logger.exception("Failed to read SQL file %s: %s", local_path, exc)
            raise

    logger.warning("No SQL source provided; using minimal schema")
    return """
    CREATE TABLE IF NOT EXISTS app_inventory (
        store TEXT,
        product_name TEXT,
        brand_name TEXT
    );
    """


def _execute_sql(sql: str, db_url: str) -> None:
    """Execute SQL script using psql for pg_dump compatibility."""
    try:
        subprocess.run(
            ["psql", db_url, "-v", "ON_ERROR_STOP=1"],
            input=sql,
            text=True,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.error("psql failed: %s", exc.stderr.strip())
        raise


def main() -> None:
    setup_logging()
    logger.info("Starting database initialisation")
    try:
        db = get_db()
        sql = _load_sql()
        _execute_sql(sql, db.url)
    except Exception:
        logger.exception("Database initialisation failed")
        sys.exit(1)
    logger.info("Database initialisation complete")



if __name__ == "__main__":
    main()
