#!/bin/bash
# polyMad startup script — Phase 2
# Validates secrets, starts FastAPI backend, then starts Streamlit.
# FastAPI runs on port 8000 (internal only).
# Streamlit runs on $PORT (Railway-exposed).

set -e

# ── Validate JWT_SECRET_KEY (hard fail — do not start without it) ─────────────
if [ -z "${JWT_SECRET_KEY}" ] || [ ${#JWT_SECRET_KEY} -lt 32 ]; then
    echo "ERROR: JWT_SECRET_KEY must be set and at least 32 characters."
    echo "Generate a secure value with:"
    echo "  python -c \"import secrets; print(secrets.token_hex(32))\""
    exit 1
fi

# ── Inject secrets from env vars into Streamlit secrets.toml ─────────────────
mkdir -p .streamlit

cat > .streamlit/secrets.toml << EOF
SUPABASE_URL      = "${SUPABASE_URL:-}"
SUPABASE_ANON_KEY = "${SUPABASE_ANON_KEY:-}"
SMTP_USER         = "${SMTP_USER:-}"
SMTP_PASSWORD     = "${SMTP_PASSWORD:-}"
SMTP_FROM         = "${SMTP_FROM:-}"
FASTAPI_BASE_URL  = "http://localhost:8000"
EOF

echo "✓ secrets.toml written"

# ── Export JWT vars so FastAPI subprocess can read them ───────────────────────
export JWT_SECRET_KEY="${JWT_SECRET_KEY}"
export JWT_ALGORITHM="${JWT_ALGORITHM:-HS256}"
export JWT_SECRET_KEY_PREVIOUS="${JWT_SECRET_KEY_PREVIOUS:-}"
export FASTAPI_INTERNAL_URL="http://localhost:8000"
export RAILWAY_PUBLIC_DOMAIN="${RAILWAY_PUBLIC_DOMAIN:-}"

# ── Start FastAPI backend in background ───────────────────────────────────────
echo "→ Starting FastAPI on port 8000..."
uvicorn src.api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips="*" \
    --no-access-log &

FASTAPI_PID=$!

# ── Wait for FastAPI to be healthy (up to 15 seconds) ────────────────────────
echo "→ Waiting for FastAPI to be ready..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "✓ FastAPI is ready"
        break
    fi
    if [ "$i" -eq 15 ]; then
        echo "ERROR: FastAPI did not start within 15 seconds. Check logs."
        kill $FASTAPI_PID 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

# ── Start Streamlit (foreground — Railway monitors this process) ──────────────
PORT="${PORT:-8501}"
echo "→ Starting Streamlit on port $PORT"

exec streamlit run src/dashboard.py \
    --server.port="$PORT" \
    --server.address="0.0.0.0" \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false
