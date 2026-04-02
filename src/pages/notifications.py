"""
Notifications preferences page.

Allows the user to configure email alerts, Telegram bot, and alert thresholds.
Moves notification settings out of the sidebar into a dedicated page.
"""
import streamlit as st

import src.components.auth_bridge as auth_bridge
from src.components.app_header import render_app_header
from src.components.wallet import process_auth_flow

try:
    from src.data.supabase_client import upsert_alert_config, get_alert_config
except ImportError:
    upsert_alert_config = None
    get_alert_config = None


def render_notifications_page(t=None, supa_url: str = "", supa_key: str = "") -> None:
    """Render the notifications preferences page."""

    def _t(key, default):
        try:
            return t(key) if t else default
        except Exception:
            return default

    render_app_header(t)
    process_auth_flow()

    if not auth_bridge.is_authenticated():
        st.info(_t("notif_login_required", "Sign in to configure notifications."))
        return

    addr = auth_bridge.get_authenticated_address() or ""
    plan = auth_bridge.get_authenticated_plan()

    st.title(_t("notifications_title", "Notifications"))

    # Load existing config
    config = {}
    if supa_url and supa_key and get_alert_config:
        config = get_alert_config(supa_url, supa_key, addr) or {}

    # ── Email alerts ───────────────────────────────────────────────────────
    st.subheader(_t("email_alerts_section", "Email Alerts"))

    if plan == "free":
        st.warning(_t("email_alerts_upgrade", "Email alerts require a Pro or Trader plan."))
        st.button(_t("upgrade_btn", "Upgrade to Pro"), disabled=True)
    else:
        email_enabled = st.toggle(
            _t("email_alerts_toggle", "Enable email alerts"),
            value=bool(config.get("notify_email")),
            key="notif_email_toggle",
        )
        notif_email = st.text_input(
            _t("alert_email_label", "Alert email address"),
            value=config.get("notify_email", ""),
            placeholder="alerts@example.com",
            disabled=not email_enabled,
            key="notif_email_input",
        )

    st.divider()

    # ── Telegram bot ───────────────────────────────────────────────────────
    st.subheader(_t("telegram_section", "Telegram Bot"))

    if plan != "trader":
        st.warning(_t("telegram_upgrade", "Telegram notifications require the Trader plan."))
    else:
        bot_username = st.secrets.get("TELEGRAM_BOT_USERNAME", "@polymadBot") if hasattr(st, "secrets") else "@polymadBot"
        st.markdown(
            f"Connect your Telegram account to receive real-time alerts.\n\n"
            f"**1.** Open Telegram and search for **{bot_username}**\n\n"
            f"**2.** Send `/start` to the bot\n\n"
            f"**3.** The bot will confirm your connection"
        )
        telegram_chat_id = config.get("telegram_chat_id", "")
        if telegram_chat_id:
            st.success(_t("telegram_connected", f"✅ Telegram connected (chat_id: {telegram_chat_id})"))
        else:
            st.info(_t("telegram_not_connected", "Not connected yet. Follow the steps above."))

    st.divider()

    # ── Alert thresholds ───────────────────────────────────────────────────
    st.subheader(_t("thresholds_section", "Alert Thresholds"))

    edge_threshold = st.slider(
        _t("edge_threshold_label", "Minimum edge to trigger alert (%)"),
        min_value=1,
        max_value=30,
        value=int(float(config.get("edge_threshold", 0.05)) * 100),
        step=1,
        format="%d%%",
        key="notif_edge_slider",
        help=_t("edge_threshold_help", "Only send alerts when the model edge exceeds this threshold."),
    )

    categories = st.multiselect(
        _t("categories_label", "Alert categories"),
        options=["weather", "sports", "politics", "crypto"],
        default=config.get("categories", ["weather"]),
        key="notif_categories",
        disabled=(plan == "free"),
    )
    if plan == "free":
        st.caption(_t("categories_free_note", "Upgrade to Pro to enable all categories."))

    st.divider()

    # ── Save button ────────────────────────────────────────────────────────
    if st.button(_t("save_notifications_btn", "Save Notification Settings"), type="primary"):
        if supa_url and supa_key and upsert_alert_config:
            notify_email_val = notif_email.strip() if (plan != "free" and email_enabled) else ""
            ok = upsert_alert_config(
                supa_url, supa_key,
                wallet_address=addr,
                edge_threshold=edge_threshold / 100.0,
                categories=categories,
                notify_email=notify_email_val,
            )
            if ok:
                st.success(_t("notifications_saved", "Notification settings saved."))
            else:
                st.error(_t("notifications_save_error", "Could not save settings. Please try again."))
        else:
            st.warning(_t("notifications_no_backend", "Database not configured — settings not saved."))
