from app.config import settings


class RiskEngine:
    def assess(self, score: float, data_quality: str, rr: float) -> tuple[bool,float,str]:
        if rr < settings.min_rr: return False,0.0,"R/R أقل من الحد الأدنى"
        if score < settings.min_score: return False,0.0,"Score أقل من الحد الأدنى"
        if data_quality == "INVALID": return False,0.0,"جودة البيانات غير صالحة"
        risk=0.005
        if score>=88: risk=0.01
        elif score>=82: risk=0.0075
        if data_quality != "GOOD": risk=min(risk,0.005)
        return True,min(risk,settings.max_risk_per_trade),"ACCEPT"
