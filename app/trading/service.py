from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from app.config import settings
from app.market.quality import validate_bars
from app.market.regime import MarketRegimeEngine
from app.models.domain import Decision, Signal, TradeType
from app.options.selector import ContractSelector
from app.probability.engine import ProbabilityEngine
from app.risk.engine import RiskEngine
from app.strategies.engine import StrategyEngine


SECTOR_MAP = {
    "AMD": "Semiconductors",
    "MU": "Semiconductors",
    "INTC": "Semiconductors",
    "NVDA": "Semiconductors",
    "AVGO": "Semiconductors",
    "MSFT": "Technology",
    "ORCL": "Technology",
    "IBM": "Technology",
    "AAPL": "Technology",
    "META": "Communication Services",
    "AMZN": "Consumer Discretionary",
    "TSLA": "Consumer Discretionary",
    "UBER": "Industrials",
    "RKLB": "Industrials",
    "SPCX": "Industrials",
}


class SignalService:
    """
    مسؤول عن:
    - تحليل الأسهم
    - ترتيب أفضل الفرص
    - تحليل Equity Options
    - تحليل SPX Options
    - إرجاع Candidates فقط

    مهم:
    هذا Service لا ينشر في Telegram
    ولا يفتح Paper Trade مباشرة.

    الاختيار والنشر سيتم لاحقًا من Telegram layer
    عبر /pick ثم /publish.
    """

    def __init__(self, provider, history_repo):
        self.provider = provider
        self.history = history_repo

        self.strategy = StrategyEngine()
        self.risk = RiskEngine()
        self.selector = ContractSelector()
        self.prob = ProbabilityEngine()

    # =========================================================
    # Market
    # =========================================================

    async def market_is_open(self) -> tuple[bool, str]:
        if settings.allow_off_hours_scan:
            return True, "OVERRIDE"

        try:
            clock = await self.provider.market_clock()
            return bool(clock.get("is_open")), str(clock.get("timestamp", ""))
        except Exception:
            return False, "تعذر التحقق من حالة السوق"

    # =========================================================
    # Helpers
    # =========================================================

    @staticmethod
    def _clamp_count(
        requested: int | None,
        per_type_max: int,
    ) -> int:
        """
        يحول الرقم المطلوب إلى نطاق آمن 1..3.
        """

        if requested is None:
            requested = settings.default_signals_per_scan

        try:
            requested = int(requested)
        except (TypeError, ValueError):
            requested = settings.default_signals_per_scan

        requested = max(1, requested)

        hard_max = min(
            settings.max_signals_per_scan,
            per_type_max,
        )

        return min(requested, hard_max)

    @staticmethod
    def _is_swing(trade_type: TradeType) -> bool:
        return "SWING" in trade_type.value

    @staticmethod
    def _is_intraday(trade_type: TradeType) -> bool:
        return "INTRADAY" in trade_type.value

    async def _analyze(
        self,
        symbol: str,
        trade_type: TradeType,
    ):
        swing = self._is_swing(trade_type)

        timeframe = (
            settings.swing_timeframe
            if swing
            else settings.intraday_timeframe
        )

        lookback_days = (
            settings.swing_lookback_days
            if swing
            else settings.intraday_lookback_days
        )

        min_bars = (
            settings.swing_min_bars
            if swing
            else settings.intraday_min_bars
        )

        df = await self.provider.bars(
            symbol,
            timeframe,
            lookback_days,
        )

        valid, quality = validate_bars(
            df,
            min_bars,
        )

        if not valid:
            return None, quality

        analysis = self.strategy.analyze(df)

        return analysis, quality

    # =========================================================
    # Ranking
    # =========================================================

    @staticmethod
    def _rr_quality(rr: float) -> float:
        """
        R/R Bonus.

        لا نجعل R/R العالي يسيطر على Technical Score،
        لكنه يساعد في ترتيب الفرص المتقاربة.
        """

        if rr >= 3.0:
            return 100.0

        if rr >= 2.5:
            return 92.0

        if rr >= 2.0:
            return 85.0

        if rr >= 1.75:
            return 78.0

        if rr >= 1.5:
            return 70.0

        return 40.0

    @staticmethod
    def _data_quality_score(data_quality: str) -> float:
        q = str(data_quality).upper()

        if q == "GOOD":
            return 100.0

        if q == "LIMITED":
            return 75.0

        if q == "STALE":
            return 35.0

        if q == "INVALID":
            return 0.0

        return 60.0

    @staticmethod
    def _market_alignment_score(
        direction: str,
        regime: str,
    ) -> float:
        regime = str(regime).upper()

        if direction == "LONG":
            if "STRONG_BULL" in regime:
                return 100.0
            if "BULL" in regime:
                return 90.0
            if "RANGE" in regime:
                return 65.0
            if "BEAR" in regime:
                return 35.0

        if direction == "SHORT":
            if "STRONG_BEAR" in regime:
                return 100.0
            if "BEAR" in regime:
                return 90.0
            if "RANGE" in regime:
                return 65.0
            if "BULL" in regime:
                return 35.0

        return 60.0

    def _stock_ranking_score(
        self,
        signal: Signal,
    ) -> float:
        """
        Ranking مختلف عن Technical Score.

        Technical Score يظل محفوظًا داخل signal.score.
        Ranking يستخدم:
        - Technical
        - R/R
        - Market alignment
        - Data quality
        """

        technical = float(signal.score)

        rr_score = self._rr_quality(signal.rr)

        market_score = self._market_alignment_score(
            signal.direction,
            signal.market_regime,
        )

        data_score = self._data_quality_score(
            signal.data_quality,
        )

        ranking = (
            technical * 0.55
            + rr_score * 0.20
            + market_score * 0.15
            + data_score * 0.10
        )

        return round(ranking, 2)

    def _option_ranking_score(
        self,
        signal: Signal,
    ) -> float:
        option = signal.option or {}

        underlying_score = float(
            option.get(
                "underlying_score",
                signal.score,
            )
        )

        contract_score = float(
            option.get(
                "contract_score",
                0,
            )
        )

        spread = float(
            option.get(
                "spread_pct",
                999,
            )
            or 999
        )

        if spread <= 3:
            liquidity_score = 100.0
        elif spread <= 5:
            liquidity_score = 90.0
        elif spread <= 8:
            liquidity_score = 75.0
        elif spread <= settings.option_max_spread_pct:
            liquidity_score = 60.0
        else:
            liquidity_score = 20.0

        rr_score = self._rr_quality(signal.rr)

        data_score = self._data_quality_score(
            signal.data_quality,
        )

        ranking = (
            underlying_score * 0.35
            + contract_score * 0.30
            + liquidity_score * 0.15
            + rr_score * 0.10
            + data_score * 0.10
        )

        return round(ranking, 2)

    # =========================================================
    # Stock Candidates
    # =========================================================

    async def _stock_candidates(
        self,
        stock_types: list[TradeType],
    ) -> tuple[list[Signal], list[str]]:
        regime = await MarketRegimeEngine(
            self.provider
        ).get()

        candidates: list[Signal] = []
        rejects: list[str] = []

        for symbol in settings.stocks:
            for trade_type in stock_types:

                try:
                    analysis, quality = await self._analyze(
                        symbol,
                        trade_type,
                    )

                    if not analysis:
                        rejects.append(
                            f"{symbol}/{trade_type.value}: "
                            f"{quality}"
                        )
                        continue

                    if analysis["direction"] not in {
                        "LONG",
                        "SHORT",
                    }:
                        rejects.append(
                            f"{symbol}/{trade_type.value}: "
                            "اتجاه محايد"
                        )
                        continue

                    accepted, risk_pct, reason = (
                        self.risk.assess(
                            analysis["score"],
                            quality,
                            analysis["rr"],
                        )
                    )

                    if not accepted:
                        rejects.append(
                            f"{symbol}/{trade_type.value}: "
                            f"{reason}"
                        )
                        continue

                    probability = self.prob.summarize(
                        self.history.all(),
                        trade_type.value,
                    )

                    signal = Signal(
                        symbol=symbol,
                        trade_type=trade_type,
                        direction=analysis["direction"],
                        decision=Decision.READY,
                        score=analysis["score"],
                        entry_low=analysis["entry_low"],
                        entry_high=analysis["entry_high"],
                        stop=analysis["stop"],
                        tp1=analysis["tp1"],
                        tp2=analysis["tp2"],
                        tp3=analysis["tp3"],
                        rr=analysis["rr"],
                        risk_pct=risk_pct,
                        reasons=analysis["reasons"],
                        invalidation=[
                            "كسر/اختراق مستوى الإبطال "
                            f"{analysis['stop']:.2f}"
                        ],
                        strategies=list(
                            analysis["scores"].keys()
                        ),
                        market_regime=regime,
                        sector=SECTOR_MAP.get(
                            symbol,
                            "N/A",
                        ),
                        data_quality=quality,
                        probability_status=probability[
                            "status"
                        ],
                        probability_samples=probability[
                            "samples"
                        ],
                        probability=probability.get(
                            "probability"
                        ),
                    )

                    candidates.append(signal)

                except Exception as exc:
                    rejects.append(
                        f"{symbol}/{trade_type.value}: "
                        f"{type(exc).__name__}"
                    )

        candidates.sort(
            key=self._stock_ranking_score,
            reverse=True,
        )

        return candidates, rejects

    async def best_stocks(
        self,
        requested_count: int | None = None,
    ) -> tuple[list[Signal], list[str]]:
        """
        يرجع أفضل 1-3 فرص أسهم.
        """

        count = self._clamp_count(
            requested_count,
            settings.max_stock_signals_per_scan,
        )

        trade_types: list[TradeType] = []

        if settings.enable_stock_intraday:
            trade_types.append(
                TradeType.STOCK_INTRADAY
            )

        if settings.enable_stock_swing:
            trade_types.append(
                TradeType.STOCK_SWING
            )

        candidates, rejects = await self._stock_candidates(
            trade_types
        )

        selected: list[Signal] = []
        used_symbols: set[str] = set()

        for signal in candidates:
            # داخل نفس Scan لا نريد اختيار نفس السهم
            # Intraday + Swing معًا.
            # نأخذ أفضل Strategy لذلك الرمز.
            if signal.symbol in used_symbols:
                continue

            selected.append(signal)
            used_symbols.add(signal.symbol)

            if len(selected) >= count:
                break

        return selected, rejects

    async def best_stock(self):
        """
        Compatibility مع الكود القديم.
        """

        candidates, rejects = await self.best_stocks(1)

        return (
            candidates[0] if candidates else None,
            rejects,
        )

    # =========================================================
    # Equity Options
    # =========================================================

    async def _build_equity_option_signal(
        self,
        base: Signal,
    ) -> tuple[Signal | None, str | None]:
        swing = self._is_swing(
            base.trade_type
        )

        min_dte = (
            settings.option_swing_min_dte
            if swing
            else settings.option_intraday_min_dte
        )

        max_dte = (
            settings.option_swing_max_dte
            if swing
            else settings.option_intraday_max_dte
        )

        option_type = (
            "call"
            if base.direction == "LONG"
            else "put"
        )

        try:
            chain = await self.provider.option_chain(
                base.symbol,
                min_dte,
                max_dte,
                option_type,
            )

            contract = self.selector.select(
                chain,
                base.direction,
            )

            if not contract:
                return (
                    None,
                    f"{base.symbol}: "
                    f"لا يوجد عقد "
                    f"{option_type.upper()} "
                    "يحقق شروط السيولة/Delta",
                )

            trade_type = (
                TradeType.EQUITY_OPTION_SWING
                if swing
                else TradeType.EQUITY_OPTION_INTRADAY
            )

            probability = self.prob.summarize(
                self.history.all(),
                trade_type.value,
            )

            entry_low = float(contract["mid"])
            entry_high = float(contract["ask"])

            # Paper premium guard.
            premium_risk = max(
                entry_high * 0.22,
                0.01,
            )

            stop = round(
                max(
                    0.01,
                    entry_low - premium_risk,
                ),
                2,
            )

            tp1 = round(
                entry_high
                + premium_risk * 1.5,
                2,
            )

            tp2 = round(
                entry_high
                + premium_risk * 2.0,
                2,
            )

            tp3 = round(
                entry_high
                + premium_risk * 2.8,
                2,
            )

            unified_score = round(
                (
                    float(base.score)
                    + float(
                        contract["contract_score"]
                    )
                )
                / 2,
                1,
            )

            if unified_score < settings.min_score:
                return (
                    None,
                    f"{base.symbol}: "
                    "Contract/Unified Score منخفض",
                )

            contract.update(
                {
                    "entry_low": entry_low,
                    "entry_high": entry_high,
                    "underlying_score": base.score,
                    "underlying_direction": base.direction,
                    "underlying_entry_low": (
                        base.entry_low
                    ),
                    "underlying_entry_high": (
                        base.entry_high
                    ),
                    "underlying_stop": base.stop,
                    "underlying_tp1": base.tp1,
                    "underlying_tp2": base.tp2,
                    "underlying_tp3": base.tp3,
                }
            )

            signal = Signal(
                symbol=base.symbol,
                trade_type=trade_type,

                # Premium trades are LONG premium
                # whether contract is CALL or PUT.
                direction="LONG",

                decision=Decision.READY,
                score=unified_score,
                entry_low=entry_low,
                entry_high=entry_high,
                stop=stop,
                tp1=tp1,
                tp2=tp2,
                tp3=tp3,
                rr=2.0,
                risk_pct=min(
                    base.risk_pct,
                    0.005,
                ),
                reasons=base.reasons,
                invalidation=[
                    "إبطال التحليل الأساسي عند "
                    f"{base.stop:.2f}"
                ],
                strategies=base.strategies,
                market_regime=base.market_regime,
                sector=base.sector,
                data_quality="LIMITED",
                probability_status=probability[
                    "status"
                ],
                probability_samples=probability[
                    "samples"
                ],
                probability=probability.get(
                    "probability"
                ),
                option=contract,
            )

            return signal, None

        except Exception as exc:
            return (
                None,
                f"{base.symbol} Options API: "
                f"{type(exc).__name__}",
            )

    async def best_equity_options(
        self,
        requested_count: int | None = None,
    ) -> tuple[list[Signal], list[str]]:
        """
        يرجع أفضل 1-3 عقود Equity Options.

        نحاول تنويع الأصول:
        NVDA + AAPL + TSLA
        أفضل من:
        NVDA strike1 + NVDA strike2 + NVDA strike3
        """

        count = self._clamp_count(
            requested_count,
            settings.max_equity_option_signals_per_scan,
        )

        stock_types: list[TradeType] = []

        if settings.enable_equity_options_intraday:
            stock_types.append(
                TradeType.STOCK_INTRADAY
            )

        if settings.enable_equity_options_swing:
            stock_types.append(
                TradeType.STOCK_SWING
            )

        underlying_candidates, rejects = (
            await self._stock_candidates(
                stock_types
            )
        )

        # لا ندخل Option Chain لكل الأسهم.
        # نأخذ أقوى عدد محدود.
        unique_underlyings: list[Signal] = []
        seen_symbols: set[str] = set()

        for candidate in underlying_candidates:
            if candidate.symbol in seen_symbols:
                continue

            unique_underlyings.append(candidate)
            seen_symbols.add(candidate.symbol)

            if (
                len(unique_underlyings)
                >= settings.option_underlying_candidates
            ):
                break

        option_candidates: list[Signal] = []

        for base in unique_underlyings:
            signal, reject_reason = (
                await self._build_equity_option_signal(
                    base
                )
            )

            if signal:
                option_candidates.append(signal)

            elif reject_reason:
                rejects.append(reject_reason)

        option_candidates.sort(
            key=self._option_ranking_score,
            reverse=True,
        )

        selected: list[Signal] = []
        selected_underlyings: set[str] = set()
        selected_contracts: set[str] = set()

        for signal in option_candidates:
            option = signal.option or {}
            contract_symbol = str(
                option.get("symbol", "")
            )

            # يمنع نفس العقد حرفيًا.
            if (
                settings.prevent_exact_duplicate_trade
                and contract_symbol
                and contract_symbol
                in selected_contracts
            ):
                continue

            # Prefer unique underlyings.
            if (
                settings.prefer_unique_option_underlyings
                and signal.symbol
                in selected_underlyings
            ):
                continue

            selected.append(signal)

            selected_underlyings.add(
                signal.symbol
            )

            if contract_symbol:
                selected_contracts.add(
                    contract_symbol
                )

            if len(selected) >= count:
                break

        return selected, rejects

    async def best_equity_option(self):
        """
        Compatibility مع الكود القديم.
        """

        candidates, rejects = (
            await self.best_equity_options(1)
        )

        return (
            candidates[0] if candidates else None,
            rejects,
        )

    # =========================================================
    # Index Options / SPX
    # =========================================================

    async def _index_analysis_candidates(
        self,
    ):
        index = (
            settings.indices[0]
            if settings.indices
            else "SPX"
        )

        proxy = (
            settings.index_analysis_proxy_spx
            if index == "SPX"
            else index
        )

        types: list[TradeType] = []

        if settings.enable_index_options_intraday:
            types.append(
                TradeType.INDEX_OPTION_INTRADAY
            )

        if settings.enable_index_options_swing:
            types.append(
                TradeType.INDEX_OPTION_SWING
            )

        ranked = []
        rejects = []

        for trade_type in types:
            try:
                analysis, quality = await self._analyze(
                    proxy,
                    trade_type,
                )

                if (
                    not analysis
                    or analysis["direction"]
                    not in {"LONG", "SHORT"}
                ):
                    rejects.append(
                        f"{index}/{trade_type.value}: "
                        "اتجاه محايد"
                    )
                    continue

                accepted, risk_pct, reason = (
                    self.risk.assess(
                        analysis["score"],
                        quality,
                        analysis["rr"],
                    )
                )

                if not accepted:
                    rejects.append(
                        f"{index}/{trade_type.value}: "
                        f"{reason}"
                    )
                    continue

                ranked.append(
                    (
                        analysis["score"],
                        trade_type,
                        analysis,
                        quality,
                        risk_pct,
                    )
                )

            except Exception as exc:
                rejects.append(
                    f"{index}/{trade_type.value}: "
                    f"{type(exc).__name__}"
                )

        ranked.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        return (
            index,
            proxy,
            ranked,
            rejects,
        )

    async def best_index_options(
        self,
        requested_count: int | None = None,
    ) -> tuple[list[Signal], list[str]]:
        """
        SPX فيه أصل واحد فقط.

        لذلك Top 1-3 تعني:
        أفضل سيناريوهات مستقلة
        Intraday / Swing / contracts مختلفة.

        لا نكرر نفس العقد.
        """

        count = self._clamp_count(
            requested_count,
            settings.max_index_option_signals_per_scan,
        )

        (
            index,
            proxy,
            ranked,
            rejects,
        ) = await self._index_analysis_candidates()

        market_regime = await MarketRegimeEngine(
            self.provider
        ).get()

        candidates: list[Signal] = []

        for (
            _,
            trade_type,
            analysis,
            quality,
            risk_pct,
        ) in ranked:

            swing = self._is_swing(
                trade_type
            )

            min_dte = (
                settings.option_swing_min_dte
                if swing
                else settings.option_intraday_min_dte
            )

            max_dte = (
                settings.option_swing_max_dte
                if swing
                else settings.option_intraday_max_dte
            )

            option_type = (
                "call"
                if analysis["direction"] == "LONG"
                else "put"
            )

            try:
                chain = await self.provider.option_chain(
                    index,
                    min_dte,
                    max_dte,
                    option_type,
                )

                contract = self.selector.select(
                    chain,
                    analysis["direction"],
                )

                if not contract:
                    rejects.append(
                        f"{index}/{trade_type.value}: "
                        "لا يوجد عقد يحقق الشروط"
                    )
                    continue

                probability = self.prob.summarize(
                    self.history.all(),
                    trade_type.value,
                )

                entry_low = float(
                    contract["mid"]
                )

                entry_high = float(
                    contract["ask"]
                )

                premium_risk = max(
                    entry_high * 0.22,
                    0.01,
                )

                stop = round(
                    max(
                        0.01,
                        entry_low - premium_risk,
                    ),
                    2,
                )

                tp1 = round(
                    entry_high
                    + premium_risk * 1.5,
                    2,
                )

                tp2 = round(
                    entry_high
                    + premium_risk * 2.0,
                    2,
                )

                tp3 = round(
                    entry_high
                    + premium_risk * 2.8,
                    2,
                )

                unified_score = round(
                    (
                        float(
                            analysis["score"]
                        )
                        + float(
                            contract[
                                "contract_score"
                            ]
                        )
                    )
                    / 2,
                    1,
                )

                if unified_score < settings.min_score:
                    rejects.append(
                        f"{index}/{trade_type.value}: "
                        "Unified Score منخفض"
                    )
                    continue

                contract.update(
                    {
                        "entry_low": entry_low,
                        "entry_high": entry_high,
                        "underlying_score": (
                            analysis["score"]
                        ),
                        "underlying_direction": (
                            analysis["direction"]
                        ),
                        "underlying_entry_low": (
                            analysis["entry_low"]
                        ),
                        "underlying_entry_high": (
                            analysis["entry_high"]
                        ),
                        "underlying_stop": (
                            analysis["stop"]
                        ),
                        "underlying_tp1": (
                            analysis["tp1"]
                        ),
                        "underlying_tp2": (
                            analysis["tp2"]
                        ),
                        "underlying_tp3": (
                            analysis["tp3"]
                        ),
                    }
                )

                signal = Signal(
                    symbol=index,
                    trade_type=trade_type,
                    direction="LONG",
                    decision=Decision.READY,
                    score=unified_score,
                    entry_low=entry_low,
                    entry_high=entry_high,
                    stop=stop,
                    tp1=tp1,
                    tp2=tp2,
                    tp3=tp3,
                    rr=2.0,
                    risk_pct=min(
                        risk_pct,
                        0.005,
                    ),
                    reasons=analysis["reasons"],
                    invalidation=[
                        f"إبطال بنية {proxy} "
                        f"عند "
                        f"{analysis['stop']:.2f}"
                    ],
                    strategies=list(
                        analysis["scores"].keys()
                    ),
                    market_regime=market_regime,
                    sector="INDEX",
                    data_quality="LIMITED",
                    probability_status=probability[
                        "status"
                    ],
                    probability_samples=probability[
                        "samples"
                    ],
                    probability=probability.get(
                        "probability"
                    ),
                    option=contract,
                )

                candidates.append(signal)

            except Exception as exc:
                rejects.append(
                    f"{index}/{trade_type.value}: "
                    f"{type(exc).__name__}"
                )

        candidates.sort(
            key=self._option_ranking_score,
            reverse=True,
        )

        selected: list[Signal] = []
        used_contracts: set[str] = set()

        for signal in candidates:
            contract_symbol = str(
                (signal.option or {}).get(
                    "symbol",
                    "",
                )
            )

            if (
                contract_symbol
                and contract_symbol
                in used_contracts
            ):
                continue

            selected.append(signal)

            if contract_symbol:
                used_contracts.add(
                    contract_symbol
                )

            if len(selected) >= count:
                break

        return selected, rejects

    async def best_index_option(self):
        """
        Compatibility مع الكود القديم.
        """

        candidates, rejects = (
            await self.best_index_options(1)
        )

        return (
            candidates[0] if candidates else None,
            rejects,
        )
