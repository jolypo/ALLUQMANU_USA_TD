from __future__ import annotations

import re
from datetime import datetime, timezone

from app.config import settings


OCC = re.compile(
    r"^(?P<root>[A-Z0-9.]+)"
    r"(?P<date>\d{6})"
    r"(?P<type>[CP])"
    r"(?P<strike>\d{8})$"
)


def parse_occ(symbol: str) -> dict:
    """
    Parse OCC option symbol.

    Example:
    NVDA260918C00185000
    """

    match = OCC.match(symbol)

    if not match:
        return {}

    expiration_date = datetime.strptime(
        match.group("date"),
        "%y%m%d",
    ).date()

    option_type = (
        "CALL"
        if match.group("type") == "C"
        else "PUT"
    )

    strike = (
        int(
            match.group("strike")
        )
        / 1000
    )

    dte = (
        expiration_date
        - datetime.now(
            timezone.utc
        ).date()
    ).days

    return {
        "expiration": str(
            expiration_date
        ),
        "type": option_type,
        "strike": strike,
        "dte": dte,
    }


def _safe_float(
    value,
    default: float | None = None,
):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class ContractSelector:
    """
    Selects the strongest contract from an Alpaca
    option snapshots response.

    It does NOT decide whether the underlying itself
    is tradable. That decision belongs to SignalService.

    Filters:
    - correct CALL / PUT direction
    - positive DTE
    - valid Bid/Ask
    - maximum spread
    - Delta range
    - basic contract liquidity/quality
    """

    def select(
        self,
        payload: dict,
        direction: str,
    ) -> dict | None:

        snapshots = (
            payload.get(
                "snapshots",
                {},
            )
            or {}
        )

        desired_type = (
            "CALL"
            if direction == "LONG"
            else "PUT"
        )

        best: dict | None = None

        for contract_symbol, snapshot in snapshots.items():
            meta = parse_occ(
                contract_symbol
            )

            if not meta:
                continue

            if (
                meta["type"]
                != desired_type
            ):
                continue

            if meta["dte"] <= 0:
                continue

            quote = (
                snapshot.get(
                    "latestQuote"
                )
                or snapshot.get(
                    "latest_quote"
                )
                or {}
            )

            greeks = (
                snapshot.get(
                    "greeks"
                )
                or {}
            )

            trade = (
                snapshot.get(
                    "latestTrade"
                )
                or snapshot.get(
                    "latest_trade"
                )
                or {}
            )

            daily_bar = (
                snapshot.get(
                    "dailyBar"
                )
                or snapshot.get(
                    "daily_bar"
                )
                or {}
            )

            # =================================================
            # Bid / Ask
            # =================================================

            bid = _safe_float(
                quote.get(
                    "bp",
                    quote.get(
                        "bid_price"
                    ),
                )
            )

            ask = _safe_float(
                quote.get(
                    "ap",
                    quote.get(
                        "ask_price"
                    ),
                )
            )

            if (
                bid is None
                or ask is None
                or bid <= 0
                or ask <= 0
                or ask <= bid
            ):
                continue

            mid = (
                bid + ask
            ) / 2

            spread_pct = (
                (
                    ask - bid
                )
                / mid
                * 100
                if mid > 0
                else 999.0
            )

            if (
                spread_pct
                > settings.option_max_spread_pct
            ):
                continue

            # =================================================
            # Greeks
            # =================================================

            delta = _safe_float(
                greeks.get(
                    "delta"
                )
            )

            if delta is None:
                continue

            abs_delta = abs(
                delta
            )

            if not (
                settings.option_min_abs_delta
                <= abs_delta
                <= settings.option_max_abs_delta
            ):
                continue

            gamma = _safe_float(
                greeks.get(
                    "gamma"
                )
            )

            theta = _safe_float(
                greeks.get(
                    "theta"
                )
            )

            vega = _safe_float(
                greeks.get(
                    "vega"
                )
            )

            rho = _safe_float(
                greeks.get(
                    "rho"
                )
            )

            # =================================================
            # IV
            # =================================================

            implied_volatility = _safe_float(
                snapshot.get(
                    "impliedVolatility",
                    snapshot.get(
                        "implied_volatility"
                    ),
                )
            )

            # =================================================
            # Liquidity
            # =================================================

            volume = _safe_float(
                daily_bar.get(
                    "v",
                    daily_bar.get(
                        "volume"
                    ),
                ),
                0.0,
            )

            open_interest = _safe_float(
                snapshot.get(
                    "openInterest",
                    snapshot.get(
                        "open_interest"
                    ),
                ),
                0.0,
            )

            last_trade_price = _safe_float(
                trade.get(
                    "p",
                    trade.get(
                        "price"
                    ),
                )
            )

            # =================================================
            # Contract Score
            # =================================================

            # Spread component
            if spread_pct <= 2:
                spread_score = 100.0
            elif spread_pct <= 4:
                spread_score = 90.0
            elif spread_pct <= 6:
                spread_score = 78.0
            elif spread_pct <= 8:
                spread_score = 65.0
            else:
                spread_score = 50.0

            # Delta component
            delta_distance = abs(
                abs_delta - 0.55
            )

            delta_score = max(
                0.0,
                100.0
                - delta_distance * 180,
            )

            # Volume component
            if volume >= 2000:
                volume_score = 100.0
            elif volume >= 1000:
                volume_score = 90.0
            elif volume >= 500:
                volume_score = 80.0
            elif volume >= 100:
                volume_score = 65.0
            elif volume > 0:
                volume_score = 45.0
            else:
                volume_score = 35.0

            # Open interest component
            if open_interest >= 5000:
                oi_score = 100.0
            elif open_interest >= 2000:
                oi_score = 90.0
            elif open_interest >= 1000:
                oi_score = 80.0
            elif open_interest >= 250:
                oi_score = 65.0
            elif open_interest > 0:
                oi_score = 45.0
            else:
                oi_score = 35.0

            contract_score = (
                spread_score * 0.35
                + delta_score * 0.30
                + volume_score * 0.20
                + oi_score * 0.15
            )

            item = {
                "symbol":
                    contract_symbol,

                "type":
                    meta["type"],

                "strike":
                    meta["strike"],

                "expiration":
                    meta["expiration"],

                "dte":
                    meta["dte"],

                "bid":
                    round(
                        bid,
                        4,
                    ),

                "ask":
                    round(
                        ask,
                        4,
                    ),

                "mid":
                    round(
                        mid,
                        4,
                    ),

                "spread_pct":
                    round(
                        spread_pct,
                        2,
                    ),

                "delta":
                    round(
                        delta,
                        4,
                    ),

                "gamma":
                    round(
                        gamma,
                        6,
                    )
                    if gamma is not None
                    else None,

                "theta":
                    round(
                        theta,
                        6,
                    )
                    if theta is not None
                    else None,

                "vega":
                    round(
                        vega,
                        6,
                    )
                    if vega is not None
                    else None,

                "rho":
                    round(
                        rho,
                        6,
                    )
                    if rho is not None
                    else None,

                "iv":
                    round(
                        implied_volatility,
                        6,
                    )
                    if implied_volatility is not None
                    else None,

                "volume":
                    int(
                        volume
                    )
                    if volume is not None
                    else 0,

                "open_interest":
                    int(
                        open_interest
                    )
                    if open_interest is not None
                    else 0,

                "last_trade_price":
                    round(
                        last_trade_price,
                        4,
                    )
                    if last_trade_price is not None
                    else None,

                "contract_score":
                    round(
                        contract_score,
                        1,
                    ),
            }

            if (
                best is None
                or item[
                    "contract_score"
                ]
                > best[
                    "contract_score"
                ]
            ):
                best = item

        return best
