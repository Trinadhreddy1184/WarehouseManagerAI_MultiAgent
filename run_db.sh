#!/usr/bin/env bash
set -euo pipefail

log() { printf "\n\033[1;32m[run_all]\033[0m %s\n" "$*"; }
die() { echo "❌ $*" >&2; exit 1; }

# load .env if present
if [ -f .env ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs)
fi


: "${DB_HOST:=localhost}"
: "${DB_PORT:=5432}"
: "${DB_NAME:=warehouse}"
: "${DB_USER:=app}"
: "${DB_PASS:=app_pw}"
: "${AWS_REGION:=${AWS_DEFAULT_REGION:-us-east-1}}"

# choose dump source
: "${S3_BUCKET:=scotch-sampledata}"
: "${S3_KEY:=vip_tables_20250623.sql}"
: "${S3_PRESIGNED_URL:=}"
: "${SQL_FILE:=}"

APP_DIR="${APP_DIR:-/opt/WarehouseManagerAI}"
VIEWS_SQL="${VIEWS_SQL:-$APP_DIR/views/999_app_views.sql}"
TMP_DIR="$APP_DIR/tmp"
mkdir -p "$TMP_DIR"

# helper: run admin psql as the local postgres superuser
psql_admin() {
  if sudo -n -u postgres true 2>/dev/null; then
    sudo -u postgres psql "$@"
  else
    # fallback: try passwordless local socket as postgres
    psql -U postgres "$@"
  fi
}

# 0) wait for postgres
log "Waiting for Postgres at $DB_HOST:$DB_PORT…"
for i in {1..60}; do
  if pg_isready -h "$DB_HOST" -p "$DB_PORT" -q; then
    log "Postgres is ready."
    break
  fi
  sleep 2
  [[ $i -eq 60 ]] && die "Postgres is not ready on $DB_HOST:$DB_PORT"
done

# 1) ensure role/db/extension
log "Ensuring role '$DB_USER', db '$DB_NAME', and pgvector extension…"
psql_admin -v ON_ERROR_STOP=1 -d postgres -c "DO \$\$BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASS}';
  END IF;
END\$\$;"
psql_admin -v ON_ERROR_STOP=1 -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 \
  || psql_admin -v ON_ERROR_STOP=1 -d postgres -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
psql_admin -v ON_ERROR_STOP=1 -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 2) locate or download SQL dump
RAW_DUMP="${SQL_FILE:-$TMP_DIR/100_dump.sql}"
if [[ -z "${SQL_FILE}" ]]; then
  if [[ -n "${S3_PRESIGNED_URL}" ]]; then
    if [[ ! -f "$RAW_DUMP" ]]; then
      log "Downloading dump via presigned URL → $RAW_DUMP"
      curl -fSL "$S3_PRESIGNED_URL" -o "$RAW_DUMP"
    else
      log "Using cached dump at $RAW_DUMP"
    fi
  else
    if [[ ! -f "$RAW_DUMP" ]]; then
      command -v aws >/dev/null 2>&1 || die "aws CLI not found; set SQL_FILE or install aws cli"
      log "Downloading dump from s3://$S3_BUCKET/$S3_KEY → $RAW_DUMP"
      aws s3 cp "s3://$S3_BUCKET/$S3_KEY" "$RAW_DUMP" --region "$AWS_REGION"
    else
      log "Using cached dump at $RAW_DUMP"
    fi
  fi
fi
[[ -f "$RAW_DUMP" ]] || die "Dump not found at $RAW_DUMP"

# 3) reset database (clean import each run)
log "Resetting database '$DB_NAME' for a clean import…"
psql_admin -v ON_ERROR_STOP=1 -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}';" || true
psql_admin -v ON_ERROR_STOP=1 -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME};"
psql_admin -v ON_ERROR_STOP=1 -d postgres -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
psql_admin -v ON_ERROR_STOP=1 -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 4) import dump (no sanitization)
log "Importing SQL dump into '$DB_NAME' (this may take a while)…"
PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  --single-transaction -v ON_ERROR_STOP=1 -f "$RAW_DUMP"

# 5) apply app views
[[ -f "$VIEWS_SQL" ]] || die "Missing $VIEWS_SQL"
log "Applying $VIEWS_SQL …"
PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$VIEWS_SQL"

# 6) verify
log "Verifying app_inventory…"
PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT COUNT(*) AS total_items FROM app_inventory;"
PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT store, product_name, brand_name FROM app_inventory LIMIT 5;"

log "✅ Done."

