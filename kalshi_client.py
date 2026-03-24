"""
Kalshi API client for market data.
No authentication required for reading markets.

Env:
  KALSHI_USE_DEMO=1 — use demo REST host (pair with demo WebSocket + demo API keys)
  KALSHI_REST_URL — override REST base (default: production elections API)
"""
from datetime import datetime, timezone
import os
import requests

BASE_URL_PROD = "https://api.elections.kalshi.com/trade-api/v2"
BASE_URL_DEMO = "https://demo-api.kalshi.co/trade-api/v2"


def base_url() -> str:
    if os.environ.get("KALSHI_USE_DEMO"):
        return BASE_URL_DEMO
    return os.environ.get("KALSHI_REST_URL", BASE_URL_PROD)


def get_markets(limit: int = 200, status: str = "open", series_ticker: str | None = None) -> list[dict]:
    """Fetch open markets from Kalshi."""
    params = {"limit": limit, "status": status}
    if series_ticker:
        params["series_ticker"] = series_ticker
    resp = requests.get(f"{base_url()}/markets", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("markets", [])


def get_market(ticker: str) -> dict | None:
    """Fetch a single market by ticker."""
    resp = requests.get(f"{base_url()}/markets/{ticker}", timeout=10)
    if resp.status_code != 200:
        return None
    return resp.json().get("market")


def get_orderbook(ticker: str) -> dict | None:
    """Fetch orderbook for a market."""
    resp = requests.get(f"{base_url()}/markets/{ticker}/orderbook", timeout=10)
    if resp.status_code != 200:
        return None
    return resp.json()


def parse_close_time(close_time: str | None) -> datetime | None:
    """Parse close_time string to datetime. Returns None if invalid."""
    if not close_time:
        return None
    try:
        return datetime.fromisoformat(close_time.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def days_until_close(market: dict) -> int | None:
    """Return days until market closes. Negative if already closed."""
    ct = market.get("close_time")
    dt = parse_close_time(ct)
    if not dt:
        return None
    delta = dt - datetime.now(timezone.utc)
    return delta.days


def is_settled(market: dict) -> bool:
    """True if market has settled (determined or finalized)."""
    status = (market.get("status") or "").lower()
    return status in ("determined", "finalized")


def get_settlement_result(market: dict) -> str | None:
    """Returns 'yes', 'no', or None if not settled."""
    if not is_settled(market):
        return None
    result = (market.get("result") or "").lower()
    return result if result in ("yes", "no") else None


def get_yes_probability(market: dict) -> int | None:
    """Return YES probability in cents (1-99). Handles yes_ask_dollars or yes_ask."""
    ya = market.get("yes_ask") or market.get("yes_ask_dollars")
    if ya is None:
        return None
    try:
        val = float(ya)
        return int(val * 100) if val < 2 else int(val)
    except (ValueError, TypeError):
        return None
