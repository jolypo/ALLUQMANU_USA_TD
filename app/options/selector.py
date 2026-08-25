from __future__ import annotations
import re
from datetime import datetime, timezone
from app.config import settings

OCC=re.compile(r"^(?P<root>[A-Z0-9.]+)(?P<date>\d{6})(?P<type>[CP])(?P<strike>\d{8})$")


def parse_occ(symbol: str) -> dict:
    m=OCC.match(symbol)
    if not m: return {}
    d=datetime.strptime(m.group("date"),"%y%m%d").date()
    return {"expiration":str(d),"type":"CALL" if m.group("type")=="C" else "PUT","strike":int(m.group("strike"))/1000,"dte":(d-datetime.now(timezone.utc).date()).days}


class ContractSelector:
    def select(self, payload: dict, direction: str) -> dict | None:
        snaps=payload.get("snapshots",{}) or {}
        desired="CALL" if direction=="LONG" else "PUT"
        best=None
        for sym,snap in snaps.items():
            meta=parse_occ(sym)
            if not meta or meta["type"]!=desired or meta["dte"]<=0: continue
            q=snap.get("latestQuote") or snap.get("latest_quote") or {}
            g=snap.get("greeks") or {}
            bid=q.get("bp") or q.get("bid_price") or 0
            ask=q.get("ap") or q.get("ask_price") or 0
            if not bid or not ask or ask<=bid: continue
            mid=(bid+ask)/2
            spread=(ask-bid)/mid*100 if mid else 999
            delta=g.get("delta")
            if delta is None: continue
            ad=abs(float(delta))
            if spread>settings.option_max_spread_pct or not(settings.option_min_abs_delta<=ad<=settings.option_max_abs_delta): continue
            score=100 - min(spread*4,35) - abs(ad-0.55)*60
            item={"symbol":sym,**meta,"bid":round(float(bid),2),"ask":round(float(ask),2),"mid":round(float(mid),2),"spread_pct":round(float(spread),2),"delta":float(delta),"gamma":g.get("gamma"),"theta":g.get("theta"),"vega":g.get("vega"),"rho":g.get("rho"),"iv":snap.get("impliedVolatility") or snap.get("implied_volatility"),"contract_score":round(score,1)}
            if best is None or item["contract_score"]>best["contract_score"]: best=item
        return best
