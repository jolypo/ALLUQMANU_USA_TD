def trade_type_ar(v: str) -> str:
    return {
        "STOCK_INTRADAY": "سهم أمريكي — مضاربة يومية",
        "STOCK_SWING": "سهم أمريكي — سوينغ",
        "EQUITY_OPTION_INTRADAY": "خيارات سهم — مضاربة يومية",
        "EQUITY_OPTION_SWING": "خيارات سهم — سوينغ",
        "INDEX_OPTION_INTRADAY": "خيارات مؤشر — مضاربة يومية",
        "INDEX_OPTION_SWING": "خيارات مؤشر — سوينغ",
    }.get(v, v)


def signal_text(s: dict) -> str:
    prob = (
        f'{s.get("probability"):.1f}%'
        if s.get("probability_status") == "VALIDATED" and s.get("probability") is not None
        else "غير موثقة إحصائيًا بعد"
    )
    option = s.get("option") or {}
    under_dir = option.get("underlying_direction", s.get("direction"))
    dir_ar = "صاعد" if under_dir == "LONG" else "هابط"
    is_option = bool(option)
    title = "🚨 فرصة Options جديدة" if is_option else "🚨 فرصة تداول جديدة"
    lines = [
        title,
        f'الأصل: {s["symbol"]}',
        f'📈 الاتجاه: {dir_ar}',
        f'🧭 نوع الصفقة: {trade_type_ar(s["trade_type"])}',
        f'💰 منطقة الدخول: {s["entry_low"]} – {s["entry_high"]}',
        f'🛑 وقف الخسارة/حارس العقد: {s["stop"]}',
        f'🎯 TP1: {s["tp1"]}',
        f'🎯 TP2: {s["tp2"]}',
        f'🎯 TP3: {s["tp3"]}',
        f'⭐ قوة الإشارة: {s["score"]}/100',
        f'⚖️ R/R النظري: 1 : {s["rr"]}',
        f'🛡️ المخاطرة المقترحة: {s["risk_pct"]*100:.2f}%',
        f'📊 الاحتمالية الإحصائية: {prob}',
        f'🧪 العينات المتشابهة: {s.get("probability_samples", 0)}',
        f'📌 الحالة الإحصائية: {s.get("probability_status", "UNVALIDATED")}',
        f'📈 حالة السوق: {s.get("market_regime", "UNKNOWN")}',
        f'🏦 القطاع: {s.get("sector", "N/A")}',
        "📌 أسباب الصفقة:",
    ]
    lines += [f'• {x}' for x in s.get("reasons", [])]
    if s.get("strategies"):
        lines += ["🧠 المحاور المتوافقة:", "• " + " • ".join(s.get("strategies", []))]
    if s.get("invalidation"):
        lines += ["⚠️ متى يبطل السيناريو؟"] + [f'• {x}' for x in s["invalidation"]]
    if option:
        lines += [
            "📄 بيانات العقد:",
            f'• النوع: {option.get("type", "N/A")}',
            f'• Strike: {option.get("strike", "N/A")}',
            f'• Expiration: {option.get("expiration", "N/A")}',
            f'• DTE: {option.get("dte", "N/A")}',
            f'• Bid: ${option.get("bid", "N/A")} | Ask: ${option.get("ask", "N/A")}',
            f'• Spread: {option.get("spread_pct", "N/A")}% | Contract Score: {option.get("contract_score", "N/A")}',
            "📊 Greeks:",
            f'• Delta: {option.get("delta", "N/A")} | Gamma: {option.get("gamma", "N/A")}',
            f'• Theta: {option.get("theta", "N/A")} | Vega: {option.get("vega", "N/A")}',
            f'• IV: {option.get("iv") if option.get("iv") is not None else "N/A"}',
            "📈 بيانات الأصل الأساسي:",
            f'• الدخول: {option.get("underlying_entry_low", "N/A")} – {option.get("underlying_entry_high", "N/A")}',
            f'• مستوى الإبطال: {option.get("underlying_stop", "N/A")}',
            f'• TP1/TP2/TP3: {option.get("underlying_tp1", "N/A")} / {option.get("underlying_tp2", "N/A")} / {option.get("underlying_tp3", "N/A")}',
            "📡 جودة بيانات الخيارات: INDICATIVE — ليست OPRA Real-Time",
        ]
    lines += [f'📊 جودة البيانات: {s.get("data_quality", "N/A")}', f'🆔 Trade: {s.get("trade_id", "N/A")}']
    return "\n".join(lines)
