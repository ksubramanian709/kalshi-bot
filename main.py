"""
Event-driven prediction market paper-trading MVP.
$100k mock portfolio, position sizing, P/L tracking.
No real trades executed.
"""
import argparse
import time

from kalshi_client import get_market, get_markets, get_yes_probability, days_until_close
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


def run_cycle():
    """One cycle: settle any closed positions, fetch markets, filter, size positions, execute, track P/L."""
    state = load_portfolio()

    # Settle positions whose markets have resolved
    state, settled = settle_positions(state, get_market)
    for s in settled:
        log_settlement(
            s["ticker"], s["result"], s["contracts"], s["cost_usd"],
            s["payout"], s["pnl"], state["cash_balance"], s.get("market_title", ""),
        )
        print(f"[SETTLED] {s['ticker'][:45]} {s['result'].upper()} | P/L ${s['pnl']:+,.2f} | Cash: ${state['cash_balance']:,.2f}")
    all_markets = []
    for series in SERIES_TO_SCAN:
        markets = get_markets(limit=100, series_ticker=series) if series else get_markets(limit=200)
        all_markets.extend(markets)

    # Deduplicate
    seen = set()
    unique = []
    for m in all_markets:
        t = m.get("ticker")
        if t and t not in seen:
            seen.add(t)
            unique.append(m)

    # Build price map for P/L (ticker -> yes_price)
    price_map = {}
    for m in unique:
        t = m.get("ticker")
        p = get_yes_probability(m)
        if t and p is not None:
            price_map[t] = p

    buy_count = 0
    existing_tickers = {p.get("ticker") for p in state.get("positions", [])}

    for market in unique:
        ticker = market.get("ticker")
        if not ticker or ticker in existing_tickers:
            continue

        signal = get_signal(market)
        yes_price = get_yes_probability(market)
        days = days_until_close(market)
        title = market.get("title", "")

        if signal.action != "buy" or (yes_price is not None and yes_price >= 99):
            continue

        # Position sizing
        cost_usd, contracts = compute_position_size(state, ticker, yes_price or 60, days)
        if contracts < 1 or cost_usd <= 0:
            continue

        # Execute
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

    save_portfolio(state)

    # P/L summary
    unrealized, port_value = compute_unrealized_pnl(state, price_map)
    realized = state.get("realized_pnl", 0)
    total_pnl = realized + unrealized
    pct_return = 100 * (port_value - STARTING_BALANCE) / STARTING_BALANCE if STARTING_BALANCE else 0

    realized = state.get("realized_pnl", 0)
    print(f"---")
    print(f"Portfolio: ${port_value:,.2f} | Cash: ${state.get('cash_balance',0):,.2f} | Invested: ${state['total_invested']:,.2f}")
    print(f"P/L: ${total_pnl:+,.2f} ({pct_return:+.2f}%) | Realized: ${realized:+,.2f} | Unrealized: ${unrealized:+,.2f} | Trades: {state.get('trade_count', 0)}")
    if buy_count == 0:
        print("No new buys this cycle")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="Run one cycle then exit")
    p.add_argument("--reset", action="store_true", help="Reset portfolio to $100k")
    args = p.parse_args()

    if args.reset:
        import os
        from portfolio import PORTFOLIO_FILE
        if os.path.exists(PORTFOLIO_FILE):
            os.remove(PORTFOLIO_FILE)
        print("Portfolio reset to $100,000")

    print("Paper-trading MVP — $100k portfolio, position sizing")
    print("Strategy: Buy YES when 60-98% prob, <30 days | 2-5% per trade")
    print("-" * 50)

    while True:
        try:
            run_cycle()
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")

        if args.once:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
