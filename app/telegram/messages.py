def trade_type_ar(v:str)->str:
    return {"STOCK_INTRADAY":"سهم أمريكي — مضاربة يومية","STOCK_SWING":"سهم أمريكي — سوينغ","EQUITY_OPTION_INTRADAY":"خيارات سهم — مضاربة يومية","EQUITY_OPTION_SWING":"خيارات سهم — سوينغ","INDEX_OPTION_INTRADAY":"خيارات مؤشر — مضاربة يومية","INDEX_OPTION_SWING":"خيارات مؤشر — سوينغ"}.get(v,v)


def signal_text(s:dict)->str:
    prob=f'{s.get("probability"):.1f}%' if s.get("probability_status")=="VALIDATED" and s.get("probability") is not None else "غير موثقة إحصائيًا بعد"
    under_dir=(s.get("option") or {}).get("underlying_direction",s.get("direction"))
    dir_ar="صاعد" if under_dir=="LONG" else "هابط"
    lines=["🚨 فرصة تداول ورقية جديدة","",f'الأصل: {s["symbol"]}',f'📈 الاتجاه: {dir_ar}',f'🧭 نوع الصفقة: {trade_type_ar(s["trade_type"])}',f'📌 الحالة: {s["decision"]}',"",f'💰 منطقة الدخول: {s["entry_low"]} – {s["entry_high"]}',f'🛑 وقف الخسارة/حارس العقد: {s["stop"]}',f'🎯 TP1: {s["tp1"]}',f'🎯 TP2: {s["tp2"]}',f'🎯 TP3: {s["tp3"]}',"",f'⭐ التقييم: {s["score"]}/100',f'⚖️ R/R النظري: 1 : {s["rr"]}',f'🛡️ المخاطرة المقترحة: {s["risk_pct"]*100:.2f}%',f'📊 الاحتمالية الإحصائية: {prob}',f'🧪 العينات المتشابهة: {s["probability_samples"]}',f'📈 حالة السوق: {s["market_regime"]}',f'🏦 القطاع: {s.get("sector","N/A")}',"","📌 أسباب الصفقة:"]
    lines += [f'• {x}' for x in s["reasons"]]
    if s.get("invalidation"):
        lines += ["","⚠️ متى يبطل السيناريو؟"]+[f'• {x}' for x in s["invalidation"]]
    if s.get("option"):
        o=s["option"]
        lines += ["","📄 بيانات العقد:",f'• {o["type"]} | Strike {o["strike"]}',f'• الانتهاء: {o["expiration"]} | DTE: {o["dte"]}',f'• Bid/Ask: ${o["bid"]} / ${o["ask"]}',f'• Spread: {o["spread_pct"]}%',f'• Delta: {o.get("delta")}',f'• Gamma: {o.get("gamma")}',f'• Theta: {o.get("theta")}',f'• Vega: {o.get("vega")}',f'• IV: {o.get("iv") if o.get("iv") is not None else "N/A"}',f'• الأصل: دخول {o.get("underlying_entry_low","N/A")}–{o.get("underlying_entry_high","N/A")}',f'• إبطال الأصل: {o.get("underlying_stop","N/A")}',f'• أهداف الأصل: {o.get("underlying_tp1","N/A")} / {o.get("underlying_tp2","N/A")} / {o.get("underlying_tp3","N/A")}',"",'📡 جودة بيانات الخيارات: INDICATIVE — ليست OPRA Real-Time']
    lines += ["","⚠️ تداول ورقي فقط — لا يوجد تنفيذ حقيقي"]
    return "\n".join(lines)
