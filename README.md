# Prediction Market Paper-Trading MVP

Minimal paper-trading system with **$100k mock portfolio**, position sizing, and P/L tracking.

**No real trades.** Data only.

## Features

- **$100,000 starting balance** (paper)
- **Position sizing** — 2–5% of portfolio per trade, adjusted by:
  - Probability (70–90% = full size, 60–70% = 85%)
  - Time to close (5–21 days = full size)
  - Max 15% exposure per series (e.g. NBA)
  - 20% cash reserve
- **P/L tracking** — Unrealized (mark-to-market) + realized (on settlement)
- **No 99–100% markets** — Skips already-settled markets
- **Default: Kalshi WebSocket** for live ticker updates (buy checks); **REST** for housekeeping (settlement, universe refresh, printed summary)
- **Default universe: fast subset** — NBA/UCL series + a small unfiltered `open` slice (a few hundred markets, seconds to load). Set **`KALSHI_FULL_MARKET_UNIVERSE=1`** to paginate **all** open markets (can mean 100+ API pages every housekeeping — slow)
- **NumPy momentum filter** — After base strategy passes, requires positive mean step-return over a short rolling window (see `momentum.py`)

## Strategy

- **Buy YES** when implied probability 60–98% and closes within 30 days
- **Momentum gate** (when enough price samples exist): `mean(np.diff(p) / p[:-1]) > 0` on rolling implied YES; blocks buys when the series is flat or collapsing on average
- Each trade uses a rules-based % of portfolio

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
- **Housekeeping REST** runs periodically (default **300s**): settlement, refresh market list, full `---` summary.
- **Live `[value]` line** (WebSocket mode, default **every 45s**): quick mark-to-market using cached prices (WebSocket when available). Set `--value-interval 30`, `KALSHI_VALUE_PRINT_SEC`, or `0` to turn off.
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
| `main.py` | Orchestrates WS + REST, strategy, sizing, momentum, persistence |
| `portfolio.py` | $100k balance, position sizing, P/L, `portfolio.json` |
| `kalshi_client.py` | Kalshi REST (markets); demo via `KALSHI_USE_DEMO` |
| `kalshi_auth.py` | RSA headers for WebSocket handshake |
| `kalshi_ws.py` | WebSocket ticker stream + reconnect |
| `strategy.py` | Probability / time-to-close filter |
| `momentum.py` | Rolling implied prices + NumPy momentum gate |
| `logger.py` | Appends rows to `data/trades.csv` |
| `ws.py` | Optional minimal WS smoke test |

## Logging

All structured trade history goes to **`data/trades.csv`** (created automatically). **`data/portfolio.json`** is the live portfolio state (gitignored if listed in `.gitignore`).

### Console

- **WS mode:** `REST:` / `WebSocket:` URLs, housekeeping interval, first-cycle portfolio block, `[WS] subscribed to ticker channel`, buy lines, periodic `---` summary on housekeeping.
- **Poll mode:** `REST polling mode`, interval, same portfolio block each cycle.

### `data/trades.csv`

The **`reason`** column combines strategy text and momentum diagnostics, joined with **`"; "`** when both apply:

| Column | Description |
|--------|-------------|
| `timestamp` | ISO 8601 UTC (e.g. `2026-03-24T04:21:47Z`) |
| `ticker` | Kalshi market ticker |
| `action` | `buy` or `settle` (settlements use `settle`; `hold` is supported by the logger API but not written on every skipped signal) |
| `reason` | Strategy text; **buys** append momentum status after `"; "` e.g. `66% implied, closes in 15d; momentum: ok (mean return 0.0123)` |
| `yes_price` | Entry YES implied (cents), empty for `settle` |
| `days_to_close` | Days until close, empty for `settle` |
| `contracts` | Contracts bought or settled |
| `cost_usd` | USD cost (buy) or cost basis referenced on settle row |
| `balance_after` | Cash after the event |
| `market_title` | Short market title |

**Settlement rows** (`action=settle`): `reason` describes result, payout, and P/L; several numeric columns are left empty as in `logger.log_settlement`.

**Example buy row (with momentum):**

```csv
2026-03-24T04:21:47Z,KXNBAGAME-26MAR25MIACLE-CLE,buy,"66% implied, closes in 15d; momentum: ok (mean return 0.0081)",66,15,2575,1699.50,98300.50,Miami at Cleveland Winner?
```

### `data/portfolio.json`

| Field | Description |
|-------|-------------|
| `cash_balance` | USD remaining |
| `total_invested` | Sum of `cost_usd` for open positions |
| `realized_pnl` | Realized P/L |
| `trade_count` | Total buys |
| `positions` | `{ticker, contracts, entry_price_cents, cost_usd, entry_time, market_title, series_ticker}` |

## P/L behavior

- **Printed portfolio / unrealized** — Updated on each **housekeeping** REST cycle in WS mode (default every 300s), or every **poll** interval in `--poll` mode. Ticker stream still updates internal prices for decisions between prints.
- **Realized P/L** — When a market settles, REST `get_market` provides result; row logged to `trades.csv`, position removed, cash updated.

## Limitations

- **Paper only** — No slippage, fees, or liquidity modeled
- **No sell** — Held until settlement
- **API / rate limits** — Large universes may be throttled

## Tuning

- **`portfolio.py`** — `BASE_POSITION_PCT`, `MAX_POSITION_PCT`, reserves, series cap
- **`strategy.py`** — min/max probability, max days to close
- **`momentum.py` / env** — window length, min samples, optional `KALSHI_MOMENTUM_REQUIRE_HISTORY=1`

## Requirements

- Python 3.10+
- See `requirements.txt` (`requests`, `numpy`, `websockets`, `cryptography`, `certifi`, `feedparser`, …)
