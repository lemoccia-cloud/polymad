"""
APScheduler jobs for polyMad Telegram Bot.

Jobs:
  daily_digest — runs every day at 08:00 UTC
    1. Runs analysis pipeline (edge_threshold = per-subscriber config, default 10%)
    2. Fetches all active Telegram subscribers from Supabase
    3. For each subscriber: filters alerts by their threshold, sends Telegram message

The scheduler runs inside the FastAPI asyncio event loop — no separate process needed.
"""
import asyncio
import logging
import os
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from src.bot._supabase import get_active_subscribers
from src.bot.analysis import run_analysis_for_bot
from src.bot.formatters import format_alerts_message, format_no_alerts_message

logger = logging.getLogger(__name__)

_DEFAULT_EDGE = 0.10
_DEFAULT_BANKROLL = 1000.0
_MAX_ALERTS_SHOWN = 8


async def _send_daily_digest() -> None:
    """
    Core digest job: run analysis, send to all active subscribers.
    Catches all exceptions to prevent scheduler from stopping on errors.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.warning("scheduler: TELEGRAM_BOT_TOKEN not set — skipping digest")
        return

    subscribers = get_active_subscribers()
    if not subscribers:
        logger.info("scheduler: digest — no active subscribers, skipping")
        return

    logger.info("scheduler: daily digest — %d subscriber(s)", len(subscribers))

    # Run analysis once at the lowest threshold among all subscribers
    # so we fetch the full set and filter per-subscriber afterwards
    min_edge = min(
        float(s.get("edge_threshold", _DEFAULT_EDGE)) for s in subscribers
    )
    try:
        alerts = await run_analysis_for_bot(
            edge_threshold=min_edge,
            max_markets=100,
        )
    except Exception as exc:
        logger.error("scheduler: analysis failed: %s", exc)
        return

    logger.info("scheduler: %d total alerts at threshold=%.0f%%", len(alerts), min_edge * 100)

    bot = Bot(token=token)
    sent = 0

    for sub in subscribers:
        chat_id = sub.get("chat_id")
        edge = float(sub.get("edge_threshold", _DEFAULT_EDGE))

        # Filter alerts for this subscriber's threshold
        subscriber_alerts = [a for a in alerts if a.edge > edge]

        if not subscriber_alerts:
            # Only notify subscribers who have explicit threshold < default
            # to avoid spamming "no alerts" every morning
            if edge < _DEFAULT_EDGE:
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=format_no_alerts_message(edge),
                        parse_mode="Markdown",
                    )
                except Exception as exc:
                    logger.warning("scheduler: send failed to %s: %s", chat_id, exc)
            continue

        msg = format_alerts_message(
            subscriber_alerts,
            edge_threshold=edge,
            bankroll=_DEFAULT_BANKROLL,
            is_digest=True,
            max_alerts=_MAX_ALERTS_SHOWN,
        )
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            sent += 1
            # Small delay between messages to respect Telegram rate limits
            await asyncio.sleep(0.1)
        except Exception as exc:
            logger.warning("scheduler: send failed to %s: %s", chat_id, exc)

    logger.info("scheduler: digest sent to %d/%d subscribers", sent, len(subscribers))


def build_scheduler() -> AsyncIOScheduler:
    """
    Create and configure the APScheduler.
    Jobs are added but NOT started here — caller calls scheduler.start().
    """
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _send_daily_digest,
        trigger="cron",
        hour=8,
        minute=0,
        id="daily_digest",
        name="polyMad Daily Digest",
        replace_existing=True,
        misfire_grace_time=3600,  # fire up to 1h late if server was down
    )
    logger.info("scheduler: daily digest job registered (08:00 UTC)")
    return scheduler
