# Prediction Market Paper-Trading MVP

Minimal event-driven paper-trading system with **$100k mock portfolio**, position sizing, and P/L tracking.

**No real trades.** Data only.

## Features

- **$100,000 starting balance** (paper)
- **Position sizing** — 2–5% of portfolio per trade, adjusted by:
  - Probability (70–90% = full size, 60–70% = 85%)
  - Time to close (5–21 days = full size)
  - Max 15% exposure per series (e.g. NBA)
  - 20% cash reserve
- **P/L tracking** — Unrealized (mark-to-market) + realized (on settlement) each cycle
- **No 99–100% markets** — Skips already-settled markets

## Strategy

- **Buy YES** when implied probability 60–98% and closes within 30 days
- Each trade uses an optimized % of portfolio

## Quick Start

```bash
pip install -r requirements.txt
python main.py              # Run continuously (every 60s)
python main.py --once       # Run one cycle and exit
python main.py --reset --once   # Reset to $100k and run once
```

## Files

| File | Purpose |
|------|---------|
| `main.py` | Orchestrates fetch → strategy → position size → execute |
| `portfolio.py` | $100k balance, position sizing, P/L, persistence |
| `kalshi_client.py` | Kalshi API + helpers |
| `strategy.py` | High-probability filter (60-98%, <30 days) |
| `logger.py` | Writes to `data/trades.csv` |

## Output

- **data/trades.csv** — Every trade logged with full data (see below)
- **data/portfolio.json** — Full state: cash, positions, total_invested
- **Console** — Per-trade line + P/L summary each cycle

### data/trades.csv schema

| Column        | Description                                      |
|---------------|--------------------------------------------------|
| timestamp     | ISO 8601 UTC (e.g. 2026-03-24T04:21:47Z)         |
| ticker        | Kalshi market ticker                             |
| action        | `buy`, `hold`, or `settle` (when market resolves) |
| reason        | Strategy rationale (e.g. "66% implied, closes in 15d") |
| yes_price     | Entry price in cents (60–98)                     |
| days_to_close | Days until market closes                          |
| contracts     | Number of contracts bought                       |
| cost_usd      | USD spent on the trade                           |
| balance_after | Cash balance after the trade                     |
| market_title  | Market description (e.g. "Miami at Cleveland Winner?") |

**Example row:**
```csv
2026-03-24T04:21:47Z,KXNBAGAME-26MAR25MIACLE-CLE,buy,"66% implied, closes in 15d",66,15,2575,1699.50,98300.50,Miami at Cleveland Winner?
```

### data/portfolio.json schema

| Field          | Description                    |
|----------------|--------------------------------|
| cash_balance   | USD remaining                  |
| total_invested | Sum of cost_usd for all positions |
| realized_pnl   | Realized P/L (reserved)        |
| trade_count    | Total trades executed          |
| positions      | Array of `{ticker, contracts, entry_price_cents, cost_usd, entry_time, market_title, series_ticker}` |

## P/L Behavior

- **Trade count** — Increments on each buy
- **Unrealized P/L** — Mark-to-market each cycle from current Kalshi prices
- **Realized P/L** — When a position’s market settles (status `determined`/`finalized`), we:
  1. Check Kalshi for the result (YES or NO)
  2. Add payout ($1 per contract if YES won) to cash
  3. Remove the position and update realized P/L
  4. Log a `settle` row in trades.csv

## Limitations

- **Paper only** — No slippage, fees, or liquidity constraints modeled
- **No sell** — Positions are held until settlement; no paper “close” flow
- **Kalshi rate limits** — Large scans may hit API limits

## Tuning

Edit `portfolio.py`:
- `BASE_POSITION_PCT` (0.02) — Base size per trade
- `MAX_POSITION_PCT` (0.05) — Cap per trade
- `MIN_CASH_RESERVE_PCT` (0.20) — Keep 20% in cash
- `MAX_SERIES_EXPOSURE_PCT` (0.15) — Max in one series

## Requirements

- Python 3.10+
- `requests`, `feedparser`
