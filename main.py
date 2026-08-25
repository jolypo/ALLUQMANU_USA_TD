from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from telegram import Update

from app.config import settings
from app.providers.alpaca import AlpacaProvider
from app.repositories.json_repo import JsonRepository
from app.scheduler.monitor import TradeMonitor
from app.telegram.bots import TelegramHub
from app.trading.service import SignalService


# =========================================================
# Core Dependencies
# =========================================================

provider = AlpacaProvider()

history = JsonRepository(
    "trade_history.json"
)

open_repo = JsonRepository(
    "open_trades.json"
)

state_repo = JsonRepository(
    "state.json"
)

service = SignalService(
    provider,
    history,
)

hub = TelegramHub(
    service,
    open_repo,
    history,
    state_repo,
)

monitor = TradeMonitor(
    open_repo=open_repo,
    history_repo=history,
    state_repo=state_repo,
    provider=provider,
    signal_bot=hub.app.bot,
    profit_bot=hub.profit,
    report_bot=hub.report,
    channel_id=settings.telegram_channel_chat_id,
    interval=settings.trade_monitor_seconds,
)


# =========================================================
# Application Lifecycle
# =========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup:
    - Initialize Signal Bot application.
    - Start Telegram processing.
    - Start monitoring-only scheduler.
    - Configure Telegram webhook.

    Shutdown:
    - Stop scheduler.
    - Stop Telegram application.
    - Close Alpaca HTTP session.
    """

    await hub.app.initialize()
    await hub.app.start()

    monitor.start()

    if settings.public_base_url:
        webhook_url = (
            f"{settings.public_base_url.rstrip('/')}"
            "/telegram/webhook"
        )

        webhook_kwargs = {
            "url": webhook_url,
            "allowed_updates": Update.ALL_TYPES,
            "drop_pending_updates": False,
        }

        if settings.telegram_webhook_secret:
            webhook_kwargs[
                "secret_token"
            ] = settings.telegram_webhook_secret

        await hub.app.bot.set_webhook(
            **webhook_kwargs
        )

    try:
        yield

    finally:
        await monitor.stop()

        await hub.app.stop()
        await hub.app.shutdown()

        await provider.close()


# =========================================================
# FastAPI
# =========================================================

app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)


# =========================================================
# Root
# =========================================================

@app.get("/")
async def root():
    return {
        "service": settings.app_name,
        "status": "ok",
        "paper_mode": settings.paper_mode,
        "live_trading": settings.live_trading,
    }


# =========================================================
# Health
# =========================================================

@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": settings.app_name,
        "environment": settings.environment,
        "paper_mode": settings.paper_mode,
        "live_trading": settings.live_trading,
        "channel_configured": bool(
            settings.telegram_channel_chat_id
        ),
        "webhook_configured": bool(
            settings.public_base_url
        ),
        "monitoring": True,
        "manual_publish_required": (
            settings.require_manual_publish
        ),
        "max_signals_per_scan": (
            settings.max_signals_per_scan
        ),
        "max_open_trades": (
            settings.max_open_trades
        ),
        "weekly_report_image": (
            settings.weekly_report_image_enabled
        ),
        "option_card_orientation": (
            settings.option_card_orientation
        ),
        "enable_0dte": (
            settings.enable_0dte
        ),
    }


# =========================================================
# Telegram Webhook
# =========================================================

@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
):
    """
    Webhook is used only by Signal Bot.

    Profit Bot and Report Bot are outbound-only.
    """

    if settings.telegram_webhook_secret:
        received_secret = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token"
        )

        if (
            received_secret
            != settings.telegram_webhook_secret
        ):
            raise HTTPException(
                status_code=403,
                detail="invalid webhook secret",
            )

    data = await request.json()

    update = Update.de_json(
        data,
        hub.app.bot,
    )

    await hub.app.process_update(
        update
    )

    return {
        "ok": True
    }
