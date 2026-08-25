from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ALLUQMANU_USA_TD"
    environment: str = "production"
    host: str = "0.0.0.0"
    port: int = 10000
    public_base_url: str | None = None

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

    min_score: float = 75
    min_rr: float = 1.5
    max_risk_per_trade: float = 0.01
    max_total_open_risk: float = 0.03
    max_open_trades: int = 5
    probability_min_samples: int = 50

    intraday_timeframe: str = "15Min"
    intraday_lookback_days: int = 25
    intraday_min_bars: int = 60
    swing_timeframe: str = "1Day"
    swing_lookback_days: int = 320
    swing_min_bars: int = 120

    option_intraday_min_dte: int = 1
    option_intraday_max_dte: int = 7
    option_swing_min_dte: int = 7
    option_swing_max_dte: int = 35
    option_max_spread_pct: float = 10
    option_min_abs_delta: float = 0.35
    option_max_abs_delta: float = 0.75

    trade_monitor_seconds: int = 300
    report_hour_riyadh: int = 23
    trailing_stop_enabled: bool = False
    trailing_after_tp1_to_entry: bool = True
    trailing_after_tp2_atr: float = 1.0
    near_stop_fraction: float = 0.25

    store_dir: str = "data"
    watermark_name: str = "ALLUQMANU_USA_TD"
    message_timezones: str = "America/New_York,Asia/Riyadh"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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
