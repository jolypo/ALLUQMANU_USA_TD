from __future__ import annotations

from datetime import datetime
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.config import settings


# =========================================================
# Fonts
# =========================================================

def _font(size: int, bold: bool = False):
    candidates = [
        (
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans-Bold.ttf"
            if bold
            else
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans.ttf"
        )
    ]

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass

    return ImageFont.load_default()


# =========================================================
# Helpers
# =========================================================

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(value: Any) -> str:
    value = _safe_float(value)

    if value >= 1000:
        return f"${value:,.2f}"

    return f"${value:.2f}"


def _pct(value: Any) -> str:
    value = _safe_float(value)
    return f"{value:+.2f}%"


def _date_text(value: str) -> str:
    try:
        dt = datetime.fromisoformat(
            str(value).replace(
                "Z",
                "+00:00",
            )
        )

        return dt.strftime(
            "%d %b %Y"
        )

    except Exception:
        return "N/A"


def _clip_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font,
    max_width: int,
) -> str:
    text = str(text)

    if draw.textlength(
        text,
        font=font,
    ) <= max_width:
        return text

    suffix = "..."

    while text:
        shortened = (
            text[:-1]
            + suffix
        )

        if draw.textlength(
            shortened,
            font=font,
        ) <= max_width:
            return shortened

        text = text[:-1]

    return suffix


# =========================================================
# Colors
# =========================================================

BG = (8, 14, 20)

PANEL = (15, 24, 32)

PANEL_ALT = (19, 30, 39)

TEXT = (235, 239, 242)

MUTED = (145, 157, 168)

GOLD = (213, 168, 63)

GREEN = (59, 190, 112)

GREEN_SOFT = (19, 66, 44)

RED = (220, 79, 79)

RED_SOFT = (74, 27, 31)

AMBER = (232, 170, 66)

AMBER_SOFT = (75, 52, 23)

LINE = (43, 56, 66)

WATERMARK = (38, 48, 56)


# =========================================================
# Summary Card
# =========================================================

def _summary_box(
    draw: ImageDraw.ImageDraw,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    label: str,
    value: str,
    value_color=TEXT,
):
    draw.rounded_rectangle(
        (
            x1,
            y1,
            x2,
            y2,
        ),
        radius=22,
        fill=PANEL,
        outline=LINE,
        width=2,
    )

    draw.text(
        (
            x1 + 22,
            y1 + 18,
        ),
        label,
        font=_font(
            22,
            False,
        ),
        fill=MUTED,
    )

    draw.text(
        (
            x1 + 22,
            y1 + 58,
        ),
        value,
        font=_font(
            34,
            True,
        ),
        fill=value_color,
    )


# =========================================================
# Trade Row
# =========================================================

def _trade_row(
    draw: ImageDraw.ImageDraw,
    y: int,
    row: dict,
    width: int,
    row_height: int = 72,
):
    result = str(
        row.get(
            "result",
            "",
        )
    )

    pnl = _safe_float(
        row.get(
            "pnl_pct",
            0,
        )
    )

    if result == "WIN":
        fill = GREEN_SOFT
        accent = GREEN

    elif result == "LOSS":
        fill = RED_SOFT
        accent = RED

    elif result == "BREAKEVEN":
        fill = PANEL_ALT
        accent = MUTED

    elif result == "OPEN_PROFIT":
        fill = GREEN_SOFT
        accent = GREEN

    elif result == "OPEN_LOSS":
        fill = RED_SOFT
        accent = RED

    else:
        fill = AMBER_SOFT
        accent = AMBER

    x1 = 55
    x2 = width - 55

    draw.rounded_rectangle(
        (
            x1,
            y,
            x2,
            y + row_height,
        ),
        radius=15,
        fill=fill,
    )

    draw.rectangle(
        (
            x1,
            y,
            x1 + 7,
            y + row_height,
        ),
        fill=accent,
    )

    name_font = _font(
        24,
        True,
    )

    cell_font = _font(
        21,
        False,
    )

    pnl_font = _font(
        22,
        True,
    )

    name = _clip_text(
        draw,
        row.get(
            "name",
            "N/A",
        ),
        name_font,
        315,
    )

    trade_type = _clip_text(
        draw,
        row.get(
            "trade_type",
            "N/A",
        ),
        cell_font,
        300,
    )

    entry = _money(
        row.get(
            "entry_price",
            0,
        )
    )

    price_kind = row.get(
        "price_kind",
        "LAST",
    )

    price_label = (
        "Exit"
        if price_kind == "EXIT"
        else "Last"
    )

    last_or_exit = _money(
        row.get(
            "price",
            0,
        )
    )

    pnl_text = _pct(
        pnl
    )

    result_text = result.replace(
        "_",
        " ",
    )

    # Name
    draw.text(
        (
            82,
            y + 22,
        ),
        name,
        font=name_font,
        fill=TEXT,
    )

    # Type
    draw.text(
        (
            430,
            y + 24,
        ),
        trade_type,
        font=cell_font,
        fill=TEXT,
    )

    # Entry
    draw.text(
        (
            770,
            y + 24,
        ),
        entry,
        font=cell_font,
        fill=TEXT,
    )

    # Last / Exit
    draw.text(
        (
            955,
            y + 13,
        ),
        price_label,
        font=_font(
            16,
            False,
        ),
        fill=MUTED,
    )

    draw.text(
        (
            955,
            y + 34,
        ),
        last_or_exit,
        font=cell_font,
        fill=TEXT,
    )

    # P&L
    draw.text(
        (
            1175,
            y + 23,
        ),
        pnl_text,
        font=pnl_font,
        fill=accent,
    )

    # Status
    draw.text(
        (
            1370,
            y + 23,
        ),
        result_text,
        font=_font(
            18,
            True,
        ),
        fill=accent,
    )


# =========================================================
# Weekly Report Image
# =========================================================

def weekly_performance_card(
    report: dict,
    path: str,
):
    """
    Professional weekly performance image.

    Shows:
    - realized weekly summary
    - closed trades
    - current open positions
    - green profits
    - red losses
    - entry
    - exit / last
    - watermark

    Realized and unrealized performance are intentionally
    kept separate.
    """

    summary = report.get(
        "summary",
        {},
    )

    closed_trades = report.get(
        "closed_trades",
        [],
    )

    open_trades = report.get(
        "open_trades",
        [],
    )

    open_summary = report.get(
        "open_summary",
        {},
    )

    # Maximum rows shown to keep Telegram image readable.
    max_closed_rows = 8
    max_open_rows = 5

    shown_closed = closed_trades[
        :max_closed_rows
    ]

    shown_open = open_trades[
        :max_open_rows
    ]

    # Dynamic image height.
    header_height = 370

    closed_section_height = (
        125
        + max(
            1,
            len(shown_closed),
        )
        * 84
    )

    open_section_height = (
        125
        + max(
            1,
            len(shown_open),
        )
        * 84
    )

    footer_height = 110

    width = 1600

    height = (
        header_height
        + closed_section_height
        + open_section_height
        + footer_height
    )

    image = Image.new(
        "RGB",
        (
            width,
            height,
        ),
        BG,
    )

    draw = ImageDraw.Draw(
        image
    )

    # =====================================================
    # Header
    # =====================================================

    draw.text(
        (
            60,
            42,
        ),
        "WEEKLY PERFORMANCE REPORT",
        font=_font(
            48,
            True,
        ),
        fill=GOLD,
    )

    draw.text(
        (
            60,
            105,
        ),
        settings.watermark_name,
        font=_font(
            27,
            True,
        ),
        fill=MUTED,
    )

    week_start = _date_text(
        report.get(
            "week_start",
            "",
        )
    )

    week_end = _date_text(
        report.get(
            "week_end",
            "",
        )
    )

    period_text = (
        f"{week_start}  —  {week_end}"
    )

    draw.text(
        (
            1110,
            62,
        ),
        period_text,
        font=_font(
            24,
            True,
        ),
        fill=TEXT,
    )

    # =====================================================
    # Summary Cards
    # =====================================================

    cards_top = 165

    card_gap = 18

    card_width = 235

    positions = []

    start_x = 55

    for index in range(6):
        x1 = (
            start_x
            + index
            * (
                card_width
                + card_gap
            )
        )

        positions.append(
            (
                x1,
                cards_top,
                x1 + card_width,
                cards_top + 120,
            )
        )

    net_pnl = _safe_float(
        summary.get(
            "net_pnl_pct",
            0,
        )
    )

    net_color = (
        GREEN
        if net_pnl > 0
        else RED
        if net_pnl < 0
        else TEXT
    )

    max_dd = _safe_float(
        summary.get(
            "max_drawdown_pct",
            0,
        )
    )

    values = [
        (
            "Trades",
            str(
                summary.get(
                    "trades",
                    0,
                )
            ),
            TEXT,
        ),
        (
            "Wins",
            str(
                summary.get(
                    "wins",
                    0,
                )
            ),
            GREEN,
        ),
        (
            "Losses",
            str(
                summary.get(
                    "losses",
                    0,
                )
            ),
            RED,
        ),
        (
            "Win Rate",
            (
                f"{summary.get('win_rate', 0)}%"
            ),
            TEXT,
        ),
        (
            "Net P&L",
            (
                f"{net_pnl:+.2f}%"
            ),
            net_color,
        ),
        (
            "Max DD",
            (
                f"{max_dd:.2f}%"
            ),
            RED
            if max_dd < 0
            else TEXT,
        ),
    ]

    for box, values_tuple in zip(
        positions,
        values,
    ):
        _summary_box(
            draw,
            *box,
            *values_tuple,
        )

    # Profit Factor line
    draw.text(
        (
            60,
            315,
        ),
        (
            "Profit Factor: "
            f"{summary.get('profit_factor', 0)}"
        ),
        font=_font(
            22,
            True,
        ),
        fill=TEXT,
    )

    draw.text(
        (
            370,
            315,
        ),
        (
            "Breakeven: "
            f"{summary.get('breakeven', 0)}"
        ),
        font=_font(
            22,
            True,
        ),
        fill=MUTED,
    )

    draw.text(
        (
            650,
            315,
        ),
        "Realized results only",
        font=_font(
            22,
            True,
        ),
        fill=GOLD,
    )

    # =====================================================
    # Closed Trades Section
    # =====================================================

    y = header_height

    draw.text(
        (
            60,
            y,
        ),
        "CLOSED THIS WEEK",
        font=_font(
            33,
            True,
        ),
        fill=TEXT,
    )

    y += 55

    # Header row
    headers = [
        (82, "Trade"),
        (430, "Type"),
        (770, "Entry"),
        (955, "Exit"),
        (1175, "P&L"),
        (1370, "Result"),
    ]

    for x, label in headers:
        draw.text(
            (
                x,
                y,
            ),
            label,
            font=_font(
                18,
                True,
            ),
            fill=MUTED,
        )

    y += 35

    if shown_closed:
        for row in shown_closed:
            _trade_row(
                draw,
                y,
                row,
                width,
            )

            y += 84

    else:
        draw.rounded_rectangle(
            (
                55,
                y,
                width - 55,
                y + 72,
            ),
            radius=15,
            fill=PANEL,
        )

        draw.text(
            (
                82,
                y + 22,
            ),
            "No closed trades this week",
            font=_font(
                23,
                True,
            ),
            fill=MUTED,
        )

        y += 84

    if len(
        closed_trades
    ) > max_closed_rows:
        draw.text(
            (
                60,
                y,
            ),
            (
                f"+ "
                f"{len(closed_trades) - max_closed_rows} "
                "more closed trades"
            ),
            font=_font(
                18,
                False,
            ),
            fill=MUTED,
        )

        y += 35

    # =====================================================
    # Open Trades Section
    # =====================================================

    y += 35

    draw.line(
        (
            55,
            y,
            width - 55,
            y,
        ),
        fill=LINE,
        width=2,
    )

    y += 35

    draw.text(
        (
            60,
            y,
        ),
        "OPEN POSITIONS",
        font=_font(
            33,
            True,
        ),
        fill=TEXT,
    )

    unrealized = _safe_float(
        open_summary.get(
            "unrealized_pnl_pct",
            0,
        )
    )

    unrealized_color = (
        GREEN
        if unrealized > 0
        else RED
        if unrealized < 0
        else TEXT
    )

    draw.text(
        (
            1030,
            y + 5,
        ),
        (
            "Unrealized: "
            f"{unrealized:+.2f}%"
        ),
        font=_font(
            24,
            True,
        ),
        fill=unrealized_color,
    )

    y += 55

    open_headers = [
        (82, "Trade"),
        (430, "Type"),
        (770, "Entry"),
        (955, "Last"),
        (1175, "P&L"),
        (1370, "Status"),
    ]

    for x, label in open_headers:
        draw.text(
            (
                x,
                y,
            ),
            label,
            font=_font(
                18,
                True,
            ),
            fill=MUTED,
        )

    y += 35

    if shown_open:
        for row in shown_open:
            _trade_row(
                draw,
                y,
                row,
                width,
            )

            y += 84

    else:
        draw.rounded_rectangle(
            (
                55,
                y,
                width - 55,
                y + 72,
            ),
            radius=15,
            fill=PANEL,
        )

        draw.text(
            (
                82,
                y + 22,
            ),
            "No open positions",
            font=_font(
                23,
                True,
            ),
            fill=MUTED,
        )

        y += 84

    if len(
        open_trades
    ) > max_open_rows:
        draw.text(
            (
                60,
                y,
            ),
            (
                f"+ "
                f"{len(open_trades) - max_open_rows} "
                "more open positions"
            ),
            font=_font(
                18,
                False,
            ),
            fill=MUTED,
        )

        y += 35

    # =====================================================
    # Footer / Watermark
    # =====================================================

    footer_y = height - 85

    draw.line(
        (
            55,
            footer_y - 25,
            width - 55,
            footer_y - 25,
        ),
        fill=LINE,
        width=2,
    )

    draw.text(
        (
            60,
            footer_y,
        ),
        (
            "Paper Trading Only • "
            "Closed = Realized • "
            "Open = Unrealized"
        ),
        font=_font(
            20,
            False,
        ),
        fill=MUTED,
    )

    draw.text(
        (
            1210,
            footer_y,
        ),
        settings.watermark_name,
        font=_font(
            24,
            True,
        ),
        fill=WATERMARK,
    )

    # =====================================================
    # Save
    # =====================================================

    image.save(
        path,
        format="PNG",
        optimize=True,
    )
