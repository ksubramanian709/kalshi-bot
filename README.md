# Prediction Market Paper-Trading MVP

Minimal paper-trading system with **$100k mock portfolio**, position sizing, P/L tracking, technical filters, and optional historical replay.

**No real trades.** Data only.

## Features

- **$100,000 starting balance** (paper)
- **Position sizing** — **~1% of portfolio** per trade (premium / max loss on YES), scaled by a **Kelly scaler** derived from past **`settle`** rows in `data/trades.csv` (see `kelly.py`). Hard cap **1%** of equity per trade; still applies **20% cash reserve** and **15% max exposure per series** (e.g. NBA).
- **Kelly** — Fractional Kelly (¼) on empirical win/loss stats from settles; floor when edge is weak; full **1%** base when there are fewer than **5** historical settles.
- **NumPy momentum filter** — After the base strategy passes, requires positive mean step-return on a rolling implied YES series (`momentum.py`).
- **Technicals (NumPy)** — RSI(14), MACD(12,26,9), Bollinger(20, 2σ) on the same series; gates buys when history is long enough (`technicals.py`). Snapshots append to **`data/technicals/technical_log.csv`** (directory gitignored).
- **Paper stop-loss** — Can exit before settlement if unrealized loss exceeds **15% of cost** or YES **bid** drops **≥12¢** below entry; uses bid when available (`portfolio.py`, `kalshi_client.get_yes_bid_cents`). Checked on housekeeping and on the periodic `[value]` WebSocket loop.
- **No 99–100% markets** — Skips very high implied YES (strategy cap **85%**).
- **Default: Kalshi WebSocket** for live ticker updates (buy checks); **REST** for housekeeping (settlement, stops, universe refresh, summary).
- **Default universe: fast subset** — NBA/UCL series + a small unfiltered `open` slice. Set **`KALSHI_FULL_MARKET_UNIVERSE=1`** to paginate **all** open markets (slow).

## Strategy

- **Buy YES** when implied probability **60–85%** and market closes within **30 days** (`strategy.py`).
- **Momentum gate** (when enough samples): `mean(np.diff(p) / p[:-1]) > 0` on rolling implied YES; blocks flat/collapsing series.
- **Technicals gate** (when **≥40** samples): blocks **RSI > 70**, **MACD histogram < 0**, or price **above upper Bollinger**; short history → no veto.
- **Sizing** — `~1% × kelly_scaler` of portfolio value (subject to cash/series limits).

## Backtest (historical CSV)

Replay **`data/trades.csv`** with FIFO matching (buy → settle/stop per ticker) and print summary stats (equity, P/L, win rate, max drawdown, rough Sharpe, Kelly scaler read from file):

```bash
python backtest.py
python backtest.py --trades /path/to/trades.csv
```

Output is **stdout only** unless you redirect (e.g. `python backtest.py | tee backtest_output.txt`). Intraday technicals and stop rules are **not** simulated from the CSV alone (no per-tick path).

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**WebSocket mode (default)** — needs API credentials:

```bash
export KALSHI_API_KEY_ID="your-key-id"
export KALSHI_PRIVATE_KEY_PATH="$HOME/.config/kalshi/kalshi-private.pem"
python main.py
```

- Buys react to **ticker WebSocket** updates (with per-ticker cooldown / min price delta).
- **Housekeeping REST** runs periodically (default **300s**): settlement, **stop-loss checks**, refresh market list, full `---` summary.
- **Live `[value]` line** (WebSocket mode, default **every 45s**): mark-to-market and **stop-loss** pass using cached prices (REST fallback). Set `--value-interval 30`, `KALSHI_VALUE_PRINT_SEC`, or `0` to turn off.
- Demo API: `export KALSHI_USE_DEMO=1` (matches demo REST + WS).

**REST-only (no keys):**

```bash
python main.py --poll              # full cycle + buy scan each interval (default 60s)
python main.py --poll --once
```

**Other flags:**

```bash
python main.py --once              # one REST cycle (+ buy scan), then exit (needs keys for WS path)
python main.py --reset             # optional: delete saved portfolio only (then next run starts $100k fresh)
python main.py --interval 120      # poll: cycle seconds; WS: housekeeping seconds
python main.py --ticker-cooldown 5 --min-price-delta 1   # WS buy-check throttles
python main.py --value-interval 30    # live portfolio line every 30s (0 = off)
```

Useful env vars: `KALSHI_HOUSEKEEPING_SEC`, `KALSHI_CYCLE_SEC`, `KALSHI_MOMENTUM_*`, **`KALSHI_FULL_MARKET_UNIVERSE=1`** (slow: every open market), `KALSHI_MARKETS_STATUS`, `KALSHI_MARKETS_MAX_PAGES`, `KALSHI_MARKETS_FETCH_QUIET=1`.

**Full-universe mode** re-downloads the whole paginated list on **each** housekeeping cycle (default 300s), not only on first launch — that’s why it’s opt-in.

### Running in the background

- **Same machine, you can close the terminal:** run detached, e.g.  
  `nohup .venv/bin/python main.py >> bot.log 2>&1 &`  
  (`jobs` / `fg` to manage; `kill` the PID to stop.)
- **macOS:** `tmux` / `screen` session, or a **LaunchAgent** plist to start on login.
- **Laptop off / asleep:** the process stops unless the OS keeps running. For 24/7 you’d use a **small cloud VPS** (or similar) where `python main.py` runs under `systemd`, `supervisord`, or Docker — the bot has no built-in “cloud mode”; it’s just a long-lived process.

**First startup with full universe** can sit on `[markets] page N…` for a long time — use the **default fast subset** unless you really need every ticker.

### Saving progress (default behavior)

- **Normal runs do not reset anything.** Cash, open positions, realized P/L, and trade count are stored in **`data/portfolio.json`** next to the code (same path no matter which directory you run `python` from).
- The file is **written after each housekeeping cycle and after each buy**, so stopping with Ctrl+C and starting again **resumes** where you left off.
- **`python main.py --reset`** is the only built-in command that **deletes** `portfolio.json` on purpose (paper $100k, empty positions). Omit it to keep your progress.

## Files

| File | Purpose |
|------|---------|
| `main.py` | Orchestrates WS + REST, strategy, sizing, momentum, technicals, stops, persistence |
| `portfolio.py` | Balance, 1%×Kelly sizing, P/L, stop-loss exits, `portfolio.json` |
| `kelly.py` | Kelly scaler from `data/trades.csv` settles |
| `technicals.py` | RSI / MACD / Bollinger + optional `data/technicals/` CSV log |
| `backtest.py` | FIFO replay of `trades.csv` for summary metrics |
| `kalshi_client.py` | Kalshi REST (markets, bid/ask); demo via `KALSHI_USE_DEMO` |
| `kalshi_auth.py` | RSA headers for WebSocket handshake |
| `kalshi_ws.py` | WebSocket ticker stream + reconnect |
| `strategy.py` | Probability / time-to-close filter |
| `momentum.py` | Rolling implied prices + NumPy momentum gate |
| `logger.py` | Appends rows to `data/trades.csv` |
| `ws.py` | Optional minimal WS smoke test |

## Logging

All structured trade history goes to **`data/trades.csv`** (created automatically). **`data/portfolio.json`** is the live portfolio state (gitignored). **`data/technicals/`** holds indicator logs (gitignored).

### Console

- **WS mode:** `REST:` / `WebSocket:` URLs, housekeeping interval, first-cycle portfolio block, `[WS] subscribed to ticker channel`, buy lines, `[STOP]` lines, periodic `---` summary on housekeeping.
- **Poll mode:** `REST polling mode`, interval, same portfolio block each cycle.

### `data/trades.csv`

The **`reason`** column can combine strategy text, momentum, and technicals, joined with **`"; "`** when multiple apply.

| Column | Description |
|--------|-------------|
| `timestamp` | ISO 8601 UTC (e.g. `2026-03-24T04:21:47Z`) |
| `ticker` | Kalshi market ticker |
| `action` | `buy`, `settle`, or `stop` (paper exit before settlement) |
| `reason` | Strategy / filters; settlements include payout and P/L |
| `yes_price` | Entry YES implied (cents), or exit cents on some stops |
| `days_to_close` | Days until close (empty for settle/stop when not set) |
| `contracts` | Contracts bought, settled, or stopped |
| `cost_usd` | USD cost (buy) or basis on settle/stop rows |
| `balance_after` | Cash after the event |
| `market_title` | Short market title |

**Example buy row (momentum + technicals):**

```csv
...,buy,"66% implied, closes in 15d; momentum: ok (...); technicals: ok RSI=...",
```

### `data/portfolio.json`

| Field | Description |
|-------|-------------|
| `cash_balance` | USD remaining |
| `total_invested` | Sum of `cost_usd` for open positions |
| `realized_pnl` | Realized P/L |
| `trade_count` | Buys + closes that increment the counter |
| `positions` | `{ticker, contracts, entry_price_cents, cost_usd, entry_time, market_title, series_ticker}` |

## P/L behavior

- **Printed portfolio / unrealized** — Updated on each **housekeeping** REST cycle in WS mode (default every 300s), or every **poll** interval in `--poll` mode. Ticker stream still updates internal prices for decisions between prints.
- **Realized P/L** — On **settlement**, REST `get_market` provides result; row logged, position removed. On **stop-loss**, paper sell at bid (or ask fallback), P/L realized, row logged with `action=stop`.

## Limitations

- **Paper only** — No slippage, fees, or full liquidity modeling
- **Backtest** — Uses CSV event stream; does not replay intraday path for technicals/stops
- **API / rate limits** — Large universes may be throttled

## Tuning

- **`portfolio.py`** — `BASE_POSITION_PCT`, `MAX_POSITION_PCT`, reserves, series cap, `STOP_LOSS_*`
- **`kelly.py`** — `MIN_SETTLES_FOR_KELLY`, `KELLY_FRACTION`, floor/cap
- **`strategy.py`** — min/max probability, max days to close
- **`momentum.py` / env** — window length, min samples, optional `KALSHI_MOMENTUM_REQUIRE_HISTORY=1`
- **`technicals.py`** — periods/thresholds (RSI/MACD/BB), `MIN_BARS`

## Requirements

- Python 3.10+
- See `requirements.txt` (`requests`, `numpy`, `websockets`, `cryptography`, `certifi`, `feedparser`, …)
