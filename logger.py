"""
Log signals to data/trades.csv.
Creates file and directory if they don't exist.
"""
import csv
import os
from datetime import datetime
from typing import Literal

from portfolio import DATA_DIR

TRADES_FILE = os.path.join(DATA_DIR, "trades.csv")
HEADERS = [
    "timestamp", "ticker", "action", "reason", "yes_price", "days_to_close",
    "contracts", "cost_usd", "balance_after", "market_title",
]


def _ensure_file_exists():
    """Create data dir and CSV with headers if needed."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(HEADERS)


def log_settlement(ticker: str, result: str, contracts: int, cost_usd: float, payout: float, pnl: float, balance_after: float, market_title: str = "") -> None:
    """Log a settled position to trades.csv."""
    _ensure_file_exists()
    reason = f"{result.upper()} won, payout ${payout:.2f}, P/L ${pnl:+.2f}"
    row = [
        datetime.utcnow().isoformat() + "Z",
        ticker,
        "settle",
        reason[:200],
        "", "", contracts, cost_usd, balance_after, market_title[:100] if market_title else "",
    ]
    with open(TRADES_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(row)


def log_trade(
    action: Literal["buy", "hold", "stop", "sell"],
    reason: str,
    ticker: str,
    yes_price: int | None = None,
    days_to_close: int | None = None,
    market_title: str = "",
    contracts: int = 0,
    cost_usd: float = 0.0,
    balance_after: float = 0.0,
) -> None:
    """Append one trade to trades.csv."""
    _ensure_file_exists()
    row = [
        datetime.utcnow().isoformat() + "Z",
        ticker,
        action,
        reason[:200] if reason else "",
        yes_price or "",
        days_to_close if days_to_close is not None else "",
        contracts or "",
        cost_usd or "",
        balance_after or "",
        market_title[:100] if market_title else "",
    ]
    with open(TRADES_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(row)


def log_signal(
    action: Literal["buy", "hold", "stop", "sell"],
    reason: str,
    ticker: str,
    yes_price: int | None = None,
    days_to_close: int | None = None,
    market_title: str = "",
    contracts: int = 0,
    cost_usd: float = 0.0,
    balance_after: float = 0.0,
) -> None:
    """Alias for log_trade for backward compat."""
    log_trade(action, reason, ticker, yes_price, days_to_close, market_title, contracts, cost_usd, balance_after)
