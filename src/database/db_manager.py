"""Simple database manager using SQLAlchemy.

This module exposes a :class:`DBManager` that constructs a SQLAlchemy
engine based on environment variables or a SQLAlchemy URL and provides
convenience methods for executing queries and returning pandas data frames.
"""
from __future__ import annotations

import os
from typing import Any, Optional, Mapping

import logging

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


logger = logging.getLogger(__name__)


def _build_sqlalchemy_url() -> str:
    """Construct a SQLAlchemy connection URL from environment variables.

    If the environment variable ``DATABASE_URL`` is set it will be used
    directly.  Otherwise individual variables ``DB_HOST``, ``DB_PORT``,
    ``DB_NAME``, ``DB_USER`` and ``DB_PASS`` are used to assemble a URL of
    the form ``postgresql://user:password@host:port/db``.
    """
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    db = os.getenv("DB_NAME", "warehouse")
    user = os.getenv("DB_USER", "app")
    pwd = os.getenv("DB_PASS", "app_pw")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


class DBManager:
    """High‑level database wrapper."""

    def __init__(self, url: Optional[str] = None) -> None:
        self.url = url or _build_sqlalchemy_url()
        self.engine: Engine = create_engine(self.url, pool_pre_ping=True, future=True)
        logger.debug("DBManager initialised with url=%s", self.url)

    def query_df(self, sql: str, params: Optional[Mapping[str, Any]] = None) -> pd.DataFrame:
        """Execute a SELECT query and return the results as a DataFrame."""
        logger.debug("Running query: %s", sql)
        with self.engine.connect() as conn:
            return pd.read_sql(text(sql), conn, params=params)

    def execute(self, sql: str, params: Optional[Mapping[str, Any]] = None) -> None:
        """Execute a non‑returning statement (INSERT/UPDATE/DDL)."""
        logger.debug("Executing statement: %s", sql)
        with self.engine.begin() as conn:
            conn.execute(text(sql), params or {})

    def close(self) -> None:
        try:
            self.engine.dispose()
            logger.debug("Database engine disposed")
        except Exception as exc:  # pragma: no cover - best effort cleanup
            logger.exception("Error disposing engine: %s", exc)


# Global helper similar to the original project
_GLOBAL_DB: Optional[DBManager] = None


def get_db(url: Optional[str] = None) -> DBManager:
    """Get a global database manager instance.

    The first call constructs the DBManager; subsequent calls return the
    existing instance.  An explicit URL overrides environment variables.
    """
    global _GLOBAL_DB
    if _GLOBAL_DB is None:
        logger.info("Creating global DBManager instance")
        _GLOBAL_DB = DBManager(url)
    return _GLOBAL_DB
