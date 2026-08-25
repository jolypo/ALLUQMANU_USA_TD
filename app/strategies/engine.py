from __future__ import annotations
import pandas as pd
from app.utils.indicators import add_indicators


class StrategyEngine:
    def analyze(self, raw: pd.DataFrame) -> dict:
        df = add_indicators(raw)
        r = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(r.close)
        atr = float(r.atr) if pd.notna(r.atr) else max(close*0.02, 0.01)
        scores: dict[str,float] = {}
        reasons=[]

        trend = 50.0
        if close > r.ema20 > r.ema50: trend += 25
        if pd.notna(r.ema200) and r.ema50 > r.ema200: trend += 15
        if close < r.ema20 < r.ema50: trend -= 30
        scores["Trend"] = max(0,min(100,trend))

        momentum = 50.0
        if 50 <= r.rsi <= 70: momentum += 20
        if r.macd_hist > 0: momentum += 20
        if r.macd_hist > prev.macd_hist: momentum += 10
        scores["Momentum"] = max(0,min(100,momentum))

        volume = 50.0 + (20 if r.rvol >= 1.2 else 0) + (15 if r.volume > prev.volume else 0)
        scores["Volume"] = max(0,min(100,volume))

        high20 = float(df.high.iloc[-21:-1].max()) if len(df)>=21 else float(df.high.max())
        low20 = float(df.low.iloc[-21:-1].min()) if len(df)>=21 else float(df.low.min())
        structure=50.0
        if close > high20: structure += 35; reasons.append("اختراق مقاومة حديثة")
        elif close > r.ema20 and close > (high20+low20)/2: structure += 20
        if close < low20: structure -= 35
        scores["Structure"] = max(0,min(100,structure))

        vwap_score = 50 + (25 if close > r.vwap else -20)
        scores["VWAP"] = max(0,min(100,vwap_score))

        # Programmable ICT-style observations; treated as features, not claims of predictive certainty.
        ict = 50.0
        recent_low = float(df.low.iloc[-6:-1].min())
        recent_high = float(df.high.iloc[-6:-1].max())
        liquidity_sweep = float(r.low) < recent_low and close > recent_low
        bos = close > recent_high
        bullish_fvg = len(df) >= 3 and float(df.low.iloc[-1]) > float(df.high.iloc[-3])
        if liquidity_sweep: ict += 20; reasons.append("Liquidity Sweep صاعد")
        if bos: ict += 20; reasons.append("BOS صاعد")
        if bullish_fvg: ict += 10; reasons.append("Bullish FVG")
        scores["ICT"] = max(0,min(100,ict))

        # Family-weighted score to reduce double counting.
        unified = 0.30*scores["Trend"] + 0.20*scores["Structure"] + 0.18*scores["Momentum"] + 0.15*scores["Volume"] + 0.07*scores["VWAP"] + 0.10*scores["ICT"]
        direction = "LONG" if unified >= 60 else "SHORT" if unified <= 40 else "NEUTRAL"
        if direction == "LONG":
            entry_low, entry_high = close-0.15*atr, close+0.10*atr
            stop = min(low20, close-1.25*atr)
            risk = max(entry_high-stop, atr*0.5)
            tp1, tp2, tp3 = entry_high+risk*1.5, entry_high+risk*2.0, entry_high+risk*2.8
        elif direction == "SHORT":
            entry_low, entry_high = close-0.10*atr, close+0.15*atr
            stop = max(high20, close+1.25*atr)
            risk = max(stop-entry_low, atr*0.5)
            tp1, tp2, tp3 = entry_low-risk*1.5, entry_low-risk*2.0, entry_low-risk*2.8
        else:
            entry_low=entry_high=stop=tp1=tp2=tp3=close
            risk=0
        rr = 2.0 if risk > 0 else 0
        if close > r.ema20: reasons.append("السعر أعلى EMA20")
        if r.macd_hist > 0: reasons.append("MACD إيجابي")
        if r.rvol >= 1.2: reasons.append("Relative Volume مرتفع")
        return {"score": round(unified,1), "direction":direction, "scores":scores, "reasons":reasons[:6], "entry_low":round(entry_low,2), "entry_high":round(entry_high,2), "stop":round(stop,2), "tp1":round(tp1,2), "tp2":round(tp2,2), "tp3":round(tp3,2), "rr":round(rr,2), "atr":round(atr,4)}
