"""E-mail alert notifications via Gmail SMTP."""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone


def _build_html(alerts: list, edge_threshold: float, bankroll: float, lang: str) -> str:
    """Build HTML e-mail body from alert list."""
    labels = {
        "en": {
            "title": "Opportunity Alerts",
            "subtitle": "The following opportunities were found with edge above threshold",
            "city": "City / Market",
            "edge": "Edge",
            "ev": "EV ($)",
            "kelly": "Kelly Bet",
            "return": "Return %",
            "prob_model": "Model Prob",
            "prob_market": "Market Prob",
            "cta": "Open app",
            "footer": "polyMad · Opportunity Finder",
            "threshold": "Threshold",
        },
        "pt": {
            "title": "Alertas de Oportunidades",
            "subtitle": "As seguintes oportunidades foram encontradas com edge acima do limite",
            "city": "Cidade / Mercado",
            "edge": "Edge",
            "ev": "EV ($)",
            "kelly": "Aposta Kelly",
            "return": "Retorno %",
            "prob_model": "Prob Modelo",
            "prob_market": "Prob Mercado",
            "cta": "Abrir app",
            "footer": "polyMad · Buscador de Oportunidades",
            "threshold": "Limite",
        },
        "es": {
            "title": "Alertas de Oportunidades",
            "subtitle": "Se encontraron las siguientes oportunidades con edge por encima del límite",
            "city": "Ciudad / Mercado",
            "edge": "Edge",
            "ev": "EV ($)",
            "kelly": "Apuesta Kelly",
            "return": "Retorno %",
            "prob_model": "Prob Modelo",
            "prob_market": "Prob Mercado",
            "cta": "Abrir app",
            "footer": "polyMad · Buscador de Oportunidades",
            "threshold": "Límite",
        },
        "zh": {
            "title": "机会警报",
            "subtitle": "发现以下超过阈值的机会",
            "city": "城市 / 市场",
            "edge": "优势",
            "ev": "期望值 ($)",
            "kelly": "凯利投注",
            "return": "回报率 %",
            "prob_model": "模型概率",
            "prob_market": "市场概率",
            "cta": "打开应用",
            "footer": "polyMad · 机会发现器",
            "threshold": "阈值",
        },
    }
    l = labels.get(lang, labels["en"])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rows = []
    for r in alerts:
        m = r.market
        bet_usd = bankroll * r.suggested_bet_fraction
        return_pct = (1 / m.market_implied_prob - 1) * 100 if m.market_implied_prob > 0 else 0
        ev_dollars = bet_usd * r.expected_value

        label = f"{m.city} {m.bucket_type} {m.threshold_celsius}°C"
        edge_color = "#059669" if r.edge > 0.15 else "#d97706"

        rows.append(f"""
        <tr>
          <td style="padding:12px 16px;border-bottom:1px solid #1e293b;color:#f1f5f9;font-size:14px;">{label}</td>
          <td style="padding:12px 16px;border-bottom:1px solid #1e293b;color:{edge_color};font-weight:700;font-size:14px;">+{r.edge*100:.1f}%</td>
          <td style="padding:12px 16px;border-bottom:1px solid #1e293b;color:#60a5fa;font-size:14px;">${ev_dollars:.2f}</td>
          <td style="padding:12px 16px;border-bottom:1px solid #1e293b;color:#f1f5f9;font-size:14px;">${bet_usd:.2f}</td>
          <td style="padding:12px 16px;border-bottom:1px solid #1e293b;color:#34d399;font-size:14px;">+{return_pct:.1f}%</td>
          <td style="padding:12px 16px;border-bottom:1px solid #1e293b;color:#94a3b8;font-size:13px;">{m.market_implied_prob*100:.1f}%</td>
          <td style="padding:12px 16px;border-bottom:1px solid #1e293b;color:#94a3b8;font-size:13px;">{r.forecast.model_probability*100:.1f}%</td>
        </tr>""")

    rows_html = "".join(rows)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0a0f1e;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0f1e;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

        <!-- Header -->
        <tr>
          <td style="background:#111827;border:1px solid #1e293b;border-radius:16px 16px 0 0;padding:32px;text-align:center;">
            <div style="font-size:28px;font-weight:800;color:#f1f5f9;letter-spacing:-0.5px;">
              🌡 polyMad
            </div>
            <div style="font-size:20px;font-weight:700;color:#f1f5f9;margin-top:8px;">
              {l["title"]}
            </div>
            <div style="font-size:13px;color:#64748b;margin-top:6px;">
              {now} · {l["threshold"]}: {edge_threshold*100:.0f}%
            </div>
            <div style="font-size:14px;color:#94a3b8;margin-top:12px;">
              {l["subtitle"]}
            </div>
          </td>
        </tr>

        <!-- Table -->
        <tr>
          <td style="background:#0f172a;border-left:1px solid #1e293b;border-right:1px solid #1e293b;padding:0;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <thead>
                <tr style="background:#1e293b;">
                  <th style="padding:10px 16px;text-align:left;color:#64748b;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">{l["city"]}</th>
                  <th style="padding:10px 16px;text-align:left;color:#64748b;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">{l["edge"]}</th>
                  <th style="padding:10px 16px;text-align:left;color:#64748b;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">{l["ev"]}</th>
                  <th style="padding:10px 16px;text-align:left;color:#64748b;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">{l["kelly"]}</th>
                  <th style="padding:10px 16px;text-align:left;color:#64748b;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">{l["return"]}</th>
                  <th style="padding:10px 16px;text-align:left;color:#64748b;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">{l["prob_market"]}</th>
                  <th style="padding:10px 16px;text-align:left;color:#64748b;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">{l["prob_model"]}</th>
                </tr>
              </thead>
              <tbody>
                {rows_html}
              </tbody>
            </table>
          </td>
        </tr>

        <!-- CTA -->
        <tr>
          <td style="background:#111827;border:1px solid #1e293b;border-radius:0 0 16px 16px;padding:28px;text-align:center;">
            <a href="https://polymad.streamlit.app"
               style="display:inline-block;background:linear-gradient(135deg,#F59E0B,#D97706);color:#111827;font-weight:700;font-size:15px;padding:14px 32px;border-radius:10px;text-decoration:none;">
              {l["cta"]} →
            </a>
            <div style="font-size:12px;color:#475569;margin-top:20px;">{l["footer"]}</div>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_alert_email(
    alerts: list,
    recipient: str,
    smtp_user: str,
    smtp_password: str,
    smtp_from: str,
    edge_threshold: float = 0.05,
    bankroll: float = 1000.0,
    lang: str = "en",
) -> tuple[bool, str]:
    """Send alert e-mail via Gmail SMTP SSL.

    Returns (True, "") on success or (False, error_message) on failure.
    """
    if not alerts:
        return False, "No alerts to send"
    if not recipient or "@" not in recipient:
        return False, "Invalid recipient e-mail"

    subject_map = {
        "en": f"polyMad — {len(alerts)} opportunit{'y' if len(alerts)==1 else 'ies'} found (edge > {edge_threshold*100:.0f}%)",
        "pt": f"polyMad — {len(alerts)} oportunidade{'s' if len(alerts)>1 else ''} encontrada{'s' if len(alerts)>1 else ''} (edge > {edge_threshold*100:.0f}%)",
        "es": f"polyMad — {len(alerts)} oportunidad{'es' if len(alerts)>1 else ''} encontrada{'s' if len(alerts)>1 else ''} (edge > {edge_threshold*100:.0f}%)",
        "zh": f"polyMad — 发现 {len(alerts)} 个机会 (edge > {edge_threshold*100:.0f}%)",
    }
    subject = subject_map.get(lang, subject_map["en"])
    html_body = _build_html(alerts, edge_threshold, bankroll, lang)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_from, recipient, msg.as_string())
        return True, ""
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP authentication failed — check credentials"
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"
