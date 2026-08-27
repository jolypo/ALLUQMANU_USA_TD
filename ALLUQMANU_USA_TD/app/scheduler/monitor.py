from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.reports.performance import daily_category_reports, weekly_report_data
from app.reports.profit_card import profit_update_card
from app.reports.weekly_card import weekly_performance_card
from app.strategies.engine import StrategyEngine


class TradeMonitor:
    """Monitoring only. Never creates a new signal."""

    def __init__(
        self,
        open_repo,
        history_repo,
        state_repo,
        provider,
        signal_bot,
        profit_bot,
        report_bot,
        channel_id,
        interval: int = 60,
    ):
        self.open_repo = open_repo
        self.history_repo = history_repo
        self.state_repo = state_repo
        self.provider = provider
        self.signal_bot = signal_bot
        self.profit_bot = profit_bot
        self.report_bot = report_bot
        self.channel_id = channel_id
        self.interval = interval
        self._task = None
        self._last_daily = None
        self._last_weekly = None

    async def _send(self, bot, text: str, chat_id=None, reply_to_message_id=None):
        target = chat_id if chat_id is not None else self.channel_id
        if not target:
            return None
        try:
            return await bot.send_message(
                chat_id=target,
                text=text,
                reply_to_message_id=reply_to_message_id,
                allow_sending_without_reply=True,
            )
        except Exception as exc:
            print(f"[monitor-send] {type(exc).__name__}: {exc}")
            return None

    async def _send_photo(self, bot, path: str, caption=None, chat_id=None, reply_to_message_id=None):
        target = chat_id if chat_id is not None else self.channel_id
        if not target:
            return None
        try:
            with open(path, "rb") as f:
                return await bot.send_photo(
                    chat_id=target,
                    photo=f,
                    caption=caption,
                    reply_to_message_id=reply_to_message_id,
                    allow_sending_without_reply=True,
                )
        except Exception as exc:
            print(f"[monitor-photo] {type(exc).__name__}: {exc}")
            return None

    @staticmethod
    def _f(v, default=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    def _entry(self, trade: dict) -> float:
        filled = self._f(trade.get("filled_entry_price"), 0.0)
        if filled > 0:
            return filled
        lo = self._f(trade.get("entry_low"), 0.0)
        hi = self._f(trade.get("entry_high"), 0.0)
        return (lo + hi) / 2 if lo > 0 and hi > 0 else max(lo, hi, 0.0)

    def _long(self, trade: dict) -> bool:
        return str(trade.get("direction", "LONG")).upper() != "SHORT"

    def _pnl_pct(self, trade: dict, price: float) -> float:
        entry = self._entry(trade)
        if entry <= 0:
            return 0.0
        diff = price - entry if self._long(trade) else entry - price
        return diff / entry * 100

    def _cash(self, trade: dict, price: float) -> tuple[float, float]:
        if not trade.get("option"):
            return 0.0, 0.0
        entry = self._entry(trade)
        qty = max(1, int(self._f(trade.get("contracts", 1), 1)))
        diff = price - entry if self._long(trade) else entry - price
        usd = diff * settings.option_multiplier * qty
        return usd, usd * settings.usd_sar_rate

    def _label(self, trade: dict) -> str:
        option = trade.get("option") or {}
        typ = str(option.get("type") or option.get("option_type") or "OPTION").upper()
        if typ == "C":
            typ = "CALL"
        if typ == "P":
            typ = "PUT"
        return f"{trade.get('symbol', '')} {option.get('strike', '')} {typ}".strip()

    @staticmethod
    def _reply_id(trade: dict):
        try:
            return int(trade.get("channel_message_id")) if trade.get("channel_message_id") else None
        except (TypeError, ValueError):
            return None

    async def _momentum_state(self, trade: dict) -> tuple[str, str, str]:
        """Evaluate momentum on the underlying, not the option premium alone."""
        try:
            df = await self.provider.bars(
                str(trade.get("symbol")),
                settings.intraday_timeframe,
                min(12, settings.intraday_lookback_days),
            )
            if len(df) < 40:
                raise ValueError("insufficient bars")
            analysis = StrategyEngine().analyze(df)
            momentum = float(analysis["scores"].get("Momentum", 50))
            trend = float(analysis["scores"].get("Trend", 50))
            desired = (trade.get("option") or {}).get("underlying_direction") or trade.get("direction", "LONG")
            aligned = analysis.get("direction") == desired
            if aligned and momentum >= 70 and trend >= 65:
                return "🟢", "قوي", "استمرار مع حماية الربح"
            if (not aligned and analysis.get("direction") in {"LONG", "SHORT"}) or momentum <= 42:
                return "🔴", "ضعيف أو انعكاس", "يفضل الخروج من العقد"
            return "🟡", "يتباطأ", "تأمين جزء من الربح / رفع الوقف"
        except Exception:
            return "🟡", "يتباطأ", "تأمين جزء من الربح / رفع الوقف"

    async def _profit_update(self, trade: dict, previous: float, price: float):
        usd, sar = self._cash(trade, price)
        pnl = self._pnl_pct(trade, price)
        path = os.path.join(tempfile.gettempdir(), f"profit_{trade.get('trade_id', 'trade')}.png")
        profit_update_card(trade, usd, sar, price, path)
        caption = (
            f"📈 ارتفاع سعر العقد\n"
            f"{self._label(trade)}\n"
            f"💵 الدخول: ${self._entry(trade):.2f} | السابق: ${previous:.2f} | الحالي: ${price:.2f}\n"
            f"📊 من الدخول: {pnl:+.2f}%\n"
            f"💵 الربح: {usd:+.2f}$\n"
            f"🇸🇦 الربح بالريال السعودي: {sar:+.2f} ريال\n"
            f"🆔 {trade.get('trade_id', '')}"
        )
        try:
            await self._send_photo(
                self.profit_bot,
                path,
                caption,
                reply_to_message_id=self._reply_id(trade),
            )
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

        trade["max_profit_usd"] = round(max(self._f(trade.get("max_profit_usd"), 0.0), usd), 2)

        if usd >= settings.option_profit_success_usd and not trade.get("success_100_reached"):
            trade["success_100_reached"] = True
            trade["success_100_at"] = datetime.now(timezone.utc).isoformat()
            icon, state, advice = await self._momentum_state(trade)
            path = os.path.join(tempfile.gettempdir(), f"milestone_{trade.get('trade_id', 'trade')}.png")
            profit_update_card(trade, usd, sar, price, path)
            msg = (
                f"🎉 مبروك الأرباح\n"
                f"{self._label(trade)}\n"
                f"💵 الربح الحالي: +${usd:,.2f}\n"
                f"🇸🇦 الربح بالريال السعودي: +{sar:,.2f} ريال\n"
                f"📈 سعر العقد الحالي: ${price:.2f}\n"
                f"🧠 الزخم: {icon} {state} — {advice}\n"
                f"ملاحظة:\n"
                f"🟢 قوي → استمرار مع حماية الربح\n"
                f"🟡 يتباطأ → تأمين جزء من الربح / رفع الوقف\n"
                f"🔴 ضعيف أو انعكاس → يفضل الخروج من العقد\n"
                f"🆔 {trade.get('trade_id', '')}"
            )
            try:
                await self._send_photo(
                    self.profit_bot,
                    path,
                    msg,
                    reply_to_message_id=self._reply_id(trade),
                )
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass

    @staticmethod
    def _daily_text(category: str, summary: dict) -> str:
        title = {
            "stock": "📊 التقرير اليومي — الأسهم الأمريكية",
            "equity_option": "📊 التقرير اليومي — عقود الأسهم",
            "index_option": "📊 التقرير اليومي — عقود المؤشر",
        }[category]
        lines = [
            title,
            f"الصفقات اليوم: {summary['activity']}",
            f"المغلقة: {summary['closed']}",
            f"✅ الناجحة: {summary['wins']}",
            f"🔴 الخاسرة: {summary['losses']}",
            f"⚪ Breakeven: {summary['breakeven']}",
            f"📈 Win Rate: {summary['win_rate']:.2f}%",
            f"⚖️ Profit Factor: {summary['profit_factor']}",
            f"📊 Net P&L: {summary['net_pnl_pct']:+.2f}%",
            f"📉 Max Drawdown: {summary['max_drawdown_pct']:+.2f}%",
        ]
        if category != "stock":
            lines.extend([
                f"💵 صافي الربح: {summary['net_cash_usd']:+.2f}$",
                f"🇸🇦 صافي الربح: {summary['net_cash_sar']:+.2f} ريال",
            ])
        return "\n".join(lines)

    async def _send_daily_reports(self):
        reports = daily_category_reports(self.history_repo.all(), self.open_repo.all())
        for category in ("stock", "equity_option", "index_option"):
            if category in reports:
                await self._send(
                    self.report_bot,
                    self._daily_text(category, reports[category]),
                    chat_id=settings.telegram_admin_user_id,
                )

    async def _send_weekly_report(self):
        if not self.channel_id:
            return
        report = weekly_report_data(self.history_repo.all(), self.open_repo.all())
        summary = report.get("summary", {})
        open_summary = report.get("open_summary", {})
        path = os.path.join(tempfile.gettempdir(), "ALLUQMANU_USA_TD_WEEKLY_REPORT.png")
        try:
            weekly_performance_card(report, path)
            caption = (
                f"📈 التقرير الأسبوعي\n"
                f"الصفقات المغلقة: {summary.get('trades', 0)} | الرابحة: {summary.get('wins', 0)} | الخاسرة: {summary.get('losses', 0)}\n"
                f"Win Rate: {summary.get('win_rate', 0)}% | Profit Factor: {summary.get('profit_factor', 0)}\n"
                f"Net Realized P&L: {float(summary.get('net_pnl_pct', 0)):+.2f}%\n"
                f"Open Positions: {open_summary.get('total', 0)} | Unrealized: {float(open_summary.get('unrealized_pnl_pct', 0)):+.2f}%"
            )
            await self._send_photo(self.report_bot, path, caption)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    async def _scheduled_reports(self):
        now = datetime.now(ZoneInfo("Asia/Riyadh"))
        if (
            settings.daily_report_enabled
            and now.hour >= settings.report_hour_riyadh
            and self._last_daily != now.date()
        ):
            self._last_daily = now.date()
            await self._send_daily_reports()

        if (
            settings.weekly_report_enabled
            and settings.weekly_report_image_enabled
            and now.weekday() == 4
            and now.hour >= settings.report_hour_riyadh
        ):
            key = f"{now.isocalendar().year}-{now.isocalendar().week}"
            if self._last_weekly != key:
                self._last_weekly = key
                await self._send_weekly_report()

    async def cycle(self):
        rows = self.open_repo.all()
        changed = False

        stock_symbols = {
            trade.get("symbol")
            for trade in rows
            if trade.get("status") == "OPEN" and not trade.get("option") and trade.get("symbol")
        }
        stockbars = {}
        try:
            if stock_symbols:
                stockbars = await self.provider.latest_bars(sorted(stock_symbols))
        except Exception:
            pass

        contracts = [
            (trade.get("option") or {}).get("symbol")
            for trade in rows
            if trade.get("status") == "OPEN" and trade.get("option")
        ]
        contracts = [x for x in contracts if x]
        optquotes = {}
        try:
            if contracts:
                optquotes = await self.provider.option_quotes(sorted(set(contracts)))
        except Exception:
            pass

        market_open = True
        try:
            market_open = bool((await self.provider.market_clock()).get("is_open"))
        except Exception:
            pass

        still_open = []
        for trade in rows:
            if trade.get("status") != "OPEN":
                still_open.append(trade)
                continue

            previous = self._f(trade.get("last_price"), 0.0) if trade.get("last_price") is not None else None
            price = None

            if trade.get("option"):
                quote = optquotes.get((trade.get("option") or {}).get("symbol"), {}) or {}
                bid = quote.get("bp", quote.get("bid_price"))
                ask = quote.get("ap", quote.get("ask_price"))
                try:
                    bid = float(bid) if bid is not None else 0.0
                    ask = float(ask) if ask is not None else 0.0
                    price = (bid + ask) / 2 if bid > 0 and ask > 0 else bid if bid > 0 else ask if ask > 0 else None
                except (TypeError, ValueError):
                    price = None
            else:
                bar = stockbars.get(trade.get("symbol"), {}) or {}
                try:
                    price = float(bar.get("c")) if bar.get("c") is not None else None
                except (TypeError, ValueError):
                    price = None

            if price is None:
                still_open.append(trade)
                continue

            price = round(price, 4)
            trade["last_price"] = price
            trade["last_monitored_at"] = datetime.now(timezone.utc).isoformat()
            changed = True

            # Existing trades with an old filled_entry_price remain compatible.
            confirmed = bool(trade.get("entry_confirmed", trade.get("filled_entry_price") is not None))
            if not confirmed:
                lo = self._f(trade.get("entry_low"), 0.0)
                hi = self._f(trade.get("entry_high"), 0.0)
                lo, hi = min(lo, hi), max(lo, hi)
                if lo <= price <= hi:
                    trade["entry_confirmed"] = True
                    trade["filled_entry_price"] = price
                    trade["entered_at"] = datetime.now(timezone.utc).isoformat()
                    label = self._label(trade) if trade.get("option") else trade.get("symbol")
                    await self._send(
                        self.signal_bot,
                        f"✅ تم الدخول في الصفقة\n{label}\n💵 سعر الدخول: ${price:.2f}\n🆔 {trade.get('trade_id', '')}",
                        reply_to_message_id=self._reply_id(trade),
                    )
                else:
                    still_open.append(trade)
                    continue

            if trade.get("option") and previous and price > previous:
                await self._profit_update(trade, previous, price)

            entry = self._entry(trade)
            long_trade = self._long(trade)
            stop = self._f(trade.get("stop"), 0.0)
            initial_risk = abs(entry - stop) or max(entry * 0.01, 0.01)

            if "INTRADAY" in str(trade.get("trade_type", "")) and not market_open:
                pnl = round(self._pnl_pct(trade, price), 2)
                trade.update(
                    status="CLOSED",
                    exit_price=price,
                    exit_reason="TIME_EXIT",
                    closed_at=datetime.now(timezone.utc).isoformat(),
                    pnl_pct=pnl,
                )
                usd, sar = self._cash(trade, price)
                trade["cash_pnl_usd"] = round(usd, 2)
                trade["cash_pnl_sar"] = round(sar, 2)
                self.history_repo.append(trade)
                label = self._label(trade) if trade.get("option") else trade.get("symbol")
                await self._send(
                    self.signal_bot,
                    f"🟠 إغلاق زمني\n{label}\nالخروج: {price:.2f}\nالنتيجة: {pnl:+.2f}%\n🆔 {trade.get('trade_id', '')}",
                    reply_to_message_id=self._reply_id(trade),
                )
                continue

            distance_to_stop = price - stop if long_trade else stop - price
            if (
                distance_to_stop <= initial_risk * settings.near_stop_fraction
                and distance_to_stop > 0
                and not trade.get("near_stop_sent")
            ):
                trade["near_stop_sent"] = True
                label = self._label(trade) if trade.get("option") else trade.get("symbol")
                await self._send(
                    self.signal_bot,
                    f"⚠️ Near Stop Loss\n{label}\nالسعر: {price:.2f} | الوقف: {stop:.2f}\n🆔 {trade.get('trade_id', '')}",
                    reply_to_message_id=self._reply_id(trade),
                )

            hit_stop = price <= stop if long_trade else price >= stop
            if hit_stop:
                pnl = round(self._pnl_pct(trade, price), 2)
                trade.update(
                    status="LOSS",
                    exit_price=price,
                    exit_reason="STOP_LOSS",
                    closed_at=datetime.now(timezone.utc).isoformat(),
                    pnl_pct=pnl,
                )
                usd, sar = self._cash(trade, price)
                trade["cash_pnl_usd"] = round(usd, 2)
                trade["cash_pnl_sar"] = round(sar, 2)
                self.history_repo.append(trade)
                label = self._label(trade) if trade.get("option") else trade.get("symbol")
                await self._send(
                    self.signal_bot,
                    f"🔴 وقف الخسارة\n{label}\nالخروج: {price:.2f}\nالنتيجة: {pnl:+.2f}%\n🆔 {trade.get('trade_id', '')}",
                    reply_to_message_id=self._reply_id(trade),
                )
                continue

            for n in (1, 2, 3):
                target = self._f(trade.get(f"tp{n}"), 0.0)
                flag = f"tp{n}_hit"
                target_hit = price >= target if long_trade else price <= target
                if target and target_hit and not trade.get(flag):
                    trade[flag] = True
                    pnl = self._pnl_pct(trade, price)
                    if trade.get("option"):
                        usd, sar = self._cash(trade, price)
                        msg = (
                            f"🟢 تحقق TP{n}\n{self._label(trade)}\n"
                            f"💰 السعر: ${price:.2f} | الهدف: ${target:.2f}\n"
                            f"📈 الربح: {pnl:+.2f}%\n💵 الربح: {usd:+.2f}$\n"
                            f"🇸🇦 الربح بالريال السعودي: {sar:+.2f} ريال\n🆔 {trade.get('trade_id', '')}"
                        )
                    else:
                        msg = (
                            f"🟢 تحقق TP{n}\n{trade.get('symbol')}\n"
                            f"السعر: {price:.2f} | الهدف: {target:.2f}\n"
                            f"النتيجة: {pnl:+.2f}%\n🆔 {trade.get('trade_id', '')}"
                        )
                    await self._send(
                        self.profit_bot,
                        msg,
                        reply_to_message_id=self._reply_id(trade),
                    )
                    if n == 1 and settings.trailing_after_tp1_to_entry:
                        trade["stop"] = round(entry, 4)

            if trade.get("tp3_hit"):
                pnl = round(self._pnl_pct(trade, price), 2)
                trade.update(
                    status="WIN",
                    exit_price=price,
                    exit_reason="TP3",
                    closed_at=datetime.now(timezone.utc).isoformat(),
                    pnl_pct=pnl,
                )
                usd, sar = self._cash(trade, price)
                trade["cash_pnl_usd"] = round(usd, 2)
                trade["cash_pnl_sar"] = round(sar, 2)
                self.history_repo.append(trade)
                continue

            still_open.append(trade)

        if changed:
            self.open_repo.replace(still_open)
        await self._scheduled_reports()

    async def loop(self):
        while True:
            try:
                await self.cycle()
            except Exception as exc:
                print(f"[monitor] {type(exc).__name__}: {exc}")
            await asyncio.sleep(self.interval)

    def start(self):
        if not self._task:
            self._task = asyncio.create_task(self.loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            finally:
                self._task = None
