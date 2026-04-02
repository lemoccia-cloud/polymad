#!/bin/bash
# dev.sh — start FastAPI + Streamlit locally for development
#
# Usage:
#   bash scripts/dev.sh
#
# Reads SUPABASE_* from .streamlit/secrets.toml automatically.
# Stripe keys are read from environment if already exported, otherwise
# stub values are used (billing endpoints will return 503, rest works fine).

set -e
cd "$(dirname "$0")/.."

PYTHON="/usr/local/bin/python3.11"

# ── Read secrets.toml ─────────────────────────────────────────────────────────
SECRETS=".streamlit/secrets.toml"
_val() { grep "^$1" "$SECRETS" 2>/dev/null | sed 's/.*= *"\(.*\)"/\1/' | tr -d ' '; }

export SUPABASE_URL="${SUPABASE_URL:-$(_val SUPABASE_URL)}"
export SUPABASE_ANON_KEY="${SUPABASE_ANON_KEY:-$(_val SUPABASE_ANON_KEY)}"
export SMTP_USER="${SMTP_USER:-$(_val SMTP_USER)}"
export SMTP_PASSWORD="${SMTP_PASSWORD:-$(_val SMTP_PASSWORD)}"
export SMTP_FROM="${SMTP_FROM:-$(_val SMTP_FROM)}"
export FASTAPI_INTERNAL_URL="http://localhost:8000"

# JWT key — generate a stable dev key if not set
if [ -z "$JWT_SECRET_KEY" ]; then
    KEY_FILE=".dev_jwt_key"
    if [ ! -f "$KEY_FILE" ]; then
        $PYTHON -c "import secrets; print(secrets.token_hex(32))" > "$KEY_FILE"
        echo "✓ Generated dev JWT key → $KEY_FILE (gitignored)"
    fi
    export JWT_SECRET_KEY="$(cat $KEY_FILE)"
fi

# Stripe stubs (billing endpoints gracefully return 503 without real keys)
export STRIPE_SECRET_KEY="${STRIPE_SECRET_KEY:-sk_test_stub}"
export STRIPE_WEBHOOK_SECRET="${STRIPE_WEBHOOK_SECRET:-whsec_stub}"
export STRIPE_PRICE_PRO_MONTHLY="${STRIPE_PRICE_PRO_MONTHLY:-price_stub_pro}"
export STRIPE_PRICE_TRADER_MONTHLY="${STRIPE_PRICE_TRADER_MONTHLY:-price_stub_trader}"

echo "╔══════════════════════════════════╗"
echo "║  polyMad dev server              ║"
echo "╚══════════════════════════════════╝"
echo "  Supabase : $SUPABASE_URL"
echo "  FastAPI  : http://localhost:8000"
echo "  Streamlit: http://localhost:8501"
echo ""

# ── Start FastAPI ─────────────────────────────────────────────────────────────
echo "→ Starting FastAPI..."
$PYTHON -m uvicorn src.api.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --reload \
    --log-level warning &
FASTAPI_PID=$!

# Wait for FastAPI to be ready
for i in $(seq 1 15); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "✓ FastAPI ready (pid $FASTAPI_PID)"
        break
    fi
    if [ "$i" -eq 15 ]; then
        echo "✗ FastAPI did not start. Check for import errors above."
        kill $FASTAPI_PID 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

# ── Start Streamlit ───────────────────────────────────────────────────────────
echo "→ Starting Streamlit..."
trap "kill $FASTAPI_PID 2>/dev/null; exit" INT TERM

$PYTHON -m streamlit run src/dashboard.py \
    --server.port 8501 \
    --server.address 127.0.0.1 \
    --server.headless false

kill $FASTAPI_PID 2>/dev/null || true
