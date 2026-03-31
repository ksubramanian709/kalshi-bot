"""
Kalshi API client for market data.
No authentication required for reading markets.

Env:
  KALSHI_USE_DEMO=1 — use demo REST host (pair with demo WebSocket + demo API keys)
  KALSHI_REST_URL — override REST base (default: production elections API)
"""
from datetime import datetime, timezone
import os
import time

import requests

BASE_URL_PROD = "https://api.elections.kalshi.com/trade-api/v2"
BASE_URL_DEMO = "https://demo-api.kalshi.co/trade-api/v2"


def base_url() -> str:
    if os.environ.get("KALSHI_USE_DEMO"):
        return BASE_URL_DEMO
    return os.environ.get("KALSHI_REST_URL", BASE_URL_PROD)


def _get_with_429_retry(
    url: str,
    params: dict | None = None,
    *,
    timeout: int = 60,
    quiet: bool = False,
    max_attempts: int = 15,
) -> requests.Response:
    """GET with retries on HTTP 429 and transient network errors."""
    params = params or {}
    last: requests.Response | None = None
    for attempt in range(max_attempts):
        try:
            last = requests.get(url, params=params, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as e:
            wait = min(2.0 ** min(attempt, 7), 120.0)
            if not quiet:
                print(f"[kalshi] network error — {e!s:.80s}; retry in {wait:.0f}s", flush=True)
            time.sleep(wait)
            continue
        if last.status_code == 429:
            ra = last.headers.get("Retry-After")
            try:
                wait = float(ra) if ra is not None and str(ra).strip() != "" else None
            except (TypeError, ValueError):
                wait = None
            if wait is None:
                wait = min(2.0 ** min(attempt, 7), 120.0)
            if not quiet:
                print(
                    f"[kalshi] HTTP 429 rate limit — sleep {wait:.1f}s (attempt {attempt + 1}/{max_attempts})…",
                    flush=True,
                )
            time.sleep(wait)
            continue
        last.raise_for_status()
        return last
    assert last is not None
    last.raise_for_status()
    return last


def get_markets(limit: int = 200, status: str = "open", series_ticker: str | None = None) -> list[dict]:
    """Fetch one page of markets from Kalshi (no cursor)."""
    params: dict = {"limit": min(max(1, limit), 1000)}
    if status:
        params["status"] = status
    if series_ticker:
        params["series_ticker"] = series_ticker
    quiet = os.environ.get("KALSHI_MARKETS_FETCH_QUIET", "").lower() in ("1", "true", "yes")
    resp = _get_with_429_retry(f"{base_url()}/markets", params, timeout=30, quiet=quiet)
    return resp.json().get("markets", [])


def get_all_markets(
    *,
    status: str | None = "open",
    series_ticker: str | None = None,
    page_limit: int = 1000,
    max_pages: int | None = None,
) -> list[dict]:
    """
    Paginate through GET /markets until the API returns no cursor / empty page.

    ``page_limit`` is per request (Kalshi max 1000). ``max_pages`` caps total pages
    (default from env KALSHI_MARKETS_MAX_PAGES or 500).

    If ``status`` is None or "", the status query param is omitted (any status).
    """
    page_limit = max(1, min(page_limit, 1000))
    if max_pages is None:
        max_pages = int(os.environ.get("KALSHI_MARKETS_MAX_PAGES", "500"))
    quiet = os.environ.get("KALSHI_MARKETS_FETCH_QUIET", "").lower() in ("1", "true", "yes")
    page_delay = float(os.environ.get("KALSHI_MARKETS_PAGE_DELAY_SEC", "0.25"))
    all_markets: list[dict] = []
    cursor: str | None = None

    if not quiet:
        st = status if status else "(any status)"
        print(
            f"[markets] Paginating GET /markets (status={st!r}, max {max_pages} pages × {page_limit})…",
            flush=True,
        )

    for page_idx in range(1, max(1, max_pages) + 1):
        params: dict = {"limit": page_limit}
        if status:
            params["status"] = status
        if series_ticker:
            params["series_ticker"] = series_ticker
        if cursor:
            params["cursor"] = cursor
        resp = _get_with_429_retry(f"{base_url()}/markets", params, timeout=60, quiet=quiet)
        payload = resp.json()
        chunk = payload.get("markets") or []
        all_markets.extend(chunk)
        if not quiet:
            print(
                f"[markets] page {page_idx}: +{len(chunk)} (running total {len(all_markets)})",
                flush=True,
            )
        next_cursor = payload.get("cursor")
        if not chunk or not next_cursor:
            break
        cursor = next_cursor
        if page_delay > 0:
            time.sleep(page_delay)

    if not quiet:
        print(f"[markets] Done. {len(all_markets)} market rows fetched (deduped later by ticker).", flush=True)

    return all_markets


def get_market(ticker: str) -> dict | None:
    """Fetch a single market by ticker.  Retries on 429 and transient network errors."""
    url = f"{base_url()}/markets/{ticker}"
    quiet = os.environ.get("KALSHI_MARKETS_FETCH_QUIET", "").lower() in ("1", "true", "yes")
    max_attempts = 15
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, timeout=15)
        except (requests.ConnectionError, requests.Timeout) as e:
            wait = min(2.0 ** min(attempt, 7), 120.0)
            if not quiet:
                print(f"[kalshi] get_market network error — {e!s:.80s}; retry in {wait:.0f}s", flush=True)
            time.sleep(wait)
            continue
        if resp.status_code == 429:
            ra = resp.headers.get("Retry-After")
            try:
                wait = float(ra) if ra is not None and str(ra).strip() != "" else None
            except (TypeError, ValueError):
                wait = None
            if wait is None:
                wait = min(2.0 ** min(attempt, 7), 120.0)
            if not quiet:
                print(f"[kalshi] get_market 429 — sleep {wait:.1f}s…", flush=True)
            time.sleep(wait)
            continue
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("market")
    return None


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


def get_yes_bid_cents(market: dict) -> int | None:
    """YES bid in cents for paper exits. Uses yes_bid_dollars / yes_bid."""
    yb = market.get("yes_bid") or market.get("yes_bid_dollars")
    if yb is None:
        return None
    try:
        val = float(yb)
        return int(val * 100) if val < 2 else int(val)
    except (ValueError, TypeError):
        return None
