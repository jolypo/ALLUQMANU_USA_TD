from app.reports.performance import performance

def test_performance_basic():
    p=performance([{"status":"WIN","pnl_pct":10},{"status":"LOSS","pnl_pct":-5}])
    assert p["trades"]==2 and p["win_rate"]==50.0 and p["profit_factor"]==2.0
