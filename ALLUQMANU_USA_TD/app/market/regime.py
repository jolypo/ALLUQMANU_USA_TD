from app.strategies.engine import StrategyEngine


class MarketRegimeEngine:
    def __init__(self, provider): self.provider=provider
    async def get(self) -> str:
        try:
            df=await self.provider.bars("SPY","1Day",260)
            if len(df)<60: return "UNKNOWN"
            a=StrategyEngine().analyze(df)
            if a["score"]>=75: return "BULL"
            if a["score"]<=35: return "BEAR"
            return "RANGE"
        except Exception:
            return "UNKNOWN"
