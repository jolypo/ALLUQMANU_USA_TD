from __future__ import annotations

from app.config import settings


class ProbabilityEngine:
    """
    Historical probability calibration.

    Important:
    - Score is NOT probability.
    - Probability remains UNVALIDATED until enough
      closed Paper Trades exist.
    - Manual CLOSED trades are classified by pnl_pct.
    """

    @staticmethod
    def _result(trade: dict) -> str | None:
        status = str(
            trade.get(
                "status",
                "",
            )
        ).upper()

        if status == "WIN":
            return "WIN"

        if status == "LOSS":
            return "LOSS"

        if status in {
            "CLOSED",
            "BREAKEVEN",
        }:
            try:
                pnl = float(
                    trade.get(
                        "pnl_pct",
                        0,
                    )
                    or 0
                )
            except (TypeError, ValueError):
                return None

            if pnl > 0:
                return "WIN"

            if pnl < 0:
                return "LOSS"

            return "BREAKEVEN"

        return None

    def summarize(
        self,
        history: list[dict],
        trade_type: str,
    ) -> dict:
        rows = []

        for trade in history:
            if trade.get(
                "trade_type"
            ) != trade_type:
                continue

            result = self._result(
                trade
            )

            if result in {
                "WIN",
                "LOSS",
            }:
                rows.append(
                    result
                )

        n = len(
            rows
        )

        required = (
            settings.probability_min_samples
        )

        if n < required:
            return {
                "status":
                    "UNVALIDATED",

                "samples":
                    n,

                "probability":
                    None,

                "required":
                    required,
            }

        wins = sum(
            1
            for result in rows
            if result == "WIN"
        )

        probability = round(
            100
            * wins
            / n,
            1,
        )

        return {
            "status":
                "VALIDATED",

            "samples":
                n,

            "probability":
                probability,

            "required":
                required,
        }
