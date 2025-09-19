#!/usr/bin/env bash
# scripts/smoke_db_via_container_ip.sh
# Smoke-test the WarehouseManagerAI Postgres instance by talking directly to the
# container IP instead of relying on the host port forward. This is helpful when
# localhost:5432 is blocked or owned by another service.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

export REPO_ROOT


log() { echo -e "\n\033[1;34m[smoke]\033[0m $*"; }
die() { echo "❌ $*" >&2; exit 1; }

# Load environment defaults if present
if [ -f .env ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs)
fi

command -v docker >/dev/null 2>&1 || die "docker not found in PATH"
if command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  DC="docker compose"
fi

: "${DB_NAME:?DB_NAME not set (define in .env)}"
: "${DB_USER:?DB_USER not set (define in .env)}"
: "${DB_PASS:?DB_PASS not set (define in .env)}"
: "${DB_PORT:=5432}"
DB_CONTAINER="${DB_CONTAINER:-warehousemanagerai_db}"

log "Ensuring pgvector container is running…"
$DC up -d db

log "Waiting for PostgreSQL readiness inside container…"
until docker exec "$DB_CONTAINER" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; do
  sleep 1
done
log "Postgres is ready."

log "Checking app_inventory view inside the container…"
VIEW_EXISTS=$(
  docker exec -e PGPASSWORD="$DB_PASS" "$DB_CONTAINER" \
    psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT to_regclass('public.app_inventory');" || true
)

if [ "$VIEW_EXISTS" != "app_inventory" ]; then
  echo
  echo "⚠️  app_inventory view missing. Run 'run_all.sh' or apply views/999_app_views.sql first."
  exit 2
fi

log "Sample data from app_inventory (container psql)…"
docker exec -e PGPASSWORD="$DB_PASS" "$DB_CONTAINER" \
  psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT store, product_name, brand_name FROM app_inventory LIMIT 5;" || true

log "Resolving container IP for direct connections…"
DB_CONTAINER_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$DB_CONTAINER" 2>/dev/null || true)
if [ -z "$DB_CONTAINER_IP" ]; then
  die "Unable to determine container IP address"
fi
log "Container IP is $DB_CONTAINER_IP"

# Override host/URL so Python uses the container IP instead of localhost
export DB_HOST="$DB_CONTAINER_IP"
export DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@${DB_CONTAINER_IP}:${DB_PORT}/${DB_NAME}"

MASKED_URL="postgresql://${DB_USER}:***@${DB_CONTAINER_IP}:${DB_PORT}/${DB_NAME}"
log "Using DATABASE_URL=${MASKED_URL}"

log "Running Python smoke test via container IP…"
python3 - <<'PY'
import os, sys, textwrap

ROOT = os.getenv("REPO_ROOT", os.getcwd())

sys.path.append(os.path.join(ROOT, "src"))

from src.agents.product_lookup_agent import ProductLookupAgent
from src.database.db_manager import get_db


db_url = os.getenv("DATABASE_URL", "")
masked = (db_url[: db_url.find("@")] + "@***") if "@" in db_url else (db_url or "(not set)")
print("[py] DATABASE_URL:", masked)


try:
    df = get_db().query_df("SELECT 1 AS ok", None)
    assert not df.empty and int(df.iloc[0]["ok"]) == 1
    print("[py] DB connection OK via container IP.")
except Exception as exc:
    print("[py][x] DB connection failed:", repr(exc))
    raise SystemExit(3)

agent = ProductLookupAgent()
questions = [
    "Do we have gin?",
    "How many items in store 1?",
    "Show me vodka in store 2",
    "How many products match tequila?",
    "products",
]

for q in questions:
    print("\n[py] Q:", q)
    chat_history = [("user", q)]
    try:
        score = agent.score_request(q, chat_history)
        print(f"[py] score_request -> {score:.2f}")
        answer = agent.handle(q, chat_history) or ""
        print(textwrap.shorten("[py] A: " + answer, width=500))
    except Exception as exc:
        print("[py][x] Error:", repr(exc))

print("\n[py] Smoke test complete.")
PY

log "✅ Finished. Python and psql both reached the database using the container IP."
