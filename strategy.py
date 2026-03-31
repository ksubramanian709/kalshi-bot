"""
High-probability strategy: only bet on likely events.
- YES probability >= 60%
- Closes within 30 days
"""
from dataclasses import dataclass
from typing import Literal

from kalshi_client import get_yes_probability, days_until_close


@dataclass
class Signal:
    action: Literal["buy", "hold"]
    reason: str


MIN_PROBABILITY = 60   # Only bet when implied YES >= 60%
MAX_PROBABILITY = 85   # Cap: above this the risk/reward is terrible (risk $X to gain pennies)
MAX_DAYS_TO_CLOSE = 30  # Only bet when market closes within 1 month


def get_signal(market: dict) -> Signal:
    """
    Buy YES only when market has >= 60% probability and closes in < 30 days.
    Otherwise hold.
    """
    prob = get_yes_probability(market)
    days = days_until_close(market)

    if prob is None:
        return Signal(action="hold", reason="No price data")

    if days is None:
        return Signal(action="hold", reason="No close time")

    if days < 0:
        return Signal(action="hold", reason="Market already closed")

    if days > MAX_DAYS_TO_CLOSE:
        return Signal(
            action="hold",
            reason=f"Closes in {days}d (max {MAX_DAYS_TO_CLOSE}d)",
        )

    if prob < MIN_PROBABILITY:
        return Signal(
            action="hold",
            reason=f"Probability {prob}% < {MIN_PROBABILITY}%",
        )

    if prob > MAX_PROBABILITY:
        return Signal(
            action="hold",
            reason=f"Already settled at {prob}% (max {MAX_PROBABILITY}%)",
        )

    return Signal(
        action="buy",
        reason=f"{prob}% implied, closes in {days}d",
    )
