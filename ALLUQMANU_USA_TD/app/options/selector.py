from __future__ import annotations
import re
from datetime import datetime, timezone
from app.config import settings

OCC = re.compile(r"^(?P<root>[A-Z0-9.]+)(?P<date>\d{6})(?P<type>[CP])(?P<strike>\d{8})$")


def parse_occ(symbol: str) -> dict:
    m = OCC.match(str(symbol).upper())
    if not m:
        return {}
    d = datetime.strptime(m.group("date"), "%y%m%d").date()
    return {
        "root": m.group("root"),
        "expiration": str(d),
        "type": "CALL" if m.group("type") == "C" else "PUT",
        "strike": int(m.group("strike")) / 1000,
        "dte": (d - datetime.now(timezone.utc).date()).days,
    }


class ContractSelector:
    def select(
        self,
        payload: dict,
        direction: str,
        expected_underlying: str | None = None,
        underlying_price: float | None = None,
    ) -> dict | None:
        snaps = payload.get("snapshots", {}) or {}
        desired = "CALL" if direction == "LONG" else "PUT"
        best = None
        expected = str(expected_underlying or "").upper().replace("/", "")
        for sym, snap in snaps.items():
            meta = parse_occ(sym)
            if not meta or meta["type"] != desired or meta["dte"] <= 0:
                continue
            root = meta["root"].replace("/", "")
            allowed_roots = {expected}
            if expected == "SPX":
                allowed_roots.add("SPXW")
            if expected and root not in allowed_roots:
                continue
            if underlying_price and underlying_price > 0:
                distance_pct = abs(meta["strike"] - underlying_price) / underlying_price * 100
                if distance_pct > settings.option_max_strike_distance_pct:
                    continue
            else:
                distance_pct = None

            q = snap.get("latestQuote") or snap.get("latest_quote") or {}
            g = snap.get("greeks") or {}
            daily = snap.get("dailyBar") or snap.get("daily_bar") or {}
            bid = q.get("bp") or q.get("bid_price") or 0
            ask = q.get("ap") or q.get("ask_price") or 0
            try:
                bid, ask = float(bid), float(ask)
            except (TypeError, ValueError):
                continue
            if bid <= 0 or ask <= bid:
                continue
            mid = (bid + ask) / 2
            spread = (ask - bid) / mid * 100 if mid else 999
            delta = g.get("delta")
            if delta is None:
                continue
            try:
                ad = abs(float(delta))
            except (TypeError, ValueError):
                continue
            if spread > settings.option_max_spread_pct:
                continue
            if not (settings.option_min_abs_delta <= ad <= settings.option_max_abs_delta):
                continue

            theta = g.get("theta")
            iv = snap.get("impliedVolatility") or snap.get("implied_volatility")
            volume = daily.get("v") or daily.get("volume") or 0
            score = 100.0
            score -= min(spread * 4.0, 35.0)
            score -= abs(ad - 0.55) * 55.0
            try:
                theta_ratio = abs(float(theta)) / mid if theta is not None and mid > 0 else 0
                score -= min(theta_ratio * 12.0, 15.0)
            except (TypeError, ValueError):
                pass
            try:
                ivf = float(iv) if iv is not None else None
                if ivf is not None and ivf > 1.5:
                    score -= 8.0
            except (TypeError, ValueError):
                pass
            try:
                if float(volume) > 0:
                    score += min(6.0, 1.5 * (float(volume) ** 0.25))
            except (TypeError, ValueError):
                pass
            score = max(0.0, min(100.0, score))
            if score < settings.option_min_contract_score:
                continue
            item = {
                "symbol": sym,
                **meta,
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "mid": round(mid, 2),
                "spread_pct": round(spread, 2),
                "delta": float(delta),
                "gamma": g.get("gamma"),
                "theta": theta,
                "vega": g.get("vega"),
                "rho": g.get("rho"),
                "iv": iv,
                "volume": volume,
                "strike_distance_pct": round(distance_pct, 2) if distance_pct is not None else None,
                "contract_score": round(score, 1),
            }
            if best is None or item["contract_score"] > best["contract_score"]:
                best = item
        return best
