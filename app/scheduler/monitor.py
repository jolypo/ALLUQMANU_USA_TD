from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.reports.performance import (
    performance,
    weekly_report_data,
)
from app.reports.weekly_card import weekly_performance_card


class TradeMonitor:
    """
    Monitoring-only scheduler.

    مسؤول فقط عن:
    - متابعة الصفقات المفتوحة.
    - TP1 / TP2 / TP3.
    - Stop Loss.
    - Near Stop.
    - Time Exit.
    - التقرير اليومي.
    - التقرير الأسبوعي المصور.

    مهم:
    لا يوجد داخل هذا Scheduler أي مسار
    لإنشاء Signal أو Paper Trade جديد.
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
    # Reports
    # =========================================================

    async def _send_daily_report(self):
        """
        التقرير اليومي يبقى نصيًا حاليًا.

        التقرير الأسبوعي فقط هو المصور
        حسب التصميم الذي اعتمدناه.
        """

        result = performance(
            self.history_repo.all()
        )

        text = (
            "📊 التقرير اليومي — Paper Trading\n\n"

            f"الصفقات المغلقة: "
            f"{result['trades']}\n"

            f"الرابحة: "
            f"{result['wins']}\n"

            f"الخاسرة: "
            f"{result['losses']}\n"

            f"Win Rate: "
            f"{result['win_rate']}%\n"

            f"Profit Factor: "
            f"{result['profit_factor']}\n"

            f"Net P&L: "
            f"{result['net_pnl_pct']}%\n"

            f"Max Drawdown: "
            f"{result['max_drawdown_pct']}%\n\n"

            "⚠️ Paper Trading فقط"
        )

        await self._send(
            self.report_bot,
            text,
        )

    async def _send_weekly_report(self):
        """
        ينشئ صورة Weekly Performance Report
        ويرسلها بواسطة Report Bot.

        الصورة تفصل بين:
        - Closed / Realized
        - Open / Unrealized
        """

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

                f"Net Realized P&L: "
                f"{net_pnl:+.2f}%\n"

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

    async def _scheduled_reports(self):
        if not self.channel_id:
            return

        now = datetime.now(
            ZoneInfo(
                "Asia/Riyadh"
            )
        )

        # -------------------------------------------------
        # Daily report
        # -------------------------------------------------

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

        # -------------------------------------------------
        # Weekly report
        #
        # Friday evening Riyadh.
        # weekday:
        # Monday = 0
        # Friday = 4
        # -------------------------------------------------

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
    # Trade Monitoring
    # =========================================================

    async def cycle(self):
        rows = self.open_repo.all()

        changed = False

        # =====================================================
        # Stock latest bars
        # =====================================================

        stocks = [
            trade["symbol"]
            for trade in rows
            if (
                trade.get("status")
                == "OPEN"
                and trade.get("option")
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
        # Option quotes
        #
        # Includes:
        # - Equity Options
        # - SPX Options
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
                trade.get("status")
                == "OPEN"
                and trade.get(
                    "option"
                )
            )
        ]

        option_contracts = [
            contract
            for contract
            in option_contracts
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
            # Do not force-close trades if market clock
            # cannot be retrieved.
            market_open = True

        # =====================================================
        # Process Open Trades
        # =====================================================

        still_open = []

        for trade in rows:
            if (
                trade.get("status")
                != "OPEN"
            ):
                still_open.append(
                    trade
                )
                continue

            price = None

            # -------------------------------------------------
            # Option
            # -------------------------------------------------

            if trade.get("option"):
                option = (
                    trade.get(
                        "option",
                        {},
                    )
                    or {}
                )

                contract_symbol = (
                    option.get(
                        "symbol"
                    )
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

            # -------------------------------------------------
            # Stock
            # -------------------------------------------------

            else:
                bar = (
                    stockbars.get(
                        trade["symbol"],
                        {},
                    )
                    or {}
                )

                if (
                    bar.get("c")
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

            # -------------------------------------------------
            # No usable price
            # -------------------------------------------------

            if price is None:
                still_open.append(
                    trade
                )
                continue

            price = round(
                price,
                4,
            )

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
            # Direction
            # =================================================

            long_trade = (
                trade.get(
                    "direction"
                )
                == "LONG"
            )

            entry_low = float(
                trade["entry_low"]
            )

            entry_high = float(
                trade["entry_high"]
            )

            entry = (
                entry_low
                + entry_high
            ) / 2

            stop = float(
                trade["stop"]
            )

            initial_risk = (
                abs(
                    entry - stop
                )
                or max(
                    entry * 0.01,
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
                    (
                        (
                            price - entry
                        )
                        / entry
                        * 100
                    )
                    * (
                        1
                        if long_trade
                        else -1
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
                price - stop
                if long_trade
                else stop - price
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
                    (
                        (
                            price - entry
                        )
                        / entry
                        * 100
                    )
                    * (
                        1
                        if long_trade
                        else -1
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

                    await self._send(
                        self.profit_bot,
                        (
                            f"🟢 تحقق TP"
                            f"{target_number}\n\n"

                            f"{trade['symbol']}\n"

                            f"🆔 "
                            f"{trade.get('trade_id', 'Paper Trade')}\n\n"

                            f"السعر الورقي الحالي: "
                            f"{price:.2f}\n"

                            f"الهدف: "
                            f"{target:.2f}"
                        ),
                    )

                    # -----------------------------------------
                    # TP1 -> Break Even
                    # -----------------------------------------

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
            # TP3 = Trade Completed
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
                    (
                        (
                            price - entry
                        )
                        / entry
                        * 100
                    )
                    * (
                        1
                        if long_trade
                        else -1
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
        # Save Open Trades
        # =====================================================

        if changed:
            self.open_repo.replace(
                still_open
            )

        # =====================================================
        # Scheduled Reports
        # =====================================================

        await self._scheduled_reports()

    # =========================================================
    # Loop
    # =========================================================

    async def loop(self):
        while True:
            try:
                await self.cycle()

            except Exception:
                # Scheduler must stay alive even if
                # one cycle encounters a temporary API failure.
                pass

            await asyncio.sleep(
                self.interval
            )

    # =========================================================
    # Start / Stop
    # =========================================================

    def start(self):
        if not self._task:
            self._task = asyncio.create_task(
                self.loop()
            )

    async def stop(self):
        if self._task:
            self._task.cancel()

            try:
                await self._task

            except asyncio.CancelledError:
                pass

            finally:
                self._task = None
