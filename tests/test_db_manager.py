import os
import sys
from textwrap import dedent

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database.db_manager import DBManager


def test_connects_using_db_password(monkeypatch):
    """Placeholder: PostgreSQL connection logic disabled during DuckDB-only testing."""

    pytest.skip("PostgreSQL connection handling is disabled while using DuckDB only")


def test_query_df_retries_on_connection_refused(monkeypatch):
    """Placeholder for transient PostgreSQL retry behaviour."""

    pytest.skip("Transient PostgreSQL retry logic is disabled while using DuckDB only")


def test_query_df_does_not_retry_non_transient_error(monkeypatch):
    """Placeholder for non-transient PostgreSQL error handling."""

    pytest.skip("PostgreSQL retry behaviour tests are disabled in DuckDB-only mode")


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


def test_query_df_uses_duckdb_fallback(tmp_path):
    duckdb_path = tmp_path / "mirror.duckdb"
    sql_dump = tmp_path / "dump.sql"
    _write_basic_inventory_dump(sql_dump)

    mgr = DBManager(
        max_retries=1,
        retry_interval=0,
        enable_duckdb_fallback=True,
        duckdb_path=str(duckdb_path),
        duckdb_tables=["app_inventory"],
        duckdb_auto_sync=False,
        duckdb_sql_dump_path=str(sql_dump),
    )

    try:
        df = mgr.query_df(
            "SELECT store, product_name, brand_name FROM app_inventory",
            params=None,
        )
    finally:
        mgr.close()

    assert list(df.columns) == ["store", "product_name", "brand_name"]
    assert df.iloc[0]["product_name"] == "Widget"


def test_vector_similarity_uses_duckdb_fallback(tmp_path):
    duckdb_path = tmp_path / "mirror.duckdb"
    sql_dump = tmp_path / "dump.sql"
    _write_vector_dump(sql_dump)

    mgr = DBManager(
        max_retries=1,
        retry_interval=0,
        enable_duckdb_fallback=True,
        duckdb_path=str(duckdb_path),
        duckdb_tables=["vip_products", "vip_brands"],
        duckdb_auto_sync=False,
        duckdb_sql_dump_path=str(sql_dump),
    )

    try:
        df = mgr.vector_similarity([0.0, 1.0], limit=2)
    finally:
        mgr.close()

    assert not df.empty
    assert "product_name" in df.columns
    assert df.iloc[0]["product_name"] == "Consumer Gin"
    assert df.iloc[0]["brand_name"] == "Brand Co"


def test_execute_updates_duckdb(tmp_path):
    duckdb_path = tmp_path / "mirror.duckdb"
    sql_dump = tmp_path / "dump.sql"
    _write_vector_dump(sql_dump)

    mgr = DBManager(
        enable_duckdb_fallback=True,
        duckdb_path=str(duckdb_path),
        duckdb_tables=["vip_products", "vip_brands"],
        duckdb_auto_sync=False,
        duckdb_sql_dump_path=str(sql_dump),
    )

    try:
        mgr.execute(
            "UPDATE vip_products SET product_name = :name WHERE vip_product_id = :pid",
            {"name": "Updated Gin", "pid": 1},
        )
        df = mgr.query_df(
            "SELECT product_name FROM vip_products WHERE vip_product_id = :pid",
            {"pid": 1},
        )
    finally:
        mgr.close()

    assert df.iloc[0]["product_name"] == "Updated Gin"
