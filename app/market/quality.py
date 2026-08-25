import pandas as pd


def validate_bars(df: pd.DataFrame, min_bars: int) -> tuple[bool,str]:
    if df.empty: return False,"لا توجد بيانات تاريخية"
    if len(df) < min_bars: return False,f"عدد الشموع غير كافٍ: {len(df)}/{min_bars}"
    needed={"open","high","low","close","volume"}
    if not needed.issubset(df.columns): return False,"أعمدة OHLCV ناقصة"
    if df[list(needed)].isna().any().any(): return False,"بيانات OHLCV تحتوي قيماً فارغة"
    if (df[["open","high","low","close"]] <= 0).any().any(): return False,"سعر غير صالح"
    if (df["volume"] < 0).any(): return False,"حجم تداول غير صالح"
    return True,"GOOD"
