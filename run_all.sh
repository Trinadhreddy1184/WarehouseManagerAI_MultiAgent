#!/usr/bin/env bash
set -euo pipefail
cd /opt/WarehouseManagerAI

# Load env exactly as you requested
if [ -f .env ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs)
fi

log() { echo -e "\n\033[1;32m[run_all]\033[0m $*"; }
die() { echo "❌ $*" >&2; exit 1; }

# Required env (your set)
: "${BEDROCK_MODEL_ID:?missing}"
: "${LLM_TEMPERATURE:?missing}"
: "${LLM_TOP_P:?missing}"
: "${LLM_MAX_TOKENS:?missing}"

: "${S3_BUCKET:?missing}"
: "${S3_KEY:?missing}"

: "${DB_HOST:=localhost}"
: "${DB_PORT:=5432}"
: "${DB_NAME:?missing}"
: "${DB_USER:?missing}"
: "${DB_PASS:?missing}"
: "${DATABASE_URL:=postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}}"

APP_DIR="/opt/WarehouseManagerAI"
VIEWS_SQL="${APP_DIR}/views/999_app_views.sql"

# Pick compose command
if command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  DC="docker compose"
fi

# Free port 5432 in case host PG is running
sudo systemctl stop postgresql >/dev/null 2>&1 || true
sudo fuser -k 5432/tcp >/dev/null 2>&1 || true

log "Starting Postgres (pgvector) via Docker Compose…"
$DC up -d db || true

STATUS=$(docker inspect -f '{{.State.Status}}' warehousemanagerai_db 2>/dev/null || echo "not-found")
if [ "$STATUS" != "running" ]; then
  log "Container status: $STATUS. Resetting volume and retrying…"
  $DC down
  docker volume rm warehousemanagerai_db_data >/dev/null 2>&1 || true
  $DC up -d db
fi

log "Waiting for Postgres to be ready…"
until docker exec warehousemanagerai_db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; do
  sleep 1
done
log "Postgres is ready on ${DB_HOST}:${DB_PORT}"

# Helper: stream filter to drop problematic role lines (NO temp files)
stream_filter() {
  # Remove GRANT/REVOKE statements (any target), and strip owner changes
  # This avoids missing-role errors like 'crunchy_read_only'
  sed -E \
    -e '/^\s*GRANT\s+/I d' \
    -e '/^\s*REVOKE\s+/I d' \
    -e '/ALTER\s+.*\s+OWNER\s+TO\s+[^;]+;/I d'
}

# Check for existing data
log "Checking for existing data (vip_products)…"
TABLE_EXISTS=$(
  docker exec -e PGPASSWORD="$DB_PASS" warehousemanagerai_db \
    psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT to_regclass('public.vip_products');" || true
)

if [ "$TABLE_EXISTS" = "vip_products" ]; then
  log "Data already present; skipping import."
  docker exec -e PGPASSWORD="$DB_PASS" warehousemanagerai_db \
    psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;"
else
  log "No data found; preparing schema + extension…"
  docker exec -e PGPASSWORD="$DB_PASS" warehousemanagerai_db \
    psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public AUTHORIZATION ${DB_USER};"
  docker exec -e PGPASSWORD="$DB_PASS" warehousemanagerai_db \
    psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;"

  if [ -n "${SQL_FILE:-}" ] && [ -f "$SQL_FILE" ]; then
    log "Importing from local file: $SQL_FILE (sanitized grants/owners)"
    stream_filter < "$SQL_FILE" | docker exec -i -e PGPASSWORD="$DB_PASS" warehousemanagerai_db \
      psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1
  elif [ -n "${S3_PRESIGNED_URL:-}" ]; then
    log "Importing from presigned URL (sanitized grants/owners)…"
    curl -sSL "$S3_PRESIGNED_URL" | stream_filter | docker exec -i -e PGPASSWORD="$DB_PASS" warehousemanagerai_db \
      psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1
  else
    log "Importing from s3://$S3_BUCKET/$S3_KEY (sanitized grants/owners)…"
    aws s3 cp "s3://${S3_BUCKET}/${S3_KEY}" - | stream_filter | docker exec -i -e PGPASSWORD="$DB_PASS" warehousemanagerai_db \
      psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1
  fi
  log "Import complete."

  # Post-import: normalize ownership & permissions for app user
  log "Normalizing ownership to ${DB_USER} and granting read permissions…"
  docker exec -e PGPASSWORD="$DB_PASS" warehousemanagerai_db psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 <<PSQL
-- Make sure public schema belongs to app
ALTER SCHEMA public OWNER TO "${DB_USER}";

-- Reassign owners of tables, sequences, views, materialized views
DO \$\$
DECLARE r RECORD;
BEGIN
  -- Tables
  FOR r IN SELECT quote_ident(schemaname) AS s, quote_ident(tablename) AS n
           FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE 'ALTER TABLE ' || r.s || '.' || r.n || ' OWNER TO "${DB_USER}"';
  END LOOP;

  -- Sequences
  FOR r IN SELECT quote_ident(sequence_schema) AS s, quote_ident(sequence_name) AS n
           FROM information_schema.sequences WHERE sequence_schema='public' LOOP
    EXECUTE 'ALTER SEQUENCE ' || r.s || '.' || r.n || ' OWNER TO "${DB_USER}"';
  END LOOP;

  -- Views
  FOR r IN SELECT quote_ident(schemaname) AS s, quote_ident(viewname) AS n
           FROM pg_views WHERE schemaname='public' LOOP
    EXECUTE 'ALTER VIEW ' || r.s || '.' || r.n || ' OWNER TO "${DB_USER}"';
  END LOOP;

  -- Materialized views
  FOR r IN SELECT quote_ident(schemaname) AS s, quote_ident(matviewname) AS n
           FROM pg_matviews WHERE schemaname='public' LOOP
    EXECUTE 'ALTER MATERIALIZED VIEW ' || r.s || '.' || r.n || ' OWNER TO "${DB_USER}"';
  END LOOP;
END
\$\$;

-- Default privileges for future objects in public: readable by PUBLIC
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO PUBLIC;

-- Grant read on existing tables to PUBLIC (so any connector you use can read)
GRANT USAGE ON SCHEMA public TO PUBLIC;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO PUBLIC;
PSQL
fi

# Apply view if missing
if [ ! -f "$VIEWS_SQL" ]; then
  die "Missing $VIEWS_SQL"
fi
VIEW_EXISTS=$(
  docker exec -e PGPASSWORD="$DB_PASS" warehousemanagerai_db \
    psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT to_regclass('public.app_inventory');" || true
)
if [ "$VIEW_EXISTS" = "app_inventory" ]; then
  log "View app_inventory already exists; skipping SQL apply."
else
  log "Applying ${VIEWS_SQL} …"
  docker exec -i -e PGPASSWORD="$DB_PASS" warehousemanagerai_db \
    psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 < "$VIEWS_SQL"
  log "Views applied."
fi

# Export DB URL for app
export DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
log "DATABASE_URL set to: ${DATABASE_URL}"

# Verify
log "Verifying app_inventory…"
docker exec -e PGPASSWORD="$DB_PASS" warehousemanagerai_db \
  psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT COUNT(*) AS total_items FROM app_inventory;" || true
docker exec -e PGPASSWORD="$DB_PASS" warehousemanagerai_db \
  psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT store, product_name, brand_name FROM app_inventory LIMIT 5;" || true

log "✅ Postgres in Docker is ready, with grants/owners stripped (no extra roles needed)."

# At the bottom of run_all.sh, after database setup:
log "Launching Streamlit UI..."
pkill -f "streamlit run" 2>/dev/null || true
streamlit run src/ui/app.py --server.port 8501 --server.address 0.0.0.0


