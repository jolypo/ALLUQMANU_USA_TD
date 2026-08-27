# ALLUQMANU_USA_TD

Telegram analysis and simulated-trade tracking system for US stocks, equity options, and SPX options.

## Current workflow

- `/stock`, `/option`, `/indexoption` scan and rank candidates privately.
- Direct selection commands: `/pic1k`, `/pic2k`, `/pic3k`.
- `/publish` is still required before a selected candidate is published/tracked.
- New publications are tracked as `OPEN` but are not considered filled until the monitored price reaches the entry zone.
- Entry confirmation, profit updates, TP/SL, milestone alerts, and exits reply to the original channel signal using its stored Telegram `channel_message_id`.

## Technical engine

The signal engine now uses grouped scoring rather than stacking similar indicators as independent confirmation:

- EMA 9/20/50/200
- ADX 14
- RSI 14 + RSI slope
- MACD histogram + slope
- 5-bar momentum
- session-aware VWAP
- relative volume + volume slope
- ATR / ATR%
- structure, HH/HL, LH/LL, breakout confirmation
- secondary ICT-style observations (BOS/FVG/liquidity sweep)
- intraday/daily multi-timeframe confirmation
- relative strength versus SPY
- market regime modifier
- Alpaca news/catalyst modifier

News is only a bounded modifier; it does not create trades by itself. Clearly adverse catalyst keywords can reject a long candidate.

## Options

The underlying must pass first, then a separate contract-quality layer checks:

- OCC root / underlying consistency
- strike distance sanity
- bid/ask validity
- spread
- delta
- theta relative to premium
- IV sanity
- activity when available
- DTE

There is no arbitrary maximum contract premium filter.

Alpaca `indicative` option data is not OPRA real-time. The project keeps this limitation explicit in signal messages.

## Profit alerts

Option profit updates are sent on each monitored increase and include:

- current premium
- percentage P&L
- dollar P&L
- Saudi-riyal P&L at the configured USD/SAR rate
- a generated image showing the actual cash profit

Image tier:

- under $100 profit: green
- $100 to under $300: yellow
- $300 and above: blue

At the first time an option reaches configured `OPTION_PROFIT_SUCCESS_USD` (default $100), it is flagged `success_100_reached=true` and a separate congratulations alert includes a momentum state:

- green: strong — continue with profit protection
- yellow: slowing — secure part of profit / raise stop
- red: weak/reversal — consider exiting the contract

The milestone does not stop later profit updates.

## Daily reports

Daily reports are sent privately to `TELEGRAM_ADMIN_USER_ID`, as separate compact messages for categories that had activity that day:

1. US stocks
2. Equity options
3. Index options

Option reports also show USD and SAR cash P&L. Reaching the configured $100 option-profit milestone counts as a successful option trade for the user-defined success statistic without force-closing the position.

## Safety

`LIVE_TRADING=false` remains required. No broker order execution is implemented.

## Deployment

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Copy `.env.example` values into Render Environment and keep real bot/API secrets out of GitHub.

## Validation

Run:

```bash
python -m compileall -q .
pytest -q
```

Local validation for this revision: Python compilation passed and the included test suite passed.
