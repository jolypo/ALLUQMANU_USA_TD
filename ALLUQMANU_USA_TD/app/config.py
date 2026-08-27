from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ALLUQMANU_USA_TD"
    environment: str = "production"
    host: str = "0.0.0.0"
    port: int = 10000
    public_base_url: str | None = None

    # Safety: analysis + simulated positions only.
    paper_mode: bool = True
    live_trading: bool = False

    signal_bot_name: str = "KSA_USA_signal_bot"
    signal_bot_token: str
    profit_bot_name: str = "KSA_USA_profit88_bot"
    profit_bot_token: str
    report_bot_name: str = "KSA_USA_report88_bot"
    report_bot_token: str
    telegram_admin_user_id: int = 1280090240
    telegram_channel_chat_id: int | None = None
    telegram_webhook_secret: str | None = None

    alpaca_trading_base_url: str = "https://paper-api.alpaca.markets/v2"
    alpaca_data_base_url: str = "https://data.alpaca.markets"
    alpaca_api_key: str
    alpaca_api_secret: str
    alpaca_stock_feed: str = "iex"
    alpaca_options_feed: str = "indicative"

    stock_symbols: str = "AMD,UBER,MSFT,MU,META,INTC,ORCL,RKLB,AMZN,AVGO,TSLA,IBM,AAPL,NVDA,SPCX"
    index_option_symbols: str = "SPX"
    index_analysis_proxy_spx: str = "SPY"

    enable_stock_intraday: bool = True
    enable_stock_swing: bool = True
    enable_equity_options_intraday: bool = True
    enable_equity_options_swing: bool = True
    enable_index_options_intraday: bool = True
    enable_index_options_swing: bool = True
    enable_0dte: bool = False
    allow_off_hours_scan: bool = False

    min_score: float = 75.0
    min_rr: float = 1.5
    max_risk_per_trade: float = 0.01
    max_total_open_risk: float = 0.03
    max_open_trades: int = 5
    probability_min_samples: int = 50

    # Manual ranking / approval workflow.
    default_signals_per_scan: int = 3
    max_signals_per_scan: int = 3
    candidate_ttl_seconds: int = 600
    require_manual_publish: bool = True
    prevent_exact_duplicate_trade: bool = True
    max_daily_stock_signals: int = 6
    max_daily_equity_option_signals: int = 6
    max_daily_index_option_signals: int = 4

    intraday_timeframe: str = "15Min"
    intraday_lookback_days: int = 25
    intraday_min_bars: int = 60
    swing_timeframe: str = "1Day"
    swing_lookback_days: int = 320
    swing_min_bars: int = 120
    confirmation_timeframe: str = "1Day"
    confirmation_lookback_days: int = 260

    # Technical quality gates.
    min_adx_trend: float = 18.0
    strong_adx: float = 25.0
    min_rvol_breakout: float = 1.10
    range_regime_penalty: float = 5.0
    relative_strength_weight: float = 6.0

    # News/catalyst layer. News is a modest modifier, not a trade generator.
    news_enabled: bool = True
    news_lookback_hours: int = 6
    news_max_items: int = 8
    news_score_cap: float = 5.0

    option_intraday_min_dte: int = 1
    option_intraday_max_dte: int = 7
    option_swing_min_dte: int = 7
    option_swing_max_dte: int = 35
    option_max_spread_pct: float = 10.0
    option_min_abs_delta: float = 0.35
    option_max_abs_delta: float = 0.75
    option_min_contract_score: float = 65.0
    option_max_strike_distance_pct: float = 40.0

    # Monitoring and milestone rules.
    trade_monitor_seconds: int = 60
    option_profit_success_usd: float = 100.0
    usd_sar_rate: float = 3.75
    option_multiplier: int = 100
    trailing_stop_enabled: bool = False
    trailing_after_tp1_to_entry: bool = True
    trailing_after_tp2_atr: float = 1.0
    near_stop_fraction: float = 0.25

    daily_report_enabled: bool = True
    weekly_report_enabled: bool = True
    weekly_report_image_enabled: bool = True
    report_hour_riyadh: int = 23
    option_card_orientation: str = "horizontal"

    store_dir: str = "data"
    watermark_name: str = "ALLUQMANU_USA_TD"
    message_timezones: str = "America/New_York,Asia/Riyadh"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def stocks(self) -> list[str]:
        return [x.strip().upper() for x in self.stock_symbols.split(",") if x.strip()]

    @property
    def indices(self) -> list[str]:
        return [x.strip().upper() for x in self.index_option_symbols.split(",") if x.strip()]

    @property
    def data_path(self) -> Path:
        p = Path(self.store_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
