"""Database manager with PostgreSQL primary and DuckDB fallback support."""
from __future__ import annotations

import gzip
import json
import logging
import os
import re
import tempfile
import time
from typing import IO, Any, Callable, Generator, Mapping, Optional, Sequence, TypeVar

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_DUCKDB_TABLES: Sequence[str] = (
    "app_inventory",
    "vip_products",
    "vip_brands",
)


def _build_sqlalchemy_url() -> str:
    """Construct a SQLAlchemy connection URL from environment variables."""

    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    db = os.getenv("DB_NAME", "warehouse")
    user = os.getenv("DB_USER", "app")
    pwd = os.getenv("DB_PASSWORD") or os.getenv("DB_PASS", "app_pw")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


def _env_flag(name: str, default: bool) -> bool:
    """Return a boolean flag from environment variables."""

    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _resolve_duckdb_tables(tables: Optional[Sequence[str]]) -> Sequence[str]:
    """Resolve the list of tables to mirror into DuckDB."""

    if tables is not None:
        return [t.strip() for t in tables if t and t.strip()]
    env_value = os.getenv("DUCKDB_FALLBACK_TABLES")
    if env_value:
        return [t.strip() for t in env_value.split(",") if t.strip()]
    return list(_DEFAULT_DUCKDB_TABLES)


class DuckDBMirror:
    """Maintain a DuckDB mirror of selected PostgreSQL tables."""

    def __init__(
        self,
        path: str,
        tables: Sequence[str],
        *,
        sql_dump_path: Optional[str],
        auto_sync: bool,
        sync_interval: float,
    ) -> None:
        self.path = os.path.abspath(path)
        self.tables = [t for t in tables if t]
        self.sql_dump_path = os.path.abspath(sql_dump_path) if sql_dump_path else None
        self.auto_sync = auto_sync
        self.sync_interval = max(0.0, sync_interval)
        self._last_sync = 0.0
        self._last_dump_mtime = 0.0
        self.available = self._check_dependencies()
        self._warned_missing = False
        self._warned_missing_dump = False

    @staticmethod
    def _check_dependencies() -> bool:
        try:  # pragma: no cover - import guard
            import duckdb  # noqa: F401
        except ImportError:
            logger.warning(
                "DuckDB fallback disabled because the 'duckdb' package is not installed."
            )
            return False
        return True

    def close(self) -> None:
        # No persistent resources to dispose when using the DuckDB Python API.
        return

    @staticmethod
    def _coerce_vector(value: Any) -> Optional[list[float]]:
        if value is None:
            return None
        if isinstance(value, (bytes, bytearray)):
            return None
        if isinstance(value, memoryview):
            value = value.tolist()
        if hasattr(value, "tolist") and not isinstance(value, list):
            value = value.tolist()
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, list):
                try:
                    return [float(x) for x in parsed]
                except (TypeError, ValueError):
                    return None
            return None
        if isinstance(value, (list, tuple)):
            try:
                return [float(x) for x in value]
            except (TypeError, ValueError):
                return None
        try:
            return [float(x) for x in value]  # type: ignore[arg-type]
        except TypeError:
            return None

    @staticmethod
    def _parse_embedding(value: Any) -> Optional[list[float]]:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, list):
                try:
                    return [float(x) for x in parsed]
                except (TypeError, ValueError):
                    return None
            return None
        if isinstance(value, (list, tuple)):
            try:
                return [float(x) for x in value]
            except (TypeError, ValueError):
                return None
        if hasattr(value, "tolist"):
            return DuckDBMirror._parse_embedding(value.tolist())
        return None

    def _open_dump_stream(self, dump_path: str):
        if dump_path.endswith(".gz"):
            return gzip.open(dump_path, "rt", encoding="utf-8", errors="ignore")
        return open(dump_path, "rt", encoding="utf-8", errors="ignore")

    def _iterate_dump_entries(self, dump_path: str) -> Generator[tuple[str, Any], None, None]:
        with self._open_dump_stream(dump_path) as stream:
            statement_lines: list[str] = []
            copy_info: Optional[dict[str, Any]] = None
            copy_writer: Optional[IO[str]] = None
            try:
                for raw_line in stream:
                    if copy_info is not None:
                        line = raw_line.rstrip("\r\n")
                        if line == "\\.":
                            if copy_writer is not None:
                                try:
                                    copy_writer.flush()
                                finally:
                                    copy_writer.close()
                                copy_writer = None
                            yield ("copy", copy_info)
                            copy_info = None
                        else:
                            if copy_writer is not None:
                                copy_writer.write(line)
                                copy_writer.write("\n")
                            else:
                                copy_info.setdefault("data", []).append(line)  # type: ignore[arg-type]
                        continue

                    stripped = raw_line.lstrip()
                    if not statement_lines and stripped.startswith("--"):
                        continue

                    statement_lines.append(raw_line)
                    if raw_line.rstrip().endswith(";"):
                        statement = "".join(statement_lines).strip()
                        statement_lines = []
                        if not statement:
                            continue
                        statement_upper = statement.upper()
                        statement_lower = statement.lower()
                        if statement_upper.startswith("COPY ") and "from stdin" in statement_lower:
                            parsed_copy = self._parse_copy_command(statement)
                            if parsed_copy is None:
                                continue
                            try:
                                copy_writer = tempfile.NamedTemporaryFile(
                                    "w", delete=False, encoding="utf-8", newline=""
                                )
                            except OSError:
                                copy_writer = None
                                parsed_copy["data"] = []
                            else:
                                parsed_copy["temp_path"] = copy_writer.name
                            copy_info = parsed_copy
                        else:
                            yield ("sql", statement)
            finally:
                if copy_writer is not None:
                    try:
                        copy_writer.close()
                    except Exception:
                        pass
                if copy_info is not None:
                    temp_path = copy_info.get("temp_path")
                    if temp_path:
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass

    def _parse_copy_command(self, command: str) -> Optional[dict[str, Any]]:
        match = re.match(
            r"COPY\s+(.+?)\s*(?:\((.*?)\))?\s+FROM\s+stdin;?$",
            command,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            first_line = command.splitlines()[0] if command else command
            logger.debug("Skipping unrecognised COPY command for DuckDB fallback: %s", first_line)
            return None
        table = match.group(1).strip()
        columns = match.group(2)
        if columns is not None:
            columns = " ".join(columns.split())
        return {"table": table, "columns": columns, "command": command}

    @staticmethod
    def _normalise_table_name(identifier: str) -> str:
        name = identifier.strip()
        if name.lower().startswith('"public".'):
            return name[len('"public".') :]
        if name.lower().startswith("public."):
            return name.split(".", 1)[1]
        return name

    @staticmethod
    def _split_columns(columns: str) -> list[str]:
        return [col.strip() for col in columns.split(",") if col.strip()]

    def _get_table_columns(self, conn, table: str) -> list[str]:
        normalized = self._normalise_table_name(table)
        unquoted = normalized.strip('"')
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = ?
            ORDER BY ordinal_position
            """,
            [unquoted],
        ).fetchall()
        return [f'"{row[0]}"' for row in rows]

    def _rewrite_create_table(self, statement: str) -> str:
        rewritten = re.sub(r"vector\s*\(\s*\d+\s*\)", "TEXT", statement, flags=re.IGNORECASE)
        rewritten = re.sub(
            r"\s+DEFAULT\s+nextval\('[^']+'::regclass\)",
            "",
            rewritten,
            flags=re.IGNORECASE,
        )
        return rewritten

    def _execute_sql_statement(self, conn, statement: str) -> None:
        stmt = statement.strip().rstrip(";")
        if not stmt:
            return
        upper = stmt.upper()
        skip_prefixes = (
            "SET ",
            "SELECT PG_CATALOG",
            "SELECT CURRENT_SCHEMA",
            "ALTER TABLE",
            "GRANT ",
            "REVOKE ",
            "COMMENT ",
            "CREATE EXTENSION",
            "DROP EXTENSION",
            "CREATE SEQUENCE",
            "CREATE UNIQUE INDEX",
            "CREATE INDEX",
        )
        if upper in {"BEGIN", "COMMIT"}:
            return
        if any(upper.startswith(prefix) for prefix in skip_prefixes):
            return
        if upper.startswith("SELECT ") and "pg_catalog" in upper:
            return
        if upper.startswith("CREATE TABLE"):
            stmt = self._rewrite_create_table(stmt)
        try:
            conn.execute(stmt)
        except Exception as exc:
            logger.debug(
                "Skipping statement during DuckDB fallback load due to error: %s | statement=%s",
                exc,
                stmt.splitlines()[0],
            )

    def _execute_copy(self, conn, payload: Mapping[str, Any]) -> None:
        table = payload["table"]
        columns = payload.get("columns")
        data_lines = payload.get("data") or []
        temp_path = payload.get("temp_path")
        if columns:
            column_names = self._split_columns(columns)
        else:
            column_names = self._get_table_columns(conn, table)
        columns_clause = f"({', '.join(column_names)})" if column_names else ""
        cleanup_path: Optional[str]
        if temp_path:
            tmp_path = temp_path
            cleanup_path = temp_path
        else:
            with tempfile.NamedTemporaryFile(
                "w", delete=False, encoding="utf-8", newline="\n"
            ) as tmp:
                for line in data_lines:
                    tmp.write(line)
                    tmp.write("\n")
                tmp_path = tmp.name
            cleanup_path = tmp_path
        escaped_path = tmp_path.replace("'", "''")
        try:
            select_list = ", ".join(f"column{i}" for i in range(len(column_names)))
            if not select_list:
                select_list = "*"
            insert_sql = (
                f"INSERT INTO {table} {columns_clause} SELECT {select_list} "
                f"FROM read_csv_auto('{escaped_path}', delim='\\t', nullstr='\\N', header=False);"
            )
            conn.execute(insert_sql)
        except Exception as exc:
            logger.debug("Skipping COPY for table %s due to error: %s", table, exc)
        finally:
            if cleanup_path:
                try:
                    os.remove(cleanup_path)
                except OSError:
                    pass

    def _load_sql_dump(self, dump_path: str) -> None:
        import duckdb

        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(suffix=".duckdb")
        os.close(fd)
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
        try:
            conn = duckdb.connect(tmp_path)
            try:
                conn.execute("CREATE SCHEMA IF NOT EXISTS public;")
                conn.execute("SET schema 'public'")
                for kind, payload in self._iterate_dump_entries(dump_path):
                    if kind == "sql":
                        self._execute_sql_statement(conn, payload)
                    elif kind == "copy":
                        self._execute_copy(conn, payload)
                conn.execute("CHECKPOINT;")
            finally:
                conn.close()
            os.replace(tmp_path, self.path)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def sync_from_sql_dump(self, *, force: bool = False) -> bool:
        if not self.available:
            return False
        if not self.sql_dump_path:
            if not self._warned_missing_dump:
                logger.warning("DuckDB fallback SQL dump path not configured.")
                self._warned_missing_dump = True
            return False
        dump_path = self.sql_dump_path
        if not os.path.exists(dump_path):
            if not self._warned_missing_dump:
                logger.warning(
                    "DuckDB fallback SQL dump not found at %s", dump_path
                )
                self._warned_missing_dump = True
            return False
        self._warned_missing_dump = False
        dump_mtime = os.path.getmtime(dump_path)
        if (
            not force
            and self._last_dump_mtime
            and dump_mtime <= self._last_dump_mtime
            and os.path.exists(self.path)
        ):
            return self.is_ready()
        try:
            self._load_sql_dump(dump_path)
        except Exception as exc:
            logger.error("DuckDB fallback sync from %s failed: %s", dump_path, exc)
            return False
        self._last_sync = time.monotonic()
        self._last_dump_mtime = dump_mtime
        logger.info(
            "DuckDB fallback mirror refreshed from SQL dump at %s", dump_path
        )
        return True

    def maybe_sync_from_sql_dump(self) -> None:
        if not self.available or not self.auto_sync:
            return
        now = time.monotonic()
        if self.sync_interval and self._last_sync:
            if now - self._last_sync < self.sync_interval:
                return
        self.sync_from_sql_dump()

    def ensure_from_sql_dump(self) -> bool:
        if not self.available:
            return False
        if self.is_ready():
            return True
        return self.sync_from_sql_dump(force=True)

    def is_ready(self) -> bool:
        if not self.available:
            return False
        if not os.path.exists(self.path):
            if not self._warned_missing:
                logger.warning(
                    "DuckDB fallback database missing at %s. Run a sync when the SQL dump is available.",
                    self.path,
                )
                self._warned_missing = True
            return False
        try:
            import duckdb

            conn = duckdb.connect(self.path, read_only=True)
            try:
                conn.execute("SET schema 'public'")
                for table in self.tables:
                    if not table:
                        continue
                    if not self._table_exists(conn, table):
                        logger.debug("DuckDB fallback table %s not present", table)
                        return False
            finally:
                conn.close()
            return True
        except Exception as exc:
            logger.debug("DuckDB readiness check failed: %s", exc)
            return False

    @staticmethod
    def _table_exists(conn, table: str) -> bool:
        result = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?",
            [table],
        ).fetchone()
        return result is not None

    def _render_sql(
        self, sql: str, params: Optional[Mapping[str, Any]]
    ) -> tuple[str, list[Any]]:
        if not params:
            return sql, []

        values: list[Any] = []

        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in params:
                raise KeyError(f"Missing parameter '{key}' for DuckDB fallback query")
            values.append(params[key])
            return "?"

        rendered = re.sub(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", _replace, sql)
        return rendered, values

    def query_df(
        self, sql: str, params: Optional[Mapping[str, Any]] = None
    ) -> pd.DataFrame:
        if not self.available:
            raise RuntimeError("DuckDB fallback is not available")
        import duckdb

        rendered_sql, values = self._render_sql(sql, params)
        conn = duckdb.connect(self.path, read_only=True)
        try:
            conn.execute("SET schema 'public'")
            if values:
                result = conn.execute(rendered_sql, values).df()
            else:
                result = conn.execute(rendered_sql).df()
        finally:
            conn.close()
        return result

    def vector_similarity(
        self, query_vector: Sequence[float], *, limit: int = 5
    ) -> pd.DataFrame:
        if not self.available:
            raise RuntimeError("DuckDB fallback is not available")

        import duckdb

        conn = duckdb.connect(self.path, read_only=True)
        try:
            conn.execute("SET schema 'public'")
            products = conn.execute(
                """
                SELECT
                    vip_product_id,
                    vip_brand_id,
                    COALESCE(NULLIF(TRIM(consumer_product_name), ''), TRIM(product_name)) AS product_name,
                    embedding
                FROM vip_products
                WHERE embedding IS NOT NULL
                """
            ).df()
            brands = conn.execute(
                """
                SELECT
                    vip_brand_id,
                    COALESCE(NULLIF(TRIM(consumer_brand_name), ''), TRIM(brand_name)) AS brand_name
                FROM vip_brands
                """
            ).df()
        finally:
            conn.close()

        if products.empty:
            return pd.DataFrame(columns=["product_name", "brand_name"])

        target = self._coerce_vector(query_vector)
        if not target:
            raise ValueError("Query vector is empty or invalid")
        target_array = np.array(target, dtype="float64")

        def _distance(value: Any) -> float:
            embedding = DuckDBMirror._parse_embedding(value)
            if not embedding:
                return float("inf")
            emb_array = np.array(embedding, dtype="float64")
            if emb_array.shape != target_array.shape:
                return float("inf")
            return float(np.linalg.norm(emb_array - target_array))

        products["distance"] = products["embedding"].apply(_distance)
        products = products.replace({"distance": {np.inf: np.nan}})
        products = products.dropna(subset=["distance"])
        if products.empty:
            return pd.DataFrame(columns=["product_name", "brand_name"])

        top = products.nsmallest(max(int(limit), 1), "distance")
        brand_map = (
            dict(zip(brands["vip_brand_id"], brands["brand_name"]))
            if not brands.empty
            else {}
        )
        brand_series = top["vip_brand_id"].map(brand_map)
        result = top.assign(brand_name=brand_series)[["product_name", "brand_name"]]
        return result.reset_index(drop=True)


class DBManager:
    """High-level database wrapper with automatic DuckDB fallback."""

    def __init__(
        self,
        url: Optional[str] = None,
        *,
        max_retries: int = 3,
        retry_interval: float = 1.0,
        enable_duckdb_fallback: Optional[bool] = None,
        duckdb_path: Optional[str] = None,
        duckdb_tables: Optional[Sequence[str]] = None,
        duckdb_auto_sync: Optional[bool] = None,
        duckdb_sync_interval: Optional[float] = None,
        duckdb_sql_dump_path: Optional[str] = None,
    ) -> None:
        self.url = url or _build_sqlalchemy_url()
        self.engine: Engine = create_engine(self.url, pool_pre_ping=True, future=True)
        self.max_retries = max(1, max_retries)
        self.retry_interval = max(0.0, retry_interval)

        fallback_enabled = (
            _env_flag("ENABLE_DUCKDB_FALLBACK", True)
            if enable_duckdb_fallback is None
            else enable_duckdb_fallback
        )
        fallback_path = duckdb_path or os.getenv(
            "DUCKDB_FALLBACK_PATH", os.path.join("data", "postgres_mirror.duckdb")
        )
        tables = _resolve_duckdb_tables(duckdb_tables)
        auto_sync = (
            _env_flag("DUCKDB_AUTO_SYNC", True)
            if duckdb_auto_sync is None
            else duckdb_auto_sync
        )
        sync_interval = (
            float(os.getenv("DUCKDB_SYNC_INTERVAL", "300.0"))
            if duckdb_sync_interval is None
            else duckdb_sync_interval
        )
        dump_path = duckdb_sql_dump_path
        if dump_path is None:
            dump_path = os.getenv("DUCKDB_SQL_DUMP")
        if dump_path is None:
            dump_path = os.getenv("SQL_FILE")
        if dump_path is None:
            dump_path = os.path.join("data", "postgres_dump.sql")

        self._duckdb_mirror: Optional[DuckDBMirror] = None
        if fallback_enabled:
            mirror = DuckDBMirror(
                fallback_path,
                tables,
                sql_dump_path=dump_path,
                auto_sync=auto_sync,
                sync_interval=sync_interval,
            )
            if mirror.available:
                self._duckdb_mirror = mirror
                if mirror.auto_sync:
                    mirror.maybe_sync_from_sql_dump()
            else:
                logger.warning("DuckDB fallback requested but dependencies are unavailable.")

        logger.debug(
            "DBManager initialised with url=%s (retries=%d, interval=%.2fs, duckdb_fallback=%s)",
            self.url,
            self.max_retries,
            self.retry_interval,
            bool(self._duckdb_mirror),
        )

    @staticmethod
    def _is_transient_operational_error(exc: OperationalError) -> bool:
        """Return ``True`` for connectivity problems worth retrying."""

        message = str(exc).lower()
        keywords = {
            "connection refused",
            "could not connect",
            "connection timed out",
            "server closed the connection",
            "connection not open",
            "no such host",
            "terminating connection due to administrator command",
        }
        return any(keyword in message for keyword in keywords)

    def _run_with_retries(self, func: Callable[[], T], op: str) -> T:
        attempts = 0
        while True:
            try:
                return func()
            except OperationalError as exc:
                attempts += 1
                if attempts >= self.max_retries or not self._is_transient_operational_error(exc):
                    logger.error(
                        "Database %s failed after %d attempt(s): %s",
                        op,
                        attempts,
                        exc,
                    )
                    raise
                logger.warning(
                    "Database %s attempt %d/%d failed (%s); retrying in %.1fs",
                    op,
                    attempts,
                    self.max_retries,
                    exc,
                    self.retry_interval,
                )
                if self.retry_interval:
                    time.sleep(self.retry_interval)

    def _maybe_sync_duckdb(self) -> None:
        if self._duckdb_mirror is not None:
            self._duckdb_mirror.maybe_sync_from_sql_dump()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query_df(
        self, sql: str, params: Optional[Mapping[str, Any]] = None
    ) -> pd.DataFrame:
        """Execute a SELECT query and return the results as a DataFrame."""

        logger.debug("Running query: %s | params=%s", sql, params)

        def _query() -> pd.DataFrame:
            with self.engine.connect() as conn:
                return pd.read_sql(text(sql), conn, params=params)

        try:
            result = self._run_with_retries(_query, "query")
        except OperationalError as exc:
            if self._duckdb_mirror and self._is_transient_operational_error(exc):
                if self._duckdb_mirror.ensure_from_sql_dump():
                    logger.warning(
                        "Primary database query failed (%s); using DuckDB fallback.",
                        exc,
                    )
                    try:
                        return self._duckdb_mirror.query_df(sql, params)
                    except Exception as fallback_exc:
                        logger.error("DuckDB fallback query failed: %s", fallback_exc)
                        raise exc
            raise
        else:
            self._maybe_sync_duckdb()
            return result

    def vector_similarity(
        self, query_vector: Sequence[float], *, limit: int = 5
    ) -> pd.DataFrame:
        """Execute a semantic similarity search with DuckDB fallback support."""

        payload = list(query_vector)

        sql = """
            SELECT
                COALESCE(NULLIF(TRIM(p.consumer_product_name), ''), TRIM(p.product_name)) AS product_name,
                COALESCE(NULLIF(TRIM(b.consumer_brand_name), ''), TRIM(b.brand_name)) AS brand_name
            FROM vip_products AS p
            LEFT JOIN vip_brands AS b ON p.vip_brand_id = b.vip_brand_id
            ORDER BY p.embedding <-> :vector
            LIMIT :limit
        """

        def _query() -> pd.DataFrame:
            with self.engine.connect() as conn:
                return pd.read_sql(text(sql), conn, params={"vector": payload, "limit": limit})

        try:
            result = self._run_with_retries(_query, "vector search")
        except OperationalError as exc:
            if self._duckdb_mirror and self._is_transient_operational_error(exc):
                if self._duckdb_mirror.ensure_from_sql_dump():
                    logger.warning(
                        "Primary vector search failed (%s); using DuckDB fallback.",
                        exc,
                    )
                    return self._duckdb_mirror.vector_similarity(payload, limit=limit)
            raise
        else:
            self._maybe_sync_duckdb()
            return result

    def execute(self, sql: str, params: Optional[Mapping[str, Any]] = None) -> None:
        """Execute a non-returning statement (INSERT/UPDATE/DDL)."""

        logger.debug("Executing statement: %s | params=%s", sql, params)

        def _execute() -> None:
            with self.engine.begin() as conn:
                conn.execute(text(sql), params or {})

        self._run_with_retries(_execute, "statement")

    def sync_duckdb_backup(self) -> bool:
        """Manually trigger a DuckDB mirror sync."""

        if self._duckdb_mirror is None:
            logger.debug("DuckDB fallback not configured; sync skipped.")
            return False
        return self._duckdb_mirror.sync_from_sql_dump(force=True)

    def close(self) -> None:
        try:
            self.engine.dispose()
            logger.debug("Database engine disposed")
        except Exception as exc:  # pragma: no cover - best effort cleanup
            logger.exception("Error disposing engine: %s", exc)
        finally:
            if self._duckdb_mirror is not None:
                self._duckdb_mirror.close()


# Global helper similar to the original project
_GLOBAL_DB: Optional[DBManager] = None


def get_db(url: Optional[str] = None) -> DBManager:
    """Get a global database manager instance."""

    global _GLOBAL_DB
    if _GLOBAL_DB is None:
        logger.info("Creating global DBManager instance")
        _GLOBAL_DB = DBManager(url)
    return _GLOBAL_DB

