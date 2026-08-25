import numpy as np
import pandas as pd


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    d = s.diff()
    gain = d.clip(lower=0).rolling(period).mean()
    loss = (-d.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([(df["high"]-df["low"]), (df["high"]-prev).abs(), (df["low"]-prev).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def macd(s: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    m = ema(s, 12) - ema(s, 26)
    sig = ema(m, 9)
    return m, sig, m-sig


def vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, np.nan)
    return (typical * vol).cumsum() / vol.cumsum()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    for p in (9,20,50,200):
        x[f"ema{p}"] = ema(x["close"], p)
    x["rsi"] = rsi(x["close"])
    x["atr"] = atr(x)
    m,s,h = macd(x["close"])
    x["macd"],x["macd_signal"],x["macd_hist"] = m,s,h
    x["vwap"] = vwap(x)
    x["rvol"] = x["volume"] / x["volume"].rolling(20).mean()
    return x
