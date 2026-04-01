"""
FastAPI application factory for polyMad backend.

Security hardening applied at this layer:
  - CORS: explicit origin whitelist, no wildcard
  - Request size limit: 4 KB max body
  - Rate limiting: slowapi per-IP limits on all auth endpoints
  - Sensitive data log filter: installed before first request
  - JWT secret validated at startup (hard fail if missing/short)
  - Proxy headers trusted for Railway deployment (real client IP for rate limits)

Fase 3 additions:
  - Telegram bot (long-polling) started as asyncio task in lifespan
  - APScheduler daily digest job started in lifespan
  - Both are gracefully skipped if TELEGRAM_BOT_TOKEN is not set
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.routers import auth as auth_router
from src.api.routers import portfolio as portfolio_router
from src.api.routers import billing as billing_router
from src.api.routers import stripe_webhooks as stripe_webhooks_router
from src.api.security.jwt_handler import _get_secret
from src.api.security.log_filter import install_sensitive_filter
from src.api.security.nonce_store import nonce_store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter (shared across all routes)
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# Request size middleware
# ---------------------------------------------------------------------------
class _RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject request bodies larger than MAX_BODY_BYTES (4 KB)."""
    MAX_BODY_BYTES = 4096

    async def dispatch(self, request: Request, call_next):
        # Stripe webhook payloads can be 5–15 KB; HMAC validates authenticity.
        if request.url.path == "/api/webhooks/stripe":
            return await call_next(request)
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.MAX_BODY_BYTES:
            return Response("Request body too large", status_code=413)
        return await call_next(request)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup validation and teardown hooks."""
    # Validate JWT secret — hard fail before serving any request
    _get_secret()
    logger.info("startup: JWT_SECRET_KEY validated")

    # Install log filter to redact sensitive data from all log output
    install_sensitive_filter()
    logger.info("startup: SensitiveDataFilter installed")

    # ── Fase 3: Telegram bot + scheduler (optional — skipped if token absent) ──
    bot_task: Optional[asyncio.Task] = None
    scheduler = None
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    if telegram_token:
        try:
            from src.bot.telegram_bot import run_bot
            from src.bot.scheduler import build_scheduler

            # Start APScheduler (daily digest)
            scheduler = build_scheduler()
            scheduler.start()
            logger.info("startup: APScheduler started (daily digest 08:00 UTC)")

            # Start Telegram bot as background asyncio task
            bot_task = asyncio.create_task(run_bot(telegram_token))
            logger.info("startup: Telegram bot task created")
        except Exception as exc:
            logger.error("startup: Telegram bot/scheduler failed to start: %s", exc)
    else:
        logger.info("startup: TELEGRAM_BOT_TOKEN not set — bot disabled")

    yield

    # Teardown
    if bot_task and not bot_task.done():
        bot_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(bot_task), timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        logger.info("shutdown: Telegram bot task stopped")

    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("shutdown: APScheduler stopped")

    # Purge any lingering nonces (best-effort)
    purged = nonce_store.purge_expired()
    logger.info("shutdown: purged %d expired nonces", purged)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    Called at module level so uvicorn can use `src.api.main:app`.
    """
    app = FastAPI(
        title="polyMad API",
        version="2.0.0",
        description="Secure backend for polyMad — Polymarket analysis platform",
        docs_url="/docs",
        redoc_url=None,
        lifespan=_lifespan,
    )

    # -- Rate limiter state ---------------------------------------------------
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # -- CORS -----------------------------------------------------------------
    allowed_origins = [
        "http://localhost:8501",
        "http://localhost:8000",
    ]
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
    if railway_domain:
        allowed_origins.append(f"https://{railway_domain}")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,   # explicit whitelist — NO wildcard
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=3600,
    )

    # -- Request size limit ---------------------------------------------------
    app.add_middleware(_RequestSizeLimitMiddleware)

    # -- Routers --------------------------------------------------------------
    app.include_router(auth_router.router)
    app.include_router(portfolio_router.router)
    app.include_router(billing_router.router)
    app.include_router(stripe_webhooks_router.router)

    # -- Health check (unauthenticated) ---------------------------------------
    @app.get("/health", tags=["meta"], summary="Health check")
    def health():
        return {"status": "ok"}

    return app


# Module-level app instance for uvicorn
app = create_app()
