"""
Paper portfolio: $100k starting balance, position sizing, P/L tracking.

State is stored under this package's data/ directory so it persists across runs
regardless of shell working directory. Only --reset (or deleting portfolio.json)
starts fresh.
"""
import json
import os
from datetime import datetime
from dataclasses import dataclass, asdict

_PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_PKG_ROOT, "data")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")
STARTING_BALANCE = 100_000.0  # dollars

# Position sizing: 1% of portfolio (premium / max loss) × Kelly scaler from settles
BASE_POSITION_PCT = 0.01
MIN_POSITION_PCT = 0.0025     # 0.25% minimum after Kelly floor
MAX_POSITION_PCT = 0.01       # 1% max per trade (premium cap)
MIN_CASH_RESERVE_PCT = 0.20   # Keep 20% in cash
MAX_SERIES_EXPOSURE_PCT = 0.15  # Max 15% in same series (e.g. KXNBAGAME)

# Paper stop-loss: exit if unrealized loss >= this fraction of cost, OR bid drops vs entry
STOP_LOSS_FRACTION_OF_COST = 0.15
STOP_LOSS_CENTS_BELOW_ENTRY = 12


@dataclass
class Position:
    ticker: str
    contracts: int
    entry_price_cents: int
    cost_usd: float
    entry_time: str
    market_title: str
    series_ticker: str  # e.g. KXNBAGAME


@dataclass
class PortfolioState:
    cash_balance: float
    positions: list
    total_invested: float
    realized_pnl: float
    trade_count: int


def _series_from_ticker(ticker: str) -> str:
    """Extract series from ticker, e.g. KXNBAGAME-26MAR25... -> KXNBAGAME."""
    if "-" in ticker:
        return ticker.split("-")[0]
    return "OTHER"


def load_portfolio() -> dict:
    """Load portfolio state from JSON."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(PORTFOLIO_FILE):
        return {
            "cash_balance": STARTING_BALANCE,
            "positions": [],
            "total_invested": 0.0,
            "realized_pnl": 0.0,
            "trade_count": 0,
        }
    with open(PORTFOLIO_FILE, "r") as f:
        return json.load(f)


def save_portfolio(state: dict) -> None:
    """Save portfolio state to JSON."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(state, f, indent=2)


def print_portfolio_startup_status() -> None:
    """Tell the user whether we resumed from disk or started blank (no --reset logic here)."""
    if not os.path.exists(PORTFOLIO_FILE):
        print(
            f"No saved portfolio file — starting paper cash ${STARTING_BALANCE:,.0f} "
            f"(state will save to {PORTFOLIO_FILE})"
        )
        return
    state = load_portfolio()
    n = len(state.get("positions", []))
    print(
        f"Resuming saved portfolio — cash ${state['cash_balance']:,.2f}, "
        f"{n} open position(s), trades logged: {state.get('trade_count', 0)} "
        f"({PORTFOLIO_FILE})"
    )


def compute_position_size(
    state: dict,
    ticker: str,
    yes_price: int,
    days_to_close: int | None,
) -> tuple[float, int]:
    """
    Compute how much to spend and how many contracts.
    Premium (max loss) is capped at ~1% of portfolio × Kelly scaler.
    Returns (usd_to_spend, contracts).
    """
    from kelly import compute_kelly_scaler

    cash = state["cash_balance"]
    total_value = cash + state["total_invested"]
    reserve = total_value * MIN_CASH_RESERVE_PCT
    spendable = max(0, cash - reserve)

    if spendable < 10:  # Min $10 per trade
        return 0.0, 0

    kelly_scaler = compute_kelly_scaler()
    base_pct = BASE_POSITION_PCT * kelly_scaler
    base_pct = max(MIN_POSITION_PCT, min(MAX_POSITION_PCT, base_pct))

    usd_to_spend = total_value * base_pct
    usd_to_spend = min(usd_to_spend, spendable)

    # Check series exposure
    series = _series_from_ticker(ticker)
    series_exposure = sum(
        p.get("cost_usd", 0)
        for p in state["positions"]
        if _series_from_ticker(p.get("ticker", "")) == series
    )
    max_series = total_value * MAX_SERIES_EXPOSURE_PCT
    if series_exposure >= max_series:
        return 0.0, 0
    usd_to_spend = min(usd_to_spend, max_series - series_exposure)

    # Contracts: each costs (price/100) dollars, pays $1 if YES wins
    price_per_contract = yes_price / 100.0
    if price_per_contract <= 0:
        return 0.0, 0
    contracts = int(usd_to_spend / price_per_contract)
    if contracts < 1:
        return 0.0, 0

    actual_cost = contracts * price_per_contract
    return round(actual_cost, 2), contracts


def add_position(
    state: dict,
    ticker: str,
    contracts: int,
    entry_price_cents: int,
    cost_usd: float,
    market_title: str,
) -> dict:
    """Add a position and deduct cost from cash."""
    state = state.copy()
    state["positions"] = list(state.get("positions", []))
    state["positions"].append({
        "ticker": ticker,
        "contracts": contracts,
        "entry_price_cents": entry_price_cents,
        "cost_usd": cost_usd,
        "entry_time": datetime.utcnow().isoformat() + "Z",
        "market_title": market_title[:80],
        "series_ticker": _series_from_ticker(ticker),
    })
    state["cash_balance"] = round(state["cash_balance"] - cost_usd, 2)
    state["total_invested"] = round(state["total_invested"] + cost_usd, 2)
    state["trade_count"] = state.get("trade_count", 0) + 1
    return state


def close_position_at_price(
    state: dict,
    position_index: int,
    exit_price_cents: int,
    *,
    reason: str,
) -> tuple[dict, dict | None]:
    """
    Paper-close one open position at exit_price_cents (per contract, cents).
    Returns (new_state, event dict or None if index invalid).
    """
    positions = list(state.get("positions", []))
    if position_index < 0 or position_index >= len(positions):
        return state, None
    p = positions[position_index]
    contracts = int(p.get("contracts", 0))
    cost_usd = float(p.get("cost_usd", 0))
    ticker = p.get("ticker", "")
    market_title = p.get("market_title", "")
    proceeds = contracts * (exit_price_cents / 100.0)
    pnl = proceeds - cost_usd
    state = state.copy()
    state["positions"] = positions
    state["positions"].pop(position_index)
    state["cash_balance"] = round(state["cash_balance"] + proceeds, 2)
    state["total_invested"] = round(state["total_invested"] - cost_usd, 2)
    state["realized_pnl"] = round(state.get("realized_pnl", 0) + pnl, 2)
    state["trade_count"] = state.get("trade_count", 0) + 1
    event = {
        "ticker": ticker,
        "contracts": contracts,
        "cost_usd": cost_usd,
        "exit_price_cents": exit_price_cents,
        "proceeds": round(proceeds, 2),
        "pnl": round(pnl, 2),
        "market_title": market_title,
        "reason": reason,
    }
    return state, event


def apply_stop_losses(
    state: dict,
    get_market_fn,
) -> tuple[dict, list[dict]]:
    """
    Close positions that hit paper stop rules (bid vs entry, % of cost).
    get_market_fn(ticker) -> market dict or None.
    """
    from kalshi_client import get_yes_bid_cents, get_yes_probability

    closed: list[dict] = []
    indices_to_close: list[tuple[int, int, str]] = []

    positions = list(state.get("positions", []))
    for i, p in enumerate(positions):
        ticker = p.get("ticker")
        if not ticker:
            continue
        market = get_market_fn(ticker)
        if not market:
            continue
        exit_cents = get_yes_bid_cents(market)
        if exit_cents is None:
            exit_cents = get_yes_probability(market)
        if exit_cents is None:
            continue

        contracts = int(p.get("contracts", 0))
        cost_usd = float(p.get("cost_usd", 0))
        entry_c = int(p.get("entry_price_cents", 0))
        proceeds = contracts * (exit_cents / 100.0)
        unrealized = proceeds - cost_usd

        hit_pct = cost_usd > 0 and unrealized <= -STOP_LOSS_FRACTION_OF_COST * cost_usd
        hit_cents = entry_c > 0 and (entry_c - exit_cents) >= STOP_LOSS_CENTS_BELOW_ENTRY
        if hit_pct or hit_cents:
            tag = "stop_pct" if hit_pct else "stop_cents"
            indices_to_close.append((i, exit_cents, tag))

    if not indices_to_close:
        return state, closed

    for i, exit_cents, tag in sorted(indices_to_close, key=lambda x: -x[0]):
        state, ev = close_position_at_price(state, i, exit_cents, reason=f"paper {tag}")
        if ev:
            ev["stop_tag"] = tag
            closed.append(ev)

    return state, closed


def settle_positions(state: dict, get_market_fn) -> tuple[dict, list[dict]]:
    """
    Check each position: if market settled, realize P/L and remove.
    get_market_fn(ticker) -> market dict.
    Returns (updated_state, list of settled trades for logging).
    """
    from kalshi_client import get_settlement_result

    state = state.copy()
    positions = list(state.get("positions", []))
    settled_log = []
    to_remove = []

    for i, p in enumerate(positions):
        ticker = p.get("ticker", "")
        contracts = p.get("contracts", 0)
        cost_usd = p.get("cost_usd", 0)
        market_title = p.get("market_title", "")
        market = get_market_fn(ticker) if ticker else None
        if not market:
            continue

        result = get_settlement_result(market)
        if result is None:
            continue

        # We bought YES: payout $1 per contract if result=='yes'
        payout = contracts * 1.0 if result == "yes" else 0.0
        pnl = payout - cost_usd

        state["cash_balance"] = round(state["cash_balance"] + payout, 2)
        state["total_invested"] = round(state["total_invested"] - cost_usd, 2)
        state["realized_pnl"] = round(state.get("realized_pnl", 0) + pnl, 2)
        to_remove.append(i)
        settled_log.append({
            "ticker": ticker,
            "contracts": contracts,
            "cost_usd": cost_usd,
            "result": result,
            "payout": payout,
            "pnl": pnl,
            "market_title": market_title,
        })

    # Remove settled positions (in reverse order to preserve indices)
    for i in sorted(to_remove, reverse=True):
        positions.pop(i)
    state["positions"] = positions
    return state, settled_log


def compute_unrealized_pnl(state: dict, prices: dict[str, int]) -> tuple[float, float]:
    """
    prices: {ticker: current_yes_price_cents}
    Returns (unrealized_pnl, portfolio_value).
    """
    total_cost = 0.0
    total_value = 0.0
    for p in state.get("positions", []):
        ticker = p.get("ticker", "")
        cost = p.get("cost_usd", 0)
        contracts = p.get("contracts", 0)
        total_cost += cost
        if ticker in prices:
            # Mark to market: value = contracts * (price/100)
            total_value += contracts * (prices[ticker] / 100.0)
        else:
            # No price data, assume cost
            total_value += cost
    unrealized = total_value - total_cost
    portfolio_value = state.get("cash_balance", 0) + total_value
    return round(unrealized, 2), round(portfolio_value, 2)
