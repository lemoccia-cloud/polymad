#!/bin/bash
# polyMad Billing Smoke Test Runner
#
# Uso: bash scripts/smoke_test.sh
#
# Lê .stripe_test_keys automaticamente se existir.
# Formato de .stripe_test_keys (NÃO commitar este ficheiro):
#   STRIPE_SECRET_KEY=sk_test_...
#   STRIPE_PRICE_PRO_MONTHLY=price_...
#   STRIPE_PRICE_TRADER_MONTHLY=price_...

set -e
cd "$(dirname "$0")/.."

PYTHON="/usr/local/bin/python3.11"
KEY_FILE=".stripe_test_keys"

# ── Carregar JWT dev key ──────────────────────────────────────────────────────
if [ -z "$JWT_SECRET_KEY" ]; then
    if [ -f ".dev_jwt_key" ]; then
        export JWT_SECRET_KEY="$(cat .dev_jwt_key)"
    else
        export JWT_SECRET_KEY="$($PYTHON -c "import secrets; print(secrets.token_hex(32))")"
    fi
fi

# ── Carregar Stripe keys ──────────────────────────────────────────────────────
if [ -f "$KEY_FILE" ]; then
    # Valida que o ficheiro não tem chaves live antes de carregar
    if grep -q "sk_live_" "$KEY_FILE" 2>/dev/null; then
        echo "❌ ABORTED: $KEY_FILE contém uma chave LIVE do Stripe."
        echo "   Usa apenas sk_test_... para testes locais."
        exit 1
    fi
    # shellcheck disable=SC2046
    export $(grep -v '^#' "$KEY_FILE" | grep -v '^$' | xargs)
    echo "✓ Stripe keys carregadas de $KEY_FILE"
else
    echo "⚠️  $KEY_FILE não encontrado — checkout tests serão skipped."
    echo "   Para testar billing, cria $KEY_FILE com:"
    echo "     STRIPE_SECRET_KEY=sk_test_..."
    echo "     STRIPE_PRICE_PRO_MONTHLY=price_..."
    echo "     STRIPE_PRICE_TRADER_MONTHLY=price_..."
    echo ""
fi

# ── Carregar Supabase (necessário para FastAPI arrancar) ──────────────────────
SECRETS=".streamlit/secrets.toml"
_val() { grep "^$1" "$SECRETS" 2>/dev/null | sed 's/.*= *"\(.*\)"/\1/' | tr -d ' '; }
export SUPABASE_URL="${SUPABASE_URL:-$(_val SUPABASE_URL)}"
export SUPABASE_ANON_KEY="${SUPABASE_ANON_KEY:-$(_val SUPABASE_ANON_KEY)}"

$PYTHON scripts/smoke_test.py
