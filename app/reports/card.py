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

def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt_money(value):
    value = _safe_float(value)

    if value >= 1000:
        return f"${value:,.2f}"

    return f"${value:.2f}"


def _trade_type_label(value: str) -> str:
    mapping = {
        "EQUITY_OPTION_INTRADAY":
            "EQUITY OPTION • INTRADAY",

        "EQUITY_OPTION_SWING":
            "EQUITY OPTION • SWING",

        "INDEX_OPTION_INTRADAY":
            "INDEX OPTION • INTRADAY",

        "INDEX_OPTION_SWING":
            "INDEX OPTION • SWING",
    }

    return mapping.get(
        str(value),
        str(value).replace("_", " "),
    )


def _contract_type(option: dict) -> str:
    value = str(
        option.get(
            "type",
            option.get(
                "option_type",
                "",
            ),
        )
    ).upper()

    if value == "C":
        return "CALL"

    if value == "P":
        return "PUT"

    return value or "OPTION"


# =========================================================
# Horizontal Option Card
# =========================================================

def option_card(signal: dict, path: str):
    """
    Compact horizontal card used for BOTH:

    - Equity Options
    - SPX Index Options

    Important:
    Full details remain in the Telegram text message.
    The image only shows the core contract information.
    """

    option = signal.get("option") or {}

    symbol = str(
        signal.get(
            "symbol",
            "N/A",
        )
    ).upper()

    contract_type = _contract_type(
        option
    )

    strike = option.get(
        "strike",
        "N/A",
    )

    expiration = option.get(
        "expiration",
        "N/A",
    )

    dte = option.get(
        "dte",
        "N/A",
    )

    entry_low = option.get(
        "entry_low",
        signal.get(
            "entry_low",
            0,
        ),
    )

    entry_high = option.get(
        "entry_high",
        signal.get(
            "entry_high",
            0,
        ),
    )

    trade_type = _trade_type_label(
        signal.get(
            "trade_type",
            "",
        )
    )

    # =====================================================
    # Canvas
    # =====================================================

    width = 1600
    height = 760

    background = (
        7,
        16,
        20,
    )

    image = Image.new(
        "RGB",
        (
            width,
            height,
        ),
        background,
    )

    draw = ImageDraw.Draw(
        image
    )

    # =====================================================
    # Header
    # =====================================================

    draw.rounded_rectangle(
        (
            55,
            45,
            1545,
            170,
        ),
        radius=28,
        outline=(
            197,
            155,
            53,
        ),
        width=3,
    )

    draw.text(
        (
            95,
            78,
        ),
        "OPTIONS PAPER SIGNAL",
        font=_font(
            46,
            True,
        ),
        fill=(
            235,
            190,
            55,
        ),
    )

    draw.text(
        (
            1160,
            92,
        ),
        settings.watermark_name,
        font=_font(
            27,
            True,
        ),
        fill=(
            85,
            95,
            100,
        ),
    )

    # =====================================================
    # Main Contract Area
    # =====================================================

    draw.rounded_rectangle(
        (
            55,
            200,
            1545,
            640,
        ),
        radius=30,
        outline=(
            55,
            175,
            95,
        ),
        width=3,
    )

    # -----------------------------------------------------
    # Symbol
    # -----------------------------------------------------

    draw.text(
        (
            105,
            250,
        ),
        symbol,
        font=_font(
            90,
            True,
        ),
        fill=(
            115,
            220,
            80,
        ),
    )

    # -----------------------------------------------------
    # Contract Type + Strike
    # -----------------------------------------------------

    draw.text(
        (
            105,
            370,
        ),
        f"{contract_type}  |  STRIKE {strike}",
        font=_font(
            49,
            True,
        ),
        fill=(
            238,
            238,
            238,
        ),
    )

    # -----------------------------------------------------
    # Entry
    # -----------------------------------------------------

    draw.text(
        (
            105,
            480,
        ),
        (
            f"ENTRY "
            f"{_fmt_money(entry_low)}"
            f" - "
            f"{_fmt_money(entry_high)}"
        ),
        font=_font(
            47,
            True,
        ),
        fill=(
            115,
            220,
            80,
        ),
    )

    # =====================================================
    # Right Side
    # =====================================================

    right_x = 880

    draw.text(
        (
            right_x,
            280,
        ),
        f"EXPIRY  {expiration}",
        font=_font(
            39,
            True,
        ),
        fill=(
            235,
            235,
            235,
        ),
    )

    draw.text(
        (
            right_x,
            380,
        ),
        f"DTE  {dte}",
        font=_font(
            39,
            True,
        ),
        fill=(
            235,
            235,
            235,
        ),
    )

    draw.text(
        (
            right_x,
            485,
        ),
        trade_type,
        font=_font(
            28,
            True,
        ),
        fill=(
            185,
            185,
            185,
        ),
    )

    # =====================================================
    # Footer
    # =====================================================

    draw.text(
        (
            85,
            685,
        ),
        "Full contract details in Telegram message",
        font=_font(
            28,
            False,
        ),
        fill=(
            220,
            175,
            65,
        ),
    )

    draw.text(
        (
            1230,
            685,
        ),
        settings.watermark_name,
        font=_font(
            27,
            True,
        ),
        fill=(
            55,
            65,
            70,
        ),
    )

    # =====================================================
    # Save
    # =====================================================

    image.save(
        path,
        format="PNG",
        optimize=True,
    )
