from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from telegram import Update

from app.config import settings
from app.providers.alpaca import AlpacaProvider
from app.repositories.json_repo import JsonRepository
from app.scheduler.monitor import TradeMonitor
from app.telegram.bots import TelegramHub
from app.trading.service import SignalService

provider = AlpacaProvider()
history = JsonRepository("trade_history.json")
open_repo = JsonRepository("open_trades.json")
state_repo = JsonRepository("state.json")
service = SignalService(provider, history)
hub = TelegramHub(service, open_repo, history, state_repo)
monitor = TradeMonitor(
    open_repo,
    history,
    state_repo,
    provider,
    hub.app.bot,
    hub.profit,
    hub.report,
    settings.telegram_channel_chat_id,
    settings.trade_monitor_seconds,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialized = False
    started = False
    try:
        await hub.app.initialize()
        initialized = True
        await hub.app.start()
        started = True
        monitor.start()
        if settings.public_base_url:
            url = f"{settings.public_base_url.rstrip('/')}/telegram/webhook"
            kwargs = {}
            if settings.telegram_webhook_secret:
                kwargs["secret_token"] = settings.telegram_webhook_secret
            await hub.app.bot.set_webhook(
                url=url,
                allowed_updates=Update.ALL_TYPES,
                **kwargs,
            )
        yield
    finally:
        await monitor.stop()
        if started:
            await hub.app.stop()
        if initialized:
            await hub.app.shutdown()
        await provider.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/")
async def root():
    return {"service": settings.app_name, "status": "ok"}


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": settings.app_name,
        "environment": settings.environment,
        "paper_mode": settings.paper_mode,
        "live_trading": settings.live_trading,
        "channel_configured": bool(settings.telegram_channel_chat_id),
        "webhook_configured": bool(settings.public_base_url),
        "monitoring": True,
        "manual_publish_required": settings.require_manual_publish,
        "max_signals_per_scan": settings.max_signals_per_scan,
        "max_open_trades": settings.max_open_trades,
        "weekly_report_image": settings.weekly_report_image_enabled,
        "option_card_orientation": settings.option_card_orientation,
        "enable_0dte": settings.enable_0dte,
        "news_filter": settings.news_enabled,
        "profit_success_usd": settings.option_profit_success_usd,
        "monitor_seconds": settings.trade_monitor_seconds,
    }


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if settings.telegram_webhook_secret:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if got != settings.telegram_webhook_secret:
            raise HTTPException(403, "invalid webhook secret")
    data = await request.json()
    update = Update.de_json(data, hub.app.bot)
    await hub.app.process_update(update)
    return {"ok": True}
