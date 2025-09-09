#!/usr/bin/env bash
# scripts/test_db_and_agent.sh
# Smoke-test the Dockerized DB + ProductLookupAgent without requiring any extra roles.
# - Starts/uses the "db" service from docker-compose
# - Verifies app_inventory exists
# - Runs a short Python test that calls ProductLookupAgent

set -euo pipefail

# Always run from repo root (adjust if your path differs)
cd /opt/WarehouseManagerAI

# Load env exactly as you requested
if [ -f .env ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs)
fi

log() { echo -e "\n\033[1;32m[test]\033[0m $*"; }
die() { echo "❌ $*" >&2; exit 1; }

# Sanity checks for required tools
command -v docker >/dev/null 2>&1 || die "docker not found"
if command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  DC="docker compose"
fi

# Sanity env (DB_* must be set in .env)
: "${DB_HOST:=localhost}"
: "${DB_PORT:=5432}"
: "${DB_NAME:?DB_NAME missing}"
: "${DB_USER:?DB_USER missing}"
: "${DB_PASS:?DB_PASS missing}"

log "Bringing up Postgres (pgvector) via Docker Compose…"
$DC up -d db

# Wait for DB readiness inside the container (no role assumptions)
log "Waiting for PostgreSQL to become ready…"
until docker exec warehousemanagerai_db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; do
  sleep 1
done
log "Postgres is ready on ${DB_HOST}:${DB_PORT}."

# Verify app_inventory view exists; if not, guide the user and exit
log "Checking for view 'app_inventory'…"
VIEW_EXISTS=$(
  docker exec -e PGPASSWORD="$DB_PASS" warehousemanagerai_db \
    psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT to_regclass('public.app_inventory');" || true
)

if [ "$VIEW_EXISTS" != "app_inventory" ]; then
  echo
  echo "⚠️  The view 'app_inventory' was not found."
  echo "    Run '/opt/WarehouseManagerAI/run_all.sh' first to import data and apply views,"
  echo "    or manually apply 'views/999_app_views.sql' to the database."
  exit 2
fi

# Quick peek
log "Sample rows from app_inventory:"
docker exec -e PGPASSWORD="$DB_PASS" warehousemanagerai_db \
  psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT store, product_name, brand_name FROM app_inventory LIMIT 5;" || true

# Inline Python smoke test for ProductLookupAgent (no roles required)
log "Running Python smoke test for ProductLookupAgent…"
python3 - <<'PY'
import os, sys, textwrap

ROOT = "/opt/WarehouseManagerAI"
sys.path.append(os.path.join(ROOT, "src"))

# Load .env if available
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

# Show DB URL (masked)
db_url = os.getenv("DATABASE_URL", "")
print("[py] DATABASE_URL:", (db_url[: db_url.find("@")] + "@***") if "@" in db_url else db_url or "(not set)")

# Import app modules
from src.agents.product_lookup_agent import ProductLookupAgent
from src.database.db_manager import get_db

# DB ping
try:
    df = get_db().query_df("SELECT 1 AS ok", None)
    assert not df.empty and int(df.iloc[0]["ok"]) == 1
    print("[py] DB connection OK.")
except Exception as e:
    print("[py][x] DB connection failed:", repr(e))
    raise SystemExit(3)

agent = ProductLookupAgent()
tests = [
    "Do we have gin?",
    "How many items in store 1?",
    "Show me vodka in store 2",
    "How many products match tequila?",
    "products",
]

for q in tests:
    print("\n[py] Q:", q)
    try:
        ans = agent.handle(q)
        print(textwrap.shorten("[py] A: " + (ans or ""), width=500))
    except Exception as e:
        print("[py][x] Error:", repr(e))

print("\n[py] Smoke test complete.")
PY

echo
log "✅ Done. If the answers look reasonable, your DB + agent path is working."
echo "   Next step: embeddings + Streamlit, or expand tests as needed."

