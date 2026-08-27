import pandas as pd
from app.strategies.engine import StrategyEngine

def test_strategy_returns_structured_result():
    n=240
    df=pd.DataFrame({"open":[100+i*.2 for i in range(n)],"high":[101+i*.2 for i in range(n)],"low":[99+i*.2 for i in range(n)],"close":[100.5+i*.2 for i in range(n)],"volume":[100000+i*100 for i in range(n)]})
    r=StrategyEngine().analyze(df)
    assert 0 <= r["score"] <= 100
    assert r["direction"] in {"LONG","SHORT","NEUTRAL"}
    assert r["tp3"] >= r["tp2"] >= r["tp1"] if r["direction"]=="LONG" else True
