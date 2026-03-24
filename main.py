"""
Event-driven prediction market paper-trading MVP.
$100k mock portfolio, position sizing, P/L tracking.
No real trades executed.

WebSocket mode: ticker updates trigger buy checks (with cooldown + price-delta guard).
REST: settlement, universe refresh, P/L summary on a slower housekeeping interval (default 5 min).

Fallback: --poll for REST-only loops (no API keys).
"""
import argparse
import asyncio
import os
import time

from kalshi_auth import build_websocket_headers, websocket_auth_failure_reason
from kalshi_client import base_url, get_market, get_markets, get_yes_probability, days_until_close
from kalshi_ws import stream_tickers, websocket_url
from strategy import get_signal
from portfolio import (
    load_portfolio,
    save_portfolio,
    add_position,
    settle_positions,
    compute_position_size,
    compute_unrealized_pnl,
    STARTING_BALANCE,
)
from logger import log_signal, log_settlement


SERIES_TO_SCAN = ["KXNBAGAME", "KXUCLGAME", "KXUCL", None]

# REST housekeeping in WebSocket mode (settlement, refresh universe, P/L print — no periodic buy scan)
DEFAULT_HOUSEKEEPING_SEC = 300.0
# Legacy env name still supported for poll mode full-cycle interval
DEFAULT_POLL_INTERVAL_SEC = 60.0

TICKER_QUEUE_MAX = 10_000
DEFAULT_TICKER_COOLDOWN_SEC = 5.0
DEFAULT_MIN_PRICE_DELTA_CENTS = 1


def fetch_unique_markets() -> list[dict]:
    all_markets = []
    for series in SERIES_TO_SCAN:
        markets = get_markets(limit=100, series_ticker=series) if series else get_markets(limit=200)
        all_markets.extend(markets)

    seen: set[str] = set()
    unique: list[dict] = []
    for m in all_markets:
        t = m.get("ticker")
        if t and t not in seen:
            seen.add(t)
            unique.append(m)
    return unique


def apply_ticker_to_cache(msg: dict, cache: dict[str, dict]) -> None:
    """Patch yes bid/ask from a WebSocket ticker msg into a cached REST market dict."""
    t = msg.get("market_ticker")
    if not t or t not in cache:
        return
    m = cache[t]
    for src, dst in (("yes_ask_dollars", "yes_ask_dollars"), ("yes_bid_dollars", "yes_bid_dollars")):
        v = msg.get(src)
        if v is None or v == "":
            continue
        try:
            m[dst] = float(v) if isinstance(v, str) else float(v)
        except (ValueError, TypeError):
            pass


def _price_map_for_summary(state: dict, unique: list[dict], market_cache: dict[str, dict]) -> dict[str, int]:
    price_map: dict[str, int] = {}
    for m in unique:
        t = m.get("ticker")
        if not t:
            continue
        mkt = market_cache.get(t) or m
        p = get_yes_probability(mkt)
        if p is not None:
            price_map[t] = p

    for p in state.get("positions", []):
        t = p.get("ticker")
        if not t or t in price_map:
            continue
        mkt = market_cache.get(t) or get_market(t)
        if mkt:
            pr = get_yes_probability(mkt)
            if pr is not None:
                price_map[t] = pr
    return price_map


def scan_and_execute_buys(state: dict, unique: list[dict], market_cache: dict[str, dict]) -> tuple[dict, int]:
    """Full scan of universe for new positions (REST snapshot path)."""
    buy_count = 0
    existing_tickers = {p.get("ticker") for p in state.get("positions", [])}

    for market in unique:
        ticker = market.get("ticker")
        if not ticker or ticker in existing_tickers:
            continue

        mkt = market_cache.get(ticker) or market
        signal = get_signal(mkt)
        yes_price = get_yes_probability(mkt)
        days = days_until_close(mkt)
        title = mkt.get("title", "")

        if signal.action != "buy" or (yes_price is not None and yes_price >= 99):
            continue

        cost_usd, contracts = compute_position_size(state, ticker, yes_price or 60, days)
        if contracts < 1 or cost_usd <= 0:
            continue

        state = add_position(state, ticker, contracts, yes_price or 60, cost_usd, title)
        existing_tickers.add(ticker)

        log_signal(
            "buy", signal.reason, ticker,
            yes_price=yes_price, days_to_close=days, market_title=title,
            contracts=contracts, cost_usd=cost_usd, balance_after=state["cash_balance"],
        )
        t_short = ticker[0:45]
        cash_now = state.get("cash_balance", 0)
        print(f"[{t_short}] BUY {contracts} @ {yes_price}c = ${cost_usd:.2f} | Cash: ${cash_now:,.2f}")
        buy_count += 1

    return state, buy_count


def try_execute_buy_for_ticker(ticker: str, market_cache: dict[str, dict]) -> bool:
    """
    Event-driven buy for one ticker (under caller's lock). Loads fresh portfolio each call.
    Returns True if a new position was opened.
    """
    if ticker not in market_cache:
        return False
    state = load_portfolio()
    existing_tickers = {p.get("ticker") for p in state.get("positions", [])}
    if ticker in existing_tickers:
        return False

    mkt = market_cache[ticker]
    signal = get_signal(mkt)
    yes_price = get_yes_probability(mkt)
    days = days_until_close(mkt)
    title = mkt.get("title", "")

    if signal.action != "buy" or (yes_price is not None and yes_price >= 99):
        return False

    cost_usd, contracts = compute_position_size(state, ticker, yes_price or 60, days)
    if contracts < 1 or cost_usd <= 0:
        return False

    state = add_position(state, ticker, contracts, yes_price or 60, cost_usd, title)
    save_portfolio(state)

    log_signal(
        "buy", signal.reason, ticker,
        yes_price=yes_price, days_to_close=days, market_title=title,
        contracts=contracts, cost_usd=cost_usd, balance_after=state["cash_balance"],
    )
    t_short = ticker[0:45]
    cash_now = state.get("cash_balance", 0)
    print(f"[{t_short}] BUY {contracts} @ {yes_price}c = ${cost_usd:.2f} | Cash: ${cash_now:,.2f}")
    return True


def run_rest_cycle(
    market_cache: dict[str, dict],
    universe_tickers: set[str] | None,
    *,
    scan_buys: bool,
) -> None:
    """
    Settle, refresh universe into cache, optional full buy scan, save, print P/L.
    """
    state = load_portfolio()

    state, settled = settle_positions(state, get_market)
    for s in settled:
        log_settlement(
            s["ticker"], s["result"], s["contracts"], s["cost_usd"],
            s["payout"], s["pnl"], state["cash_balance"], s.get("market_title", ""),
        )
        print(f"[SETTLED] {s['ticker'][:45]} {s['result'].upper()} | P/L ${s['pnl']:+,.2f} | Cash: ${state['cash_balance']:,.2f}")

    unique = fetch_unique_markets()

    if universe_tickers is not None:
        universe_tickers.clear()
        for m in unique:
            t = m.get("ticker")
            if t:
                universe_tickers.add(t)

    for m in unique:
        t = m.get("ticker")
        if t:
            market_cache[t] = m

    buy_count = 0
    if scan_buys:
        state, buy_count = scan_and_execute_buys(state, unique, market_cache)

    save_portfolio(state)

    price_map = _price_map_for_summary(state, unique, market_cache)
    unrealized, port_value = compute_unrealized_pnl(state, price_map)
    realized = state.get("realized_pnl", 0)
    total_pnl = realized + unrealized
    pct_return = 100 * (port_value - STARTING_BALANCE) / STARTING_BALANCE if STARTING_BALANCE else 0

    print("---")
    print(f"Portfolio: ${port_value:,.2f} | Cash: ${state.get('cash_balance', 0):,.2f} | Invested: ${state['total_invested']:,.2f}")
    print(f"P/L: ${total_pnl:+,.2f} ({pct_return:+.2f}%) | Realized: ${realized:+,.2f} | Unrealized: ${unrealized:+,.2f} | Trades: {state.get('trade_count', 0)}")
    if scan_buys and buy_count == 0:
        print("No new buys this cycle")


def _credentials_hint() -> None:
    reason = websocket_auth_failure_reason()
    if reason:
        print(reason)
    else:
        print(
            "WebSocket mode needs KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH (PEM).\n"
            "See https://docs.kalshi.com/getting_started/api_keys"
        )
    print("Use --poll for REST-only mode without keys.")


async def _ticker_event_loop(
    queue: asyncio.Queue,
    market_cache: dict[str, dict],
    cache_lock: asyncio.Lock,
    cooldown_sec: float,
    min_delta_cents: int,
) -> None:
    """Apply ticker patches and run buy logic on meaningful, throttled updates."""
    last_eval_mono: dict[str, float] = {}
    last_yes_ask_cents: dict[str, int] = {}

    while True:
        try:
            msg = await asyncio.wait_for(queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        async with cache_lock:
            ticker = msg.get("market_ticker")
            if not ticker or ticker not in market_cache:
                continue

            apply_ticker_to_cache(msg, market_cache)
            mkt = market_cache[ticker]
            yes_price = get_yes_probability(mkt)
            if yes_price is None:
                continue

            prev = last_yes_ask_cents.get(ticker)
            if prev is not None and abs(yes_price - prev) < min_delta_cents:
                continue
            last_yes_ask_cents[ticker] = yes_price

            now = time.monotonic()
            if now - last_eval_mono.get(ticker, 0.0) < cooldown_sec:
                continue
            last_eval_mono[ticker] = now

            try_execute_buy_for_ticker(ticker, market_cache)


async def _housekeeping_loop(
    interval: float,
    market_cache: dict[str, dict],
    universe_tickers: set[str],
    cache_lock: asyncio.Lock,
) -> None:
    """Slow REST sync: settlement, universe refresh, P/L — no periodic full buy scan."""
    while True:
        await asyncio.sleep(interval)
        async with cache_lock:
            run_rest_cycle(market_cache, universe_tickers, scan_buys=False)


async def run_websocket_mode(housekeeping_interval: float, cooldown_sec: float, min_delta_cents: int) -> None:
    headers = build_websocket_headers()
    if not headers:
        _credentials_hint()
        raise SystemExit(1)

    market_cache: dict[str, dict] = {}
    universe_tickers: set[str] = set()
    cache_lock = asyncio.Lock()
    queue: asyncio.Queue = asyncio.Queue(maxsize=TICKER_QUEUE_MAX)

    print(f"REST: {base_url()}")
    print(f"WebSocket: {websocket_url()}")
    print(
        f"Housekeeping every {housekeeping_interval:.0f}s (settle, universe, P/L) — "
        f"buys on ticker events (cooldown {cooldown_sec:.0f}s, min Δ{min_delta_cents}c ask)"
    )
    print("-" * 50)

    async with cache_lock:
        run_rest_cycle(market_cache, universe_tickers, scan_buys=True)

    await asyncio.gather(
        stream_tickers(queue, universe_tickers, build_websocket_headers),
        _ticker_event_loop(queue, market_cache, cache_lock, cooldown_sec, min_delta_cents),
        _housekeeping_loop(housekeeping_interval, market_cache, universe_tickers, cache_lock),
    )


def run_poll_mode(interval: float, once: bool) -> None:
    print("REST polling mode (no WebSocket)")
    print(f"Full cycle (including buy scan) every {interval:.0f}s")
    print("-" * 50)
    cache: dict[str, dict] = {}
    while True:
        try:
            run_rest_cycle(cache, None, scan_buys=True)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
        if once:
            break
        time.sleep(interval)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="Run one cycle then exit")
    p.add_argument("--reset", action="store_true", help="Reset portfolio to $100k")
    p.add_argument("--poll", action="store_true", help="REST-only polling (no API keys)")
    p.add_argument(
        "--interval",
        type=float,
        default=None,
        help=(
            "Poll mode: seconds between full REST cycles (default 60). "
            "WebSocket mode: housekeeping interval in seconds (default 300; env KALSHI_HOUSEKEEPING_SEC)."
        ),
    )
    p.add_argument(
        "--ticker-cooldown",
        type=float,
        default=float(os.environ.get("KALSHI_TICKER_COOLDOWN_SEC", DEFAULT_TICKER_COOLDOWN_SEC)),
        help="Min seconds between buy checks per ticker on WS updates (default 5)",
    )
    p.add_argument(
        "--min-price-delta",
        type=int,
        default=int(os.environ.get("KALSHI_MIN_PRICE_DELTA_CENTS", DEFAULT_MIN_PRICE_DELTA_CENTS)),
        help="Min YES ask change (cents) to re-run strategy on a ticker (default 1)",
    )
    args = p.parse_args()

    if args.reset:
        import portfolio
        if os.path.exists(portfolio.PORTFOLIO_FILE):
            os.remove(portfolio.PORTFOLIO_FILE)
        print("Portfolio reset to $100,000")

    print("Paper-trading MVP — $100k portfolio, position sizing")
    print("Strategy: Buy YES when 60-98% prob, <30 days | 2-5% per trade")

    if args.poll:
        interval = args.interval if args.interval is not None else float(
            os.environ.get("KALSHI_CYCLE_SEC", DEFAULT_POLL_INTERVAL_SEC)
        )
        run_poll_mode(interval, args.once)
        return

    if args.once:
        headers = build_websocket_headers()
        if not headers:
            _credentials_hint()
            raise SystemExit(1)
        market_cache: dict[str, dict] = {}
        universe: set[str] = set()
        run_rest_cycle(market_cache, universe, scan_buys=True)
        return

    hk = args.interval if args.interval is not None else float(
        os.environ.get("KALSHI_HOUSEKEEPING_SEC", os.environ.get("KALSHI_CYCLE_SEC", DEFAULT_HOUSEKEEPING_SEC))
    )

    try:
        asyncio.run(
            run_websocket_mode(
                housekeeping_interval=hk,
                cooldown_sec=max(0.5, args.ticker_cooldown),
                min_delta_cents=max(1, args.min_price_delta),
            )
        )
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
