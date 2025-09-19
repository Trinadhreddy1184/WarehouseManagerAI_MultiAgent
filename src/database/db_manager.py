"""Simple database manager using SQLAlchemy.

This module exposes a :class:`DBManager` that constructs a SQLAlchemy
engine based on environment variables or a SQLAlchemy URL and provides
convenience methods for executing queries and returning pandas data frames.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
from typing import Any, Mapping, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

_RESOLVED_DB_HOST: Optional[str] = None


def _host_port_reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    """Best-effort TCP connectivity probe used to mirror the smoke scripts."""

    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _inspect_container_ip(container: str) -> Optional[str]:
    """Return the IPv4 address of a running Docker container if possible."""

    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                container,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        logger.debug("docker executable not available; skipping container IP lookup")
        return None
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        logger.warning(
            "Failed to inspect container %s for IP address: %s",
            container,
            stderr or exc,
        )
        return None

    ip = result.stdout.strip()
    return ip or None


def _apply_db_settings(host: str, port: int) -> None:
    """Update environment variables so SQLAlchemy picks up the correct target."""

    global _RESOLVED_DB_HOST

    user = os.getenv("DB_USER", "app")
    pwd = os.getenv("DB_PASSWORD") or os.getenv("DB_PASS", "app_pw")
    name = os.getenv("DB_NAME", "warehouse")

    os.environ["DB_HOST"] = host
    os.environ["DB_PORT"] = str(port)

    url = f"postgresql://{user}:{pwd}@{host}:{port}/{name}"
    os.environ["DATABASE_URL"] = url

    if _RESOLVED_DB_HOST != host:
        masked = f"postgresql://{user}:***@{host}:{port}/{name}"
        logger.info("Database target resolved to %s (URL=%s)", host, masked)
        _RESOLVED_DB_HOST = host


def _ensure_container_ip_if_needed() -> None:
    """Mirror the smoke script logic to prefer the container IP when required."""

    host = (os.getenv("DB_HOST", "").strip() or "localhost")
    port_raw = os.getenv("DB_PORT", "5432").strip() or "5432"
    use_container_ip = os.getenv("USE_CONTAINER_IP", "").strip() == "1"
    container = os.getenv("DB_CONTAINER", "warehousemanagerai_db")
    cached_ip = os.getenv("DB_CONTAINER_IP", "").strip()

    try:
        port = int(port_raw)
    except ValueError:
        logger.warning("Invalid DB_PORT=%r; defaulting to 5432", port_raw)
        port = 5432

    reason: Optional[str] = None
    if use_container_ip:
        reason = "USE_CONTAINER_IP=1"
    elif not host:
        reason = "DB_HOST not provided"
    elif host.lower() in {"localhost", "127.0.0.1"}:
        reason = f"DB_HOST={host}"
    elif not _host_port_reachable(host, port):
        reason = f"{host}:{port} unreachable"

    target_host = host

    if reason:
        ip = cached_ip or _inspect_container_ip(container)
        if ip:
            os.environ["DB_CONTAINER_IP"] = ip
            target_host = ip
            logger.debug(
                "Using container IP %s for %s (%s)",
                ip,
                container,
                reason,
            )
        else:
            logger.warning(
                "Unable to determine container IP for %s (%s); continuing with DB_HOST=%s",
                container,
                reason,
                host,
            )

    _apply_db_settings(target_host, port)

def _build_sqlalchemy_url() -> str:
    """Construct a SQLAlchemy connection URL from environment variables.

    If the environment variable ``DATABASE_URL`` is set it will be used
    directly.  Otherwise individual variables ``DB_HOST``, ``DB_PORT``,
    ``DB_NAME``, ``DB_USER`` and a password are used to assemble a URL of
    the form ``postgresql://user:password@host:port/db``.  ``DB_PASSWORD``
    is preferred for specifying the password but ``DB_PASS`` is honoured for
    backwards compatibility.
    """
    _ensure_container_ip_if_needed()
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    db = os.getenv("DB_NAME", "warehouse")
    user = os.getenv("DB_USER", "app")
    pwd = os.getenv("DB_PASSWORD") or os.getenv("DB_PASS", "app_pw")
    url = f"postgresql://{user}:{pwd}@{host}:{port}/{db}"
    os.environ["DATABASE_URL"] = url
    return url


def ensure_database_url() -> str:
    """Resolve and cache the SQLAlchemy URL using the active environment."""

    return _build_sqlalchemy_url()


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
