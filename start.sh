#!/bin/bash
# polyMad startup script
# Generates .streamlit/secrets.toml from environment variables,
# then starts the Streamlit app on $PORT (Railway/Render) or 8501 (default).

set -e

# ── Inject secrets from env vars ─────────────────────────────────────────────
mkdir -p .streamlit

cat > .streamlit/secrets.toml << EOF
SUPABASE_URL      = "${SUPABASE_URL:-}"
SUPABASE_ANON_KEY = "${SUPABASE_ANON_KEY:-}"
SMTP_USER         = "${SMTP_USER:-}"
SMTP_PASSWORD     = "${SMTP_PASSWORD:-}"
SMTP_FROM         = "${SMTP_FROM:-}"
EOF

echo "✓ secrets.toml written"

# ── Start Streamlit ───────────────────────────────────────────────────────────
PORT="${PORT:-8501}"
echo "→ Starting polyMad on port $PORT"

exec streamlit run src/dashboard.py \
    --server.port="$PORT" \
    --server.address="0.0.0.0" \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false
