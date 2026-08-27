from __future__ import annotations
from datetime import datetime, timedelta, timezone
import asyncio
import httpx
import pandas as pd
from app.config import settings


class AlpacaProvider:
    def __init__(self):
        self.headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
        }
        self.client = httpx.AsyncClient(timeout=20, headers=self.headers)
        self._sem = asyncio.Semaphore(5)

    async def close(self):
        await self.client.aclose()

    async def _get(self, url: str, params: dict | None = None) -> dict:
        async with self._sem:
            last = None
            for attempt in range(3):
                try:
                    r = await self.client.get(url, params=params)
                    if r.status_code == 429 and attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    r.raise_for_status()
                    return r.json()
                except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as e:
                    last = e
                    retryable = (
                        not isinstance(e, httpx.HTTPStatusError)
                        or e.response.status_code in {429, 500, 502, 503, 504}
                    )
                    if not retryable or attempt == 2:
                        raise
                    await asyncio.sleep(1.25 * (attempt + 1))
            if last:
                raise last
        return {}

    async def bars(self, symbol: str, timeframe: str, lookback_days: int) -> pd.DataFrame:
        start = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        url = f"{settings.alpaca_data_base_url}/v2/stocks/{symbol}/bars"
        data = await self._get(url, {
            "timeframe": timeframe,
            "start": start,
            "adjustment": "all",
            "feed": settings.alpaca_stock_feed,
            "limit": 10000,
            "sort": "asc",
        })
        rows = data.get("bars", [])
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([{
            "timestamp": x.get("t"),
            "open": x.get("o"),
            "high": x.get("h"),
            "low": x.get("l"),
            "close": x.get("c"),
            "volume": x.get("v"),
        } for x in rows])

    async def latest_bars(self, symbols: list[str]) -> dict:
        if not symbols:
            return {}
        url = f"{settings.alpaca_data_base_url}/v2/stocks/bars/latest"
        d = await self._get(url, {"symbols": ",".join(symbols), "feed": settings.alpaca_stock_feed})
        return d.get("bars", {})

    async def market_clock(self) -> dict:
        return await self._get(f"{settings.alpaca_trading_base_url}/clock")

    async def option_chain(self, underlying: str, min_dte: int, max_dte: int, opt_type: str | None = None) -> dict:
        now = datetime.now(timezone.utc).date()
        params = {
            "feed": settings.alpaca_options_feed,
            "limit": 1000,
            "expiration_date_gte": str(now + timedelta(days=min_dte)),
            "expiration_date_lte": str(now + timedelta(days=max_dte)),
        }
        if opt_type:
            params["type"] = opt_type
        url = f"{settings.alpaca_data_base_url}/v1beta1/options/snapshots/{underlying}"
        return await self._get(url, params)

    async def option_quotes(self, contract_symbols: list[str]) -> dict:
        if not contract_symbols:
            return {}
        url = f"{settings.alpaca_data_base_url}/v1beta1/options/quotes/latest"
        d = await self._get(url, {
            "symbols": ",".join(contract_symbols[:100]),
            "feed": settings.alpaca_options_feed,
        })
        return d.get("quotes", {})

    async def news(self, symbol: str, lookback_hours: int = 6, limit: int = 8) -> list[dict]:
        start = (datetime.now(timezone.utc) - timedelta(hours=max(1, lookback_hours))).isoformat()
        url = f"{settings.alpaca_data_base_url}/v1beta1/news"
        d = await self._get(url, {
            "symbols": symbol,
            "start": start,
            "sort": "desc",
            "limit": max(1, min(50, limit)),
            "include_content": "false",
        })
        return d.get("news", []) or []
