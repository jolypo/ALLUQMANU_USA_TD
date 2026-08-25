from __future__ import annotations

from app.config import settings


class RiskEngine:
    """
    Signal-level risk gate.

    مسؤول عن:
    - الحد الأدنى للـ Score
    - الحد الأدنى للـ R/R
    - جودة البيانات
    - تحديد نسبة المخاطرة المقترحة للصفقة

    مهم:
    هذا المحرك لا يحسب إجمالي مخاطر المحفظة.
    إجمالي المخاطر المفتوحة يتم فحصه لاحقًا
    وقت /publish داخل TelegramHub.
    """

    def assess(
        self,
        score: float,
        data_quality: str,
        rr: float,
    ) -> tuple[bool, float, str]:

        # =====================================================
        # Normalize
        # =====================================================

        try:
            score = float(score)
        except (TypeError, ValueError):
            return (
                False,
                0.0,
                "Score غير صالح",
            )

        try:
            rr = float(rr)
        except (TypeError, ValueError):
            return (
                False,
                0.0,
                "R/R غير صالح",
            )

        quality = str(
            data_quality or ""
        ).upper()

        # =====================================================
        # Hard Rejections
        # =====================================================

        if rr < settings.min_rr:
            return (
                False,
                0.0,
                "R/R أقل من الحد الأدنى",
            )

        if score < settings.min_score:
            return (
                False,
                0.0,
                "Score أقل من الحد الأدنى",
            )

        if quality == "INVALID":
            return (
                False,
                0.0,
                "جودة البيانات غير صالحة",
            )

        if quality == "STALE":
            return (
                False,
                0.0,
                "البيانات قديمة ولا تصلح لإشارة جديدة",
            )

        # =====================================================
        # Base Risk by Signal Strength
        # =====================================================

        if score >= 92:
            risk = 0.0100

        elif score >= 88:
            risk = 0.0075

        elif score >= 82:
            risk = 0.0050

        else:
            risk = 0.0040

        # =====================================================
        # Data Quality Adjustment
        # =====================================================

        if quality == "LIMITED":
            risk = min(
                risk,
                0.0050,
            )

        elif quality != "GOOD":
            risk = min(
                risk,
                0.0040,
            )

        # =====================================================
        # R/R Adjustment
        # =====================================================

        # Stronger R/R can keep normal risk.
        # Weak-but-acceptable R/R gets slightly reduced risk.
        if rr < 1.75:
            risk *= 0.85

        # =====================================================
        # Global Cap
        # =====================================================

        risk = min(
            risk,
            settings.max_risk_per_trade,
        )

        risk = round(
            risk,
            4,
        )

        return (
            True,
            risk,
            "ACCEPT",
        )
