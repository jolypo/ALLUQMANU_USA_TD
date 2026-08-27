from __future__ import annotations

import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

from app.config import settings
from app.reports.card import option_card
from app.reports.performance import (
    performance,
    weekly_report_data,
)
from app.reports.weekly_card import (
    weekly_performance_card,
)
from app.telegram.messages import signal_text


class TelegramHub:
    """
    Telegram control layer.

    IMPORTANT:
    - Admin commands are private-only.
    - Scanning does NOT create Trades.
    - Scanning does NOT publish to the channel.
    - Admin scans -> chooses /pick -> confirms /publish.
    - Only /publish creates the Trade.
    """

    def __init__(
        self,
        service,
        open_repo,
        history_repo,
        state_repo,
    ):
        self.service = service
        self.open_repo = open_repo
        self.history_repo = history_repo
        self.state_repo = state_repo

        self.app = (
            Application.builder()
            .token(settings.signal_bot_token)
            .updater(None)
            .build()
        )

        self.profit = Bot(settings.profit_bot_token)
        self.report = Bot(settings.report_bot_token)

        # -----------------------------------------------------
        # Pending scan selections
        #
        # user_id -> {
        #     candidates: [...],
        #     scan_type: stock / option / index,
        #     created_monotonic: float,
        #     picked_index: int | None,
        #     published_indexes: set[int],
        # }
        # -----------------------------------------------------
        self.pending_scans: dict[int, dict] = {}

        # Pending manual closes
        #
        # user_id -> {
        #     trade_id: "...",
        #     created_monotonic: float,
        # }
        self.pending_closes: dict[int, dict] = {}

        # Pending close-all confirmations
        self.pending_close_all: dict[int, float] = {}

        handlers = {
            "start": self.start,
            "help": self.help,
            "myid": self.myid,

            # Scan
            "stock": self.stock,
            "option": self.option,
            "indexoption": self.indexoption,

            # Manual approval
            "pick": self.pick,
            "pic1k": self.pick,
            "pic2k": self.pick,
            "pic3k": self.pick,
            "publish": self.publish,
            "cancel": self.cancel,

            # Manual close
            "close_stock": self.close_stock,
            "close_option": self.close_option,
            "close_index": self.close_index,
            "close_trade": self.close_trade,
            "confirm_close": self.confirm_close,
            "close_all": self.close_all,
            "confirm_close_all": self.confirm_close_all,

            # Existing commands
            "open": self.open_trades,
            "status": self.status,
            "health": self.status,
            "risk": self.risk,
            "performance": self.performance,
            "report": self.report_cmd,
            "settings": self.settings_cmd,
            "pause": self.pause,
            "resume": self.resume,
            "market": self.market,
        }

        for command, handler in handlers.items():
            self.app.add_handler(
                CommandHandler(command, handler)
            )

        # Telegram inline-menu navigation.
        # Existing slash commands stay available as a fallback, but the
        # normal admin workflow can now be completed entirely by buttons.
        self.app.add_handler(
            CallbackQueryHandler(self.menu_callback)
        )

    # =========================================================
    # Inline Telegram Menus
    # =========================================================

    @staticmethod
    def _main_menu_markup() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔍 Trading", callback_data="menu:trading")],
                [InlineKeyboardButton("📂 Open Trades", callback_data="menu:open")],
                [InlineKeyboardButton("📊 Reports", callback_data="menu:reports")],
                [InlineKeyboardButton("🛡️ Risk", callback_data="menu:risk")],
                [InlineKeyboardButton("⚙️ System", callback_data="menu:system")],
            ]
        )

    @staticmethod
    def _back_main_markup() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Main Menu", callback_data="menu:main")]]
        )

    @staticmethod
    def _trading_menu_markup() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📈 Stock Scan", callback_data="scan:stock")],
                [InlineKeyboardButton("🟢 Equity Options", callback_data="scan:option")],
                [InlineKeyboardButton("📊 Index Options", callback_data="scan:index")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu:main")],
            ]
        )

    @staticmethod
    def _reports_menu_markup() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📈 Performance", callback_data="cmd:performance")],
                [InlineKeyboardButton("📊 Weekly Report", callback_data="cmd:report")],
                [InlineKeyboardButton("🌎 Market Status", callback_data="cmd:market")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu:main")],
            ]
        )

    @staticmethod
    def _risk_menu_markup() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🛡️ Risk Status", callback_data="cmd:risk")],
                [InlineKeyboardButton("📂 Open Risk", callback_data="cmd:open")],
                [InlineKeyboardButton("⚙️ Risk Settings", callback_data="cmd:settings")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu:main")],
            ]
        )

    @staticmethod
    def _system_menu_markup(paused: bool) -> InlineKeyboardMarkup:
        toggle = (
            InlineKeyboardButton("▶️ Resume Scanning", callback_data="cmd:resume")
            if paused
            else InlineKeyboardButton("⏸ Pause Scanning", callback_data="cmd:pause")
        )
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("❤️ Health", callback_data="cmd:health")],
                [InlineKeyboardButton("📡 Status", callback_data="cmd:status")],
                [InlineKeyboardButton("⚙️ Settings", callback_data="cmd:settings")],
                [toggle],
                [InlineKeyboardButton("👤 My ID", callback_data="cmd:myid")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu:main")],
            ]
        )

    def _open_menu_markup(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📈 Stock Trades", callback_data="open:stock")],
                [InlineKeyboardButton("🟢 Equity Options", callback_data="open:option")],
                [InlineKeyboardButton("📊 Index Options", callback_data="open:index")],
                [InlineKeyboardButton("❌ Close Trade", callback_data="close:list:all")],
                [InlineKeyboardButton("❌ Close All", callback_data="close:all")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu:main")],
            ]
        )

    @staticmethod
    def _candidate_markup(rows: list[dict], kind: str) -> InlineKeyboardMarkup:
        buttons = []
        for index, trade in enumerate(rows[:3], start=1):
            option = trade.get("option") or {}
            suffix = ""
            if option:
                opt_type = str(option.get("type", "")).upper()
                if opt_type:
                    suffix = f" {opt_type}"
            label = f"{index}️⃣ {trade.get('symbol', 'N/A')}{suffix}"
            buttons.append(
                [InlineKeyboardButton(label, callback_data=f"pick:{index}")]
            )
        buttons.append(
            [InlineKeyboardButton("🔄 Rescan", callback_data=f"scan:{kind}")]
        )
        buttons.append(
            [InlineKeyboardButton("🔙 Back", callback_data="menu:trading")]
        )
        return InlineKeyboardMarkup(buttons)

    @staticmethod
    def _approval_markup() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ Approve", callback_data="trade:publish")],
                [InlineKeyboardButton("❌ Cancel", callback_data="trade:cancel")],
                [InlineKeyboardButton("🔙 Back", callback_data="trade:results")],
            ]
        )

    async def _edit_menu(self, query, text: str, markup: InlineKeyboardMarkup):
        try:
            await query.edit_message_text(text=text, reply_markup=markup)
        except Exception:
            await query.message.reply_text(text=text, reply_markup=markup)

    def _filtered_open_rows(self, category: str) -> list[dict]:
        rows = self._open_rows()
        if category == "stock":
            return [r for r in rows if str(r.get("trade_type", "")).startswith("STOCK_")]
        if category == "option":
            return [r for r in rows if str(r.get("trade_type", "")).startswith("EQUITY_OPTION_")]
        if category == "index":
            return [r for r in rows if str(r.get("trade_type", "")).startswith("INDEX_OPTION_")]
        return rows

    async def _show_open_rows(self, query, category: str, close_mode: bool = False):
        rows = self._filtered_open_rows(category)
        if not rows:
            return await self._edit_menu(
                query,
                "📂 Open Trades\nNo open trades in this category.",
                self._open_menu_markup(),
            )

        title_map = {
            "stock": "📈 Stock Trades",
            "option": "🟢 Equity Options",
            "index": "📊 Index Options",
            "all": "📂 Open Trades",
        }
        lines = [title_map.get(category, "📂 Open Trades")]
        buttons = []
        for idx, trade in enumerate(rows[:20], start=1):
            label = self._contract_label(trade)
            trade_id = str(trade.get("trade_id", ""))
            lines.append(f"{idx}. {label} — {trade_id}")
            if close_mode and trade_id:
                buttons.append(
                    [InlineKeyboardButton(f"❌ {label}", callback_data=f"close:trade:{trade_id}")]
                )
        if close_mode:
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="menu:open")])
            markup = InlineKeyboardMarkup(buttons)
        else:
            markup = self._open_menu_markup()
        await self._edit_menu(query, "\n".join(lines), markup)

    async def _show_close_confirmation(self, query, trade_id: str):
        trade = self._find_open_trade(trade_id)
        if not trade:
            return await self._edit_menu(query, "❌ Trade not found.", self._open_menu_markup())

        user_id = query.from_user.id
        self.pending_closes[user_id] = {
            "trade_id": trade_id,
            "created_monotonic": time.monotonic(),
        }
        last_price = await self._latest_trade_price(trade)
        entry = self._entry_reference(trade)
        pnl_text = "N/A"
        if last_price is not None and entry > 0:
            pnl_text = f"{self._trade_pnl_pct(trade, last_price):+.2f}%"

        text = (
            "⚠️ Confirm Close\n"
            f"{self._contract_label(trade)}\n"
            f"Trade ID: {trade_id}\n"
            f"Entry: {entry}\n"
            f"Last Price: {last_price if last_price is not None else 'N/A'}\n"
            f"P&L: {pnl_text}"
        )
        markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ Confirm Close", callback_data=f"close:confirm:{trade_id}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="menu:open")],
            ]
        )
        await self._edit_menu(query, text, markup)

    async def menu_callback(self, update: Update, context):
        query = update.callback_query
        if not query:
            return
        await query.answer()

        if not self.allowed(update):
            return await self._deny(update)
        if not await self._require_private(update):
            return

        data = str(query.data or "")

        if data == "menu:main":
            return await self._edit_menu(
                query,
                "✅ ALLUQMANU_USA_TD Ready",
                self._main_menu_markup(),
            )
        if data == "menu:trading":
            return await self._edit_menu(query, "🔍 Trading Menu", self._trading_menu_markup())
        if data == "menu:open":
            return await self._edit_menu(query, "📂 Open Trades", self._open_menu_markup())
        if data == "menu:reports":
            return await self._edit_menu(query, "📊 Reports", self._reports_menu_markup())
        if data == "menu:risk":
            return await self._edit_menu(query, "🛡️ Risk Management", self._risk_menu_markup())
        if data == "menu:system":
            return await self._edit_menu(query, "⚙️ System", self._system_menu_markup(self._paused()))

        if data.startswith("scan:"):
            kind = data.split(":", 1)[1]
            context.args = ["3"]
            context.user_data["_menu_callback"] = True
            context.user_data["_menu_query"] = query
            await self._edit_menu(query, "🔎 Scanning...", self._trading_menu_markup())
            return await self._run_scan(update, context, kind)

        if data.startswith("pick:"):
            number = data.split(":", 1)[1]
            context.args = [number]
            context.user_data["_menu_callback"] = True
            context.user_data["_menu_query"] = query
            return await self.pick(update, context)

        if data == "trade:publish":
            context.user_data["_menu_callback"] = True
            context.user_data["_menu_query"] = query
            return await self.publish(update, context)

        if data == "trade:cancel":
            context.user_data["_menu_callback"] = True
            context.user_data["_menu_query"] = query
            await self.cancel(update, context)
            return await self._edit_menu(query, "❌ Trade Cancelled", self._trading_menu_markup())

        if data == "trade:results":
            user_id = update.effective_user.id
            session = self.pending_scans.get(user_id)
            if not session:
                return await self._edit_menu(query, "No active scan results.", self._trading_menu_markup())
            return await self._edit_menu(
                query,
                "Top Opportunities",
                self._candidate_markup(session.get("candidates", []), session.get("scan_type", "option")),
            )

        if data.startswith("open:"):
            category = data.split(":", 1)[1]
            return await self._show_open_rows(query, category, close_mode=False)

        if data.startswith("close:list:"):
            category = data.split(":", 2)[2]
            return await self._show_open_rows(query, category, close_mode=True)

        if data.startswith("close:trade:"):
            trade_id = data.split(":", 2)[2]
            return await self._show_close_confirmation(query, trade_id)

        if data.startswith("close:confirm:"):
            trade_id = data.split(":", 2)[2]
            context.args = [trade_id]
            context.user_data["_menu_callback"] = True
            context.user_data["_menu_query"] = query
            await self.confirm_close(update, context)
            return await self._edit_menu(query, "✅ Trade Closed", self._open_menu_markup())

        if data == "close:all":
            self.pending_close_all[update.effective_user.id] = time.monotonic()
            markup = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✅ Confirm Close All", callback_data="close:confirm_all")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="menu:open")],
                ]
            )
            return await self._edit_menu(query, "⚠️ Confirm closing ALL open trades?", markup)

        if data == "close:confirm_all":
            context.user_data["_menu_callback"] = True
            context.user_data["_menu_query"] = query
            await self.confirm_close_all(update, context)
            return await self._edit_menu(query, "✅ Close All completed", self._open_menu_markup())

        command_map = {
            "cmd:performance": self.performance,
            "cmd:report": self.report_cmd,
            "cmd:market": self.market,
            "cmd:risk": self.risk,
            "cmd:open": self.open_trades,
            "cmd:settings": self.settings_cmd,
            "cmd:health": self.status,
            "cmd:status": self.status,
            "cmd:pause": self.pause,
            "cmd:resume": self.resume,
            "cmd:myid": self.myid,
        }
        handler = command_map.get(data)
        if handler:
            await handler(update, context)
            if data in {"cmd:pause", "cmd:resume"}:
                return await self._edit_menu(query, "⚙️ System", self._system_menu_markup(self._paused()))
            return

    # =========================================================
    # Authorization
    # =========================================================

    def allowed(self, update: Update) -> bool:
        return bool(
            update.effective_user
            and update.effective_user.id
            == settings.telegram_admin_user_id
        )

    async def _deny(self, update: Update):
        await update.effective_message.reply_text(
            "⛔ غير مصرح لهذا الحساب."
        )

    def _is_private(self, update: Update) -> bool:
        return bool(
            update.effective_chat
            and update.effective_chat.type == "private"
        )

    async def _require_private(self, update: Update) -> bool:
        if self._is_private(update):
            return True

        await update.effective_message.reply_text(
            "🔒 هذا الأمر يعمل في المحادثة الخاصة "
            "مع Signal Bot فقط."
        )
        return False

    # =========================================================
    # Pause State
    # =========================================================

    def _paused(self) -> bool:
        rows = self.state_repo.all()

        return bool(
            rows
            and rows[0].get("paused")
        )

    def _set_paused(self, value: bool):
        self.state_repo.replace(
            [{"paused": value}]
        )

    # =========================================================
    # Common Helpers
    # =========================================================

    @staticmethod
    def _requested_count(context) -> int:
        """
        /stock
        /stock 2
        /stock 3

        Invalid values are safely clamped.
        """

        default = settings.default_signals_per_scan

        if not context.args:
            return default

        try:
            requested = int(context.args[0])
        except (TypeError, ValueError):
            return default

        return max(
            1,
            min(
                requested,
                settings.max_signals_per_scan,
            ),
        )

    @staticmethod
    def _trade_type_ar(value: str) -> str:
        mapping = {
            "STOCK_INTRADAY":
                "سهم أمريكي — مضاربة يومية",

            "STOCK_SWING":
                "سهم أمريكي — سوينغ",

            "EQUITY_OPTION_INTRADAY":
                "خيارات سهم — مضاربة يومية",

            "EQUITY_OPTION_SWING":
                "خيارات سهم — سوينغ",

            "INDEX_OPTION_INTRADAY":
                "خيارات مؤشر — مضاربة يومية",

            "INDEX_OPTION_SWING":
                "خيارات مؤشر — سوينغ",
        }

        return mapping.get(value, value)

    @staticmethod
    def _is_option_trade(trade: dict) -> bool:
        return bool(trade.get("option"))

    @staticmethod
    def _is_index_trade(trade: dict) -> bool:
        return str(
            trade.get("trade_type", "")
        ).startswith("INDEX_OPTION")

    @staticmethod
    def _trade_prefix(trade: dict) -> str:
        if str(
            trade.get("trade_type", "")
        ).startswith("INDEX_OPTION"):
            return "IDX"

        if trade.get("option"):
            return "OPT"

        return "STK"

    @staticmethod
    def _contract_label(trade: dict) -> str:
        option = trade.get("option") or {}

        if not option:
            return trade.get("symbol", "N/A")

        contract_type = str(
            option.get("type", "")
        ).upper()

        strike = option.get("strike", "")

        return (
            f'{trade.get("symbol", "N/A")} '
            f'{strike} {contract_type}'
        ).strip()

    @staticmethod
    def _entry_reference(trade: dict) -> float:
        stored = trade.get(
            "filled_entry_price",
            trade.get("entry_price"),
        )

        if stored is not None:
            try:
                return float(stored)
            except (TypeError, ValueError):
                pass

        direction = str(
            trade.get("direction", "LONG")
        ).upper()

        if direction == "SHORT":
            value = trade.get(
                "entry_low",
                trade.get("entry_high", 0),
            )
        else:
            value = trade.get(
                "entry_high",
                trade.get("entry_low", 0),
            )

        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _trade_pnl_pct(
        cls,
        trade: dict,
        current_price: float,
    ) -> float:
        entry = cls._entry_reference(trade)

        if entry <= 0:
            return 0.0

        try:
            price = float(current_price)
        except (TypeError, ValueError):
            return 0.0

        direction = str(
            trade.get("direction", "LONG")
        ).upper()

        multiplier = (
            -1.0
            if direction == "SHORT"
            else 1.0
        )

        return (
            (
                price - entry
            )
            / entry
            * 100.0
            * multiplier
        )

    # =========================================================
    # Candidate Expiry
    # =========================================================

    def _scan_expired(self, session: dict) -> bool:
        age = (
            time.monotonic()
            - session["created_monotonic"]
        )

        return (
            age
            > settings.candidate_ttl_seconds
        )

    def _clear_expired_scan(
        self,
        user_id: int,
    ) -> bool:
        session = self.pending_scans.get(user_id)

        if not session:
            return False

        if not self._scan_expired(session):
            return False

        self.pending_scans.pop(
            user_id,
            None,
        )

        return True

    # =========================================================
    # Portfolio / Duplicate / Daily Gates
    # =========================================================

    def _open_rows(self) -> list[dict]:
        return [
            row
            for row in self.open_repo.all()
            if row.get("status") == "OPEN"
        ]

    def _exact_duplicate(
        self,
        candidate: dict,
        rows: list[dict],
    ) -> bool:
        """
        Important:
        NVDA Stock + NVDA Option is ALLOWED.

        What is blocked:
        - same stock trade idea
        - exact same option contract
        """

        candidate_option = candidate.get("option")

        for row in rows:
            row_option = row.get("option")

            # Stock vs stock
            if not candidate_option and not row_option:
                if (
                    row.get("symbol")
                    == candidate.get("symbol")
                    and row.get("trade_type")
                    == candidate.get("trade_type")
                    and row.get("direction")
                    == candidate.get("direction")
                ):
                    return True

            # Option vs option
            if candidate_option and row_option:
                candidate_contract = str(
                    candidate_option.get(
                        "symbol",
                        "",
                    )
                )

                row_contract = str(
                    row_option.get(
                        "symbol",
                        "",
                    )
                )

                if (
                    candidate_contract
                    and row_contract
                    and candidate_contract
                    == row_contract
                ):
                    return True

        return False

    def _portfolio_gate(
        self,
        trade: dict,
    ) -> tuple[bool, str]:
        rows = self._open_rows()

        # -----------------------------------------------
        # Open trade count
        # -----------------------------------------------
        if len(rows) >= settings.max_open_trades:
            return (
                False,
                "تم بلوغ الحد الأقصى "
                "للصفقات المفتوحة.",
            )

        # -----------------------------------------------
        # Total risk
        # -----------------------------------------------
        total_risk = sum(
            float(
                row.get(
                    "risk_pct",
                    0,
                )
                or 0
            )
            for row in rows
        )

        new_risk = float(
            trade.get(
                "risk_pct",
                0,
            )
            or 0
        )

        if (
            total_risk + new_risk
            > settings.max_total_open_risk
        ):
            return (
                False,
                "إجمالي المخاطر المفتوحة "
                "سيتجاوز الحد المسموح.",
            )

        # -----------------------------------------------
        # Exact duplicate only
        #
        # Do NOT block NVDA stock merely because
        # NVDA option is already open.
        # -----------------------------------------------
        if (
            settings.prevent_exact_duplicate_trade
            and self._exact_duplicate(
                trade,
                rows,
            )
        ):
            return (
                False,
                "يوجد بالفعل Trade مطابق "
                "أو عقد مطابق مفتوح.",
            )

        # -----------------------------------------------
        # Sector concentration
        #
        # Do not hard reject simply because
        # two same-sector trades exist.
        # Risk ceiling remains the hard protection.
        # -----------------------------------------------

        return True, "ACCEPT"

    def _daily_publish_count(
        self,
        category: str,
    ) -> int:
        """
        Counts trades created/published today
        from open + history.

        category:
        stock
        option
        index
        """

        today = datetime.now(
            timezone.utc
        ).date()

        rows = (
            self.open_repo.all()
            + self.history_repo.all()
        )

        count = 0
        seen_ids: set[str] = set()

        for row in rows:
            trade_id = str(
                row.get(
                    "trade_id",
                    "",
                )
            )

            if trade_id and trade_id in seen_ids:
                continue

            published_at = (
                row.get("published_at")
                or row.get("created_at")
            )

            if not published_at:
                continue

            try:
                created_date = (
                    datetime.fromisoformat(
                        str(
                            published_at
                        ).replace(
                            "Z",
                            "+00:00",
                        )
                    )
                    .astimezone(timezone.utc)
                    .date()
                )
            except Exception:
                continue

            if created_date != today:
                continue

            trade_type = str(
                row.get(
                    "trade_type",
                    "",
                )
            )

            matches = False

            if category == "stock":
                matches = trade_type.startswith(
                    "STOCK_"
                )

            elif category == "option":
                matches = trade_type.startswith(
                    "EQUITY_OPTION_"
                )

            elif category == "index":
                matches = trade_type.startswith(
                    "INDEX_OPTION_"
                )

            if matches:
                count += 1

                if trade_id:
                    seen_ids.add(trade_id)

        return count

    def _daily_gate(
        self,
        trade: dict,
    ) -> tuple[bool, str]:
        trade_type = str(
            trade.get(
                "trade_type",
                "",
            )
        )

        if trade_type.startswith("STOCK_"):
            current = self._daily_publish_count(
                "stock"
            )

            limit = (
                settings.max_daily_stock_signals
            )

            label = "صفقات الأسهم"

        elif trade_type.startswith(
            "EQUITY_OPTION_"
        ):
            current = self._daily_publish_count(
                "option"
            )

            limit = (
                settings
                .max_daily_equity_option_signals
            )

            label = "عقود الأسهم"

        else:
            current = self._daily_publish_count(
                "index"
            )

            limit = (
                settings
                .max_daily_index_option_signals
            )

            label = "عقود المؤشر"

        if current >= limit:
            return (
                False,
                f"تم بلوغ الحد اليومي لـ{label}: "
                f"{current}/{limit}",
            )

        return True, "ACCEPT"

    # =========================================================
    # Start / Help
    # =========================================================

    async def start(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        await update.effective_message.reply_text(
            "✅ ALLUQMANU_USA_TD Ready",
            reply_markup=self._main_menu_markup(),
        )

    async def help(
        self,
        update: Update,
        context,
    ):
        return await self.start(
            update,
            context,
        )

    async def myid(
        self,
        update: Update,
        context,
    ):
        if not update.effective_user:
            return

        await update.effective_message.reply_text(
            "👤 Telegram User ID:\n"
            f"{update.effective_user.id}"
        )

    # =========================================================
    # Scanning
    # =========================================================

    async def _run_scan(
        self,
        update: Update,
        context,
        kind: str,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        if not await self._require_private(update):
            return

        if self._paused():
            return await (
                update.effective_message.reply_text(
                    "⏸️ البحث عن إشارات جديدة موقوف.\n"
                    "استخدم /resume."
                )
            )

        is_open, clock = (
            await self.service.market_is_open()
        )

        if not is_open:
            return await (
                update.effective_message.reply_text(
                    "⏰ السوق الأمريكي مغلق "
                    "أو تعذر تأكيد أنه مفتوح.\n\n"

                    "لن يتم فتح أو نشر أي صفقة.\n"
                    f"{clock}"
                )
            )

        requested = self._requested_count(
            context
        )

        labels = {
            "stock": "الأسهم الأمريكية",
            "option": "خيارات الأسهم",
            "index": "خيارات SPX",
        }

        menu_mode_active = bool(context.user_data.get("_menu_callback"))
        if not menu_mode_active:
            await update.effective_message.reply_text(
                f"🔎 بدأ فحص {labels[kind]}\n\n"
                f"المطلوب: أفضل {requested} "
                "فرصة كحد أقصى\n\n"
                "⚠️ لن يتم نشر أو فتح أي صفقة "
                "قبل اختيارك وموافقتك."
            )

        if kind == "stock":
            candidates, rejects = (
                await self.service.best_stocks(
                    requested
                )
            )

        elif kind == "option":
            candidates, rejects = (
                await self.service
                .best_equity_options(
                    requested
                )
            )

        else:
            candidates, rejects = (
                await self.service
                .best_index_options(
                    requested
                )
            )

        if not candidates:
            message = (
                "❌ لا توجد صفقة READY حاليًا."
            )

            if rejects:
                message += (
                    "\n\nأسباب مختصرة:\n"
                    + "\n".join(
                        f"• {item}"
                        for item in rejects[-7:]
                    )
                )

            menu_query = context.user_data.pop("_menu_query", None)
            menu_mode = bool(context.user_data.pop("_menu_callback", False))
            if menu_mode and menu_query is not None:
                return await self._edit_menu(
                    menu_query,
                    "No READY opportunities right now.",
                    self._trading_menu_markup(),
                )
            return await (
                update.effective_message.reply_text(
                    message
                )
            )

        rows: list[dict] = [
            signal.to_dict()
            for signal in candidates
        ]

        user_id = update.effective_user.id

        self.pending_scans[user_id] = {
            "candidates": rows,
            "scan_type": kind,
            "created_monotonic":
                time.monotonic(),
            "picked_index": None,
            "published_indexes": set(),
        }

        lines = [
            "✅ اكتمل الفحص",
            "",
            f"تم العثور على {len(rows)} "
            "فرصة READY:",
            "",
        ]

        medals = {
            1: "🥇",
            2: "🥈",
            3: "🥉",
        }

        for index, trade in enumerate(
            rows,
            start=1,
        ):
            medal = medals.get(
                index,
                "🔹",
            )

            lines.append(
                f"{medal} {index}) "
                f"{self._contract_label(trade)}"
            )

            lines.append(
                "النوع: "
                f"{self._trade_type_ar(trade['trade_type'])}"
            )

            lines.append(
                f"Score: {trade['score']}/100"
            )

            lines.append(
                f"R/R: 1 : {trade['rr']}"
            )

            if trade.get("option"):
                option = trade["option"]

                lines.append(
                    "Expiration: "
                    f"{option.get('expiration', 'N/A')}"
                )

                lines.append(
                    "DTE: "
                    f"{option.get('dte', 'N/A')}"
                )

                lines.append(
                    "Bid/Ask: "
                    f"${option.get('bid', 'N/A')} / "
                    f"${option.get('ask', 'N/A')}"
                )

            lines.append("")

        lines.extend(
            [
                "اختر الصفقة برقم:",
                "",
            ]
        )

        for index in range(
            1,
            len(rows) + 1,
        ):
            lines.append(
                f"/pic{index}k"
            )

        lines.extend(
            [
                "",
                "⏳ صلاحية نتائج الفحص: "
                f"{settings.candidate_ttl_seconds // 60} "
                "دقائق.",
                "",
                "⚠️ لا شيء تم نشره حتى الآن.",
            ]
        )

        menu_query = context.user_data.pop("_menu_query", None)
        menu_mode = bool(context.user_data.pop("_menu_callback", False))
        if menu_mode and menu_query is not None:
            compact = [f"Top {len(rows)} Opportunities", ""]
            for index, trade in enumerate(rows, start=1):
                option = trade.get("option") or {}
                side = str(option.get("type", "")).upper()
                label = f"{index}️⃣ {trade.get('symbol', 'N/A')}"
                if side:
                    label += f" {side}"
                compact.append(label)
                compact.append(f"Score: {trade['score']}/100 | R/R: 1:{trade['rr']}")
            await self._edit_menu(
                menu_query,
                "\n".join(compact),
                self._candidate_markup(rows, kind),
            )
        else:
            await update.effective_message.reply_text(
                "\n".join(lines)
            )

    async def stock(
        self,
        update: Update,
        context,
    ):
        await self._run_scan(
            update,
            context,
            "stock",
        )

    async def option(
        self,
        update: Update,
        context,
    ):
        await self._run_scan(
            update,
            context,
            "option",
        )

    async def indexoption(
        self,
        update: Update,
        context,
    ):
        await self._run_scan(
            update,
            context,
            "index",
        )

    # =========================================================
    # Pick
    # =========================================================

    async def pick(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        if not await self._require_private(update):
            return

        user_id = update.effective_user.id

        if self._clear_expired_scan(user_id):
            return await (
                update.effective_message.reply_text(
                    "⚠️ انتهت صلاحية نتائج الفحص.\n"
                    "أعد البحث للحصول على أسعار "
                    "وبيانات محدثة."
                )
            )

        session = self.pending_scans.get(
            user_id
        )

        if not session:
            return await (
                update.effective_message.reply_text(
                    "❌ لا يوجد فحص نشط.\n\n"
                    "استخدم أولًا:\n"
                    "/stock 3\n"
                    "أو /option 3\n"
                    "أو /indexoption 3"
                )
            )

        selected_number = None
        command_text = (update.effective_message.text or "").split()[0]
        match = re.match(r"^/pic([123])k(?:@\w+)?$", command_text, re.IGNORECASE)
        if match:
            selected_number = int(match.group(1))
        elif context.args:
            try:
                selected_number = int(context.args[0])
            except ValueError:
                selected_number = None
        if selected_number is None:
            return await update.effective_message.reply_text(
                "استخدم: /pic1k أو /pic2k أو /pic3k"
            )

        candidates = session["candidates"]

        if not (
            1
            <= selected_number
            <= len(candidates)
        ):
            return await (
                update.effective_message.reply_text(
                    "❌ رقم الصفقة غير موجود.\n"
                    f"اختر من 1 إلى "
                    f"{len(candidates)}."
                )
            )

        index = selected_number - 1

        if index in session[
            "published_indexes"
        ]:
            return await (
                update.effective_message.reply_text(
                    "⚠️ هذه الصفقة سبق نشرها "
                    "من نفس الفحص."
                )
            )

        session["picked_index"] = index

        trade = candidates[index]

        lines = [
            "✅ تم اختيار الصفقة",
            "",
            f"رقم الاختيار: {selected_number}",
            "",
            f"الأصل: {self._contract_label(trade)}",
            "النوع: "
            f"{self._trade_type_ar(trade['trade_type'])}",
            f"Score: {trade['score']}/100",
            f"R/R: 1 : {trade['rr']}",
            "",
            f"الدخول: "
            f"{trade['entry_low']} – "
            f"{trade['entry_high']}",
            f"وقف الخسارة: {trade['stop']}",
            f"TP1: {trade['tp1']}",
            f"TP2: {trade['tp2']}",
            f"TP3: {trade['tp3']}",
            "",
            "⚠️ لم يتم فتح أو نشر الصفقة بعد.",
            "",
            "للاعتماد والنشر:",
            "/publish",
            "",
            "للإلغاء:",
            "/cancel",
        ]

        menu_query = context.user_data.pop("_menu_query", None)
        menu_mode = bool(context.user_data.pop("_menu_callback", False))
        if menu_mode and menu_query is not None:
            await self._edit_menu(
                menu_query,
                "\n".join([
                    "Selected Trade",
                    self._contract_label(trade),
                    f"Score: {trade['score']}/100",
                    f"R/R: 1:{trade['rr']}",
                    f"Entry: {trade['entry_low']} – {trade['entry_high']}",
                    f"Stop: {trade['stop']}",
                    f"TP1: {trade['tp1']}",
                    f"TP2: {trade['tp2']}",
                    f"TP3: {trade['tp3']}",
                ]),
                self._approval_markup(),
            )
        else:
            await update.effective_message.reply_text(
                "\n".join(lines)
            )

    # =========================================================
    # Publish
    # =========================================================

    async def publish(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        if not await self._require_private(update):
            return

        user_id = update.effective_user.id

        if self._clear_expired_scan(user_id):
            return await (
                update.effective_message.reply_text(
                    "⚠️ انتهت صلاحية الصفقة المختارة.\n\n"
                    "لم يتم إنشاء Trade "
                    "ولم يتم النشر.\n\n"
                    "أعد الفحص للحصول على "
                    "بيانات محدثة."
                )
            )

        session = self.pending_scans.get(
            user_id
        )

        if not session:
            return await (
                update.effective_message.reply_text(
                    "❌ لا توجد صفقة بانتظار النشر."
                )
            )

        picked_index = session.get(
            "picked_index"
        )

        if picked_index is None:
            return await (
                update.effective_message.reply_text(
                    "❌ اختر الصفقة أولًا.\n\n"
                    "استخدم /pic1k أو /pic2k أو /pic3k"
                )
            )

        if picked_index in session[
            "published_indexes"
        ]:
            return await (
                update.effective_message.reply_text(
                    "⚠️ هذه الصفقة سبق نشرها."
                )
            )

        trade = dict(
            session["candidates"][
                picked_index
            ]
        )

        # -----------------------------------------------
        # Re-check portfolio at PUBLISH time.
        # Not at scan time.
        # -----------------------------------------------
        ok, reason = self._portfolio_gate(
            trade
        )

        if not ok:
            return await (
                update.effective_message.reply_text(
                    "❌ لم يتم اعتماد الصفقة.\n\n"
                    f"السبب:\n{reason}\n\n"
                    "لم يتم فتح أو نشر شيء."
                )
            )

        daily_ok, daily_reason = (
            self._daily_gate(trade)
        )

        if not daily_ok:
            return await (
                update.effective_message.reply_text(
                    "❌ لم يتم اعتماد الصفقة.\n\n"
                    f"{daily_reason}\n\n"
                    "لم يتم فتح أو نشر شيء."
                )
            )

        if not settings.telegram_channel_chat_id:
            return await (
                update.effective_message.reply_text(
                    "❌ TELEGRAM_CHANNEL_CHAT_ID "
                    "غير مضبوط.\n\n"
                    "لم يتم إنشاء Trade "
                    "لأن النشر في القناة فشل "
                    "قبل أن يبدأ."
                )
            )

        # -----------------------------------------------
        # Assign Trade ID only after admin approval.
        # -----------------------------------------------
        prefix = self._trade_prefix(trade)

        trade["trade_id"] = (
            f"{prefix}-"
            f"{uuid.uuid4().hex[:8].upper()}"
        )

        trade["status"] = "OPEN"

        trade["published_at"] = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        trade["entry_confirmed"] = False
        trade["filled_entry_price"] = None

        trade.update(
            {
                "tp1_hit": False,
                "tp2_hit": False,
                "tp3_hit": False,
                "near_stop_sent": False,
                "manual_publish": True,
            }
        )

        text = signal_text(trade)

        image_path = None

        try:
            # -------------------------------------------
            # OPTION IMAGE
            #
            # Horizontal card for BOTH:
            # - Equity Options
            # - SPX Index Options
            # -------------------------------------------
            if trade.get("option"):
                image_path = os.path.join(
                    tempfile.gettempdir(),
                    f'{trade["trade_id"]}.png',
                )

                option_card(
                    trade,
                    image_path,
                )

                with open(
                    image_path,
                    "rb",
                ) as photo_file:
                    await self.app.bot.send_photo(
                        chat_id=(
                            settings
                            .telegram_channel_chat_id
                        ),
                        photo=photo_file,
                    )

            # Old detailed message remains unchanged.
            sent_message = await self.app.bot.send_message(
                chat_id=(
                    settings.telegram_channel_chat_id
                ),
                text=text,
            )
            trade["channel_message_id"] = sent_message.message_id

        except Exception as exc:
            # Critical:
            # Do NOT create open trade if Telegram
            # publishing fails.
            return await (
                update.effective_message.reply_text(
                    "❌ فشل نشر الصفقة في القناة.\n\n"
                    "لم يتم إنشاء Trade.\n\n"
                    f"الخطأ: "
                    f"{type(exc).__name__}"
                )
            )

        finally:
            if image_path:
                try:
                    os.remove(image_path)
                except OSError:
                    pass

        # -----------------------------------------------
        # Only NOW persist as OPEN.
        # -----------------------------------------------
        self.open_repo.append(trade)

        session[
            "published_indexes"
        ].add(picked_index)

        session["picked_index"] = None

        menu_query = context.user_data.pop("_menu_query", None)
        menu_mode = bool(context.user_data.pop("_menu_callback", False))
        if menu_mode and menu_query is not None:
            await self._edit_menu(
                menu_query,
                "✅ Trade Approved\n"
                "📡 Published to Channel\n"
                f"🆔 {trade['trade_id']}",
                InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("📂 Open Trades", callback_data="menu:open")],
                        [InlineKeyboardButton("🔙 Main Menu", callback_data="menu:main")],
                    ]
                ),
            )
        else:
            await update.effective_message.reply_text(
                "✅ تم اعتماد ونشر الصفقة بنجاح.\n\n"
                f"🆔 Trade ID:\n"
                f"{trade['trade_id']}\n\n"
                "📡 تم نشرها في القناة.\n"
                "📂 أصبحت الآن ضمن الصفقات المفتوحة."
            )

    # =========================================================
    # Cancel Selection
    # =========================================================

    async def cancel(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        if not await self._require_private(update):
            return

        user_id = update.effective_user.id

        session = self.pending_scans.get(
            user_id
        )

        if not session:
            return await (
                update.effective_message.reply_text(
                    "ℹ️ لا يوجد اختيار نشط لإلغائه."
                )
            )

        session["picked_index"] = None

        await update.effective_message.reply_text(
            "✅ تم إلغاء الاختيار.\n"
            "لم يتم فتح أو نشر أي صفقة.\n\n"
            "تستطيع اختيار فرصة أخرى من "
            "نفس نتائج الفحص قبل انتهاء صلاحيتها."
        )

    # =========================================================
    # Latest Price Helpers
    # =========================================================

    async def _latest_trade_price(
        self,
        trade: dict,
    ) -> float | None:
        """
        Used for manual Paper close.

        Stock:
        latest IEX bar close.

        Options:
        indicative latest quote midpoint.
        """

        option = trade.get("option")

        try:
            if option:
                contract_symbol = option.get(
                    "symbol"
                )

                if not contract_symbol:
                    return trade.get(
                        "last_price"
                    )

                quotes = (
                    await self.service.provider
                    .option_quotes(
                        [contract_symbol]
                    )
                )

                quote = quotes.get(
                    contract_symbol,
                    {},
                )

                bid = quote.get("bp")
                ask = quote.get("ap")

                if (
                    bid is not None
                    and ask is not None
                ):
                    bid = float(bid)
                    ask = float(ask)

                    if bid > 0 and ask > 0:
                        return round(
                            (
                                bid + ask
                            )
                            / 2,
                            4,
                        )

                if bid is not None:
                    return float(bid)

                if ask is not None:
                    return float(ask)

            else:
                symbol = trade.get("symbol")

                bars = (
                    await self.service.provider
                    .latest_bars(
                        [symbol]
                    )
                )

                bar = bars.get(
                    symbol,
                    {},
                )

                close = bar.get("c")

                if close is not None:
                    return float(close)

        except Exception:
            pass

        fallback = trade.get(
            "last_price"
        )

        if fallback is None:
            return None

        try:
            return float(fallback)
        except Exception:
            return None

    # =========================================================
    # Manual Close Helpers
    # =========================================================

    def _find_open_trade(
        self,
        trade_id: str,
    ) -> dict | None:
        trade_id = trade_id.upper()

        for trade in self._open_rows():
            if str(
                trade.get(
                    "trade_id",
                    "",
                )
            ).upper() == trade_id:
                return trade

        return None

    async def _prepare_close(
        self,
        update: Update,
        trade: dict,
    ):
        user_id = update.effective_user.id

        trade_id = trade["trade_id"]

        last_price = (
            await self._latest_trade_price(
                trade
            )
        )

        self.pending_closes[user_id] = {
            "trade_id": trade_id,
            "created_monotonic":
                time.monotonic(),
        }

        entry = self._entry_reference(
            trade
        )

        pnl_text = "N/A"

        if (
            last_price is not None
            and entry > 0
        ):
            pnl = self._trade_pnl_pct(
                trade,
                last_price,
            )

            pnl_text = f"{pnl:+.2f}%"

        await update.effective_message.reply_text(
            "🔎 تم العثور على الصفقة\n\n"

            f"الأصل:\n"
            f"{self._contract_label(trade)}\n\n"

            f"النوع:\n"
            f"{self._trade_type_ar(trade['trade_type'])}\n\n"

            f"Trade ID:\n"
            f"{trade_id}\n\n"

            f"سعر الدخول المرجعي:\n"
            f"{entry}\n\n"

            f"آخر سعر متاح:\n"
            f"{last_price if last_price is not None else 'N/A'}\n\n"

            f"P&L التقريبي:\n"
            f"{pnl_text}\n\n"

            "⚠️ هل تريد إغلاقها ًا؟\n\n"

            "للتأكيد:\n"
            f"/confirm_close {trade_id}"
        )

    # =========================================================
    # Close Stock
    # =========================================================

    async def close_stock(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        if not await self._require_private(update):
            return

        if not context.args:
            return await (
                update.effective_message.reply_text(
                    "استخدم:\n"
                    "/close_stock NVDA"
                )
            )

        symbol = context.args[0].upper()

        rows = [
            trade
            for trade in self._open_rows()
            if (
                trade.get("symbol") == symbol
                and str(
                    trade.get(
                        "trade_type",
                        "",
                    )
                ).startswith("STOCK_")
            )
        ]

        if not rows:
            return await (
                update.effective_message.reply_text(
                    f"📂 لا توجد صفقة سهم "
                    f"مفتوحة على {symbol}."
                )
            )

        if len(rows) > 1:
            lines = [
                f"⚠️ توجد {len(rows)} "
                f"صفقات سهم مفتوحة على {symbol}.",
                "",
                "اختر Trade ID:",
                "",
            ]

            for trade in rows:
                lines.append(
                    f"/close_trade "
                    f"{trade['trade_id']}"
                )

            return await (
                update.effective_message.reply_text(
                    "\n".join(lines)
                )
            )

        await self._prepare_close(
            update,
            rows[0],
        )

    # =========================================================
    # Close Equity Option
    # =========================================================

    async def close_option(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        if not await self._require_private(update):
            return

        if not context.args:
            return await (
                update.effective_message.reply_text(
                    "استخدم:\n"
                    "/close_option NVDA"
                )
            )

        symbol = context.args[0].upper()

        rows = [
            trade
            for trade in self._open_rows()
            if (
                trade.get("symbol") == symbol
                and str(
                    trade.get(
                        "trade_type",
                        "",
                    )
                ).startswith(
                    "EQUITY_OPTION_"
                )
            )
        ]

        if not rows:
            return await (
                update.effective_message.reply_text(
                    f"📂 لا توجد عقود أسهم "
                    f"مفتوحة على {symbol}."
                )
            )

        if len(rows) > 1:
            lines = [
                f"📄 يوجد {len(rows)} "
                f"عقد مفتوح على {symbol}:",
                "",
            ]

            for trade in rows:
                lines.extend(
                    [
                        self._contract_label(
                            trade
                        ),
                        f"Trade ID: "
                        f"{trade['trade_id']}",
                        "",
                    ]
                )

            lines.append(
                "اختر العقد باستخدام:"
            )

            for trade in rows:
                lines.append(
                    f"/close_trade "
                    f"{trade['trade_id']}"
                )

            return await (
                update.effective_message.reply_text(
                    "\n".join(lines)
                )
            )

        await self._prepare_close(
            update,
            rows[0],
        )

    # =========================================================
    # Close Index Option
    # =========================================================

    async def close_index(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        if not await self._require_private(update):
            return

        symbol = (
            context.args[0].upper()
            if context.args
            else "SPX"
        )

        rows = [
            trade
            for trade in self._open_rows()
            if (
                trade.get("symbol") == symbol
                and str(
                    trade.get(
                        "trade_type",
                        "",
                    )
                ).startswith(
                    "INDEX_OPTION_"
                )
            )
        ]

        if not rows:
            return await (
                update.effective_message.reply_text(
                    f"📂 لا توجد عقود مؤشر "
                    f"مفتوحة على {symbol}."
                )
            )

        if len(rows) > 1:
            lines = [
                f"📊 يوجد {len(rows)} "
                f"عقد مؤشر مفتوح على {symbol}:",
                "",
            ]

            for trade in rows:
                lines.extend(
                    [
                        self._contract_label(
                            trade
                        ),
                        f"Trade ID: "
                        f"{trade['trade_id']}",
                        "",
                    ]
                )

            lines.append(
                "اختر باستخدام:"
            )

            for trade in rows:
                lines.append(
                    f"/close_trade "
                    f"{trade['trade_id']}"
                )

            return await (
                update.effective_message.reply_text(
                    "\n".join(lines)
                )
            )

        await self._prepare_close(
            update,
            rows[0],
        )

    # =========================================================
    # Close by Trade ID
    # =========================================================

    async def close_trade(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        if not await self._require_private(update):
            return

        if not context.args:
            return await (
                update.effective_message.reply_text(
                    "استخدم:\n"
                    "/close_trade OPT-XXXXXXXX"
                )
            )

        trade_id = context.args[0].upper()

        trade = self._find_open_trade(
            trade_id
        )

        if not trade:
            return await (
                update.effective_message.reply_text(
                    "❌ لم يتم العثور على "
                    "Trade مفتوح بهذا ID."
                )
            )

        await self._prepare_close(
            update,
            trade,
        )

    # =========================================================
    # Confirm Close
    # =========================================================

    async def confirm_close(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        if not await self._require_private(update):
            return

        if not context.args:
            return await (
                update.effective_message.reply_text(
                    "استخدم:\n"
                    "/confirm_close TRADE_ID"
                )
            )

        user_id = update.effective_user.id
        trade_id = context.args[0].upper()

        pending = self.pending_closes.get(
            user_id
        )

        if not pending:
            return await (
                update.effective_message.reply_text(
                    "❌ لا يوجد طلب إغلاق "
                    "بانتظار التأكيد."
                )
            )

        age = (
            time.monotonic()
            - pending["created_monotonic"]
        )

        if age > 300:
            self.pending_closes.pop(
                user_id,
                None,
            )

            return await (
                update.effective_message.reply_text(
                    "⚠️ انتهت صلاحية تأكيد الإغلاق.\n"
                    "أعد طلب الإغلاق."
                )
            )

        if (
            pending["trade_id"].upper()
            != trade_id
        ):
            return await (
                update.effective_message.reply_text(
                    "❌ Trade ID لا يطابق "
                    "الصفقة المنتظرة للتأكيد."
                )
            )

        trade = self._find_open_trade(
            trade_id
        )

        if not trade:
            self.pending_closes.pop(
                user_id,
                None,
            )

            return await (
                update.effective_message.reply_text(
                    "ℹ️ الصفقة لم تعد مفتوحة."
                )
            )

        exit_price = (
            await self._latest_trade_price(
                trade
            )
        )

        if exit_price is None:
            return await (
                update.effective_message.reply_text(
                    "❌ تعذر الحصول على سعر "
                    "حالي موثوق للإغلاق ال.\n\n"
                    "لم يتم إغلاق الصفقة."
                )
            )

        entry = self._entry_reference(
            trade
        )

        pnl_pct = self._trade_pnl_pct(
            trade,
            exit_price,
        )

        closed_trade = dict(trade)

        closed_trade.update(
            {
                "status": "CLOSED",
                "exit_price": exit_price,
                "last_price": exit_price,
                "pnl_pct": round(
                    pnl_pct,
                    4,
                ),
                "exit_reason":
                    "MANUAL_CLOSE",
                "closed_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),
            }
        )

        # Remove from open repository.
        open_rows = [
            row
            for row in self.open_repo.all()
            if row.get("trade_id") != trade_id
        ]

        self.open_repo.replace(
            open_rows
        )

        # Add to permanent history.
        self.history_repo.append(
            closed_trade
        )

        self.pending_closes.pop(
            user_id,
            None,
        )

        result_icon = (
            "🟢"
            if pnl_pct >= 0
            else "🔴"
        )

        private_message = (
            f"{result_icon} تم الإغلاق ال بنجاح\n\n"

            f"الأصل:\n"
            f"{self._contract_label(closed_trade)}\n\n"

            f"Trade ID:\n"
            f"{trade_id}\n\n"

            f"الدخول:\n"
            f"{entry}\n\n"

            f"الخروج:\n"
            f"{exit_price}\n\n"

            f"النتيجة:\n"
            f"{pnl_pct:+.2f}%\n\n"

            "Exit Reason:\n"
            "MANUAL_CLOSE"
        )

        await update.effective_message.reply_text(
            private_message
        )

        # Publish close result to channel because
        # the original trade was published there.
        if settings.telegram_channel_chat_id:
            try:
                await self.app.bot.send_message(
                    chat_id=(
                        settings
                        .telegram_channel_chat_id
                    ),
                    text=(
                        "🟠 تم إغلاق الصفقة يدويًا\n\n"

                        f"{self._contract_label(closed_trade)}\n\n"

                        f"🆔 {trade_id}\n\n"

                        f"الدخول:\n{entry}\n\n"

                        f"الخروج:\n{exit_price}\n\n"

                        f"📊 النتيجة:\n"
                        f"{pnl_pct:+.2f}%\n\n"

                        "Exit Reason:\n"
                        "MANUAL_CLOSE\n\n"

                        "⚠️ "
                    ),
                )
            except Exception:
                # Closing the Trade itself remains valid
                # even if channel notification temporarily fails.
                await (
                    update.effective_message.reply_text(
                        "⚠️ تم إغلاق الصفقة وتسجيلها، "
                        "لكن تعذر إرسال إشعار الإغلاق "
                        "إلى القناة."
                    )
                )

    # =========================================================
    # Close All
    # =========================================================

    async def close_all(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        if not await self._require_private(update):
            return

        rows = self._open_rows()

        if not rows:
            return await (
                update.effective_message.reply_text(
                    "📂 لا توجد صفقات مفتوحة."
                )
            )

        user_id = update.effective_user.id

        self.pending_close_all[
            user_id
        ] = time.monotonic()

        stock_count = sum(
            1
            for trade in rows
            if str(
                trade.get(
                    "trade_type",
                    "",
                )
            ).startswith("STOCK_")
        )

        option_count = sum(
            1
            for trade in rows
            if str(
                trade.get(
                    "trade_type",
                    "",
                )
            ).startswith(
                "EQUITY_OPTION_"
            )
        )

        index_count = sum(
            1
            for trade in rows
            if str(
                trade.get(
                    "trade_type",
                    "",
                )
            ).startswith(
                "INDEX_OPTION_"
            )
        )

        await update.effective_message.reply_text(
            "⚠️ طلب إغلاق جميع الصفقات\n\n"

            f"إجمالي الصفقات المفتوحة:\n"
            f"{len(rows)}\n\n"

            f"Stocks: {stock_count}\n"
            f"Equity Options: {option_count}\n"
            f"Index Options: {index_count}\n\n"

            "لن يتم الإغلاق حتى تؤكد.\n\n"

            "للتأكيد:\n"
            "/confirm_close_all"
        )

    async def confirm_close_all(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        if not await self._require_private(update):
            return

        user_id = update.effective_user.id

        started = self.pending_close_all.get(
            user_id
        )

        if started is None:
            return await (
                update.effective_message.reply_text(
                    "❌ لا يوجد طلب Close All "
                    "بانتظار التأكيد."
                )
            )

        if (
            time.monotonic() - started
            > 300
        ):
            self.pending_close_all.pop(
                user_id,
                None,
            )

            return await (
                update.effective_message.reply_text(
                    "⚠️ انتهت صلاحية التأكيد.\n"
                    "استخدم /close_all من جديد."
                )
            )

        rows = self._open_rows()

        if not rows:
            self.pending_close_all.pop(
                user_id,
                None,
            )

            return await (
                update.effective_message.reply_text(
                    "📂 لا توجد صفقات مفتوحة."
                )
            )

        closed = []
        failed = []

        for trade in rows:
            try:
                exit_price = (
                    await self._latest_trade_price(
                        trade
                    )
                )

                if exit_price is None:
                    failed.append(
                        trade["trade_id"]
                    )
                    continue

                entry = self._entry_reference(
                    trade
                )

                pnl_pct = self._trade_pnl_pct(
                    trade,
                    exit_price,
                )

                result = dict(trade)

                result.update(
                    {
                        "status": "CLOSED",
                        "exit_price":
                            exit_price,
                        "last_price":
                            exit_price,
                        "pnl_pct":
                            round(
                                pnl_pct,
                                4,
                            ),
                        "exit_reason":
                            "MANUAL_CLOSE_ALL",
                        "closed_at":
                            datetime.now(
                                timezone.utc
                            ).isoformat(),
                    }
                )

                self.history_repo.append(
                    result
                )

                closed.append(result)

            except Exception:
                failed.append(
                    trade.get(
                        "trade_id",
                        "UNKNOWN",
                    )
                )

        closed_ids = {
            trade["trade_id"]
            for trade in closed
        }

        remaining = [
            trade
            for trade in self.open_repo.all()
            if trade.get("trade_id")
            not in closed_ids
        ]

        self.open_repo.replace(
            remaining
        )

        self.pending_close_all.pop(
            user_id,
            None,
        )

        message = (
            "✅ انتهى طلب Close All\n\n"

            f"تم إغلاق:\n"
            f"{len(closed)} صفقة\n\n"

            f"تعذر إغلاق:\n"
            f"{len(failed)} صفقة\n\n"

            "Exit Reason:\n"
            "MANUAL_CLOSE_ALL"
        )

        if failed:
            message += (
                "\n\n⚠️ الصفقات التي بقيت مفتوحة:\n"
                + "\n".join(
                    f"• {trade_id}"
                    for trade_id in failed
                )
            )

        await update.effective_message.reply_text(
            message
        )

        if (
            closed
            and settings.telegram_channel_chat_id
        ):
            try:
                await self.app.bot.send_message(
                    chat_id=(
                        settings
                        .telegram_channel_chat_id
                    ),
                    text=(
                        "🟠 إغلاق يدوي جماعي "
                        "للصفقات ال\n\n"

                        f"عدد الصفقات المغلقة: "
                        f"{len(closed)}\n\n"

                        "Exit Reason:\n"
                        "MANUAL_CLOSE_ALL\n\n"

                        "⚠️ "
                    ),
                )
            except Exception:
                pass

    # =========================================================
    # Open Trades
    # =========================================================

    async def open_trades(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        rows = self._open_rows()

        if not rows:
            return await (
                update.effective_message.reply_text(
                    "📂 لا توجد صفقات مفتوحة."
                )
            )

        lines = [
            "📂 الصفقات المفتوحة",
            "",
            f"العدد: {len(rows)} / "
            f"{settings.max_open_trades}",
            "",
        ]

        for index, trade in enumerate(
            rows,
            start=1,
        ):
            lines.extend(
                [
                    f"{index}) "
                    f"{self._contract_label(trade)}",
                    f"🆔 "
                    f"{trade.get('trade_id', 'N/A')}",
                    "النوع: "
                    f"{self._trade_type_ar(trade.get('trade_type', ''))}",
                    f"Entry: "
                    f"{trade.get('entry_low')} – "
                    f"{trade.get('entry_high')}",
                    f"Last: "
                    f"{trade.get('last_price', 'N/A')}",
                    f"Status: "
                    f"{trade.get('status', 'OPEN')}",
                    "",
                ]
            )

        await update.effective_message.reply_text(
            "\n".join(lines)
        )

    # =========================================================
    # Status
    # =========================================================

    async def status(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        try:
            is_open, stamp = (
                await self.service.market_is_open()
            )
        except Exception:
            is_open = False
            stamp = "N/A"

        await update.effective_message.reply_text(
            "🤖 RUNNING ✅\n\n"

            f"Paper Mode: {settings.paper_mode}\n"
            f"Live Trading: {settings.live_trading}\n"
            f"Paused: {self._paused()}\n\n"

            f"US Market Open: {is_open}\n"

            f"Stocks Universe: "
            f"{len(settings.stocks)}\n"

            f"Index: "
            f"{','.join(settings.indices)}\n\n"

            f"Manual Publish: "
            f"{settings.require_manual_publish}\n"

            f"Max Per Scan: "
            f"{settings.max_signals_per_scan}\n"

            f"Max Open Trades: "
            f"{settings.max_open_trades}\n\n"

            "0DTE: OFF\n"

            f"Channel ID: "
            f"{'SET' if settings.telegram_channel_chat_id else 'PENDING'}"
        )

    # =========================================================
    # Risk
    # =========================================================

    async def risk(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        rows = self._open_rows()

        total = sum(
            float(
                trade.get(
                    "risk_pct",
                    0,
                )
                or 0
            )
            for trade in rows
        )

        await update.effective_message.reply_text(
            "🛡️ حالة المخاطر\n\n"

            f"Open Trades:\n"
            f"{len(rows)} / "
            f"{settings.max_open_trades}\n\n"

            f"Max Risk / Trade:\n"
            f"{settings.max_risk_per_trade * 100:.2f}%\n\n"

            f"Max Total Open Risk:\n"
            f"{settings.max_total_open_risk * 100:.2f}%\n\n"

            f"Current Open Risk:\n"
            f"{total * 100:.2f}%\n\n"

            f"MIN R/R:\n"
            f"1 : {settings.min_rr}\n\n"

            "📌 يسمح النظام بسهم وعقد Option "
            "على نفس الأصل إذا لم يكونا "
            "Trade مكررًا وكان Risk Engine يسمح."
        )

    # =========================================================
    # Performance
    # =========================================================

    async def performance(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        result = performance(
            self.history_repo.all()
        )

        await update.effective_message.reply_text(
            "📊 الأداء\n\n"

            f"الصفقات: "
            f"{result['trades']}\n"

            f"الفوز: "
            f"{result['wins']}\n"

            f"الخسارة: "
            f"{result['losses']}\n"

            f"Win Rate: "
            f"{result['win_rate']}%\n"

            f"Profit Factor: "
            f"{result['profit_factor']}\n"

            f"Net P&L: "
            f"{result['net_pnl_pct']}%"
        )

    async def report_cmd(
        self,
        update: Update,
        context,
    ):
        """
        Manual weekly image report.

        - Admin only.
        - Private chat only.
        - Sends the report privately to the admin.
        - Does not publish anything to the channel.
        """

        if not self.allowed(update):
            return await self._deny(update)

        if not await self._require_private(update):
            return

        await update.effective_message.reply_text(
            "📊 جاري تجهيز التقرير الأسبوعي المصور..."
        )

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
            "ALLUQMANU_USA_TD_MANUAL_WEEKLY_REPORT.png",
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
                "📈 التقرير الأسبوعي — \n\n"
                f"الصفقات المغلقة: {summary.get('trades', 0)}\n"
                f"الرابحة: {summary.get('wins', 0)}\n"
                f"الخاسرة: {summary.get('losses', 0)}\n"
                f"Breakeven: {summary.get('breakeven', 0)}\n\n"
                f"Win Rate: {summary.get('win_rate', 0)}%\n"
                f"Profit Factor: {summary.get('profit_factor', 0)}\n"
                f"Net Realized P&L: {net_pnl:+.2f}%\n"
                f"Max Drawdown: {summary.get('max_drawdown_pct', 0)}%\n\n"
                f"Open Positions: {open_summary.get('total', 0)}\n"
                f"Open Profit: {open_summary.get('profitable', 0)}\n"
                f"Open Loss: {open_summary.get('losing', 0)}\n"
                f"Unrealized P&L: {unrealized:+.2f}%\n\n"
                "🟢 الأخضر = ربح\n"
                "🔴 الأحمر = خسارة\n\n"
                "⚠️ Closed = Realized\n"
                "⚠️ Open = Unrealized\n"
                "⚠️  فقط"
            )

            with open(
                image_path,
                "rb",
            ) as image_file:
                await update.effective_message.reply_photo(
                    photo=image_file,
                    caption=caption,
                )

        except Exception as exc:
            await update.effective_message.reply_text(
                "❌ تعذر إنشاء التقرير المصور.\n\n"
                f"Error: {type(exc).__name__}"
            )

        finally:
            try:
                if os.path.exists(image_path):
                    os.remove(image_path)
            except OSError:
                pass

    # =========================================================
    # Settings
    # =========================================================

    async def settings_cmd(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        await update.effective_message.reply_text(
            "⚙️ الإعدادات\n\n"

            f"Stock Feed: "
            f"{settings.alpaca_stock_feed}\n"

            f"Options Feed: "
            f"{settings.alpaca_options_feed}\n\n"

            f"Min Score: "
            f"{settings.min_score}\n"

            f"Min R/R: "
            f"{settings.min_rr}\n\n"

            f"Default Scan Count: "
            f"{settings.default_signals_per_scan}\n"

            f"Max Scan Count: "
            f"{settings.max_signals_per_scan}\n\n"

            f"Candidate TTL: "
            f"{settings.candidate_ttl_seconds // 60} "
            "minutes\n\n"

            f"Watermark: "
            f"{settings.watermark_name}\n"

            f"Option Card: "
            f"{settings.option_card_orientation}\n\n"

            "0DTE: OFF"
        )

    # =========================================================
    # Pause / Resume
    # =========================================================

    async def pause(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        self._set_paused(True)

        await update.effective_message.reply_text(
            "⏸️ تم إيقاف إنشاء الإشارات اليدوية.\n"
            "متابعة الصفقات المفتوحة تبقى فعالة."
        )

    async def resume(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        self._set_paused(False)

        await update.effective_message.reply_text(
            "▶️ تم استئناف البحث اليدوي "
            "عن الإشارات."
        )

    # =========================================================
    # Market
    # =========================================================

    async def market(
        self,
        update: Update,
        context,
    ):
        if not self.allowed(update):
            return await self._deny(update)

        from app.market.regime import (
            MarketRegimeEngine,
        )

        regime = await MarketRegimeEngine(
            self.service.provider
        ).get()

        is_open, stamp = (
            await self.service.market_is_open()
        )

        await update.effective_message.reply_text(
            "🌎 حالة السوق الأمريكي\n\n"

            f"Market Regime:\n"
            f"{regime}\n\n"

            f"US Market Open:\n"
            f"{is_open}\n\n"

            "المرجع الأساسي:\n"
            "SPY / IEX"
        )