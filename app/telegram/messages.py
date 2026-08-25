from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


# =========================================================
# Trade Type
# =========================================================

def trade_type_ar(value: str) -> str:
    return {
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
    }.get(
        value,
        value,
    )


# =========================================================
# Helpers
# =========================================================

def _safe_float(
    value,
    default: float = 0.0,
) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(
    value,
    decimals: int = 2,
) -> str:
    try:
        number = float(value)
        return f"${number:,.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"


def _number(
    value,
    decimals: int = 2,
) -> str:
    try:
        number = float(value)
        return f"{number:,.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"


def _option_type(option: dict) -> str:
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

    return value or "N/A"


def _direction_ar(
    signal: dict,
) -> str:
    option = (
        signal.get("option")
        or {}
    )

    underlying_direction = (
        option.get(
            "underlying_direction"
        )
        or signal.get(
            "direction"
        )
    )

    if underlying_direction == "LONG":
        return "صاعد"

    if underlying_direction == "SHORT":
        return "هابط"

    return "محايد"


def _probability_text(
    signal: dict,
) -> tuple[str, str]:
    """
    Score is NOT Probability.

    Probability is only displayed numerically
    when statistically validated.
    """

    status = str(
        signal.get(
            "probability_status",
            "UNVALIDATED",
        )
    ).upper()

    probability = signal.get(
        "probability"
    )

    if (
        status == "VALIDATED"
        and probability is not None
    ):
        try:
            text = (
                f"{float(probability):.1f}%"
            )
        except (TypeError, ValueError):
            text = (
                "غير موثقة إحصائيًا بعد"
            )
    else:
        text = (
            "غير موثقة إحصائيًا بعد"
        )

    return text, status


def _time_lines() -> list[str]:
    now_utc = datetime.now(
        ZoneInfo("UTC")
    )

    new_york = now_utc.astimezone(
        ZoneInfo(
            "America/New_York"
        )
    )

    riyadh = now_utc.astimezone(
        ZoneInfo(
            "Asia/Riyadh"
        )
    )

    return [
        "🕒 آخر تحديث:",
        (
            "نيويورك: "
            f"{new_york.strftime('%d %b %Y - %I:%M %p')}"
        ),
        (
            "الرياض: "
            f"{riyadh.strftime('%d %b %Y - %I:%M %p')}"
        ),
    ]


def _title(
    signal: dict,
) -> str:
    trade_type = str(
        signal.get(
            "trade_type",
            "",
        )
    )

    if trade_type.startswith(
        "INDEX_OPTION_"
    ):
        return (
            "🚨 فرصة Index Options ورقية"
        )

    if trade_type.startswith(
        "EQUITY_OPTION_"
    ):
        return (
            "🚨 فرصة Options ورقية جديدة"
        )

    return (
        "🚨 فرصة تداول ورقية جديدة"
    )


# =========================================================
# Main Signal Message
# =========================================================

def signal_text(
    signal: dict,
) -> str:
    """
    Final channel message.

    Important:
    - This keeps the old detailed message style.
    - No ranking is shown in the public channel.
    - Ranking remains private during scan/pick.
    - Option horizontal image is sent separately.
    """

    probability_text, probability_status = (
        _probability_text(
            signal
        )
    )

    direction_ar = _direction_ar(
        signal
    )

    symbol = str(
        signal.get(
            "symbol",
            "N/A",
        )
    ).upper()

    trade_type = str(
        signal.get(
            "trade_type",
            "N/A",
        )
    )

    score = signal.get(
        "score",
        "N/A",
    )

    rr = signal.get(
        "rr",
        "N/A",
    )

    risk_pct = (
        _safe_float(
            signal.get(
                "risk_pct",
                0,
            )
        )
        * 100
    )

    samples = signal.get(
        "probability_samples",
        0,
    )

    lines = [
        _title(signal),
        "",
        f"الأصل: {symbol}",
        f"📈 الاتجاه: {direction_ar}",
        (
            "🧭 نوع الصفقة: "
            f"{trade_type_ar(trade_type)}"
        ),
        "",
        (
            "💰 منطقة الدخول: "
            f"{_number(signal.get('entry_low'))}"
            " – "
            f"{_number(signal.get('entry_high'))}"
        ),
        (
            "🛑 وقف الخسارة/حارس العقد: "
            f"{_number(signal.get('stop'))}"
        ),
        (
            "🎯 TP1: "
            f"{_number(signal.get('tp1'))}"
        ),
        (
            "🎯 TP2: "
            f"{_number(signal.get('tp2'))}"
        ),
        (
            "🎯 TP3: "
            f"{_number(signal.get('tp3'))}"
        ),
        "",
        f"⭐ قوة الإشارة: {score}/100",
        f"⚖️ R/R النظري: 1 : {rr}",
        (
            "🛡️ المخاطرة المقترحة: "
            f"{risk_pct:.2f}%"
        ),
        "",
        (
            "📊 الاحتمالية الإحصائية: "
            f"{probability_text}"
        ),
        (
            "🧪 العينات المتشابهة: "
            f"{samples}"
        ),
        (
            "📌 الحالة الإحصائية: "
            f"{probability_status}"
        ),
        "",
        (
            "📈 حالة السوق: "
            f"{signal.get('market_regime', 'N/A')}"
        ),
        (
            "🏦 القطاع: "
            f"{signal.get('sector', 'N/A')}"
        ),
        "",
        "📌 أسباب الصفقة:",
    ]

    # =====================================================
    # Reasons
    # =====================================================

    reasons = (
        signal.get(
            "reasons"
        )
        or []
    )

    if reasons:
        lines.extend(
            f"• {reason}"
            for reason in reasons
        )
    else:
        lines.append(
            "• لا توجد أسباب مسجلة."
        )

    # =====================================================
    # Strategies
    # =====================================================

    strategies = (
        signal.get(
            "strategies"
        )
        or []
    )

    if strategies:
        lines.extend(
            [
                "",
                "🧠 الاستراتيجيات المتوافقة:",
            ]
        )

        lines.extend(
            f"• {strategy}"
            for strategy in strategies
        )

    # =====================================================
    # Invalidation
    # =====================================================

    invalidation = (
        signal.get(
            "invalidation"
        )
        or []
    )

    if invalidation:
        lines.extend(
            [
                "",
                "⚠️ متى يبطل السيناريو؟",
            ]
        )

        lines.extend(
            f"• {item}"
            for item in invalidation
        )

    # =====================================================
    # Option Contract Details
    # =====================================================

    option = (
        signal.get(
            "option"
        )
        or {}
    )

    if option:
        option_type = _option_type(
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

        bid = option.get(
            "bid"
        )

        ask = option.get(
            "ask"
        )

        spread = option.get(
            "spread_pct",
            "N/A",
        )

        lines.extend(
            [
                "",
                "📄 بيانات العقد:",
                (
                    f"• النوع: "
                    f"{option_type}"
                ),
                (
                    f"• Strike: "
                    f"{strike}"
                ),
                (
                    f"• Expiration: "
                    f"{expiration}"
                ),
                (
                    f"• DTE: "
                    f"{dte}"
                ),
                (
                    f"• Bid: "
                    f"{_money(bid)}"
                ),
                (
                    f"• Ask: "
                    f"{_money(ask)}"
                ),
                (
                    f"• Spread: "
                    f"{spread}%"
                ),
                "",
                "📊 Greeks:",
                (
                    "• Delta: "
                    f"{option.get('delta', 'N/A')}"
                ),
                (
                    "• Gamma: "
                    f"{option.get('gamma', 'N/A')}"
                ),
                (
                    "• Theta: "
                    f"{option.get('theta', 'N/A')}"
                ),
                (
                    "• Vega: "
                    f"{option.get('vega', 'N/A')}"
                ),
                (
                    "• IV: "
                    f"{option.get('iv', 'N/A')}"
                ),
            ]
        )

        # =================================================
        # Underlying Setup
        # =================================================

        lines.extend(
            [
                "",
                "📈 بيانات الأصل الأساسي:",
                (
                    "• منطقة الدخول: "
                    f"{option.get('underlying_entry_low', 'N/A')}"
                    " – "
                    f"{option.get('underlying_entry_high', 'N/A')}"
                ),
                (
                    "• مستوى الإبطال: "
                    f"{option.get('underlying_stop', 'N/A')}"
                ),
                (
                    "• TP1: "
                    f"{option.get('underlying_tp1', 'N/A')}"
                ),
                (
                    "• TP2: "
                    f"{option.get('underlying_tp2', 'N/A')}"
                ),
                (
                    "• TP3: "
                    f"{option.get('underlying_tp3', 'N/A')}"
                ),
                "",
                (
                    "📡 جودة بيانات الخيارات: "
                    "INDICATIVE — ليست OPRA Real-Time"
                ),
            ]
        )

    # =====================================================
    # Data Quality
    # =====================================================

    lines.extend(
        [
            "",
            (
                "📊 جودة البيانات: "
                f"{signal.get('data_quality', 'N/A')}"
            ),
            "",
        ]
    )

    lines.extend(
        _time_lines()
    )

    # =====================================================
    # Trade ID
    # =====================================================

    if signal.get(
        "trade_id"
    ):
        lines.extend(
            [
                "",
                (
                    "🆔 Paper Trade: "
                    f"{signal['trade_id']}"
                ),
            ]
        )

    # =====================================================
    # Footer
    # =====================================================

    lines.extend(
        [
            "",
            (
                "⚠️ تداول ورقي فقط — "
                "لا يوجد تنفيذ حقيقي"
            ),
        ]
    )

    return "\n".join(
        lines
    )
