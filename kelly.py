"""
Fractional Kelly scaler from historical settle P/L in data/trades.csv.

Uses ¼ Kelly of a simple edge model: wins vs losses as fractions of stake.
If insufficient settles or negative edge, returns a conservative floor so sizing
does not collapse to zero.
"""
from __future__ import annotations

import csv
import os
import re
_PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_PKG_ROOT, "data")
TRADES_FILE = os.path.join(DATA_DIR, "trades.csv")

# Need at least this many settled trades to trust Kelly; else scaler = 1.0
MIN_SETTLES_FOR_KELLY = 5
# Apply ¼ Kelly to full Kelly estimate (conservative)
KELLY_FRACTION = 0.25
# When computed Kelly is <= 0 or data is weird, use this floor multiplier on 1% base
KELLY_FLOOR = 0.25
KELLY_CAP = 1.0

_PNL_RE = re.compile(r"P/L\s*\$?\s*([+-]?\d+(?:\.\d+)?)", re.IGNORECASE)


def _parse_settle_pnl(reason: str) -> float | None:
    if not reason:
        return None
    m = _PNL_RE.search(reason)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def load_settle_pnls(trades_path: str | None = None) -> list[float]:
    """Return list of realized P/L values (dollars) for each settle row."""
    path = trades_path or TRADES_FILE
    if not os.path.isfile(path):
        return []
    out: list[float] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []
        for row in reader:
            if (row.get("action") or "").strip().lower() != "settle":
                continue
            pnl = _parse_settle_pnl(row.get("reason") or "")
            if pnl is not None:
                out.append(pnl)
    return out


def compute_kelly_scaler(trades_path: str | None = None) -> float:
    """
    Returns a multiplier in [KELLY_FLOOR, KELLY_CAP] applied to the 1% base risk.

    With fewer than MIN_SETTLES_FOR_KELLY settles, returns 1.0 (use full 1% base).
    """
    pnls = load_settle_pnls(trades_path)
    n = len(pnls)
    if n < MIN_SETTLES_FOR_KELLY:
        return 1.0

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n_win = len(wins)
    n_loss = len(losses)
    if n_win == 0:
        return KELLY_FLOOR

    avg_win = sum(wins) / n_win
    avg_loss_abs = abs(sum(losses) / n_loss) if n_loss else 0.0
    w = n_win / n

    # Edge per trade (expected $ P/L)
    edge = w * avg_win - (1 - w) * avg_loss_abs
    if avg_win <= 0:
        return KELLY_FLOOR
    # Full Kelly-like fraction on notional (simplified): edge / avg_win
    k_full = edge / avg_win
    k_adj = KELLY_FRACTION * k_full
    if k_adj <= 0:
        return KELLY_FLOOR
    return max(KELLY_FLOOR, min(KELLY_CAP, k_adj))
