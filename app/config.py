from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # =========================================================
    # Application
    # =========================================================
    app_name: str = "ALLUQMANU_USA_TD"
    environment: str = "production"

    host: str = "0.0.0.0"
    port: int = 10000

    # Render public URL
    # Example:
    # https://alluqmanu-usa-td.onrender.com
    public_base_url: str | None = None

    # =========================================================
    # Trading Mode
    # =========================================================
    paper_mode: bool = True
    live_trading: bool = False

    # =========================================================
    # Telegram
    # =========================================================
    signal_bot_name: str = "KSA_USA_signal_bot"
    signal_bot_token: str

    profit_bot_name: str = "KSA_USA_profit88_bot"
    profit_bot_token: str

    report_bot_name: str = "KSA_USA_report88_bot"
    report_bot_token: str

    telegram_admin_user_id: int = 1280090240

    # Optional so the application can still boot
    # before the channel is configured.
    telegram_channel_chat_id: int | None = None

    telegram_webhook_secret: str | None = None

    # =========================================================
    # Alpaca
    # =========================================================
    alpaca_trading_base_url: str = "https://paper-api.alpaca.markets/v2"
    alpaca_data_base_url: str = "https://data.alpaca.markets"

    alpaca_api_key: str
    alpaca_api_secret: str

    # Free Alpaca feeds
    alpaca_stock_feed: str = "iex"
    alpaca_options_feed: str = "indicative"

    # =========================================================
    # Allowed Universe
    # =========================================================
    stock_symbols: str = (
        "AMD,UBER,MSFT,MU,META,INTC,ORCL,RKLB,"
        "AMZN,AVGO,TSLA,IBM,AAPL,NVDA,SPCX"
    )

    index_option_symbols: str = "SPX"

    # SPX directional analysis proxy where necessary
    index_analysis_proxy_spx: str = "SPY"

    # =========================================================
    # Enabled Strategies
    # =========================================================
    enable_stock_intraday: bool = True
    enable_stock_swing: bool = True

    enable_equity_options_intraday: bool = True
    enable_equity_options_swing: bool = True

    enable_index_options_intraday: bool = True
    enable_index_options_swing: bool = True

    # Disabled by design while using free indicative option data.
    enable_0dte: bool = False

    allow_off_hours_scan: bool = False

    # =========================================================
    # Scan / Ranking
    # =========================================================

    # Default number returned if user writes:
    # /stock
    # /option
    # /indexoption
    default_signals_per_scan: int = 3

    # Hard maximum accepted from Telegram command.
    # Example:
    # /stock 3
    max_signals_per_scan: int = 3

    max_stock_signals_per_scan: int = 3
    max_equity_option_signals_per_scan: int = 3
    max_index_option_signals_per_scan: int = 3

    # Daily published Paper Trades.
    # These are independent limits.
    max_daily_stock_signals: int = 6
    max_daily_equity_option_signals: int = 6
    max_daily_index_option_signals: int = 4

    # =========================================================
    # Manual Selection Before Publishing
    # =========================================================

    # Scan candidates are NOT immediately opened or published.
    require_manual_publish: bool = True

    # Candidate expires if admin waits too long before /publish.
    # Swing can survive longer, but one common safe default
    # keeps implementation deterministic initially.
    candidate_ttl_seconds: int = 600

    # =========================================================
    # Signal Quality
    # =========================================================
    min_score: float = 75.0
    min_rr: float = 1.5

    # =========================================================
    # Risk
    # =========================================================
    max_risk_per_trade: float = 0.01

    # Portfolio risk ceiling.
    max_total_open_risk: float = 0.03

    # Increased because scans can now publish multiple trades.
    max_open_trades: int = 8

    # Do NOT reject a stock and an option simply because
    # they share the same underlying.
    allow_cross_asset_same_symbol: bool = True

    # Prevent exact duplicates.
    prevent_exact_duplicate_trade: bool = True

    probability_min_samples: int = 50

    # =========================================================
    # Historical Bars
    # =========================================================
    intraday_timeframe: str = "15Min"
    intraday_lookback_days: int = 25
    intraday_min_bars: int = 60

    swing_timeframe: str = "1Day"
    swing_lookback_days: int = 320
    swing_min_bars: int = 120

    # =========================================================
    # Option Profiles
    # =========================================================
    option_intraday_min_dte: int = 1
    option_intraday_max_dte: int = 7

    option_swing_min_dte: int = 7
    option_swing_max_dte: int = 35

    option_max_spread_pct: float = 10.0

    option_min_abs_delta: float = 0.35
    option_max_abs_delta: float = 0.75

    # Limit how many strongest underlyings reach Option Chain stage.
    option_underlying_candidates: int = 7

    # Prefer diversification across option underlyings when
    # selecting the final top candidates.
    prefer_unique_option_underlyings: bool = True

    # =========================================================
    # Trade Monitoring
    # =========================================================
    trade_monitor_seconds: int = 300

    trailing_stop_enabled: bool = False
    trailing_after_tp1_to_entry: bool = True
    trailing_after_tp2_atr: float = 1.0

    near_stop_fraction: float = 0.25

    # =========================================================
    # Reports
    # =========================================================
    report_hour_riyadh: int = 23

    daily_report_enabled: bool = True
    weekly_report_enabled: bool = True

    # Weekly report is designed as an image.
    weekly_report_image_enabled: bool = True

    # =========================================================
    # Images / Branding
    # =========================================================
    watermark_name: str = "ALLUQMANU_USA_TD"

    # Horizontal option cards remain enabled for:
    # - Equity Options
    # - SPX Index Options
    option_card_enabled: bool = True

    option_card_orientation: str = "horizontal"

    # =========================================================
    # Timezones
    # =========================================================
    message_timezones: str = "America/New_York,Asia/Riyadh"

    # =========================================================
    # Storage
    # =========================================================
    store_dir: str = "data"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # =========================================================
    # Helpers
    # =========================================================
    @property
    def stocks(self) -> list[str]:
        return [
            symbol.strip().upper()
            for symbol in self.stock_symbols.split(",")
            if symbol.strip()
        ]

    @property
    def indices(self) -> list[str]:
        return [
            symbol.strip().upper()
            for symbol in self.index_option_symbols.split(",")
            if symbol.strip()
        ]

    @property
    def data_path(self) -> Path:
        path = Path(self.store_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
