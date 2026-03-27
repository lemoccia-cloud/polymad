#!/bin/bash
# deploy_railway.sh — deploy completo do polyMad no Railway
# Uso: RAILWAY_TOKEN=<token> bash scripts/deploy_railway.sh
#
# Pré-requisitos:
#   npm install -g @railway/cli   (já instalado)
#   Conta Railway criada em https://railway.app

set -e

# ── Validação ─────────────────────────────────────────────────────────────────
if [ -z "$RAILWAY_TOKEN" ]; then
    echo "❌ RAILWAY_TOKEN não definido."
    echo "   Gere em: https://railway.app/account/tokens"
    echo "   Uso: RAILWAY_TOKEN=<token> bash scripts/deploy_railway.sh"
    exit 1
fi

export RAILWAY_TOKEN

echo "╔═══════════════════════════════════╗"
echo "║  polyMad → Railway Deploy         ║"
echo "╚═══════════════════════════════════╝"

# ── Criar projeto ─────────────────────────────────────────────────────────────
echo ""
echo "▶ 1/5  Criando projeto Railway..."
railway init --name "polymad"

# ── Setar variáveis de ambiente ───────────────────────────────────────────────
echo ""
echo "▶ 2/5  Configurando variáveis de ambiente..."

# Lê do secrets.toml local para não exigir que o usuário redigite tudo
SECRETS_FILE=".streamlit/secrets.toml"

if [ -f "$SECRETS_FILE" ]; then
    echo "   Lendo segredos de $SECRETS_FILE..."
    parse_toml_value() {
        grep "^$1" "$SECRETS_FILE" | sed 's/.*= *"\(.*\)"/\1/' | tr -d ' '
    }

    SUPABASE_URL_VAL=$(parse_toml_value "SUPABASE_URL")
    SUPABASE_KEY_VAL=$(parse_toml_value "SUPABASE_ANON_KEY")
    SMTP_USER_VAL=$(parse_toml_value "SMTP_USER")
    SMTP_PASS_VAL=$(parse_toml_value "SMTP_PASSWORD")
    SMTP_FROM_VAL=$(parse_toml_value "SMTP_FROM")

    railway variables set \
        "SUPABASE_URL=$SUPABASE_URL_VAL" \
        "SUPABASE_ANON_KEY=$SUPABASE_KEY_VAL" \
        "SMTP_USER=$SMTP_USER_VAL" \
        "SMTP_PASSWORD=$SMTP_PASS_VAL" \
        "SMTP_FROM=${SMTP_FROM_VAL:-$SMTP_USER_VAL}"
    echo "   ✓ Variáveis setadas a partir de secrets.toml"
else
    echo "   ⚠ $SECRETS_FILE não encontrado."
    echo "   Setando variáveis como strings vazias — edite depois no dashboard."
    railway variables set \
        "SUPABASE_URL=" \
        "SUPABASE_ANON_KEY=" \
        "SMTP_USER=" \
        "SMTP_PASSWORD=" \
        "SMTP_FROM="
fi

# ── Garantir que o push do Git está em dia ────────────────────────────────────
echo ""
echo "▶ 3/5  Verificando repositório Git..."
REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
if [ -z "$REMOTE" ]; then
    echo "   ⚠ Sem remote origin configurado."
    echo "   Crie o repositório em https://github.com/new e execute:"
    echo "   git remote add origin https://github.com/<user>/polymad.git"
    echo "   git push -u origin main"
    echo ""
    echo "   Depois re-execute este script."
    exit 1
fi

UNPUSHED=$(git log origin/main..HEAD --oneline 2>/dev/null | wc -l | tr -d ' ')
if [ "$UNPUSHED" -gt "0" ]; then
    echo "   → $UNPUSHED commit(s) não publicado(s). Fazendo push..."
    git push origin main
    echo "   ✓ Push concluído"
else
    echo "   ✓ Repositório atualizado"
fi

# ── Deploy ────────────────────────────────────────────────────────────────────
echo ""
echo "▶ 4/5  Iniciando deploy..."
railway up --detach

# ── URL pública ───────────────────────────────────────────────────────────────
echo ""
echo "▶ 5/5  Obtendo URL pública..."
sleep 5
railway domain 2>/dev/null || echo "   (gerando domínio — pode levar 1-2 min)"

echo ""
echo "╔═══════════════════════════════════════════════════╗"
echo "║  ✅ Deploy concluído!                              ║"
echo "║                                                    ║"
echo "║  Acompanhe os logs:  railway logs                  ║"
echo "║  Abrir no browser:   railway open                  ║"
echo "║  Dashboard:          https://railway.app/dashboard ║"
echo "╚═══════════════════════════════════════════════════╝"
