from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TradeType(str, Enum):
    STOCK_INTRADAY = "STOCK_INTRADAY"
    STOCK_SWING = "STOCK_SWING"

    EQUITY_OPTION_INTRADAY = "EQUITY_OPTION_INTRADAY"
    EQUITY_OPTION_SWING = "EQUITY_OPTION_SWING"

    INDEX_OPTION_INTRADAY = "INDEX_OPTION_INTRADAY"
    INDEX_OPTION_SWING = "INDEX_OPTION_SWING"


class Decision(str, Enum):
    READY = "READY"
    WATCH = "WATCH"
    REJECT = "REJECT"


@dataclass
class Signal:
    # =====================================================
    # Identity
    # =====================================================

    symbol: str
    trade_type: TradeType
    direction: str
    decision: Decision

    # =====================================================
    # Core Signal
    # =====================================================

    score: float

    entry_low: float
    entry_high: float

    stop: float

    tp1: float
    tp2: float
    tp3: float

    rr: float
    risk_pct: float

    # =====================================================
    # Analysis
    # =====================================================

    reasons: list[str] = field(
        default_factory=list
    )

    invalidation: list[str] = field(
        default_factory=list
    )

    strategies: list[str] = field(
        default_factory=list
    )

    market_regime: str = "UNKNOWN"

    sector: str = "N/A"

    data_quality: str = "LIMITED"

    # =====================================================
    # Statistical Probability
    # =====================================================

    probability_status: str = (
        "UNVALIDATED"
    )

    probability_samples: int = 0

    probability: float | None = None

    # =====================================================
    # Options
    # =====================================================

    option: dict[str, Any] | None = None

    # =====================================================
    # Ranking
    #
    # Optional fields only.
    # They do NOT replace score.
    # =====================================================

    ranking_score: float | None = None
    ranking_position: int | None = None

    # =====================================================
    # Metadata
    # =====================================================

    created_at: str = field(
        default_factory=lambda: (
            datetime.now(
                timezone.utc
            ).isoformat()
        )
    )

    # =====================================================
    # Serialization
    # =====================================================

    def to_dict(
        self,
    ) -> dict[str, Any]:
        data = asdict(
            self
        )

        data[
            "trade_type"
        ] = self.trade_type.value

        data[
            "decision"
        ] = self.decision.value

        return data
