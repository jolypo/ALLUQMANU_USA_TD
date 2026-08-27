from app.options.selector import parse_occ,ContractSelector

def test_occ_parser():
    d=parse_occ("AAPL260918C00185000")
    assert d["type"]=="CALL" and d["strike"]==185

def test_selector():
    p={"snapshots":{"AAPL260918C00185000":{"latestQuote":{"bp":6.1,"ap":6.3},"greeks":{"delta":0.58,"gamma":0.03,"theta":-0.1,"vega":0.15},"impliedVolatility":0.42}}}
    c=ContractSelector().select(p,"LONG")
    assert c and c["type"]=="CALL"
