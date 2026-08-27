from __future__ import annotations
from datetime import datetime, timedelta, timezone
from app.config import settings

CLOSED = {"WIN", "LOSS", "BREAKEVEN", "CLOSED"}


def _safe_float(v, default=0.0):
    try: return float(v)
    except (TypeError, ValueError): return default


def _dt(v):
    if not v: return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


def _is_closed(t):
    return str(t.get("status", "")).upper() in CLOSED


def _entry(t):
    filled = _safe_float(t.get("filled_entry_price"), 0)
    if filled > 0: return filled
    lo, hi = _safe_float(t.get("entry_low"), 0), _safe_float(t.get("entry_high"), 0)
    return (lo + hi) / 2 if lo > 0 and hi > 0 else max(lo, hi, 0)


def _pnl_pct(t, price=None):
    if price is None and t.get("pnl_pct") is not None: return _safe_float(t.get("pnl_pct"))
    price = _safe_float(price if price is not None else t.get("exit_price", t.get("last_price")), 0)
    e = _entry(t)
    if e <= 0 or price <= 0: return 0.0
    short = str(t.get("direction", "LONG")).upper() == "SHORT"
    return ((e - price) if short else (price - e)) / e * 100


def _cash_pnl(t, price=None):
    tt = str(t.get("trade_type", ""))
    if "OPTION" not in tt: return 0.0
    price = _safe_float(price if price is not None else t.get("exit_price", t.get("last_price")), 0)
    e = _entry(t)
    if e <= 0 or price <= 0: return 0.0
    contracts = max(1, int(_safe_float(t.get("contracts", 1), 1)))
    short = str(t.get("direction", "LONG")).upper() == "SHORT"
    diff = (e - price) if short else (price - e)
    return diff * settings.option_multiplier * contracts


def _normalized_result(t):
    if t.get("success_100_reached") and "OPTION" in str(t.get("trade_type", "")):
        return "WIN"
    s = str(t.get("status", "")).upper()
    if s in {"WIN", "LOSS", "BREAKEVEN"}: return s
    p = _safe_float(t.get("pnl_pct"), 0)
    if p > 0.01: return "WIN"
    if p < -0.01: return "LOSS"
    return "BREAKEVEN"


def _max_drawdown(rows):
    equity = 0.0; peak = 0.0; mdd = 0.0
    for t in rows:
        equity += _safe_float(t.get("pnl_pct"), 0)
        peak = max(peak, equity)
        mdd = min(mdd, equity - peak)
    return round(mdd, 2)


def performance(history: list[dict]) -> dict:
    closed = [t for t in history if _is_closed(t)]
    wins = [t for t in closed if _normalized_result(t) == "WIN"]
    losses = [t for t in closed if _normalized_result(t) == "LOSS"]
    be = [t for t in closed if _normalized_result(t) == "BREAKEVEN"]
    pnls = [_safe_float(t.get("pnl_pct"), 0) for t in closed]
    gw = sum(x for x in pnls if x > 0); gl = abs(sum(x for x in pnls if x < 0))
    pf = gw / gl if gl else (999.0 if gw else 0.0)
    return {
        "trades": len(closed), "wins": len(wins), "losses": len(losses), "breakeven": len(be),
        "win_rate": round(len(wins)/len(closed)*100, 2) if closed else 0.0,
        "net_pnl_pct": round(sum(pnls), 2), "profit_factor": round(pf, 2),
        "max_drawdown_pct": _max_drawdown(closed),
    }


def _category(tt: str):
    if tt.startswith("STOCK_"): return "stock"
    if tt.startswith("EQUITY_OPTION_"): return "equity_option"
    if tt.startswith("INDEX_OPTION_"): return "index_option"
    return "other"


def _today_rows(history: list[dict], open_trades: list[dict], now=None):
    now = now or datetime.now(timezone.utc); day = now.astimezone(timezone.utc).date()
    seen = {}; rows = history + open_trades
    for t in rows:
        stamp = _dt(t.get("published_at") or t.get("created_at") or t.get("closed_at"))
        if stamp and stamp.date() == day:
            seen[str(t.get("trade_id") or id(t))] = t
    return list(seen.values())


def daily_category_reports(history: list[dict], open_trades: list[dict], now=None) -> dict:
    rows = _today_rows(history, open_trades, now)
    out = {}
    for cat in ("stock", "equity_option", "index_option"):
        items = [t for t in rows if _category(str(t.get("trade_type", ""))) == cat]
        if not items: continue
        closed = [t for t in items if _is_closed(t)]
        successes = [t for t in items if _normalized_result(t) == "WIN" and (_is_closed(t) or t.get("success_100_reached"))]
        losses = [t for t in closed if _normalized_result(t) == "LOSS"]
        breakeven = [t for t in closed if _normalized_result(t) == "BREAKEVEN"]
        settled_count = len(successes) + len(losses) + len(breakeven)
        cash = sum(_cash_pnl(t) for t in closed) if cat != "stock" else 0.0
        pnls = [_safe_float(t.get("pnl_pct"), 0) for t in closed]
        gw = sum(x for x in pnls if x > 0); gl = abs(sum(x for x in pnls if x < 0))
        pf = gw/gl if gl else (999.0 if gw else 0.0)
        ranked = sorted(items, key=lambda t: (_cash_pnl(t) if cat != "stock" else _pnl_pct(t)), reverse=True)
        best = ranked[0] if ranked else None
        out[cat] = {
            "activity": len(items), "closed": len(closed), "wins": len(successes), "losses": len(losses), "breakeven": len(breakeven),
            "win_rate": round(len(successes)/settled_count*100,2) if settled_count else 0.0,
            "profit_factor": round(pf,2), "net_pnl_pct": round(sum(pnls),2), "max_drawdown_pct": _max_drawdown(closed),
            "net_cash_usd": round(cash,2), "net_cash_sar": round(cash*settings.usd_sar_rate,2),
            "best": best,
        }
    return out


def daily_report_data(history: list[dict], now=None) -> dict:
    now = now or datetime.now(timezone.utc); day = now.date()
    closed = []
    for t in history:
        d = _dt(t.get("closed_at") or t.get("updated_at"))
        if d and d.date() == day and _is_closed(t): closed.append(t)
    return {"summary": performance(closed), "rows": closed}


def weekly_report_data(history: list[dict], open_trades: list[dict], now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    closed = [t for t in history if _is_closed(t) and (_dt(t.get("closed_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= start]
    open_rows = [t for t in open_trades if str(t.get("status", "")).upper() == "OPEN"]
    open_pnls = [_pnl_pct(t) for t in open_rows]
    return {
        "summary": performance(closed),
        "closed_rows": closed,
        "open_rows": open_rows,
        "open_summary": {
            "total": len(open_rows),
            "profitable": sum(1 for x in open_pnls if x > 0),
            "losing": sum(1 for x in open_pnls if x < 0),
            "unrealized_pnl_pct": round(sum(open_pnls), 2),
        },
    }
