import os
import sys
from dataclasses import dataclass
from textwrap import dedent

import pandas as pd
import pytest
from sqlalchemy.exc import OperationalError

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database.db_manager import DBManager


def test_connects_using_db_password(monkeypatch):
    """DBManager should honour DB_PASSWORD environment variable."""

    # Ensure compatibility variable is absent and DATABASE_URL not set
    monkeypatch.delenv("DB_PASS", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_PASSWORD", "secret")

    mgr = DBManager(enable_duckdb_fallback=False)
    try:
        assert mgr.engine.url.password == "secret"
    finally:
        mgr.close()


@dataclass
class _DummyConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_query_df_retries_on_connection_refused(monkeypatch):
    mgr = DBManager(
        "postgresql://app:pw@localhost:5432/warehouse",
        max_retries=3,
        retry_interval=0,
        enable_duckdb_fallback=False,
    )

    attempts = {"count": 0}

    def flaky_connect():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise OperationalError(
                'connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused',
                None,
                None,
            )
        return _DummyConnection()

    monkeypatch.setattr(mgr.engine, "connect", flaky_connect)

    results = {"called": 0}

    def fake_read_sql(query, conn, params=None):
        results["called"] += 1
        return pd.DataFrame(
            {"store": ["A"], "product_name": ["Widget"], "brand_name": ["Brand"]}
        )

    monkeypatch.setattr(pd, "read_sql", fake_read_sql)

    try:
        df = mgr.query_df(
            "SELECT store, product_name, brand_name FROM app_inventory LIMIT 5",
            params=None,
        )
    finally:
        mgr.close()

    assert attempts["count"] == 3
    assert results["called"] == 1
    assert not df.empty


def test_query_df_does_not_retry_non_transient_error(monkeypatch):
    mgr = DBManager(
        "postgresql://app:pw@localhost:5432/warehouse",
        max_retries=3,
        retry_interval=0,
        enable_duckdb_fallback=False,
    )

    attempts = {"count": 0}

    def failing_connect():
        attempts["count"] += 1
        raise OperationalError("syntax error at or near \"SELECT\"", None, None)

    monkeypatch.setattr(mgr.engine, "connect", failing_connect)

    with pytest.raises(OperationalError):
        mgr.query_df("SELECT * FROM bad_table", params=None)

    mgr.close()
    assert attempts["count"] == 1


def _write_basic_inventory_dump(path):
    path.write_text(
        dedent(
            """
            CREATE SCHEMA public;
            CREATE TABLE public.app_inventory (
                store TEXT,
                product_name TEXT,
                brand_name TEXT
            );
            COPY public.app_inventory (store, product_name, brand_name) FROM stdin;
            A\tWidget\tBrandCo
            \\.
            """
        ).lstrip(),
        encoding="utf-8",
    )


def _write_vector_dump(path):
    path.write_text(
        dedent(
            """
            CREATE SCHEMA public;
            CREATE TABLE public.vip_products (
                vip_product_id INTEGER,
                vip_brand_id INTEGER,
                consumer_product_name TEXT,
                product_name TEXT,
                embedding TEXT
            );
            CREATE TABLE public.vip_brands (
                vip_brand_id INTEGER,
                consumer_brand_name TEXT,
                brand_name TEXT
            );
            COPY public.vip_products (vip_product_id, vip_brand_id, consumer_product_name, product_name, embedding) FROM stdin;
            1\t1\tConsumer Gin\tGin\t[0.0, 1.0]
            2\t2\tOther Product\tOther\t[1.0, 0.0]
            \\.
            COPY public.vip_brands (vip_brand_id, consumer_brand_name, brand_name) FROM stdin;
            1\tBrand Co\tBrand Co
            2\tOther Brand\tOther Brand
            \\.
            """
        ).lstrip(),
        encoding="utf-8",
    )


def test_query_df_uses_duckdb_fallback(monkeypatch, tmp_path):
    duckdb_path = tmp_path / "mirror.duckdb"
    sql_dump = tmp_path / "dump.sql"
    _write_basic_inventory_dump(sql_dump)

    mgr = DBManager(
        "postgresql://app:pw@localhost:5432/warehouse",
        max_retries=1,
        retry_interval=0,
        enable_duckdb_fallback=True,
        duckdb_path=str(duckdb_path),
        duckdb_tables=["app_inventory"],
        duckdb_auto_sync=False,
        duckdb_sql_dump_path=str(sql_dump),
    )

    def failing_connect():
        raise OperationalError(
            'connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused',
            None,
            None,
        )

    monkeypatch.setattr(mgr.engine, "connect", failing_connect)

    try:
        df = mgr.query_df(
            "SELECT store, product_name, brand_name FROM app_inventory",
            params=None,
        )
    finally:
        mgr.close()

    assert list(df.columns) == ["store", "product_name", "brand_name"]
    assert df.iloc[0]["product_name"] == "Widget"


def test_vector_similarity_uses_duckdb_fallback(monkeypatch, tmp_path):
    duckdb_path = tmp_path / "mirror.duckdb"
    sql_dump = tmp_path / "dump.sql"
    _write_vector_dump(sql_dump)

    mgr = DBManager(
        "postgresql://app:pw@localhost:5432/warehouse",
        max_retries=1,
        retry_interval=0,
        enable_duckdb_fallback=True,
        duckdb_path=str(duckdb_path),
        duckdb_tables=["vip_products", "vip_brands"],
        duckdb_auto_sync=False,
        duckdb_sql_dump_path=str(sql_dump),
    )

    def failing_connect():
        raise OperationalError(
            'connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused',
            None,
            None,
        )

    monkeypatch.setattr(mgr.engine, "connect", failing_connect)

    try:
        df = mgr.vector_similarity([0.0, 1.0], limit=5)
    finally:
        mgr.close()

    assert not df.empty
    assert df.iloc[0]["product_name"] == "Consumer Gin"
    assert df.iloc[0]["brand_name"] == "Brand Co"

