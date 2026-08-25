from __future__ import annotations
from app.config import settings
from app.models.domain import Signal,TradeType,Decision
from app.market.quality import validate_bars
from app.market.regime import MarketRegimeEngine
from app.strategies.engine import StrategyEngine
from app.risk.engine import RiskEngine
from app.options.selector import ContractSelector
from app.probability.engine import ProbabilityEngine

SECTOR_MAP={
    "AMD":"Semiconductors","MU":"Semiconductors","INTC":"Semiconductors","NVDA":"Semiconductors","AVGO":"Semiconductors",
    "MSFT":"Technology","ORCL":"Technology","IBM":"Technology","META":"Communication Services","AAPL":"Technology",
    "AMZN":"Consumer Discretionary","TSLA":"Consumer Discretionary","UBER":"Industrials","RKLB":"Industrials","SPCX":"Industrials",
}


class SignalService:
    def __init__(self,provider,history_repo):
        self.provider=provider; self.history=history_repo; self.strategy=StrategyEngine(); self.risk=RiskEngine(); self.selector=ContractSelector(); self.prob=ProbabilityEngine()

    async def market_is_open(self) -> tuple[bool,str]:
        if settings.allow_off_hours_scan: return True,"OVERRIDE"
        try:
            c=await self.provider.market_clock()
            return bool(c.get("is_open")), c.get("timestamp","")
        except Exception:
            return False,"تعذر التحقق من حالة السوق"

    async def _analyze(self,symbol:str,trade_type:TradeType):
        swing="SWING" in trade_type.value
        tf=settings.swing_timeframe if swing else settings.intraday_timeframe
        days=settings.swing_lookback_days if swing else settings.intraday_lookback_days
        minbars=settings.swing_min_bars if swing else settings.intraday_min_bars
        df=await self.provider.bars(symbol,tf,days)
        ok,q=validate_bars(df,minbars)
        if not ok: return None,q
        return self.strategy.analyze(df),q

    async def _stock_candidates(self, stock_types:list[TradeType]):
        regime=await MarketRegimeEngine(self.provider).get(); candidates=[]; rejects=[]
        for sym in settings.stocks:
            for t in stock_types:
                try:
                    a,q=await self._analyze(sym,t)
                    if not a: rejects.append(f"{sym}/{t.value}: {q}"); continue
                    if a["direction"] not in {"LONG","SHORT"}: rejects.append(f"{sym}/{t.value}: اتجاه محايد"); continue
                    ok,risk,reason=self.risk.assess(a["score"],q,a["rr"])
                    if not ok: rejects.append(f"{sym}/{t.value}: {reason}"); continue
                    p=self.prob.summarize(self.history.all(),t.value)
                    s=Signal(sym,t,a["direction"],Decision.READY,a["score"],a["entry_low"],a["entry_high"],a["stop"],a["tp1"],a["tp2"],a["tp3"],a["rr"],risk,a["reasons"],[f"كسر/اختراق مستوى الإبطال {a['stop']:.2f}"],list(a["scores"].keys()),regime,SECTOR_MAP.get(sym,"N/A"),q,p["status"],p["samples"],p.get("probability"))
                    candidates.append(s)
                except Exception as e: rejects.append(f"{sym}/{t.value}: {type(e).__name__}")
        candidates.sort(key=lambda x:x.score,reverse=True)
        return candidates,rejects

    async def best_stock(self):
        types=[]
        if settings.enable_stock_intraday: types.append(TradeType.STOCK_INTRADAY)
        if settings.enable_stock_swing: types.append(TradeType.STOCK_SWING)
        c,r=await self._stock_candidates(types)
        return (c[0] if c else None),r

    async def best_equity_option(self):
        stock_types=[]
        if settings.enable_equity_options_intraday: stock_types.append(TradeType.STOCK_INTRADAY)
        if settings.enable_equity_options_swing: stock_types.append(TradeType.STOCK_SWING)
        candidates,rejects=await self._stock_candidates(stock_types)
        # Only inspect option chains for strongest underlyings, reducing API usage.
        for base in candidates[:5]:
            swing="SWING" in base.trade_type.value
            min_dte=settings.option_swing_min_dte if swing else settings.option_intraday_min_dte
            max_dte=settings.option_swing_max_dte if swing else settings.option_intraday_max_dte
            opt_type="call" if base.direction=="LONG" else "put"
            try:
                chain=await self.provider.option_chain(base.symbol,min_dte,max_dte,opt_type)
                c=self.selector.select(chain,base.direction)
                if not c:
                    rejects.append(f"{base.symbol}: لا يوجد عقد {opt_type.upper()} يحقق شروط السيولة/Delta")
                    continue
                t=TradeType.EQUITY_OPTION_SWING if swing else TradeType.EQUITY_OPTION_INTRADAY
                p=self.prob.summarize(self.history.all(),t.value)
                entry_low=c["mid"]; entry_high=c["ask"]
                # Premium guard only. True thesis invalidation remains on the underlying.
                premium_risk=max(entry_high*0.22,0.01)
                if base.direction=="LONG": stop=round(max(0.01,entry_low-premium_risk),2); tp1=round(entry_high+premium_risk*1.5,2); tp2=round(entry_high+premium_risk*2,2); tp3=round(entry_high+premium_risk*2.8,2)
                else: stop=round(max(0.01,entry_low-premium_risk),2); tp1=round(entry_high+premium_risk*1.5,2); tp2=round(entry_high+premium_risk*2,2); tp3=round(entry_high+premium_risk*2.8,2)
                c.update({"entry_low":entry_low,"entry_high":entry_high,"underlying_direction":base.direction,"underlying_entry_low":base.entry_low,"underlying_entry_high":base.entry_high,"underlying_stop":base.stop,"underlying_tp1":base.tp1,"underlying_tp2":base.tp2,"underlying_tp3":base.tp3})
                score=round((base.score+c["contract_score"])/2,1)
                if score < settings.min_score: rejects.append(f"{base.symbol}: Contract/Unified Score منخفض"); continue
                return Signal(base.symbol,t,"LONG",Decision.READY,score,entry_low,entry_high,stop,tp1,tp2,tp3,2.0,min(base.risk_pct,0.005),base.reasons,[f"إبطال التحليل الأساسي عند {base.stop:.2f}"],base.strategies,base.market_regime,base.sector,"LIMITED",p["status"],p["samples"],p.get("probability"),c),rejects
            except Exception as e:
                rejects.append(f"{base.symbol} Options API: {type(e).__name__}")
        return None,rejects

    async def best_index_option(self):
        index=settings.indices[0] if settings.indices else "SPX"
        proxy=settings.index_analysis_proxy_spx if index=="SPX" else index
        types=[]
        if settings.enable_index_options_intraday: types.append(TradeType.INDEX_OPTION_INTRADAY)
        if settings.enable_index_options_swing: types.append(TradeType.INDEX_OPTION_SWING)
        ranked=[]; rejects=[]
        for t in types:
            try:
                a,q=await self._analyze(proxy,t)
                if not a or a["direction"] not in {"LONG","SHORT"}: rejects.append(f"{index}/{t.value}: اتجاه محايد"); continue
                ok,risk,reason=self.risk.assess(a["score"],q,a["rr"])
                if not ok: rejects.append(f"{index}/{t.value}: {reason}"); continue
                ranked.append((a["score"],t,a,q,risk))
            except Exception as e: rejects.append(f"{index}/{t.value}: {type(e).__name__}")
        ranked.sort(key=lambda x:x[0],reverse=True)
        for _,t,a,q,risk_pct in ranked:
            swing="SWING" in t.value
            min_dte=settings.option_swing_min_dte if swing else settings.option_intraday_min_dte
            max_dte=settings.option_swing_max_dte if swing else settings.option_intraday_max_dte
            opt_type="call" if a["direction"]=="LONG" else "put"
            try:
                chain=await self.provider.option_chain(index,min_dte,max_dte,opt_type)
                c=self.selector.select(chain,a["direction"])
                if not c: rejects.append(f"{index}/{t.value}: لا يوجد عقد متاح يحقق الشروط"); continue
                p=self.prob.summarize(self.history.all(),t.value)
                entry_low=c["mid"]; entry_high=c["ask"]; prem=max(entry_high*.22,.01)
                stop=round(max(.01,entry_low-prem),2)
                c.update({"entry_low":entry_low,"entry_high":entry_high,"underlying_direction":a["direction"],"underlying_entry_low":a["entry_low"],"underlying_entry_high":a["entry_high"],"underlying_stop":a["stop"],"underlying_tp1":a["tp1"],"underlying_tp2":a["tp2"],"underlying_tp3":a["tp3"]})
                score=round((a["score"]+c["contract_score"])/2,1)
                if score < settings.min_score: rejects.append(f"{index}/{t.value}: Unified Score منخفض"); continue
                return Signal(index,t,"LONG",Decision.READY,score,entry_low,entry_high,stop,round(entry_high+prem*1.5,2),round(entry_high+prem*2,2),round(entry_high+prem*2.8,2),2.0,min(risk_pct,0.005),a["reasons"],[f"إبطال بنية {proxy} عند {a['stop']:.2f}"],list(a["scores"].keys()),await MarketRegimeEngine(self.provider).get(),"INDEX","LIMITED",p["status"],p["samples"],p.get("probability"),c),rejects
            except Exception as e: rejects.append(f"{index}: {type(e).__name__}")
        return None,rejects
