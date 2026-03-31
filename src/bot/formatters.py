"""
Format OpportunityResult objects as Telegram Markdown messages.

All text is escaped for Telegram MarkdownV2 where needed.
Uses plain Markdown (not V2) for readability — caller passes parse_mode="Markdown".
"""
from datetime import datetime
from typing import List

from src.models.market import OpportunityResult

# Market type icons
_TYPE_ICONS = {
    "weather": "🌡",
    "crypto":  "₿",
    "sports":  "⚽",
    "politics":"🗳",
}

_TYPE_LABELS = {
    "weather": "CLIMA",
    "crypto":  "CRYPTO",
    "sports":  "ESPORTE",
    "politics":"POLÍTICA",
}


def _market_label(result: OpportunityResult) -> str:
    """Short human-readable label for the market."""
    m = result.market
    mtype = getattr(m, "market_type", "weather")
    if mtype == "weather":
        sym = {"above": "≥", "below": "≤", "exact": "="}.get(m.bucket_type, "")
        return f"{m.city} {sym}{m.threshold_celsius:.0f}°C"
    elif mtype == "crypto":
        sym = "≥" if m.direction == "above" else "≤"
        return f"{m.asset} {sym} ${m.threshold_usd:,.0f}"
    elif mtype == "sports":
        return f"{m.home_team} vs {m.away_team}"
    else:
        return getattr(m, "topic", "")[:50]


def _poly_url(result: OpportunityResult) -> str:
    slug = getattr(result.market, "event_slug", "")
    if slug:
        return f"https://polymarket.com/event/{slug}"
    return "https://polymarket.com/markets"


def format_single_alert(result: OpportunityResult, bankroll: float = 1000.0) -> str:
    """Format one alert as a Telegram Markdown block."""
    m = result.market
    mtype = getattr(m, "market_type", "weather")
    icon = _TYPE_ICONS.get(mtype, "📊")
    label_type = _TYPE_LABELS.get(mtype, mtype.upper())
    label = _market_label(result)

    edge_pct = result.edge * 100
    ev = result.expected_value
    kelly_usd = bankroll * result.suggested_bet_fraction
    mkt_pct = m.market_implied_prob * 100
    mdl_pct = result.forecast.model_probability * 100

    res_date = ""
    rd = getattr(m, "resolution_date", None)
    if rd:
        res_date = f"\n📅 Resolução: {rd.strftime('%d %b %Y')}"

    url = _poly_url(result)

    return (
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{icon} *{label_type} — {label}*\n"
        f"Edge: `{edge_pct:+.1f}%` | EV: `{ev:+.3f}/$` | Kelly: `${kelly_usd:.0f}`\n"
        f"Mercado: `{mkt_pct:.1f}%` vs Modelo: `{mdl_pct:.1f}%`"
        f"{res_date}\n"
        f"🔗 [Negociar →]({url})"
    )


def format_alerts_message(
    alerts: List[OpportunityResult],
    edge_threshold: float,
    bankroll: float = 1000.0,
    is_digest: bool = False,
    max_alerts: int = 8,
) -> str:
    """
    Format a list of alerts as a full Telegram message.

    Returns empty string if alerts is empty.
    """
    if not alerts:
        return ""

    shown = alerts[:max_alerts]
    header_emoji = "📅" if is_digest else "🔔"
    digest_note = " — Digest Diário" if is_digest else ""
    header = (
        f"{header_emoji} *polyMad — {len(shown)} alerta{'s' if len(shown) != 1 else ''}"
        f"{digest_note} (edge > {edge_threshold*100:.0f}%)*\n"
    )

    blocks = [format_single_alert(r, bankroll) for r in shown]
    body = "\n\n".join(blocks)

    footer = "\n\n_/unsubscribe para cancelar o digest diário._" if is_digest else ""

    return header + "\n" + body + footer


def format_no_alerts_message(edge_threshold: float) -> str:
    """Message when no alerts are found."""
    return (
        f"✅ *Nenhum alerta no momento*\n\n"
        f"Não há oportunidades com edge > {edge_threshold*100:.0f}% agora.\n"
        f"Tente `/alerts {max(1, int(edge_threshold*100) - 5)}` para um threshold menor."
    )


def format_subscribe_message(edge_threshold: float) -> str:
    return (
        f"✅ *Inscrito no digest diário!*\n\n"
        f"Você receberá alertas diários às 8h UTC quando houver oportunidades "
        f"com edge > {edge_threshold*100:.0f}%.\n\n"
        f"Use `/unsubscribe` para cancelar a qualquer momento."
    )


def format_unsubscribe_message() -> str:
    return "✅ *Cancelado.* Você não receberá mais o digest diário."


def format_start_message() -> str:
    return (
        "👋 *Bem-vindo ao polyMad Bot!*\n\n"
        "Monitoro mercados de predição no Polymarket e identifico oportunidades "
        "onde o modelo probabilístico supera o preço do mercado.\n\n"
        "*Comandos disponíveis:*\n"
        "• `/alerts [edge%]` — Ver oportunidades agora (ex: `/alerts 10`)\n"
        "• `/subscribe [edge%]` — Digest diário às 8h UTC (ex: `/subscribe 10`)\n"
        "• `/unsubscribe` — Cancelar digest diário\n"
        "• `/help` — Esta ajuda\n\n"
        "_Edge padrão: 10% · Bankroll padrão: $1.000_\n\n"
        "🌐 [polymad-production.up.railway.app](https://polymad-production.up.railway.app)"
    )


def format_help_message() -> str:
    return (
        "📖 *Ajuda — polyMad Bot*\n\n"
        "*Comandos:*\n"
        "• `/alerts [edge%]` — Analisa mercados agora e mostra alertas\n"
        "  _Ex: `/alerts 5` → edge > 5%_\n\n"
        "• `/subscribe [edge%]` — Inscreve para digest diário às 8h UTC\n"
        "  _Ex: `/subscribe 10` → edge > 10%_\n\n"
        "• `/unsubscribe` — Cancela digest diário\n\n"
        "• `/start` — Boas-vindas e instruções\n\n"
        "*O que é edge?*\n"
        "Edge = diferença entre a probabilidade do modelo e a probabilidade implícita "
        "do mercado. Edge positivo = mercado precificando abaixo do que o modelo prevê.\n\n"
        "🌐 [polymad-production.up.railway.app](https://polymad-production.up.railway.app)"
    )
