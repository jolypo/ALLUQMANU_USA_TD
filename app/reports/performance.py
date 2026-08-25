from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


# =========================================================
# Helpers
# =========================================================

def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_datetime(
    value: Any,
) -> datetime | None:
    """
    Accepts ISO datetime strings such as:
    2026-08-25T18:30:00+00:00
    2026-08-25T18:30:00Z
    """

    if not value:
        return None

    if isinstance(value, datetime):
        dt = value

    else:
        try:
            dt = datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )

        except (TypeError, ValueError):
            return None

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt.astimezone(
        timezone.utc
    )


def _is_closed(
    trade: dict,
) -> bool:
    status = str(
        trade.get(
            "status",
            "",
        )
    ).upper()

    return status in {
        "WIN",
        "LOSS",
        "BREAKEVEN",
        "CLOSED",
    }


def _normalized_result(
    trade: dict,
) -> str:
    """
    Manual closes usually use status=CLOSED.

    Result is derived from pnl_pct so a profitable
    manual close is correctly counted as WIN.
    """

    pnl = _safe_float(
        trade.get(
            "pnl_pct",
            0,
        )
    )

    if pnl > 0:
        return "WIN"

    if pnl < 0:
        return "LOSS"

    return "BREAKEVEN"


def _trade_type_label(
    trade_type: str,
) -> str:
    mapping = {
        "STOCK_INTRADAY":
            "Stock Intraday",

        "STOCK_SWING":
            "Stock Swing",

        "EQUITY_OPTION_INTRADAY":
            "Equity Option Intraday",

        "EQUITY_OPTION_SWING":
            "Equity Option Swing",

        "INDEX_OPTION_INTRADAY":
            "Index Option Intraday",

        "INDEX_OPTION_SWING":
            "Index Option Swing",
    }

    return mapping.get(
        str(trade_type),
        str(trade_type).replace(
            "_",
            " ",
        ),
    )


def _contract_name(
    trade: dict,
) -> str:
    """
    Examples:
    NVDA
    NVDA 185 CALL
    SPX 6500 CALL
    """

    symbol = str(
        trade.get(
            "symbol",
            "N/A",
        )
    ).upper()

    option = (
        trade.get("option")
        or {}
    )

    if not option:
        return symbol

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
        option_type = "CALL"

    elif option_type == "P":
        option_type = "PUT"

    strike = option.get(
        "strike",
        "",
    )

    parts = [
        symbol,
    ]

    if strike != "":
        parts.append(
            str(strike)
        )

    if option_type:
        parts.append(
            option_type
        )

    return " ".join(
        parts
    )


def _entry_price(
    trade: dict,
) -> float:
    """
    Uses filled entry when available.
    Otherwise falls back to entry_high.
    """

    value = trade.get(
        "filled_entry_price",
        trade.get(
            "entry_price",
            trade.get(
                "entry_high",
                trade.get(
                    "entry_low",
                    0,
                ),
            ),
        ),
    )

    return _safe_float(
        value
    )


def _exit_or_last_price(
    trade: dict,
) -> tuple[float, str]:
    """
    Closed -> EXIT
    Open   -> LAST
    """

    if _is_closed(trade):
        value = trade.get(
            "exit_price",
            trade.get(
                "last_price",
                0,
            ),
        )

        return (
            _safe_float(value),
            "EXIT",
        )

    value = trade.get(
        "last_price",
        trade.get(
            "current_price",
            0,
        ),
    )

    return (
        _safe_float(value),
        "LAST",
    )


def _calculate_open_pnl(
    trade: dict,
) -> float:
    """
    Calculates unrealized P&L for open positions.
    """

    entry = _entry_price(
        trade
    )

    last, _ = _exit_or_last_price(
        trade
    )

    if (
        entry <= 0
        or last <= 0
    ):
        return _safe_float(
            trade.get(
                "pnl_pct",
                0,
            )
        )

    return (
        (
            last - entry
        )
        / entry
    ) * 100


# =========================================================
# Maximum Drawdown
# =========================================================

def _max_drawdown(
    closed: list[dict],
) -> float:
    """
    Trade-return based paper trading drawdown.

    This is not capital-weighted portfolio drawdown.
    """

    if not closed:
        return 0.0

    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0

    ordered = sorted(
        closed,
        key=lambda trade: (
            _parse_datetime(
                trade.get(
                    "closed_at"
                )
            )
            or datetime.min.replace(
                tzinfo=timezone.utc
            )
        ),
    )

    for trade in ordered:
        cumulative += _safe_float(
            trade.get(
                "pnl_pct",
                0,
            )
        )

        peak = max(
            peak,
            cumulative,
        )

        drawdown = (
            cumulative
            - peak
        )

        max_drawdown = min(
            max_drawdown,
            drawdown,
        )

    return round(
        max_drawdown,
        2,
    )


# =========================================================
# Standard / Lifetime Performance
# =========================================================

def performance(
    history: list[dict],
) -> dict:
    """
    Historical performance summary.

    Used by /performance.
    """

    closed = [
        trade
        for trade in history
        if _is_closed(trade)
    ]

    wins = [
        trade
        for trade in closed
        if _normalized_result(
            trade
        ) == "WIN"
    ]

    losses = [
        trade
        for trade in closed
        if _normalized_result(
            trade
        ) == "LOSS"
    ]

    breakeven = [
        trade
        for trade in closed
        if _normalized_result(
            trade
        ) == "BREAKEVEN"
    ]

    pnl_values = [
        _safe_float(
            trade.get(
                "pnl_pct",
                0,
            )
        )
        for trade in closed
    ]

    gross_win = sum(
        pnl
        for pnl in pnl_values
        if pnl > 0
    )

    gross_loss = abs(
        sum(
            pnl
            for pnl in pnl_values
            if pnl < 0
        )
    )

    if gross_loss > 0:
        profit_factor = (
            gross_win
            / gross_loss
        )

    elif gross_win > 0:
        profit_factor = 999.0

    else:
        profit_factor = 0.0

    return {
        "trades":
            len(closed),

        "wins":
            len(wins),

        "losses":
            len(losses),

        "breakeven":
            len(breakeven),

        "win_rate":
            round(
                (
                    len(wins)
                    / len(closed)
                    * 100
                )
                if closed
                else 0,
                1,
            ),

        "net_pnl_pct":
            round(
                sum(
                    pnl_values
                ),
                2,
            ),

        "gross_profit_pct":
            round(
                gross_win,
                2,
            ),

        "gross_loss_pct":
            round(
                gross_loss,
                2,
            ),

        "profit_factor":
            round(
                profit_factor,
                2,
            ),

        "max_drawdown_pct":
            _max_drawdown(
                closed
            ),
    }


# =========================================================
# Daily Report
# =========================================================

def daily_report_data(
    history: list[dict],
    now: datetime | None = None,
) -> dict:
    """
    Daily realized performance only.

    Counts only trades closed during the current UTC day.
    Open positions are excluded.
    """

    now = (
        now
        or datetime.now(
            timezone.utc
        )
    )

    if now.tzinfo is None:
        now = now.replace(
            tzinfo=timezone.utc
        )

    now = now.astimezone(
        timezone.utc
    )

    day_start = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    daily_closed: list[dict] = []

    for trade in history:
        if not _is_closed(
            trade
        ):
            continue

        closed_at = _parse_datetime(
            trade.get(
                "closed_at"
            )
        )

        # Compatibility with older history entries.
        if closed_at is None:
            closed_at = _parse_datetime(
                trade.get(
                    "updated_at"
                )
            )

        if closed_at is None:
            continue

        if (
            day_start
            <= closed_at
            <= now
        ):
            daily_closed.append(
                trade
            )

    return {
        "generated_at":
            now.isoformat(),

        "day_start":
            day_start.isoformat(),

        "day_end":
            now.isoformat(),

        "summary":
            performance(
                daily_closed
            ),

        "closed_trades":
            daily_closed,
    }


# =========================================================
# Weekly Report
# =========================================================

def weekly_report_data(
    history: list[dict],
    open_trades: list[dict],
    now: datetime | None = None,
) -> dict:
    """
    Prepares all data required by weekly_card.py.

    Realized and unrealized performance are kept separate.
    """

    now = (
        now
        or datetime.now(
            timezone.utc
        )
    )

    if now.tzinfo is None:
        now = now.replace(
            tzinfo=timezone.utc
        )

    now = now.astimezone(
        timezone.utc
    )

    # Monday 00:00 UTC
    week_start = (
        now
        - timedelta(
            days=now.weekday()
        )
    ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    weekly_closed: list[dict] = []

    for trade in history:
        if not _is_closed(
            trade
        ):
            continue

        closed_at = _parse_datetime(
            trade.get(
                "closed_at"
            )
        )

        # Compatibility with older stored trades.
        if closed_at is None:
            closed_at = _parse_datetime(
                trade.get(
                    "updated_at"
                )
            )

        if closed_at is None:
            continue

        if (
            week_start
            <= closed_at
            <= now
        ):
            weekly_closed.append(
                trade
            )

    summary = performance(
        weekly_closed
    )

    # =====================================================
    # Closed Trades
    # =====================================================

    closed_rows = []

    for trade in weekly_closed:
        exit_price, price_kind = (
            _exit_or_last_price(
                trade
            )
        )

        pnl = _safe_float(
            trade.get(
                "pnl_pct",
                0,
            )
        )

        closed_rows.append(
            {
                "trade_id":
                    trade.get(
                        "trade_id",
                        "N/A",
                    ),

                "name":
                    _contract_name(
                        trade
                    ),

                "symbol":
                    trade.get(
                        "symbol",
                        "N/A",
                    ),

                "trade_type":
                    _trade_type_label(
                        trade.get(
                            "trade_type",
                            "",
                        )
                    ),

                "entry_price":
                    round(
                        _entry_price(
                            trade
                        ),
                        4,
                    ),

                "price":
                    round(
                        exit_price,
                        4,
                    ),

                "price_kind":
                    price_kind,

                "pnl_pct":
                    round(
                        pnl,
                        2,
                    ),

                "result":
                    _normalized_result(
                        trade
                    ),

                "exit_reason":
                    trade.get(
                        "exit_reason",
                        "N/A",
                    ),

                "closed_at":
                    trade.get(
                        "closed_at",
                        "",
                    ),
            }
        )

    closed_rows.sort(
        key=lambda row: (
            row.get(
                "closed_at",
                ""
            )
        ),
        reverse=True,
    )

    # =====================================================
    # Open Positions
    # =====================================================

    open_rows = []

    for trade in open_trades:
        if str(
            trade.get(
                "status",
                "",
            )
        ).upper() != "OPEN":
            continue

        last_price, price_kind = (
            _exit_or_last_price(
                trade
            )
        )

        pnl = _calculate_open_pnl(
            trade
        )

        if pnl > 0:
            result = (
                "OPEN_PROFIT"
            )

        elif pnl < 0:
            result = (
                "OPEN_LOSS"
            )

        else:
            result = (
                "OPEN_FLAT"
            )

        open_rows.append(
            {
                "trade_id":
                    trade.get(
                        "trade_id",
                        "N/A",
                    ),

                "name":
                    _contract_name(
                        trade
                    ),

                "symbol":
                    trade.get(
                        "symbol",
                        "N/A",
                    ),

                "trade_type":
                    _trade_type_label(
                        trade.get(
                            "trade_type",
                            "",
                        )
                    ),

                "entry_price":
                    round(
                        _entry_price(
                            trade
                        ),
                        4,
                    ),

                "price":
                    round(
                        last_price,
                        4,
                    ),

                "price_kind":
                    price_kind,

                "pnl_pct":
                    round(
                        pnl,
                        2,
                    ),

                "result":
                    result,

                "status":
                    "OPEN",
            }
        )

    open_rows.sort(
        key=lambda row: abs(
            row[
                "pnl_pct"
            ]
        ),
        reverse=True,
    )

    open_profit = [
        row
        for row in open_rows
        if row[
            "pnl_pct"
        ] > 0
    ]

    open_loss = [
        row
        for row in open_rows
        if row[
            "pnl_pct"
        ] < 0
    ]

    return {
        "generated_at":
            now.isoformat(),

        "week_start":
            week_start.isoformat(),

        "week_end":
            now.isoformat(),

        "summary":
            summary,

        "closed_trades":
            closed_rows,

        "open_trades":
            open_rows,

        "open_summary": {
            "total":
                len(
                    open_rows
                ),

            "profitable":
                len(
                    open_profit
                ),

            "losing":
                len(
                    open_loss
                ),

            "unrealized_pnl_pct":
                round(
                    sum(
                        row[
                            "pnl_pct"
                        ]
                        for row
                        in open_rows
                    ),
                    2,
                ),
        },
    }
