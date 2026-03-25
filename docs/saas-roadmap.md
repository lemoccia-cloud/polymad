# polyMad — Roadmap SaaS

## Visão

**polyMad** é uma plataforma de análise de mercados de predição que identifica
oportunidades de retorno superior usando modelos probabilísticos externos
(previsões meteorológicas, pesquisas eleitorais, odds esportivas) e os
compara com os preços praticados no Polymarket.

**Proposta de valor central:**
> Conecte sua carteira → receba análises automáticas de onde o mercado está
> precificando errado → saiba exatamente quanto apostar e qual o retorno esperado.

---

## Fase 1 — MVP Público (atual)

**Status: ✅ Em produção**

| Feature | Status |
|---------|--------|
| Dashboard Streamlit multi-idioma (EN/PT-BR/ES/ZH) | ✅ |
| Análise de mercados de temperatura (Polymarket Gamma API) | ✅ |
| Modelos ECMWF IFS (51 membros) e GFS (31 membros) | ✅ |
| Cálculo de Edge, EV e Kelly fraction | ✅ |
| Retorno esperado por aposta (Se ganhar $, Retorno %) | ✅ |
| Tema claro/escuro | ✅ |
| Conexão MetaMask (display apenas) | ✅ |
| Barra de categorias (Clima ativo, demais em breve) | ✅ |

---

## Fase 2 — Integração Real com Polymarket

**Objetivo:** Ler posições reais do usuário e calcular P&L em tempo real.

### Features

- **Autenticação por carteira** via EIP-712 message signing (sem senha)
- **Leitura de posições** via CLOB API (`GET /positions?owner={address}`)
- **P&L em tempo real:** posições abertas × preços atuais
- **Portfolio tracker:** lucro realizado, não-realizado, ROI histórico
- **Histórico de alertas:** track record de acurácia do modelo vs realidade

### Stack técnica

```
FastAPI backend (Python)
├── /auth/nonce        → gera nonce para assinatura
├── /auth/verify       → verifica assinatura EIP-712, emite JWT
├── /api/portfolio     → lê posições CLOB + calcula P&L
├── /api/markets       → análise de oportunidades
└── /api/alerts        → configurações de alerta do usuário

PostgreSQL
├── users (address, created_at, tier)
├── alert_configs (user_id, threshold, categories, notify_email)
└── alert_history (user_id, market_id, edge, result, created_at)
```

### Estimativa de esforço: 3–4 semanas

---

## Fase 3 — Notificações e Alertas

**Objetivo:** Notificar o usuário quando surgem oportunidades em tempo real.

### Features

- E-mail via SendGrid quando edge > threshold configurado
- Telegram bot (`/start`, `/alerts`, `/portfolio`)
- Webhook customizável (para integração com sistemas próprios)
- Frequência configurável: tempo real, horária, diária
- Resumo diário com top oportunidades do dia

### Estimativa de esforço: 2 semanas

---

## Fase 4 — Multi-Categoria com Modelos de IA

**Objetivo:** Expandir análise para Política, Esportes e Finanças.

### Política

- **Fonte de probabilidade "verdadeira":** agregador de pesquisas (estilo 538)
  ou modelos de ML treinados em histórico Polymarket
- **Mercados alvo:** eleições presidenciais, aprovação de leis, decisões da Fed
- **API sugerida:** FiveThirtyEight (agora ABC News), ElectionBettingOdds

### Esportes

- **Fonte:** APIs de odds de casas europeias (Pinnacle, Betfair Exchange)
  como proxy de probabilidade "eficiente"
- **Lógica:** se Polymarket precifica diferente de Pinnacle, há edge
- **Mercados alvo:** Champions League, Copa do Mundo, NBA Finals

### Finanças / Crypto

- **Fonte:** volatilidade implícita de opções (Deribit para BTC/ETH)
- **Lógica:** modelo Black-Scholes vs preço do mercado binário
- **Mercados alvo:** "Will BTC be above $X on date Y?"

### Estimativa de esforço: 8–12 semanas (por categoria)

---

## Fase 5 — Execução Automática (Opcional / Alto Risco)

**Objetivo:** Executar apostas automaticamente com aprovação do usuário.

> ⚠️ Esta fase requer análise legal por jurisdição. Automação de apostas
> pode ser regulada diferentemente em cada país.

### Features

- **Modo Paper Trading:** simula apostas sem dinheiro real, valida estratégia
- **Execução semi-automática:** usuário recebe alerta → confirma com 1 clique
- **Execução automática:** dentro de limites pré-configurados (ex: máx $50/aposta)
- **Integração CLOB:** `POST /order` com assinatura da carteira
- **Relatório mensal:** apostas realizadas, P&L, ROI, comparação vs modelo

### Estimativa de esforço: 6–8 semanas + análise legal

---

## Arquitetura Futura Completa

```
┌─────────────────────────────────────────────────────────────────┐
│                       polyMad Platform                          │
├─────────────────┬──────────────────────────┬────────────────────┤
│   Frontend      │   Backend API (FastAPI)   │   Workers (Celery) │
│                 │                           │                    │
│  Streamlit      │  Auth (EIP-712 + JWT)     │  Market scanner    │
│  ou             │  Portfolio (CLOB reader)  │  (every 5 min)     │
│  Next.js        │  Analysis pipeline        │                    │
│  + React        │  Alert engine             │  Alert dispatcher  │
│                 │  Webhook dispatcher       │  (real-time)       │
└─────────────────┴──────────────────────────┴────────────────────┘
        │                    │                          │
        ▼                    ▼                          ▼
  MetaMask /         PostgreSQL (users,          Open-Meteo API
  Polymarket         alerts, history)            Polymarket API
  Wallet             Redis (cache/queue)         Pinnacle / Betfair
                     S3 (reports)                ElectionBettingOdds
```

---

## Modelo de Monetização

| Plano | Preço | Limites |
|-------|-------|---------|
| **Free** | $0/mês | Clima apenas · 10 mercados/análise · sem alertas |
| **Pro** | $19/mês | Todas as categorias · 200 mercados · alertas por e-mail |
| **Trader** | $49/mês | Ilimitado · Telegram · paper trading · relatório mensal |
| **Institutional** | Custom | API access · white-label · SLA · execução automática |

### Projeção de receita (conservadora)

| Mês | Free | Pro | Trader | MRR |
|-----|------|-----|--------|-----|
| 3 | 500 | 50 | 10 | $1.450 |
| 6 | 2k | 200 | 40 | $7.760 |
| 12 | 8k | 500 | 100 | $14.400 |

---

## Tech Stack Recomendado

| Camada | Tecnologia | Motivo |
|--------|-----------|--------|
| Frontend (v1) | Streamlit | Já implementado, fácil de manter |
| Frontend (v2) | Next.js + React | Melhor UX, SEO, mobile |
| Backend | FastAPI (Python) | Reutiliza módulos existentes |
| Banco | PostgreSQL + SQLAlchemy | Confiável, escalável |
| Cache | Redis | Sessões, rate limiting, filas |
| Workers | Celery + Redis | Análises periódicas, alertas |
| Deploy | Railway / Render / AWS ECS | Simples, escalável |
| Autenticação | EIP-712 + JWT | Sem senha, nativo Web3 |
| Emails | SendGrid | API confiável, free tier |
| Pagamentos | Stripe | Assinaturas, free tier |

---

## Próximos Passos Imediatos

1. [ ] Deploy do MVP em Railway/Render com URL pública
2. [ ] Landing page simples (Next.js) com waitlist
3. [ ] Coletar feedback de 20 usuários beta
4. [ ] Implementar autenticação por carteira (Fase 2)
5. [ ] Definir jurisdição legal para operação
