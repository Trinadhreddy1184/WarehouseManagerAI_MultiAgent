#!/usr/bin/env bash
set -euo pipefail
cd /opt/WarehouseManagerAI
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt


# Load env exactly as you requested
if [ -f .env ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs)
fi

: "${ENABLE_LLM:=0}"
export ENABLE_LLM

log() { echo -e "\n\033[1;32m[run_all]\033[0m $*"; }
die() { echo "❌ $*" >&2; exit 1; }

# Required env (your set)
case "${ENABLE_LLM:-}" in
  1|true|TRUE|True|yes|YES|Yes|on|ON|On)
    : "${BEDROCK_MODEL_ID:?missing}"
    : "${LLM_TEMPERATURE:?missing}"
    : "${LLM_TOP_P:?missing}"
    : "${LLM_MAX_TOKENS:?missing}"
    ;;
  *)
    log "ENABLE_LLM not set – skipping Bedrock environment checks"
    ;;
esac

APP_DIR="/opt/WarehouseManagerAI"

# DuckDB paths used across the app.  The SQL dump mirrors the structure of the
# legacy PostgreSQL database so DuckDB can be refreshed from the same data.
DUCKDB_DB_PATH="${DUCKDB_DB_PATH:-$APP_DIR/data/postgres_mirror.duckdb}"
DUCKDB_SQL_DUMP="${DUCKDB_SQL_DUMP:-$APP_DIR/data/postgres_dump.sql}"
mkdir -p "$(dirname "$DUCKDB_DB_PATH")"
mkdir -p "$(dirname "$DUCKDB_SQL_DUMP")"

export DUCKDB_FALLBACK_PATH="$DUCKDB_DB_PATH"
export DUCKDB_SQL_DUMP
<<<<<<< HEAD
: "${DUCKDB_AUTO_SYNC:=0}"
export DUCKDB_AUTO_SYNC
=======
>>>>>>> parent of 0a02353 (Revert "feat: run DuckDB-only workflows and disable LLM features")

# Pick compose command
if command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  DC="docker compose"
fi

# Legacy PostgreSQL orchestration is temporarily disabled while running in a
# DuckDB-only configuration.  The Docker compose stack is left untouched so it
# can be re-enabled later if required.
#
# sudo systemctl stop postgresql >/dev/null 2>&1 || true
# sudo fuser -k 5432/tcp >/dev/null 2>&1 || true
#
# log "Starting Postgres (pgvector) via Docker Compose…"
# $DC up -d db || true
#
# STATUS=$(docker inspect -f '{{.State.Status}}' warehousemanagerai_db 2>/dev/null || echo "not-found")
# if [ "$STATUS" != "running" ]; then
#   log "Container status: $STATUS. Resetting volume and retrying…"
#   $DC down
#   docker volume rm warehousemanagerai_db_data >/dev/null 2>&1 || true
#   $DC up -d db
# fi
#
# log "Waiting for Postgres to be ready…"
# until docker exec warehousemanagerai_db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; do
#   sleep 1
# done
# log "Postgres is ready on ${DB_HOST}:${DB_PORT}"

# Helper: stream filter to drop problematic role lines (NO temp files)
stream_filter() {
  # Remove GRANT/REVOKE statements (any target), and strip owner changes
  # This avoids missing-role errors like 'crunchy_read_only'
  sed -E \
    -e '/^\s*GRANT\s+/I d' \
    -e '/^\s*REVOKE\s+/I d' \
    -e '/ALTER\s+.*\s+OWNER\s+TO\s+[^;]+;/I d'
}

# DuckDB-only data loading ----------------------------------------------------

if [ -n "${SQL_FILE:-}" ] && [ -f "$SQL_FILE" ]; then
  log "Importing from local file: $SQL_FILE (sanitized grants/owners)"
  stream_filter < "$SQL_FILE" > "$DUCKDB_SQL_DUMP"
elif [ -n "${S3_PRESIGNED_URL:-}" ]; then
  log "Importing from presigned URL (sanitized grants/owners)…"
  curl -sSL "$S3_PRESIGNED_URL" | stream_filter > "$DUCKDB_SQL_DUMP"
else
  : "${S3_BUCKET:?missing}"
  : "${S3_KEY:?missing}"
  log "Importing from s3://$S3_BUCKET/$S3_KEY (sanitized grants/owners)…"
  aws s3 cp "s3://${S3_BUCKET}/${S3_KEY}" - | stream_filter > "$DUCKDB_SQL_DUMP"
fi
log "Sanitized SQL dump written to $DUCKDB_SQL_DUMP for DuckDB refresh."

log "Building DuckDB database at $DUCKDB_DB_PATH"
python3 <<'PY'
import os
import sys
from pathlib import Path
<<<<<<< HEAD
from textwrap import dedent
=======
>>>>>>> parent of 0a02353 (Revert "feat: run DuckDB-only workflows and disable LLM features")

ROOT = Path.cwd()
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from src.database.db_manager import DBManager

dump = os.environ["DUCKDB_SQL_DUMP"]
db_path = os.environ["DUCKDB_FALLBACK_PATH"]

manager = DBManager(
    enable_duckdb_fallback=True,
    duckdb_path=db_path,
    duckdb_auto_sync=False,
    duckdb_sql_dump_path=dump,
)
try:
<<<<<<< HEAD
    synced = manager.sync_duckdb_backup()
    if not synced:
        print(
            "[run_all] DuckDB sync skipped (no usable SQL dump). Building sample dataset…",
            flush=True,
        )
        import duckdb

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(db_path)
        try:
            conn.execute("CREATE SCHEMA IF NOT EXISTS public;")
            conn.execute("SET schema 'public'")
            conn.execute("DROP VIEW IF EXISTS app_inventory")
            conn.execute("DROP TABLE IF EXISTS vip_items")
            conn.execute("DROP TABLE IF EXISTS vip_products")
            conn.execute("DROP TABLE IF EXISTS vip_brands")
            conn.execute(
                """
                CREATE TABLE vip_brands (
                    vip_brand_id INTEGER,
                    consumer_brand_name TEXT,
                    brand_name TEXT,
                    brand_short_name TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO vip_brands VALUES
                    (1, 'Sunrise Distillers', 'Sunrise Distillers', 'Sunrise'),
                    (2, 'Moonlight Brewing', 'Moonlight Brewing', 'Moonlight')
                """
            )
            conn.execute(
                """
                CREATE TABLE vip_products (
                    vip_product_id INTEGER,
                    vip_brand_id INTEGER,
                    consumer_product_name TEXT,
                    product_name TEXT,
                    product_short_name TEXT,
                    fanciful_name TEXT,
                    embedding TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO vip_products VALUES
                    (1, 1, 'Sunrise Gin', 'Sunrise Gin', 'Sunrise', 'Sunrise Reserve', '[0.1, 0.8, 0.1]'),
                    (2, 2, 'Moonlight Stout', 'Moonlight Stout', 'Moon Stout', 'Moonlight Special', '[0.8, 0.1, 0.1]')
                """
            )
            conn.execute(
                """
                CREATE TABLE vip_items (
                    vip_item_id INTEGER,
                    vip_product_id INTEGER,
                    store TEXT,
                    vip_source_id INTEGER,
                    quantity INTEGER,
                    price DOUBLE,
                    last_updated TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                INSERT INTO vip_items VALUES
                    (1, 1, 'Downtown Store', 101, 42, 24.99, '2024-01-01 10:00:00'),
                    (2, 2, 'Uptown Store', 102, 18, 12.49, '2024-01-02 09:30:00')
                """
            )
            conn.execute(
                """
                CREATE OR REPLACE VIEW app_inventory AS
                SELECT
                    i.*,
                    COALESCE(
                        NULLIF(TRIM(p.consumer_product_name), ''),
                        NULLIF(TRIM(p.product_name), ''),
                        NULLIF(TRIM(p.product_short_name), ''),
                        NULLIF(TRIM(p.fanciful_name), ''),
                        'Unknown'
                    ) AS product_name,
                    COALESCE(
                        NULLIF(TRIM(b.consumer_brand_name), ''),
                        NULLIF(TRIM(b.brand_name), ''),
                        NULLIF(TRIM(b.brand_short_name), ''),
                        'Unknown'
                    ) AS brand_name
                FROM vip_items i
                JOIN vip_products p ON p.vip_product_id = i.vip_product_id
                JOIN vip_brands b ON b.vip_brand_id = p.vip_brand_id
                """
            )
            conn.execute("CHECKPOINT;")
        finally:
            conn.close()

        dump_path = Path(dump)
        if not dump_path.exists() or dump_path.stat().st_size == 0:
            dump_path.write_text(
                dedent(
                    """
                    CREATE SCHEMA IF NOT EXISTS public;
                    CREATE TABLE IF NOT EXISTS public.vip_brands (
                        vip_brand_id INTEGER,
                        consumer_brand_name TEXT,
                        brand_name TEXT,
                        brand_short_name TEXT
                    );
                    INSERT INTO public.vip_brands VALUES
                        (1, 'Sunrise Distillers', 'Sunrise Distillers', 'Sunrise'),
                        (2, 'Moonlight Brewing', 'Moonlight Brewing', 'Moonlight');
                    CREATE TABLE IF NOT EXISTS public.vip_products (
                        vip_product_id INTEGER,
                        vip_brand_id INTEGER,
                        consumer_product_name TEXT,
                        product_name TEXT,
                        product_short_name TEXT,
                        fanciful_name TEXT,
                        embedding TEXT
                    );
                    INSERT INTO public.vip_products VALUES
                        (1, 1, 'Sunrise Gin', 'Sunrise Gin', 'Sunrise', 'Sunrise Reserve', '[0.1, 0.8, 0.1]'),
                        (2, 2, 'Moonlight Stout', 'Moonlight Stout', 'Moon Stout', 'Moonlight Special', '[0.8, 0.1, 0.1]');
                    CREATE TABLE IF NOT EXISTS public.vip_items (
                        vip_item_id INTEGER,
                        vip_product_id INTEGER,
                        store TEXT,
                        vip_source_id INTEGER,
                        quantity INTEGER,
                        price DOUBLE,
                        last_updated TIMESTAMP
                    );
                    INSERT INTO public.vip_items VALUES
                        (1, 1, 'Downtown Store', 101, 42, 24.99, '2024-01-01 10:00:00'),
                        (2, 2, 'Uptown Store', 102, 18, 12.49, '2024-01-02 09:30:00');
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
=======
>>>>>>> parent of 0a02353 (Revert "feat: run DuckDB-only workflows and disable LLM features")
    manager.sync_duckdb_backup()
finally:
    manager.close()
PY

if [ ! -f "$DUCKDB_DB_PATH" ]; then
  die "DuckDB database was not created at $DUCKDB_DB_PATH"
fi

# Apply view definitions directly in DuckDB
log "Generating app_inventory view for DuckDB…"
python3 <<'PY'
import os
import sys
from pathlib import Path

ROOT = Path.cwd()
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from src.database.db_manager import DBManager

manager = DBManager(
    enable_duckdb_fallback=True,
    duckdb_auto_sync=False,
)
try:
    columns_df = manager.query_df(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'vip_items'
        """,
        None,
    )
    col_names = {name.lower() for name in columns_df["column_name"].tolist()}
    has_store = "store" in col_names
    has_source_id = "vip_source_id" in col_names

    select_parts = ["i.*"]
    if not has_store:
        if has_source_id:
            select_parts.append("('source_' || CAST(i.vip_source_id AS VARCHAR)) AS store")
        else:
            select_parts.append("CAST(NULL AS VARCHAR) AS store")

    product_expr = """
            COALESCE(NULLIF(TRIM(p.consumer_product_name), ''),
                     NULLIF(TRIM(p.product_name), ''),
                     NULLIF(TRIM(p.product_short_name), ''),
                     NULLIF(TRIM(p.fanciful_name), ''),
                     'Unknown') AS product_name
        """.strip()

    brand_expr = """
            COALESCE(NULLIF(TRIM(b.consumer_brand_name), ''),
                     NULLIF(TRIM(b.brand_name), ''),
                     NULLIF(TRIM(b.brand_short_name), ''),
                     'Unknown') AS brand_name
        """.strip()

    select_parts.extend([product_expr, brand_expr])

    select_clause = ",\n        ".join(select_parts)
    manager.execute("DROP VIEW IF EXISTS app_inventory")
    manager.execute(
        f"""
        CREATE VIEW app_inventory AS
        SELECT
        {select_clause}
        FROM vip_items i
        JOIN vip_products p ON p.vip_product_id = i.vip_product_id
        JOIN vip_brands b ON b.vip_brand_id = p.vip_brand_id
        """
    )
finally:
    manager.close()
PY

# Export DB URL for app (duckdb:// URI)
export DATABASE_URL="duckdb:///${DUCKDB_DB_PATH}"
log "DATABASE_URL set to: ${DATABASE_URL}"

log "Verifying app_inventory via DuckDB…"
python3 <<'PY'
import os
import sys
from pathlib import Path

ROOT = Path.cwd()
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from src.database.db_manager import DBManager

manager = DBManager(
    enable_duckdb_fallback=True,
    duckdb_auto_sync=False,
)
try:
    df = manager.query_df("SELECT COUNT(*) AS total_items FROM app_inventory", None)
    print(df.to_string(index=False))
    preview = manager.query_df(
        "SELECT store, product_name, brand_name FROM app_inventory LIMIT 5",
        None,
    )
    print(preview.to_string(index=False))
finally:
    manager.close()
PY

log "Exporting database schema to src/database/schema.json using DuckDB"
python3 <<'PY'
import json
import os
import sys
from pathlib import Path

ROOT = Path.cwd()
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from src.database.db_manager import DBManager

schema_path = Path("src/database/schema.json")
manager = DBManager(
    enable_duckdb_fallback=True,
    duckdb_auto_sync=False,
)
try:
    df = manager.query_df(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
        """,
        None,
    )
finally:
    manager.close()

schema = {}
for table, column in zip(df["table_name"], df["column_name"]):
    schema.setdefault(table, []).append(column)

schema_path.parent.mkdir(parents=True, exist_ok=True)
schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
PY

log "✅ DuckDB is ready with sanitized data."



# At the bottom of run_all.sh, after database setup:
log "Launching Streamlit UI..."
pkill -f "streamlit run" 2>/dev/null || true
nohup streamlit run src/ui/app.py --server.address 0.0.0.0 --server.port 8501 > app.log 2>&1 &
sleep 2
tail -n 200 app.log
