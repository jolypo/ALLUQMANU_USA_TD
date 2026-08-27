from __future__ import annotations
from app.config import settings
from app.models.domain import Signal, TradeType, Decision
from app.market.quality import validate_bars
from app.market.regime import MarketRegimeEngine
from app.strategies.engine import StrategyEngine
from app.risk.engine import RiskEngine
from app.options.selector import ContractSelector
from app.probability.engine import ProbabilityEngine

SECTOR_MAP = {
    "AMD":"Semiconductors","MU":"Semiconductors","INTC":"Semiconductors","NVDA":"Semiconductors","AVGO":"Semiconductors",
    "MSFT":"Technology","ORCL":"Technology","IBM":"Technology","META":"Communication Services","AAPL":"Technology",
    "AMZN":"Consumer Discretionary","TSLA":"Consumer Discretionary","UBER":"Industrials","RKLB":"Industrials","SPCX":"Industrials",
}

POSITIVE_NEWS = (
    "beats estimates","raises guidance","raised guidance","upgrade","upgraded","approval","approved",
    "record revenue","contract win","wins contract","partnership","buyback","strong demand","outperform",
)
NEGATIVE_NEWS = (
    "misses estimates","cuts guidance","cut guidance","downgrade","downgraded","offering","dilution",
    "investigation","sec probe","fraud","bankruptcy","recall","lawsuit","weak demand","underperform",
)
SEVERE_NEGATIVE = ("bankruptcy","fraud","sec investigation","offering","cuts guidance","cut guidance")


class SignalService:
    def __init__(self, provider, history_repo):
        self.provider = provider
        self.history = history_repo
        self.strategy = StrategyEngine()
        self.risk = RiskEngine()
        self.selector = ContractSelector()
        self.prob = ProbabilityEngine()

    async def market_is_open(self) -> tuple[bool, str]:
        if settings.allow_off_hours_scan:
            return True, "OVERRIDE"
        try:
            c = await self.provider.market_clock()
            return bool(c.get("is_open")), c.get("timestamp", "")
        except Exception:
            return False, "تعذر التحقق من حالة السوق"

    async def _news_context(self, symbol: str) -> dict:
        if not settings.news_enabled:
            return {"modifier": 0.0, "severe_negative": False, "headline": None}
        try:
            rows = await self.provider.news(symbol, settings.news_lookback_hours, settings.news_max_items)
        except Exception:
            return {"modifier": 0.0, "severe_negative": False, "headline": None}
        raw = 0
        severe = False
        headline = None
        for item in rows:
            text = f"{item.get('headline','')} {item.get('summary','')}".lower()
            if headline is None and item.get("headline"):
                headline = str(item.get("headline"))
            raw += sum(1 for word in POSITIVE_NEWS if word in text)
            raw -= sum(1 for word in NEGATIVE_NEWS if word in text)
            if any(word in text for word in SEVERE_NEGATIVE):
                severe = True
        cap = float(settings.news_score_cap)
        modifier = max(-cap, min(cap, raw * 1.5))
        return {"modifier": modifier, "severe_negative": severe, "headline": headline}

    async def _analyze(self, symbol: str, trade_type: TradeType, benchmark_return: float | None = None, regime: str | None = None, news_context: dict | None = None):
        swing = "SWING" in trade_type.value
        tf = settings.swing_timeframe if swing else settings.intraday_timeframe
        days = settings.swing_lookback_days if swing else settings.intraday_lookback_days
        minbars = settings.swing_min_bars if swing else settings.intraday_min_bars
        df = await self.provider.bars(symbol, tf, days)
        ok, q = validate_bars(df, minbars)
        if not ok:
            return None, q
        a = self.strategy.analyze(df)

        # Multi-timeframe confirmation: intraday entries must respect daily context.
        mtf_modifier = 0.0
        mtf_label = "N/A"
        if not swing:
            try:
                daily = await self.provider.bars(symbol, settings.confirmation_timeframe, settings.confirmation_lookback_days)
                ok2, _ = validate_bars(daily, 60)
                if ok2:
                    h = self.strategy.analyze(daily)
                    mtf_label = h["direction"]
                    if h["direction"] == a["direction"]:
                        mtf_modifier = 5.0
                        a["reasons"].append("توافق 15m مع الاتجاه اليومي")
                    elif h["direction"] in {"LONG", "SHORT"} and h["direction"] != a["direction"]:
                        mtf_modifier = -8.0
                        a["reasons"].append("تعارض مع الاتجاه اليومي")
            except Exception:
                pass

        # Relative strength against benchmark on the same primary timeframe.
        rs_modifier = 0.0
        rs_value = None
        if benchmark_return is not None:
            rs_value = a.get("return20_pct", 0.0) - benchmark_return
            if a["direction"] == "LONG":
                rs_modifier = max(-settings.relative_strength_weight, min(settings.relative_strength_weight, rs_value * 0.6))
            elif a["direction"] == "SHORT":
                rs_modifier = max(-settings.relative_strength_weight, min(settings.relative_strength_weight, -rs_value * 0.6))
            if rs_modifier >= 2:
                a["reasons"].append(f"قوة نسبية أفضل من السوق {rs_value:+.1f}%")
            elif rs_modifier <= -2:
                a["reasons"].append(f"قوة نسبية أضعف من السوق {rs_value:+.1f}%")

        news = news_context if news_context is not None else await self._news_context(symbol)
        news_modifier = news["modifier"] if a["direction"] == "LONG" else -news["modifier"]
        regime = regime or await MarketRegimeEngine(self.provider).get()
        regime_modifier = 0.0
        if regime == "RANGE":
            regime_modifier -= settings.range_regime_penalty
        elif regime == "BULL":
            regime_modifier += 3.0 if a["direction"] == "LONG" else -5.0
        elif regime == "BEAR":
            regime_modifier += 3.0 if a["direction"] == "SHORT" else -5.0

        a["raw_score"] = a["score"]
        a["score"] = round(max(0.0, min(100.0, a["score"] + mtf_modifier + rs_modifier + news_modifier + regime_modifier)), 1)
        a["market_regime"] = regime
        a["mtf_direction"] = mtf_label
        a["relative_strength"] = round(rs_value, 2) if rs_value is not None else None
        a["news_modifier"] = round(news_modifier, 1)
        a["news_headline"] = news["headline"]
        a["severe_negative_news"] = bool(news["severe_negative"] and a["direction"] == "LONG")
        if news["headline"] and abs(news_modifier) >= 1.5:
            a["reasons"].append(f"Catalyst/News {news_modifier:+.1f}")
        return a, q

    async def _benchmark_return(self, trade_type: TradeType) -> float | None:
        swing = "SWING" in trade_type.value
        tf = settings.swing_timeframe if swing else settings.intraday_timeframe
        days = settings.swing_lookback_days if swing else settings.intraday_lookback_days
        try:
            df = await self.provider.bars("SPY", tf, days)
            ok, _ = validate_bars(df, 25)
            if not ok:
                return None
            a = self.strategy.analyze(df)
            return float(a.get("return20_pct", 0.0))
        except Exception:
            return None

    def _make_signal(self, sym: str, t: TradeType, a: dict, q: str, risk: float) -> Signal:
        p = self.prob.summarize(self.history.all(), t.value)
        invalid = [f"كسر/اختراق مستوى الإبطال {a['stop']:.2f}"]
        if a.get("severe_negative_news"):
            invalid.append("خبر سلبي جوهري حديث")
        return Signal(
            sym, t, a["direction"], Decision.READY, a["score"],
            a["entry_low"], a["entry_high"], a["stop"], a["tp1"], a["tp2"], a["tp3"], a["rr"], risk,
            a["reasons"][:8], invalid, list(a["scores"].keys()), a.get("market_regime", "UNKNOWN"),
            SECTOR_MAP.get(sym, "N/A"), q, p["status"], p["samples"], p.get("probability")
        )

    async def _stock_candidates(self, stock_types: list[TradeType]):
        candidates, rejects = [], []
        benchmark_cache = {}
        for t in stock_types:
            benchmark_cache[t.value] = await self._benchmark_return(t)
        try:
            regime = await MarketRegimeEngine(self.provider).get()
        except Exception:
            regime = "UNKNOWN"
        news_cache = {}
        for sym in settings.stocks:
            if sym not in news_cache:
                news_cache[sym] = await self._news_context(sym)
            for t in stock_types:
                try:
                    a, q = await self._analyze(
                        sym, t, benchmark_cache.get(t.value), regime, news_cache[sym]
                    )
                    if not a:
                        rejects.append(f"{sym}/{t.value}: {q}"); continue
                    if a["direction"] not in {"LONG", "SHORT"}:
                        rejects.append(f"{sym}/{t.value}: اتجاه محايد"); continue
                    if a.get("severe_negative_news"):
                        rejects.append(f"{sym}/{t.value}: خبر سلبي جوهري حديث"); continue
                    # Reject weak-trend + weak-volume combinations, especially inside RANGE.
                    flags = set(a.get("quality_flags", []))
                    if {"WEAK_ADX", "WEAK_VOLUME"}.issubset(flags):
                        rejects.append(f"{sym}/{t.value}: ADX وحجم تداول ضعيفان"); continue
                    ok, risk, reason = self.risk.assess(a["score"], q, a["rr"])
                    if not ok:
                        rejects.append(f"{sym}/{t.value}: {reason}"); continue
                    candidates.append(self._make_signal(sym, t, a, q, risk))
                except Exception as e:
                    rejects.append(f"{sym}/{t.value}: {type(e).__name__}")
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates, rejects

    async def best_stocks(self, max_results: int = 3):
        types = []
        if settings.enable_stock_intraday: types.append(TradeType.STOCK_INTRADAY)
        if settings.enable_stock_swing: types.append(TradeType.STOCK_SWING)
        c, r = await self._stock_candidates(types)
        # Prefer unique symbols in final ranking.
        out, seen = [], set()
        for s in c:
            if s.symbol in seen: continue
            out.append(s); seen.add(s.symbol)
            if len(out) >= max_results: break
        return out, r

    async def best_stock(self):
        c, r = await self.best_stocks(1)
        return (c[0] if c else None), r

    async def best_equity_options(self, max_results: int = 3):
        stock_types = []
        if settings.enable_equity_options_intraday: stock_types.append(TradeType.STOCK_INTRADAY)
        if settings.enable_equity_options_swing: stock_types.append(TradeType.STOCK_SWING)
        bases, rejects = await self._stock_candidates(stock_types)
        out, seen = [], set()
        for base in bases[:10]:
            if base.symbol in seen: continue
            swing = "SWING" in base.trade_type.value
            min_dte = settings.option_swing_min_dte if swing else settings.option_intraday_min_dte
            max_dte = settings.option_swing_max_dte if swing else settings.option_intraday_max_dte
            opt_type = "call" if base.direction == "LONG" else "put"
            try:
                chain = await self.provider.option_chain(base.symbol, min_dte, max_dte, opt_type)
                underlying_price = (float(base.entry_low) + float(base.entry_high)) / 2
                c = self.selector.select(chain, base.direction, base.symbol, underlying_price)
                if not c:
                    rejects.append(f"{base.symbol}: لا يوجد عقد يحقق شروط العقد/سلامة البيانات"); continue
                t = TradeType.EQUITY_OPTION_SWING if swing else TradeType.EQUITY_OPTION_INTRADAY
                p = self.prob.summarize(self.history.all(), t.value)
                entry_low, entry_high = c["mid"], c["ask"]
                prem = max(entry_high * 0.22, 0.01)
                stop = round(max(0.01, entry_low - prem), 2)
                tp1, tp2, tp3 = round(entry_high + prem*1.5,2), round(entry_high + prem*2,2), round(entry_high + prem*2.8,2)
                c.update({
                    "entry_low": entry_low, "entry_high": entry_high,
                    "underlying_direction": base.direction,
                    "underlying_entry_low": base.entry_low, "underlying_entry_high": base.entry_high,
                    "underlying_stop": base.stop, "underlying_tp1": base.tp1, "underlying_tp2": base.tp2, "underlying_tp3": base.tp3,
                })
                score = round(0.62 * base.score + 0.38 * c["contract_score"], 1)
                if score < settings.min_score:
                    rejects.append(f"{base.symbol}: Unified Score أقل من الحد الأدنى"); continue
                s = Signal(
                    base.symbol, t, "LONG", Decision.READY, score, entry_low, entry_high, stop, tp1, tp2, tp3,
                    2.0, min(base.risk_pct, 0.005), base.reasons,
                    [f"إبطال التحليل الأساسي عند {base.stop:.2f}"], base.strategies, base.market_regime, base.sector,
                    "LIMITED", p["status"], p["samples"], p.get("probability"), c
                )
                out.append(s); seen.add(base.symbol)
                if len(out) >= max_results: break
            except Exception as e:
                rejects.append(f"{base.symbol} Options API: {type(e).__name__}")
        return out, rejects

    async def best_equity_option(self):
        c, r = await self.best_equity_options(1)
        return (c[0] if c else None), r

    async def best_index_options(self, max_results: int = 3):
        index = settings.indices[0] if settings.indices else "SPX"
        proxy = settings.index_analysis_proxy_spx if index == "SPX" else index
        types = []
        if settings.enable_index_options_intraday: types.append(TradeType.INDEX_OPTION_INTRADAY)
        if settings.enable_index_options_swing: types.append(TradeType.INDEX_OPTION_SWING)
        out, rejects = [], []
        try:
            regime = await MarketRegimeEngine(self.provider).get()
        except Exception:
            regime = "UNKNOWN"
        news = await self._news_context(proxy)
        for t in types:
            try:
                a, q = await self._analyze(proxy, t, None, regime, news)
                if not a or a["direction"] not in {"LONG", "SHORT"}:
                    rejects.append(f"{index}/{t.value}: اتجاه محايد"); continue
                ok, risk, reason = self.risk.assess(a["score"], q, a["rr"])
                if not ok:
                    rejects.append(f"{index}/{t.value}: {reason}"); continue
                swing = "SWING" in t.value
                min_dte = settings.option_swing_min_dte if swing else settings.option_intraday_min_dte
                max_dte = settings.option_swing_max_dte if swing else settings.option_intraday_max_dte
                opt_type = "call" if a["direction"] == "LONG" else "put"
                chain = await self.provider.option_chain(index, min_dte, max_dte, opt_type)
                underlying_price = (a["entry_low"] + a["entry_high"]) / 2
                c = self.selector.select(chain, a["direction"], index, underlying_price)
                if not c:
                    rejects.append(f"{index}/{t.value}: لا يوجد عقد متاح يحقق الشروط"); continue
                p = self.prob.summarize(self.history.all(), t.value)
                entry_low, entry_high = c["mid"], c["ask"]
                prem = max(entry_high * .22, .01)
                stop = round(max(.01, entry_low - prem), 2)
                c.update({
                    "entry_low": entry_low, "entry_high": entry_high,
                    "underlying_direction": a["direction"],
                    "underlying_entry_low": a["entry_low"], "underlying_entry_high": a["entry_high"],
                    "underlying_stop": a["stop"], "underlying_tp1": a["tp1"], "underlying_tp2": a["tp2"], "underlying_tp3": a["tp3"],
                })
                score = round(0.62*a["score"] + 0.38*c["contract_score"], 1)
                if score < settings.min_score:
                    rejects.append(f"{index}/{t.value}: Unified Score أقل من الحد الأدنى"); continue
                out.append(Signal(
                    index, t, "LONG", Decision.READY, score, entry_low, entry_high, stop,
                    round(entry_high+prem*1.5,2), round(entry_high+prem*2,2), round(entry_high+prem*2.8,2),
                    2.0, min(risk,0.005), a["reasons"], [f"إبطال بنية {proxy} عند {a['stop']:.2f}"],
                    list(a["scores"].keys()), a.get("market_regime","UNKNOWN"), "INDEX", "LIMITED",
                    p["status"], p["samples"], p.get("probability"), c
                ))
            except Exception as e:
                rejects.append(f"{index}/{t.value}: {type(e).__name__}")
        out.sort(key=lambda x: x.score, reverse=True)
        return out[:max_results], rejects

    async def best_index_option(self):
        c, r = await self.best_index_options(1)
        return (c[0] if c else None), r
