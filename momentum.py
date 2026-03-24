"""
Rolling implied YES probability per ticker; NumPy momentum filter for buys.

Requires mean(step return) > 0 over the recent window when history is long enough.
Short history: no momentum veto (baseline strategy only).

Env:
  KALSHI_MOMENTUM_WINDOW — max samples per ticker (default 20)
  KALSHI_MOMENTUM_MIN_SAMPLES — min samples before filter applies (default 4)
  KALSHI_MOMENTUM_REQUIRE_HISTORY=1 — block buys until MIN_SAMPLES exist (default: allow if short)
"""
from __future__ import annotations

import os
from collections import deque

import numpy as np

MAX_HISTORY = int(os.environ.get("KALSHI_MOMENTUM_WINDOW", "20"))
MIN_SAMPLES = int(os.environ.get("KALSHI_MOMENTUM_MIN_SAMPLES", "4"))
_REQUIRE_FULL_HISTORY = os.environ.get("KALSHI_MOMENTUM_REQUIRE_HISTORY", "").lower() in (
    "1",
    "true",
    "yes",
)

_history: dict[str, deque[float]] = {}


def record_price_sample(ticker: str, prob_cents: int | None) -> None:
    """Append implied YES probability (dollars 0–1) for rolling returns."""
    if not ticker or prob_cents is None:
        return
    p = prob_cents / 100.0
    if p <= 0:
        return
    if ticker not in _history:
        _history[ticker] = deque(maxlen=MAX_HISTORY)
    dq = _history[ticker]
    if dq and abs(dq[-1] - p) < 1e-9:
        return
    dq.append(p)


def momentum_allows_buy(ticker: str) -> tuple[bool, str]:
    """
    If we have enough samples, require mean(np.diff(p)/p[:-1]) > 0 (positive momentum).
    Otherwise allow (insufficient history to judge collapse vs trend).
    """
    dq = _history.get(ticker)
    if dq is None or len(dq) < MIN_SAMPLES:
        if _REQUIRE_FULL_HISTORY:
            n = len(dq) if dq else 0
            return False, f"momentum: need {MIN_SAMPLES} samples (have {n})"
        return True, "momentum: short history (no veto)"

    prices = np.asarray(dq, dtype=np.float64)
    if np.any(prices[:-1] <= 0):
        return True, "momentum: invalid history (no veto)"

    rets = np.diff(prices) / prices[:-1]
    if rets.size == 0:
        return True, "momentum: no returns (no veto)"

    mean_ret = float(np.mean(rets))
    if mean_ret <= 0:
        return False, f"momentum: mean return {mean_ret:.4f} <= 0 (flat/collapsing)"
    return True, f"momentum: ok (mean return {mean_ret:.4f})"
