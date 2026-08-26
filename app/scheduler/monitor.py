from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.reports.performance import (
    daily_report_data,
    weekly_report_data,
)
from app.reports.weekly_card import (
    weekly_performance_card,
)


# =========================================================
# Constants
# =========================================================

USD_SAR = 3.75
OPTION_MULTIPLIER = 100


class TradeMonitor:
    """
    Monitoring-only scheduler.

    Responsibilities:
    - Monitor OPEN Paper Trades.
    - Option price increase alerts.
    - TP1 / TP2 / TP3.
    - Stop Loss.
    - Near Stop.
    - Intraday Time Exit.
    - Daily report.
    - Weekly image report.

    It NEVER creates new signals.
    """

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
        interval: int = 300,
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

    # =========================================================
    # Telegram Helpers
    # =========================================================

    async def _send(
        self,
        bot,
        text: str,
    ):
        if not self.channel_id:
            return

        try:
            await bot.send_message(
                chat_id=self.channel_id,
                text=text,
            )
        except Exception:
            pass

    async def _send_photo(
        self,
        bot,
        image_path: str,
        caption: str | None = None,
    ):
        if not self.channel_id:
            return

        try:
            with open(
                image_path,
                "rb",
            ) as image_file:
                await bot.send_photo(
                    chat_id=self.channel_id,
                    photo=image_file,
                    caption=caption,
                )
        except Exception:
            pass

    # =========================================================
    # Trading Helpers
    # =========================================================

    @staticmethod
    def _safe_float(
        value,
        default: float = 0.0,
    ) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _is_long(
        trade: dict,
    ) -> bool:
        return str(
            trade.get(
                "direction",
                "LONG",
            )
        ).upper() != "SHORT"

    def _entry_price(
        self,
        trade: dict,
    ) -> float:
        """
        Use actual simulated fill when available.

        Fallback:
        midpoint of entry range.
        """

        filled = trade.get(
            "filled_entry_price"
        )

        if filled is not None:
            value = self._safe_float(
                filled
            )

            if value > 0:
                return value

        entry_low = self._safe_float(
            trade.get(
                "entry_low",
                0,
            )
        )

        entry_high = self._safe_float(
            trade.get(
                "entry_high",
                entry_low,
            )
        )

        if (
            entry_low > 0
            and entry_high > 0
        ):
            return (
                entry_low
                + entry_high
            ) / 2

        return max(
            entry_low,
            entry_high,
            0.0,
        )

    def _pnl_pct(
        self,
        trade: dict,
        current_price: float,
    ) -> float:
        entry = self._entry_price(
            trade
        )

        if (
            entry <= 0
            or current_price <= 0
        ):
            return 0.0

        if self._is_long(
            trade
        ):
            return (
                (
                    current_price
                    - entry
                )
                / entry
            ) * 100

        return (
            (
                entry
                - current_price
            )
            / entry
        ) * 100

    @staticmethod
    def _option_contracts(
        trade: dict,
    ) -> int:
        """
        Defaults to one option contract.
        """

        value = trade.get(
            "contracts",
            trade.get(
                "contract_qty",
                1,
            ),
        )

        try:
            contracts = int(
                float(value)
            )
        except (
            TypeError,
            ValueError,
        ):
            contracts = 1

        return max(
            contracts,
            1,
        )

    def _option_cash_pnl(
        self,
        trade: dict,
        current_price: float,
    ) -> tuple[float, float]:
        """
        Option premium P&L.

        1 contract = 100 shares.

        Long option:
            (current - entry) * 100 * contracts

        Short option support is kept for safety,
        although current system uses long premium.
        """

        entry = self._entry_price(
            trade
        )

        if (
            entry <= 0
            or current_price <= 0
        ):
            return 0.0, 0.0

        contracts = (
            self._option_contracts(
                trade
            )
        )

        if self._is_long(
            trade
        ):
            profit_usd = (
                current_price
                - entry
            ) * OPTION_MULTIPLIER * contracts

        else:
            profit_usd = (
                entry
                - current_price
            ) * OPTION_MULTIPLIER * contracts

        profit_sar = (
            profit_usd
            * USD_SAR
        )

        return (
            profit_usd,
            profit_sar,
        )

    @staticmethod
    def _option_type(
        trade: dict,
    ) -> str:
        option = (
            trade.get(
                "option",
                {},
            )
            or {}
        )

        option_type = str(
            option.get(
                "type",
                option.get(
                    "option_type",
                    "",
                ),
            )
        ).upper()

        if option_type == "C":
            return "CALL"

        if option_type == "P":
            return "PUT"

        return (
            option_type
            or "OPTION"
        )

    def _option_label(
        self,
        trade: dict,
    ) -> str:
        option = (
            trade.get(
                "option",
                {},
            )
            or {}
        )

        symbol = str(
            trade.get(
                "symbol",
                "N/A",
            )
        ).upper()

        strike = option.get(
            "strike",
            "N/A",
        )

        option_type = (
            self._option_type(
                trade
            )
        )

        return (
            f"{symbol} "
            f"{strike} "
            f"{option_type}"
        )

    # =========================================================
    # Option Increase Alert
    # =========================================================

    async def _option_increase_alert(
        self,
        trade: dict,
        previous_price: float,
        current_price: float,
    ):
        """
        Send an alert whenever the monitored option
        premium is higher than its previous monitored price.
        """

        if previous_price <= 0:
            return

        if current_price <= previous_price:
            return

        increase_pct = (
            (
                current_price
                - previous_price
            )
            / previous_price
        ) * 100

        total_pnl_pct = (
            self._pnl_pct(
                trade,
                current_price,
            )
        )

        profit_usd, profit_sar = (
            self._option_cash_pnl(
                trade,
                current_price,
            )
        )

        entry = self._entry_price(
            trade
        )

        contracts = (
            self._option_contracts(
                trade
            )
        )

        await self._send(
            self.profit_bot,
            (
                "📈 ارتفاع سعر العقد\n\n"

                f"📄 "
                f"{self._option_label(trade)}\n\n"

                f"💵 سعر الدخول: "
                f"${entry:.2f}\n"

                f"◀️ السعر السابق: "
                f"${previous_price:.2f}\n"

                f"▶️ السعر الحالي: "
                f"${current_price:.2f}\n\n"

                f"📊 الزيادة الأخيرة: "
                f"+{increase_pct:.2f}%\n"

                f"📈 من الدخول: "
                f"{total_pnl_pct:+.2f}%\n\n"

                f"💵 الربح بالدولار: "
                f"{profit_usd:+.2f}$\n"

                f"🇸🇦 الربح بالريال: "
                f"{profit_sar:+.2f} SAR\n\n"

                f"📦 عدد العقود: "
                f"{contracts}\n\n"

                f"🆔 "
                f"{trade.get('trade_id', 'Paper Trade')}\n\n"

                "⚠️ Paper Trading"
            ),
        )

    # =========================================================
    # Daily Report
    # =========================================================

    async def _send_daily_report(
        self,
    ):
        report = daily_report_data(
            self.history_repo.all()
        )

        result = report.get(
            "summary",
            {},
        )

        text = (
            "📊 التقرير اليومي — Paper Trading\n\n"

            f"الصفقات المغلقة اليوم: "
            f"{result.get('trades', 0)}\n"

            f"الرابحة: "
            f"{result.get('wins', 0)}\n"

            f"الخاسرة: "
            f"{result.get('losses', 0)}\n"

            f"Breakeven: "
            f"{result.get('breakeven', 0)}\n"

            f"Win Rate: "
            f"{result.get('win_rate', 0)}%\n"

            f"Profit Factor: "
            f"{result.get('profit_factor', 0)}\n"

            f"Net P&L اليوم: "
            f"{result.get('net_pnl_pct', 0)}%\n"

            f"Max Drawdown: "
            f"{result.get('max_drawdown_pct', 0)}%\n\n"

            "⚠️ النتائج المحققة اليوم فقط\n"
            "⚠️ Paper Trading فقط"
        )

        await self._send(
            self.report_bot,
            text,
        )

    # =========================================================
    # Weekly Image Report
    # =========================================================

    async def _send_weekly_report(
        self,
    ):
        report = weekly_report_data(
            history=self.history_repo.all(),
            open_trades=self.open_repo.all(),
        )

        summary = report.get(
            "summary",
            {},
        )

        open_summary = report.get(
            "open_summary",
            {},
        )

        image_path = os.path.join(
            tempfile.gettempdir(),
            "ALLUQMANU_USA_TD_WEEKLY_REPORT.png",
        )

        try:
            weekly_performance_card(
                report,
                image_path,
            )

            net_pnl = float(
                summary.get(
                    "net_pnl_pct",
                    0,
                )
                or 0
            )

            unrealized = float(
                open_summary.get(
                    "unrealized_pnl_pct",
                    0,
                )
                or 0
            )

            caption = (
                "📈 التقرير الأسبوعي — Paper Trading\n\n"

                f"الصفقات المغلقة: "
                f"{summary.get('trades', 0)}\n"

                f"الرابحة: "
                f"{summary.get('wins', 0)}\n"

                f"الخاسرة: "
                f"{summary.get('losses', 0)}\n"

                f"Win Rate: "
                f"{summary.get('win_rate', 0)}%\n"

                f"Profit Factor: "
                f"{summary.get('profit_factor', 0)}\n"

                f"Net Realized P&L: "
                f"{net_pnl:+.2f}%\n\n"

                f"Open Positions: "
                f"{open_summary.get('total', 0)}\n"

                f"Unrealized P&L: "
                f"{unrealized:+.2f}%\n\n"

                "🟢 الأخضر = ربح\n"
                "🔴 الأحمر = خسارة\n\n"

                "⚠️ Paper Trading فقط"
            )

            await self._send_photo(
                self.report_bot,
                image_path,
                caption,
            )

        finally:
            try:
                if os.path.exists(
                    image_path
                ):
                    os.remove(
                        image_path
                    )
            except OSError:
                pass

    # =========================================================
    # Scheduled Reports
    # =========================================================

    async def _scheduled_reports(
        self,
    ):
        if not self.channel_id:
            return

        now = datetime.now(
            ZoneInfo(
                "Asia/Riyadh"
            )
        )

        if (
            settings.daily_report_enabled
            and now.hour
            >= settings.report_hour_riyadh
            and self._last_daily
            != now.date()
        ):
            self._last_daily = (
                now.date()
            )

            await self._send_daily_report()

        if (
            settings.weekly_report_enabled
            and settings.weekly_report_image_enabled
            and now.weekday() == 4
            and now.hour
            >= settings.report_hour_riyadh
        ):
            iso = now.isocalendar()

            weekly_key = (
                f"{iso.year}-"
                f"{iso.week}"
            )

            if (
                self._last_weekly
                != weekly_key
            ):
                self._last_weekly = (
                    weekly_key
                )

                await self._send_weekly_report()

    # =========================================================
    # Monitoring Cycle
    # =========================================================

    async def cycle(
        self,
    ):
        rows = self.open_repo.all()

        changed = False

        # =====================================================
        # Stocks
        # =====================================================

        stocks = [
            trade["symbol"]
            for trade in rows
            if (
                trade.get(
                    "status"
                )
                == "OPEN"
                and trade.get(
                    "option"
                )
                is None
            )
        ]

        stockbars = {}

        try:
            if stocks:
                stockbars = (
                    await self.provider.latest_bars(
                        sorted(
                            set(
                                stocks
                            )
                        )
                    )
                )

        except Exception:
            stockbars = {}

        # =====================================================
        # Options
        # =====================================================

        option_contracts = [
            (
                trade.get(
                    "option",
                    {},
                )
                or {}
            ).get(
                "symbol"
            )
            for trade in rows
            if (
                trade.get(
                    "status"
                )
                == "OPEN"
                and trade.get(
                    "option"
                )
            )
        ]

        option_contracts = [
            contract
            for contract in option_contracts
            if contract
        ]

        optquotes = {}

        try:
            if option_contracts:
                optquotes = (
                    await self.provider.option_quotes(
                        sorted(
                            set(
                                option_contracts
                            )
                        )
                    )
                )

        except Exception:
            optquotes = {}

        # =====================================================
        # Market Clock
        # =====================================================

        market_open = True

        try:
            clock = (
                await self.provider.market_clock()
            )

            market_open = bool(
                clock.get(
                    "is_open"
                )
            )

        except Exception:
            market_open = True

        # =====================================================
        # Iterate Trades
        # =====================================================

        still_open = []

        for trade in rows:
            if (
                trade.get(
                    "status"
                )
                != "OPEN"
            ):
                still_open.append(
                    trade
                )

                continue

            price = None

            # IMPORTANT:
            # Preserve the old price BEFORE updating it.
            previous_price = trade.get(
                "last_price"
            )

            try:
                previous_price = (
                    float(previous_price)
                    if previous_price is not None
                    else None
                )
            except (
                TypeError,
                ValueError,
            ):
                previous_price = None

            # =================================================
            # Option Quote
            # =================================================

            if trade.get(
                "option"
            ):
                option = (
                    trade.get(
                        "option",
                        {},
                    )
                    or {}
                )

                contract_symbol = option.get(
                    "symbol"
                )

                quote = (
                    optquotes.get(
                        contract_symbol,
                        {},
                    )
                    or {}
                )

                bid = quote.get(
                    "bp"
                )

                if bid is None:
                    bid = quote.get(
                        "bid_price"
                    )

                ask = quote.get(
                    "ap"
                )

                if ask is None:
                    ask = quote.get(
                        "ask_price"
                    )

                try:
                    if (
                        bid is not None
                        and ask is not None
                        and float(bid) > 0
                        and float(ask) > 0
                    ):
                        price = (
                            float(bid)
                            + float(ask)
                        ) / 2

                    elif (
                        bid is not None
                        and float(bid) > 0
                    ):
                        price = float(
                            bid
                        )

                    elif (
                        ask is not None
                        and float(ask) > 0
                    ):
                        price = float(
                            ask
                        )

                except (
                    TypeError,
                    ValueError,
                ):
                    price = None

            # =================================================
            # Stock Quote
            # =================================================

            else:
                bar = (
                    stockbars.get(
                        trade["symbol"],
                        {},
                    )
                    or {}
                )

                if (
                    bar.get(
                        "c"
                    )
                    is not None
                ):
                    try:
                        price = float(
                            bar["c"]
                        )

                    except (
                        TypeError,
                        ValueError,
                    ):
                        price = None

            # =================================================
            # No Current Price
            # =================================================

            if price is None:
                still_open.append(
                    trade
                )

                continue

            price = round(
                price,
                4,
            )

            # =================================================
            # Option Price Increase Alert
            # =================================================

            if (
                trade.get(
                    "option"
                )
                and previous_price is not None
                and previous_price > 0
                and price > previous_price
            ):
                await self._option_increase_alert(
                    trade=trade,
                    previous_price=previous_price,
                    current_price=price,
                )

            # =================================================
            # Update Current Price
            # =================================================

            trade[
                "last_price"
            ] = price

            trade[
                "last_monitored_at"
            ] = datetime.now(
                timezone.utc
            ).isoformat()

            changed = True

            # =================================================
            # Direction + Entry
            # =================================================

            long_trade = (
                self._is_long(
                    trade
                )
            )

            entry = self._entry_price(
                trade
            )

            if entry <= 0:
                still_open.append(
                    trade
                )

                continue

            stop = float(
                trade[
                    "stop"
                ]
            )

            initial_risk = (
                abs(
                    entry
                    - stop
                )
                or max(
                    entry
                    * 0.01,
                    0.01,
                )
            )

            # =================================================
            # Intraday Time Exit
            # =================================================

            if (
                "INTRADAY"
                in trade.get(
                    "trade_type",
                    "",
                )
                and not market_open
            ):
                trade[
                    "status"
                ] = "CLOSED"

                trade[
                    "exit_price"
                ] = price

                trade[
                    "exit_reason"
                ] = "TIME_EXIT"

                trade[
                    "closed_at"
                ] = datetime.now(
                    timezone.utc
                ).isoformat()

                trade[
                    "pnl_pct"
                ] = round(
                    self._pnl_pct(
                        trade,
                        price,
                    ),
                    2,
                )

                self.history_repo.append(
                    trade
                )

                await self._send(
                    self.signal_bot,
                    (
                        "🟠 إغلاق زمني\n\n"

                        f"{trade['symbol']}\n"

                        f"🆔 "
                        f"{trade.get('trade_id', 'Paper Trade')}\n\n"

                        f"الخروج الورقي: "
                        f"{price:.2f}\n"

                        f"النتيجة: "
                        f"{trade['pnl_pct']:+.2f}%\n\n"

                        "Exit Reason:\n"
                        "TIME_EXIT"
                    ),
                )

                continue

            # =================================================
            # Near Stop
            # =================================================

            distance_to_stop = (
                price
                - stop
                if long_trade
                else stop
                - price
            )

            if (
                distance_to_stop
                <= (
                    initial_risk
                    * settings.near_stop_fraction
                )
                and distance_to_stop > 0
                and not trade.get(
                    "near_stop_sent"
                )
            ):
                trade[
                    "near_stop_sent"
                ] = True

                await self._send(
                    self.signal_bot,
                    (
                        "⚠️ Near Stop Loss\n\n"

                        f"{trade['symbol']}\n"

                        f"🆔 "
                        f"{trade.get('trade_id', 'Paper Trade')}\n\n"

                        f"السعر الورقي: "
                        f"{price:.2f}\n"

                        f"وقف الصفقة: "
                        f"{stop:.2f}"
                    ),
                )

            # =================================================
            # Stop Loss
            # =================================================

            hit_stop = (
                price <= stop
                if long_trade
                else price >= stop
            )

            if hit_stop:
                trade[
                    "status"
                ] = "LOSS"

                trade[
                    "exit_price"
                ] = price

                trade[
                    "exit_reason"
                ] = "STOP_LOSS"

                trade[
                    "closed_at"
                ] = datetime.now(
                    timezone.utc
                ).isoformat()

                trade[
                    "pnl_pct"
                ] = round(
                    self._pnl_pct(
                        trade,
                        price,
                    ),
                    2,
                )

                self.history_repo.append(
                    trade
                )

                await self._send(
                    self.signal_bot,
                    (
                        "🔴 وقف الخسارة\n\n"

                        f"{trade['symbol']}\n"

                        f"🆔 "
                        f"{trade.get('trade_id', 'Paper Trade')}\n\n"

                        f"الخروج الورقي: "
                        f"{price:.2f}\n"

                        f"النتيجة: "
                        f"{trade['pnl_pct']:+.2f}%\n\n"

                        "Exit Reason:\n"
                        "STOP_LOSS"
                    ),
                )

                continue

            # =================================================
            # Targets
            # =================================================

            for target_number in (
                1,
                2,
                3,
            ):
                target_key = (
                    f"tp{target_number}"
                )

                flag_key = (
                    f"tp{target_number}_hit"
                )

                target = float(
                    trade[
                        target_key
                    ]
                )

                target_hit = (
                    price >= target
                    if long_trade
                    else price <= target
                )

                if (
                    target_hit
                    and not trade.get(
                        flag_key
                    )
                ):
                    trade[
                        flag_key
                    ] = True

                    pnl_pct = (
                        self._pnl_pct(
                            trade,
                            price,
                        )
                    )

                    # =========================================
                    # Option TP Message
                    # =========================================

                    if trade.get(
                        "option"
                    ):
                        profit_usd, profit_sar = (
                            self._option_cash_pnl(
                                trade,
                                price,
                            )
                        )

                        contracts = (
                            self._option_contracts(
                                trade
                            )
                        )

                        tp_message = (
                            f"🟢 تحقق TP"
                            f"{target_number}\n\n"

                            f"📄 "
                            f"{self._option_label(trade)}\n\n"

                            f"💵 سعر الدخول: "
                            f"${entry:.2f}\n"

                            f"💰 السعر الحالي: "
                            f"${price:.2f}\n"

                            f"🎯 الهدف: "
                            f"${target:.2f}\n\n"

                            f"📈 الربح: "
                            f"{pnl_pct:+.2f}%\n\n"

                            f"💵 الربح بالدولار: "
                            f"{profit_usd:+.2f}$\n"

                            f"🇸🇦 الربح بالريال: "
                            f"{profit_sar:+.2f} SAR\n\n"

                            f"📦 عدد العقود: "
                            f"{contracts}\n\n"

                            f"🆔 "
                            f"{trade.get('trade_id', 'Paper Trade')}\n\n"

                            "⚠️ Paper Trading"
                        )

                    # =========================================
                    # Stock TP Message
                    # =========================================

                    else:
                        tp_message = (
                            f"🟢 تحقق TP"
                            f"{target_number}\n\n"

                            f"{trade['symbol']}\n"

                            f"🆔 "
                            f"{trade.get('trade_id', 'Paper Trade')}\n\n"

                            f"السعر الورقي الحالي: "
                            f"{price:.2f}\n"

                            f"الهدف: "
                            f"{target:.2f}\n"

                            f"النتيجة: "
                            f"{pnl_pct:+.2f}%"
                        )

                    await self._send(
                        self.profit_bot,
                        tp_message,
                    )

                    # TP1 -> Break Even
                    if (
                        target_number == 1
                        and settings
                        .trailing_after_tp1_to_entry
                    ):
                        trade[
                            "stop"
                        ] = round(
                            entry,
                            4,
                        )

            # =================================================
            # TP3 Complete
            # =================================================

            if trade.get(
                "tp3_hit"
            ):
                trade[
                    "status"
                ] = "WIN"

                trade[
                    "exit_price"
                ] = price

                trade[
                    "exit_reason"
                ] = "TP3"

                trade[
                    "closed_at"
                ] = datetime.now(
                    timezone.utc
                ).isoformat()

                trade[
                    "pnl_pct"
                ] = round(
                    self._pnl_pct(
                        trade,
                        price,
                    ),
                    2,
                )

                self.history_repo.append(
                    trade
                )

                continue

            still_open.append(
                trade
            )

        # =====================================================
        # Save State
        # =====================================================

        if changed:
            self.open_repo.replace(
                still_open
            )

        # =====================================================
        # Reports
        # =====================================================

        await self._scheduled_reports()

    # =========================================================
    # Loop
    # =========================================================

    async def loop(
        self,
    ):
        while True:
            try:
                await self.cycle()

            except Exception:
                pass

            await asyncio.sleep(
                self.interval
            )

    # =========================================================
    # Start / Stop
    # =========================================================

    def start(
        self,
    ):
        if not self._task:
            self._task = asyncio.create_task(
                self.loop()
            )

    async def stop(
        self,
    ):
        if self._task:
            self._task.cancel()

            try:
                await self._task

            except asyncio.CancelledError:
                pass

            finally:
                self._task = None
