"""
polyMad Telegram Bot — command handlers and application setup.

Commands:
  /start          — welcome message and instructions
  /alerts [edge%] — run analysis now and show top alerts (default: 10%)
  /subscribe [e%] — subscribe to daily digest (saves to Supabase)
  /unsubscribe    — cancel daily digest
  /help           — show all commands

Rate limiting:
  /alerts: max 1 analysis per minute per chat_id (in-memory, no Redis needed)

Security:
  TELEGRAM_BOT_TOKEN read exclusively from os.environ — never hardcoded.
  Bot is silently skipped at startup if the token is absent.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from src.bot.analysis import run_analysis_for_bot
from src.bot.formatters import (
    format_alerts_message,
    format_help_message,
    format_no_alerts_message,
    format_start_message,
    format_subscribe_message,
    format_unsubscribe_message,
)

logger = logging.getLogger(__name__)

# In-memory rate limiter: {chat_id: last_run_utc}
_last_alerts_run: dict[int, datetime] = {}
_ALERTS_COOLDOWN_SECONDS = 60
_DEFAULT_EDGE = 0.10
_DEFAULT_BANKROLL = 1000.0
_MAX_ALERTS_SHOWN = 8


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_edge_arg(args: tuple) -> float:
    """Parse optional edge% argument from command args. Returns fraction (0-1)."""
    if args:
        try:
            val = float(args[0].replace("%", "").strip())
            return max(1.0, min(50.0, val)) / 100.0
        except (ValueError, IndexError):
            pass
    return _DEFAULT_EDGE


def _is_rate_limited(chat_id: int) -> bool:
    last = _last_alerts_run.get(chat_id)
    if last is None:
        return False
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return elapsed < _ALERTS_COOLDOWN_SECONDS


def _record_run(chat_id: int) -> None:
    _last_alerts_run[chat_id] = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        format_start_message(),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        format_help_message(),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    edge = _parse_edge_arg(context.args)

    if _is_rate_limited(chat_id):
        remaining = int(
            _ALERTS_COOLDOWN_SECONDS
            - (datetime.now(timezone.utc) - _last_alerts_run[chat_id]).total_seconds()
        )
        await update.message.reply_text(
            f"⏳ Aguarde {remaining}s antes de rodar uma nova análise.",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        f"🔍 Analisando mercados (edge > {edge*100:.0f}%)...",
        parse_mode="Markdown",
    )
    _record_run(chat_id)

    try:
        alerts = await run_analysis_for_bot(edge_threshold=edge)
    except Exception as exc:
        logger.error("cmd_alerts error: %s", exc)
        await update.message.reply_text(
            "❌ Erro ao executar análise. Tente novamente em alguns minutos.",
        )
        return

    if not alerts:
        await update.message.reply_text(
            format_no_alerts_message(edge),
            parse_mode="Markdown",
        )
        return

    msg = format_alerts_message(
        alerts, edge_threshold=edge, bankroll=_DEFAULT_BANKROLL,
        max_alerts=_MAX_ALERTS_SHOWN,
    )
    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.bot._supabase import upsert_subscriber  # lazy import — Supabase optional

    chat_id = update.effective_chat.id
    username = update.effective_user.username or ""
    edge = _parse_edge_arg(context.args)

    ok = upsert_subscriber(chat_id=chat_id, username=username, edge_threshold=edge)
    if ok:
        await update.message.reply_text(
            format_subscribe_message(edge),
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "⚠️ Não foi possível salvar sua inscrição (Supabase não configurado). "
            "Contate o administrador.",
        )


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.bot._supabase import deactivate_subscriber  # lazy import

    chat_id = update.effective_chat.id
    deactivate_subscriber(chat_id=chat_id)
    await update.message.reply_text(
        format_unsubscribe_message(),
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def build_application(token: str) -> Application:
    """Build and configure the Telegram Application."""
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    return app


async def run_bot(token: str) -> None:
    """
    Start the bot with long-polling.
    Called as a background asyncio task from FastAPI lifespan.
    Runs until cancelled.
    """
    app = build_application(token)
    logger.info("Telegram bot starting (long-polling)...")
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot polling active")
        # Wait until cancelled (FastAPI shutdown)
        try:
            import asyncio
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            logger.info("Telegram bot shutting down...")
        finally:
            await app.updater.stop()
            await app.stop()
